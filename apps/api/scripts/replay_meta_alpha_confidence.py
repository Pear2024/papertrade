"""One-off: replay live MetaAlpha RF proba on historical A4 ENTRY bars.

Reports how often proba >= 0.75 vs >= 0.55 vs all ENTRY candidates.
Uses the live bootstrap artifact (what AUTO loads). Does not train or promote.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402

from app.services.coach_brain import EMA_SEPARATION_PCT_MIN  # noqa: E402
from app.services.meta_alpha.features import FEATURE_COLS, build_features_frame  # noqa: E402
from app.services.meta_alpha.regime_meta_cpcv import compute_regime  # noqa: E402
from scripts.train_meta_alpha import (  # noqa: E402
    BINANCE_PAIR,
    bars_to_ohlcv,
    collect_a4_entries,
    fetch_klines_sync,
)

LIVE_MODEL = (
    ROOT / "app" / "services" / "meta_alpha" / "artifacts" / "meta_labeler.joblib"
)
FEATURE_PLUS = list(FEATURE_COLS) + ["regime", "primary_side"]


def _unwrap_model(obj):
    if isinstance(obj, dict):
        model = obj.get("model") or obj.get("labeler")
        if model is None:
            raise ValueError("artifact dict missing model/labeler")
        cols = obj.get("feature_cols")
        return model, list(cols) if cols else FEATURE_PLUS
    return obj, FEATURE_PLUS


def score_symbol(symbol: str, bars: list[dict], model, feature_cols: list[str], sep_min: float):
    entries = collect_a4_entries(bars, sep_min=sep_min)
    if not entries:
        return []

    ohlcv = bars_to_ohlcv(bars)
    features = build_features_frame(ohlcv)
    regime = compute_regime(ohlcv["close"], high=ohlcv["high"], low=ohlcv["low"])

    rows = []
    for idx, side in entries:
        if idx < 0 or idx >= len(ohlcv):
            continue
        ts = ohlcv.index[idx]
        if ts not in features.index:
            continue
        feat = features.loc[ts]
        if feat.isna().any():
            continue
        rv = regime.loc[ts] if ts in regime.index else float("nan")
        if rv != rv:  # NaN
            continue
        meta_x = feat[list(FEATURE_COLS)].to_frame().T
        meta_x["regime"] = float(int(rv))
        meta_x["primary_side"] = float(side)
        meta_x = meta_x[feature_cols]
        proba_s = model.predict_proba(meta_x)
        if hasattr(proba_s, "iloc"):
            proba = float(proba_s.iloc[-1])
        else:
            proba = float(proba_s[-1])
        if proba != proba:
            continue
        # bars_to_ohlcv uses naive UTC
        ts_utc = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        rows.append(
            {
                "symbol": symbol,
                "time_utc": ts_utc.isoformat().replace("+00:00", "Z"),
                "side": "BUY" if side == 1 else "SELL",
                "primary_side": side,
                "proba": proba,
                "regime": int(rv),
            }
        )
    return rows


def summarize(rows: list[dict], label: str) -> dict:
    n = len(rows)
    ge55 = [r for r in rows if r["proba"] >= 0.55]
    ge75 = [r for r in rows if r["proba"] >= 0.75]
    probs = [r["proba"] for r in rows]
    out = {
        "label": label,
        "n_entry": n,
        "n_ge_0_55": len(ge55),
        "pct_ge_0_55": (100.0 * len(ge55) / n) if n else 0.0,
        "n_ge_0_75": len(ge75),
        "pct_ge_0_75": (100.0 * len(ge75) / n) if n else 0.0,
        "proba_min": min(probs) if probs else None,
        "proba_max": max(probs) if probs else None,
        "proba_mean": (sum(probs) / n) if n else None,
        "proba_p50": sorted(probs)[n // 2] if probs else None,
        "proba_p90": sorted(probs)[max(0, int(0.9 * (n - 1)))] if probs else None,
        "proba_p95": sorted(probs)[max(0, int(0.95 * (n - 1)))] if probs else None,
        "proba_p99": sorted(probs)[max(0, int(0.99 * (n - 1)))] if probs else None,
        "recent_ge_0_75": sorted(ge75, key=lambda r: r["time_utc"], reverse=True)[:15],
        "top_proba": sorted(rows, key=lambda r: r["proba"], reverse=True)[:10],
    }
    return out


def try_db_audit() -> dict:
    """Query coach_decision_audits for logged rf_proba if DB is reachable."""
    try:
        from app.core.config import get_settings
        from app.core.database import SessionLocal
        from app.models import CoachDecisionAudit
        from sqlalchemy import func, select
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"import:{type(exc).__name__}:{exc}"}

    try:
        settings = get_settings()
        url = getattr(settings, "database_url", None)
        if not url:
            return {"ok": False, "error": "no_database_url"}
        with SessionLocal() as db:
            total = db.scalar(select(func.count()).select_from(CoachDecisionAudit)) or 0
            with_rf = (
                db.scalar(
                    select(func.count())
                    .select_from(CoachDecisionAudit)
                    .where(CoachDecisionAudit.rf_proba.is_not(None))
                )
                or 0
            )
            ge75 = (
                db.scalar(
                    select(func.count())
                    .select_from(CoachDecisionAudit)
                    .where(CoachDecisionAudit.rf_proba >= 0.75)
                )
                or 0
            )
            ge55 = (
                db.scalar(
                    select(func.count())
                    .select_from(CoachDecisionAudit)
                    .where(CoachDecisionAudit.rf_proba >= 0.55)
                )
                or 0
            )
            recent = db.scalars(
                select(CoachDecisionAudit)
                .where(CoachDecisionAudit.rf_proba.is_not(None))
                .order_by(CoachDecisionAudit.evaluated_bar_time.desc())
                .limit(20)
            ).all()
            high = db.scalars(
                select(CoachDecisionAudit)
                .where(CoachDecisionAudit.rf_proba >= 0.75)
                .order_by(CoachDecisionAudit.evaluated_bar_time.desc())
                .limit(15)
            ).all()

            def _row(r):
                bar = r.evaluated_bar_time
                if bar is None:
                    bar_s = None
                elif hasattr(bar, "isoformat"):
                    bar_s = bar.isoformat()
                else:
                    # unix seconds stored as int
                    try:
                        bar_s = datetime.fromtimestamp(
                            int(bar), tz=timezone.utc
                        ).isoformat()
                    except Exception:
                        bar_s = str(bar)
                return {
                    "symbol": r.symbol,
                    "interval": r.interval,
                    "phase": r.phase,
                    "final_action": r.final_action,
                    "rf_proba": float(r.rf_proba) if r.rf_proba is not None else None,
                    "bar": bar_s,
                }

            return {
                "ok": True,
                "total_rows": int(total),
                "rows_with_rf_proba": int(with_rf),
                "rf_ge_0_55": int(ge55),
                "rf_ge_0_75": int(ge75),
                "recent_with_rf": [_row(r) for r in recent],
                "ge_0_75_events": [_row(r) for r in high],
            }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC,ETH,SOL")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument(
        "--model",
        default=str(LIVE_MODEL),
        help="Path to live meta_labeler.joblib",
    )
    args = ap.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: model not found: {model_path}")
        return 1

    artifact = joblib.load(model_path)
    model, feature_cols = _unwrap_model(artifact)
    meta_path = model_path.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    sep_min = float(EMA_SEPARATION_PCT_MIN)

    print("=" * 72)
    print("MetaAlpha confidence replay (live bootstrap model)")
    print(f"model: {model_path}")
    print(f"trained_at_utc: {meta.get('trained_at_utc')}")
    print(
        f"train_window: {meta.get('train_window_start')} -> {meta.get('train_window_end')}"
    )
    print(
        f"n_samples_train: {meta.get('n_samples')}  "
        f"cpcv_mean_proba: {meta.get('cpcv', {}).get('mean_proba')}"
    )
    print(f"symbols={symbols} interval={args.interval} bars_target={args.bars}")
    print(f"A4 sep_min={sep_min}")
    print("=" * 72)

    all_rows: list[dict] = []
    per_symbol = {}
    for sym in symbols:
        pair = BINANCE_PAIR[sym]
        print(f"\nFetching {sym} ({pair})...")
        bars = fetch_klines_sync(pair, args.interval, target=args.bars)
        if not bars:
            print(f"  no bars for {sym}")
            continue
        t0 = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc)
        t1 = datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc)
        print(f"  bars={len(bars)}  range={t0.isoformat()} -> {t1.isoformat()}")
        rows = score_symbol(sym, bars, model, feature_cols, sep_min)
        print(f"  A4 ENTRY scored={len(rows)}")
        per_symbol[sym] = {
            "n_bars": len(bars),
            "start_utc": t0.isoformat(),
            "end_utc": t1.isoformat(),
            "summary": summarize(rows, sym),
        }
        all_rows.extend(rows)

    overall = summarize(all_rows, "ALL")
    print("\n" + "=" * 72)
    print("OVERALL (A4 ENTRY candidates only)")
    print(f"  n_entry           = {overall['n_entry']}")
    print(
        f"  RF >= 0.55        = {overall['n_ge_0_55']}  "
        f"({overall['pct_ge_0_55']:.2f}%)"
    )
    print(
        f"  RF >= 0.75        = {overall['n_ge_0_75']}  "
        f"({overall['pct_ge_0_75']:.2f}%)"
    )
    if overall["proba_min"] is not None:
        print(
            f"  proba min/mean/max = {overall['proba_min']:.4f} / "
            f"{overall['proba_mean']:.4f} / {overall['proba_max']:.4f}"
        )
    else:
        print("  (no samples)")
    if overall["proba_p90"] is not None:
        print(
            f"  proba p50/p90/p95/p99 = "
            f"{overall['proba_p50']:.4f} / {overall['proba_p90']:.4f} / "
            f"{overall['proba_p95']:.4f} / {overall['proba_p99']:.4f}"
        )

    for sym, info in per_symbol.items():
        s = info["summary"]
        print(f"\n--- {sym} ---")
        print(f"  bars={info['n_bars']}  {info['start_utc']} -> {info['end_utc']}")
        print(
            f"  ENTRY={s['n_entry']}  "
            f">=0.55: {s['n_ge_0_55']} ({s['pct_ge_0_55']:.2f}%)  "
            f">=0.75: {s['n_ge_0_75']} ({s['pct_ge_0_75']:.2f}%)"
        )
        if s["proba_mean"] is not None:
            print(
                f"  proba mean={s['proba_mean']:.4f}  "
                f"max={s['proba_max']:.4f}  p95={s['proba_p95']:.4f}"
            )

    print("\nRecent RF >= 0.75 (UTC):")
    if not overall["recent_ge_0_75"]:
        print("  (none)")
    else:
        for r in overall["recent_ge_0_75"]:
            print(
                f"  {r['time_utc']}  {r['symbol']:3s}  {r['side']:4s}  "
                f"proba={r['proba']:.4f}  regime={r['regime']}"
            )

    print("\nTop-10 highest proba (any ENTRY):")
    for r in overall["top_proba"]:
        print(
            f"  {r['time_utc']}  {r['symbol']:3s}  {r['side']:4s}  "
            f"proba={r['proba']:.4f}  regime={r['regime']}"
        )

    print("\n" + "=" * 72)
    print("DB coach_decision_audits (live logged rf_proba)")
    db_info = try_db_audit()
    print(json.dumps(db_info, indent=2, default=str))

    report = {
        "model_path": str(model_path),
        "model_meta": {
            k: meta.get(k)
            for k in (
                "trained_at_utc",
                "train_window_start",
                "train_window_end",
                "n_samples",
                "n_positive",
                "n_negative",
                "threshold",
                "cpcv",
            )
        },
        "per_symbol": {
            k: {
                "n_bars": v["n_bars"],
                "start_utc": v["start_utc"],
                "end_utc": v["end_utc"],
                "summary": {
                    kk: vv
                    for kk, vv in v["summary"].items()
                    if kk not in ("recent_ge_0_75", "top_proba")
                },
                "recent_ge_0_75": v["summary"]["recent_ge_0_75"],
                "top_proba": v["summary"]["top_proba"],
            }
            for k, v in per_symbol.items()
        },
        "overall": {
            kk: vv
            for kk, vv in overall.items()
            if kk not in ("recent_ge_0_75", "top_proba")
        },
        "overall_recent_ge_0_75": overall["recent_ge_0_75"],
        "overall_top_proba": overall["top_proba"],
        "db_audit": db_info,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    out_path = (
        ROOT
        / "app"
        / "services"
        / "meta_alpha"
        / "artifacts"
        / "confidence_replay_report.json"
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
