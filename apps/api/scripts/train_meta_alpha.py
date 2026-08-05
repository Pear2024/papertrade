"""Train MetaAlpha v1 joblib (A4 ENTRY primary → regime-switching meta-labeler).

Fetches longer multi-symbol 15m history (Binance public, paginated),
labels with side-aware triple barrier (SL 2% / TP 3% / vertical 32 bars),
fits RegimeSwitchingMetaLabeler(mode="feature"), runs CPCV with threshold
scan + take-all baseline, and writes a *candidate* artifact by default.

Multi-symbol choice: concatenate BTC/ETH/SOL samples with the frozen 12
features + regime + primary_side only (NO symbol_id) so live_gate schema
stays intact. Overlapping timestamps get a tiny per-symbol offset so CPCV
index uniqueness / purge still works.

Run from apps/api (venv active)::

    python scripts/train_meta_alpha.py
    python scripts/train_meta_alpha.py --symbols BTC,ETH,SOL --bars 100000

Does not modify locked coach_brain.py / A4 rules. Does not overwrite live
meta_labeler.joblib unless --promote and metrics clearly beat bootstrap.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.coach import _a4_side_ok, _ema, _step_position  # noqa: E402
from app.services.coach_brain import (  # noqa: E402
    BASELINE_ID,
    EMA_SEPARATION_PCT_MIN,
    SL_PCT,
    TP_PCT,
)
from app.services.meta_alpha.features import FEATURE_COLS, build_features_frame  # noqa: E402
from app.services.meta_alpha.regime_meta_cpcv import (  # noqa: E402
    CombinatorialPurgedCV,
    RegimeSwitchingMetaLabeler,
    compute_regime,
    get_sample_weights_fold,
)

ARTIFACTS = ROOT / "app" / "services" / "meta_alpha" / "artifacts"
DEFAULT_CANDIDATE = ARTIFACTS / "meta_labeler.candidate.joblib"
DEFAULT_LIVE = ARTIFACTS / "meta_labeler.joblib"
BINANCE_PAIR = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
FEE_PAD = 0.002  # ~0.20% round-trip pad vs paper fee
VERTICAL_BARS = 32
THRESHOLD = 0.55
# Bootstrap reference from prior short train (~198 samples)
BOOTSTRAP_MEAN_ACC = 0.5614
BOOTSTRAP_N_SAMPLES = 198


def fetch_klines_sync(pair: str, interval: str, target: int = 100_000) -> list[dict]:
    """Paginate Binance public klines (no API key) as far back as available."""
    url = "https://data-api.binance.vision/api/v3/klines"
    out: list[dict] = []
    end = None
    pages = 0
    max_pages = max(5, (target // 1000) + 5)
    with httpx.Client(timeout=60.0) as client:
        while len(out) < target and pages < max_pages:
            params: dict = {"symbol": pair, "interval": interval, "limit": 1000}
            if end is not None:
                params["endTime"] = end
            r = client.get(url, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            chunk = [
                {
                    "time": int(row[0]) // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
                for row in rows
            ]
            out = chunk + out
            end = int(rows[0][0]) - 1
            pages += 1
            if pages % 20 == 0:
                print(f"  ... {pair}: {len(out)} bars ({pages} pages)")
            if len(rows) < 1000:
                break
    seen: set[int] = set()
    uniq: list[dict] = []
    for b in out:
        if b["time"] in seen:
            continue
        seen.add(b["time"])
        uniq.append(b)
    uniq.sort(key=lambda x: x["time"])
    return uniq[-target:] if len(uniq) > target else uniq


def bars_to_ohlcv(bars: list[dict]):
    import pandas as pd

    df = pd.DataFrame(bars).drop_duplicates(subset=["time"]).sort_values("time")
    # Naive UTC wall-clock (unix epoch) — CPCV helpers break on tz-aware indexes.
    df = df.set_index(pd.to_datetime(df["time"], unit="s"))
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def collect_a4_entries(
    bars: list[dict],
    *,
    sep_min: float,
) -> list[tuple[int, int]]:
    """Walk A4 state machine; return (bar_index, side) for ENTRY (+flip) bars only."""
    closes = [float(b["close"]) for b in bars]
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    position = "NEUTRAL"
    entries: list[tuple[int, int]] = []
    start = 21
    for i in range(start, len(bars)):
        e9, e21 = ema9[i], ema21[i]
        if e9 is None or e21 is None:
            continue
        buy_ok, sell_ok, _ = _a4_side_ok(
            ema9=float(e9), ema21=float(e21), close=closes[i], sep_min=sep_min
        )
        phase, position = _step_position(position, buy_ok=buy_ok, sell_ok=sell_ok)
        if phase in {"ENTRY_BUY", "FLIP_TO_LONG"}:
            entries.append((i, 1))
        elif phase in {"ENTRY_SELL", "FLIP_TO_SHORT"}:
            entries.append((i, -1))
    return entries


def apply_triple_barrier(
    bars: list[dict],
    entry_idx: int,
    side: int,
    *,
    sl_pct: float,
    tp_pct: float,
    vertical: int,
) -> tuple[float, int]:
    """Side-aware SL/TP + vertical barrier. Returns (side-aware ret, exit_bar_index).

    Same-bar SL+TP → SL first (conservative).
    """
    p0 = float(bars[entry_idx]["close"])
    if p0 <= 0:
        return 0.0, entry_idx
    end = min(entry_idx + vertical, len(bars) - 1)
    for j in range(entry_idx + 1, end + 1):
        hi = float(bars[j]["high"])
        lo = float(bars[j]["low"])
        if side == 1:
            sl_hit = lo <= p0 * (1.0 - sl_pct)
            tp_hit = hi >= p0 * (1.0 + tp_pct)
            if sl_hit and tp_hit:
                p_exit = p0 * (1.0 - sl_pct)
                return side * (p_exit / p0 - 1.0), j
            if sl_hit:
                p_exit = p0 * (1.0 - sl_pct)
                return side * (p_exit / p0 - 1.0), j
            if tp_hit:
                p_exit = p0 * (1.0 + tp_pct)
                return side * (p_exit / p0 - 1.0), j
        else:
            sl_hit = hi >= p0 * (1.0 + sl_pct)
            tp_hit = lo <= p0 * (1.0 - tp_pct)
            if sl_hit and tp_hit:
                p_exit = p0 * (1.0 + sl_pct)
                return side * (p_exit / p0 - 1.0), j
            if sl_hit:
                p_exit = p0 * (1.0 + sl_pct)
                return side * (p_exit / p0 - 1.0), j
            if tp_hit:
                p_exit = p0 * (1.0 - tp_pct)
                return side * (p_exit / p0 - 1.0), j
    p_exit = float(bars[end]["close"])
    return side * (p_exit / p0 - 1.0), end


def build_training_frames(
    bars: list[dict],
    entries: list[tuple[int, int]],
    *,
    sl_pct: float,
    tp_pct: float,
    vertical: int,
    fee_pad: float,
):
    import pandas as pd

    ohlcv = bars_to_ohlcv(bars)
    features = build_features_frame(ohlcv)
    regime = compute_regime(ohlcv["close"], high=ohlcv["high"], low=ohlcv["low"])

    primary_side = pd.Series(dtype=float)
    rets = pd.Series(dtype=float)
    t1_vals: dict = {}

    for idx, side in entries:
        if idx + 1 >= len(bars):
            continue
        ret, exit_idx = apply_triple_barrier(
            bars, idx, side, sl_pct=sl_pct, tp_pct=tp_pct, vertical=vertical
        )
        ts = ohlcv.index[idx]
        primary_side.loc[ts] = float(side)
        rets.loc[ts] = float(ret)
        t1_vals[ts] = ohlcv.index[exit_idx]

    t1 = pd.Series(t1_vals, dtype="datetime64[ns]")

    if primary_side.empty:
        raise RuntimeError("No A4 ENTRY events found in history — cannot train")

    common = primary_side.index.intersection(features.index).intersection(rets.index)
    side = primary_side.loc[common]
    feat = features.loc[common]
    ev_ret = rets.loc[common]
    # User contract: side-aware ret; meta_y = 1 if ret > fee pad
    meta_y = (ev_ret > fee_pad).astype(int)
    meta_X = feat.copy()
    meta_X["regime"] = regime.reindex(common).ffill()
    meta_X["primary_side"] = side
    mask = meta_X.notna().all(axis=1) & meta_y.notna()
    meta_X = meta_X.loc[mask]
    meta_y = meta_y.loc[mask]
    t1_aligned = t1.reindex(meta_X.index)
    returns_aligned = ev_ret.reindex(meta_X.index)
    return meta_X, meta_y, t1_aligned, returns_aligned, ohlcv


def _offset_index_for_symbol(index, symbol_ord: int):
    """Tiny per-symbol offset so multi-asset timestamps stay unique for CPCV."""
    import pandas as pd

    if symbol_ord <= 0:
        return index
    return index + pd.Timedelta(microseconds=int(symbol_ord))


def build_multi_symbol_dataset(
    symbol_bars: dict[str, list[dict]],
    *,
    sep_min: float,
    sl_pct: float,
    tp_pct: float,
    vertical: int,
    fee_pad: float,
):
    """Concatenate per-symbol samples with identical 12-col schema (no symbol_id)."""
    import pandas as pd

    parts_X = []
    parts_y = []
    parts_t1 = []
    parts_ret = []
    per_symbol: dict[str, dict] = {}
    symbol_order = list(symbol_bars.keys())

    for ord_i, symbol in enumerate(symbol_order):
        bars = symbol_bars[symbol]
        entries = collect_a4_entries(bars, sep_min=sep_min)
        print(f"  {symbol}: {len(bars)} bars, A4 ENTRY events={len(entries)}")
        if len(entries) < 5:
            print(f"  WARNING: {symbol} has too few entries - skipping")
            continue
        meta_X, meta_y, t1, returns, ohlcv = build_training_frames(
            bars,
            entries,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            vertical=vertical,
            fee_pad=fee_pad,
        )
        off = ord_i
        meta_X = meta_X.copy()
        meta_X.index = _offset_index_for_symbol(meta_X.index, off)
        meta_y = meta_y.copy()
        meta_y.index = _offset_index_for_symbol(meta_y.index, off)
        t1 = t1.copy()
        t1.index = _offset_index_for_symbol(t1.index, off)
        t1 = t1.apply(lambda x: _offset_index_for_symbol(pd.DatetimeIndex([x]), off)[0])
        returns = returns.copy()
        returns.index = _offset_index_for_symbol(returns.index, off)

        n_pos = int(meta_y.sum())
        n_neg = int(len(meta_y) - n_pos)
        per_symbol[symbol] = {
            "n_bars": len(bars),
            "n_entries_raw": len(entries),
            "n_samples": len(meta_y),
            "n_positive": n_pos,
            "n_negative": n_neg,
            "train_window_start": ohlcv.index[0].isoformat(),
            "train_window_end": ohlcv.index[-1].isoformat(),
            "data_source": f"binance.public:{BINANCE_PAIR[symbol]}",
        }
        parts_X.append(meta_X)
        parts_y.append(meta_y)
        parts_t1.append(t1)
        parts_ret.append(returns)

    if not parts_X:
        raise RuntimeError("No usable symbol samples — cannot train")

    meta_X = pd.concat(parts_X).sort_index()
    meta_y = pd.concat(parts_y).sort_index()
    t1 = pd.concat(parts_t1).sort_index()
    returns = pd.concat(parts_ret).sort_index()
    # Deduplicate exact collisions (shouldn't happen with offset)
    if not meta_X.index.is_unique:
        keep = ~meta_X.index.duplicated(keep="first")
        meta_X, meta_y, t1, returns = (
            meta_X.loc[keep],
            meta_y.loc[keep],
            t1.loc[keep],
            returns.loc[keep],
        )
    return meta_X, meta_y, t1, returns, per_symbol


def fit_final(
    meta_X,
    meta_y,
    t1,
    returns,
    *,
    time_decay: float = 0.85,
):
    import numpy as np

    weights = get_sample_weights_fold(t1, meta_X.index, returns, time_decay=time_decay)
    sw = weights.reindex(meta_X.index).fillna(0.0).to_numpy()
    valid = sw > 0
    if not valid.any():
        sw = np.ones(len(meta_X), dtype=float)
        X_fit, y_fit = meta_X, meta_y
        sw_fit = sw
    else:
        X_fit, y_fit, sw_fit = meta_X.iloc[valid], meta_y.iloc[valid], sw[valid]

    model = RegimeSwitchingMetaLabeler(mode="feature")
    model.fit(X_fit, y_fit, sample_weight=sw_fit)
    return model, int(valid.sum()) if valid.any() else len(meta_X)


def _safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def _threshold_metrics(y_true, proba, returns, threshold: float) -> dict:
    import numpy as np

    y = np.asarray(y_true, dtype=int)
    p = np.asarray(proba, dtype=float)
    r = np.asarray(returns, dtype=float)
    take = p >= threshold
    n_take = int(take.sum())
    n = len(y)
    tp = int(((take == 1) & (y == 1)).sum())
    fp = int(((take == 1) & (y == 0)).sum())
    fn = int(((take == 0) & (y == 1)).sum())
    tn = int(((take == 0) & (y == 0)).sum())
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    accuracy = _safe_div(tp + tn, n)
    take_rate = _safe_div(n_take, n)
    # Simple net proxy: sum of side-aware returns on taken trades (fee already in label pad)
    net_proxy = float(r[take].sum()) if n_take else 0.0
    avg_ret_take = float(r[take].mean()) if n_take else 0.0
    return {
        "threshold": threshold,
        "n": n,
        "n_take": n_take,
        "take_rate": take_rate,
        "accuracy": accuracy,
        "precision_take": precision,
        "recall_take": recall,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "net_proxy": net_proxy,
        "avg_ret_take": avg_ret_take,
    }


def run_cpcv_full(
    meta_X,
    meta_y,
    t1,
    returns,
    *,
    n_groups: int = 6,
    n_test: int = 2,
    time_decay: float = 0.85,
    eval_threshold: float = 0.55,
    scan_thresholds: list[float] | None = None,
):
    """OOF CPCV: path accuracies + pooled threshold scan + take-all baseline."""
    import numpy as np
    import pandas as pd

    if len(meta_X) < 80:
        return {"error": "too_few_samples", "n_samples": len(meta_X)}

    scan_thresholds = scan_thresholds or [
        round(x, 2) for x in np.arange(0.45, 0.71, 0.05)
    ]

    cpcv = CombinatorialPurgedCV(n_groups=n_groups, n_test_groups=n_test)
    path_rows = []
    oof_proba = pd.Series(np.nan, index=meta_X.index, dtype=float)
    oof_counts = pd.Series(0, index=meta_X.index, dtype=int)

    try:
        for train_idx, test_idx, sw, path_id, t_start, t_end in cpcv.split(
            meta_X, t1, returns=returns, time_decay=time_decay
        ):
            X_tr, y_tr = meta_X.iloc[train_idx], meta_y.iloc[train_idx]
            X_te, y_te = meta_X.iloc[test_idx], meta_y.iloc[test_idx]
            r_te = returns.iloc[test_idx]

            model = RegimeSwitchingMetaLabeler(mode="feature")
            model.fit(X_tr, y_tr, sample_weight=sw)
            proba = model.predict_proba(X_te)

            pred = (proba >= eval_threshold).astype(int)
            acc = float((pred == y_te).mean())
            m055 = _threshold_metrics(y_te, proba, r_te, eval_threshold)
            path_rows.append(
                {
                    "path_id": int(path_id),
                    "test_start": str(t_start),
                    "test_end": str(t_end),
                    "n_test": int(len(y_te)),
                    "accuracy": acc,
                    "mean_proba": float(proba.mean()),
                    "precision_take": m055["precision_take"],
                    "recall_take": m055["recall_take"],
                    "take_rate": m055["take_rate"],
                    "net_proxy": m055["net_proxy"],
                }
            )
            # Average OOF proba when a sample appears in multiple test paths
            oof_proba.loc[X_te.index] = oof_proba.loc[X_te.index].fillna(0.0) + proba
            oof_counts.loc[X_te.index] = oof_counts.loc[X_te.index] + 1
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    if not path_rows:
        return {"error": "no_cpcv_paths"}

    path_df = pd.DataFrame(path_rows)
    covered = oof_counts > 0
    oof_p = (oof_proba[covered] / oof_counts[covered]).astype(float)
    oof_y = meta_y.loc[oof_p.index]
    oof_r = returns.loc[oof_p.index]

    # Take-all A4 baseline on the same OOF sample set
    take_all = {
        "n": int(len(oof_y)),
        "take_rate": 1.0,
        "precision": float(oof_y.mean()) if len(oof_y) else 0.0,
        "accuracy_as_all_take": float(oof_y.mean()) if len(oof_y) else 0.0,
        "net_proxy": float(oof_r.sum()) if len(oof_r) else 0.0,
        "avg_ret": float(oof_r.mean()) if len(oof_r) else 0.0,
        "n_positive": int(oof_y.sum()),
        "n_negative": int(len(oof_y) - oof_y.sum()),
    }

    threshold_scan = [
        _threshold_metrics(oof_y, oof_p, oof_r, float(th)) for th in scan_thresholds
    ]
    at_055 = _threshold_metrics(oof_y, oof_p, oof_r, eval_threshold)

    # Recommend threshold: maximize net_proxy among scans with take_rate in [0.15, 0.85]
    # and precision >= take-all precision; fallback to best net_proxy.
    base_prec = take_all["precision"]
    eligible = [
        m
        for m in threshold_scan
        if 0.15 <= m["take_rate"] <= 0.85 and m["precision_take"] >= base_prec - 1e-9
    ]
    if not eligible:
        eligible = [m for m in threshold_scan if 0.10 <= m["take_rate"] <= 0.90]
    if not eligible:
        eligible = threshold_scan
    best = max(eligible, key=lambda m: (m["net_proxy"], m["precision_take"]))

    return {
        "n_paths": int(len(path_df)),
        "n_groups": n_groups,
        "n_test_groups": n_test,
        "n_oof": int(covered.sum()),
        "mean_accuracy": float(path_df["accuracy"].mean()),
        "std_accuracy": float(path_df["accuracy"].std(ddof=0)),
        "mean_precision_take_0.55": float(path_df["precision_take"].mean()),
        "mean_recall_take_0.55": float(path_df["recall_take"].mean()),
        "mean_proba": float(path_df["mean_proba"].mean()),
        "oof_at_0.55": at_055,
        "take_all_baseline": take_all,
        "threshold_scan": threshold_scan,
        "recommended_threshold": best["threshold"],
        "recommended_metrics": best,
        "vs_bootstrap_mean_acc": float(path_df["accuracy"].mean()) - BOOTSTRAP_MEAN_ACC,
        "paths": path_rows,
    }


def decide_promote(cpcv: dict | None, *, force: bool = False) -> tuple[bool, str]:
    """Promote only if candidate clearly beats bootstrap acc AND take-all net/precision."""
    if force:
        return True, "forced_by_flag"
    if not cpcv or cpcv.get("error"):
        return False, "cpcv_missing_or_error"
    mean_acc = float(cpcv.get("mean_accuracy") or 0.0)
    take_all = cpcv.get("take_all_baseline") or {}
    at = cpcv.get("oof_at_0.55") or cpcv.get("recommended_metrics") or {}
    cand_prec = float(at.get("precision_take") or 0.0)
    cand_net = float(at.get("net_proxy") or 0.0)
    base_prec = float(take_all.get("precision") or 0.0)
    base_net = float(take_all.get("net_proxy") or 0.0)

    beats_bootstrap = mean_acc >= BOOTSTRAP_MEAN_ACC + 0.02  # clear lift vs ~0.56
    beats_takeall = (cand_prec > base_prec + 0.02) or (
        cand_net > base_net and cand_prec >= base_prec
    )
    if beats_bootstrap and beats_takeall:
        return True, (
            f"clear_win mean_acc={mean_acc:.3f} (bootstrap~{BOOTSTRAP_MEAN_ACC:.3f}) "
            f"prec={cand_prec:.3f}>{base_prec:.3f} net={cand_net:.4f} vs takeall_net={base_net:.4f}"
        )
    return False, (
        f"not_clear mean_acc={mean_acc:.3f} (bootstrap~{BOOTSTRAP_MEAN_ACC:.3f}) "
        f"prec={cand_prec:.3f} vs takeall={base_prec:.3f} "
        f"net={cand_net:.4f} vs takeall_net={base_net:.4f}"
    )


def save_artifact(
    model: RegimeSwitchingMetaLabeler,
    out_path: Path,
    *,
    meta: dict,
    threshold: float,
) -> None:
    import joblib

    out_path.parent.mkdir(parents=True, exist_ok=True)
    feature_cols = list(FEATURE_COLS) + ["regime", "primary_side"]
    payload = {
        "model": model,
        "feature_cols": feature_cols,
        "threshold": threshold,
        "mode": "feature",
        "brain_id": BASELINE_ID,
    }
    joblib.dump(payload, out_path)
    meta_path = out_path.with_name(out_path.stem + ".meta.json")
    if out_path.suffix == ".joblib":
        # meta_labeler.candidate.joblib → meta_labeler.candidate.meta.json
        meta_path = out_path.with_suffix("").with_suffix(".meta.json")
        if not str(meta_path).endswith(".meta.json"):
            meta_path = Path(str(out_path).replace(".joblib", ".meta.json"))
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return meta_path  # type: ignore[return-value]


def _meta_path_for(joblib_path: Path) -> Path:
    s = str(joblib_path)
    if s.endswith(".joblib"):
        return Path(s[: -len(".joblib")] + ".meta.json")
    return joblib_path.with_suffix(".meta.json")


def print_summary(
    *,
    symbols: list[str],
    per_symbol: dict,
    n_samples: int,
    n_pos: int,
    n_neg: int,
    cpcv: dict | None,
    out_path: Path,
    meta_path: Path,
    promoted: bool,
    promote_reason: str,
    recommended_threshold: float,
) -> None:
    print("\n" + "=" * 72)
    print("METAALPHA LARGER TRAIN - SUMMARY")
    print("=" * 72)
    print(f"Symbols (concat, no symbol_id): {', '.join(symbols)}")
    print(
        "Schema choice: frozen 12 features + regime + primary_side "
        "(symbol_id NOT added - would break live_gate)"
    )
    total_bars = 0
    for sym, info in per_symbol.items():
        total_bars += int(info["n_bars"])
        print(
            f"  {sym}: bars={info['n_bars']}  samples={info['n_samples']} "
            f"pos/neg={info['n_positive']}/{info['n_negative']}  "
            f"{info['train_window_start']} -> {info['train_window_end']}"
        )
    print(f"Total bars fetched: {total_bars}")
    print(f"Pooled samples: {n_samples} (y=1: {n_pos}, y=0: {n_neg})")
    print(
        f"Bootstrap reference: n~={BOOTSTRAP_N_SAMPLES}, "
        f"mean_acc~={BOOTSTRAP_MEAN_ACC:.3f}"
    )

    if not cpcv:
        print("CPCV: skipped")
    elif cpcv.get("error"):
        print(f"CPCV error: {cpcv['error']}")
    else:
        print(
            f"CPCV paths={cpcv['n_paths']}  "
            f"mean_acc={cpcv['mean_accuracy']:.4f} +/- {cpcv['std_accuracy']:.4f}  "
            f"(d vs bootstrap={cpcv['vs_bootstrap_mean_acc']:+.4f})"
        )
        print(
            f"  path mean precision@0.55={cpcv['mean_precision_take_0.55']:.4f}  "
            f"recall@0.55={cpcv['mean_recall_take_0.55']:.4f}"
        )
        ta = cpcv["take_all_baseline"]
        print(
            f"Take-all A4 baseline (OOF): precision={ta['precision']:.4f}  "
            f"net_proxy={ta['net_proxy']:.4f}  avg_ret={ta['avg_ret']:.5f}  n={ta['n']}"
        )
        at = cpcv["oof_at_0.55"]
        print(
            f"Meta @0.55 (OOF): take_rate={at['take_rate']:.3f}  "
            f"precision={at['precision_take']:.4f}  recall={at['recall_take']:.4f}  "
            f"net_proxy={at['net_proxy']:.4f}"
        )
        print("Threshold scan (OOF pooled):")
        print(
            f"  {'th':>5}  {'take%':>6}  {'prec':>6}  {'rec':>6}  "
            f"{'net':>10}  {'avgRet':>8}"
        )
        for m in cpcv["threshold_scan"]:
            print(
                f"  {m['threshold']:5.2f}  {100*m['take_rate']:5.1f}%  "
                f"{m['precision_take']:6.3f}  {m['recall_take']:6.3f}  "
                f"{m['net_proxy']:10.4f}  {m['avg_ret_take']:8.5f}"
            )
        print(
            f"Recommended threshold: {recommended_threshold:.2f}  "
            f"(metrics={cpcv.get('recommended_metrics')})"
        )

    print(f"Candidate artifact: {out_path}")
    print(f"Candidate meta:     {meta_path}")
    if promoted:
        print(f"PROMOTED to live:   {DEFAULT_LIVE}")
        print(f"  reason: {promote_reason}")
    else:
        print("Live model: LEFT AS-IS (not promoted)")
        print(f"  reason: {promote_reason}")
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train MetaAlpha v1 meta-labeler (larger round)")
    p.add_argument(
        "--symbols",
        default="BTC,ETH,SOL",
        help="Comma-separated app symbols (default BTC,ETH,SOL). Concatenated, no symbol_id.",
    )
    p.add_argument("--symbol", default=None, help="Single symbol override (legacy)")
    p.add_argument("--interval", default="15m")
    p.add_argument(
        "--bars",
        type=int,
        default=100_000,
        help="Target historical bars per symbol (~2.85y of 15m; API may return less)",
    )
    p.add_argument("--out", type=Path, default=DEFAULT_CANDIDATE)
    p.add_argument("--skip-cpcv", action="store_true")
    p.add_argument("--fee-pad", type=float, default=FEE_PAD)
    p.add_argument("--n-groups", type=int, default=6)
    p.add_argument("--n-test-groups", type=int, default=2)
    p.add_argument(
        "--promote",
        action="store_true",
        help="Also write live meta_labeler.joblib if metrics clearly beat bootstrap+take-all",
    )
    p.add_argument(
        "--force-promote",
        action="store_true",
        help="Overwrite live artifact regardless of metrics (use with care)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    for s in symbols:
        if s not in BINANCE_PAIR:
            print(f"Unsupported symbol {s}; known: {', '.join(BINANCE_PAIR)}")
            return 1

    sl_pct = float(SL_PCT)
    tp_pct = float(TP_PCT)
    sep_min = float(EMA_SEPARATION_PCT_MIN)

    print(
        f"Fetching {', '.join(symbols)} {args.interval} "
        f"(~{args.bars} bars each) via Binance public..."
    )
    print(
        "Multi-symbol plan: ONE model, concatenated samples, "
        "identical 12 features (no symbol_id - preserves live_gate schema)"
    )

    symbol_bars: dict[str, list[dict]] = {}
    for sym in symbols:
        pair = BINANCE_PAIR[sym]
        print(f"Fetching {sym} ({pair})...")
        try:
            bars = fetch_klines_sync(pair, args.interval, target=args.bars)
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED to fetch {sym}: {exc}")
            return 2
        if len(bars) < 200:
            print(f"Insufficient bars for {sym}: {len(bars)} (need >= 200)")
            return 2
        t0 = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc).isoformat()
        t1 = datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc).isoformat()
        print(f"  Loaded {len(bars)} bars  {t0} -> {t1}")
        symbol_bars[sym] = bars

    print("Building A4 ENTRY + triple-barrier meta samples...")
    meta_X, meta_y, t1, returns, per_symbol = build_multi_symbol_dataset(
        symbol_bars,
        sep_min=sep_min,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        vertical=VERTICAL_BARS,
        fee_pad=args.fee_pad,
    )
    n_pos = int(meta_y.sum())
    n_neg = int(len(meta_y) - n_pos)
    print(f"Pooled meta samples: {len(meta_y)} (y=1: {n_pos}, y=0: {n_neg})")

    cpcv_summary = None
    if not args.skip_cpcv:
        print(
            f"Running CPCV (n_groups={args.n_groups}, n_test={args.n_test_groups})..."
        )
        cpcv_summary = run_cpcv_full(
            meta_X,
            meta_y,
            t1,
            returns,
            n_groups=args.n_groups,
            n_test=args.n_test_groups,
            time_decay=0.85,
            eval_threshold=THRESHOLD,
        )
        if cpcv_summary.get("error"):
            print(f"CPCV: {cpcv_summary}")
        else:
            print(
                f"CPCV mean_acc={cpcv_summary['mean_accuracy']:.4f} "
                f"+/- {cpcv_summary['std_accuracy']:.4f}  "
                f"paths={cpcv_summary['n_paths']}"
            )

    model, n_fit = fit_final(meta_X, meta_y, t1, returns)
    print(f"Fitted RegimeSwitchingMetaLabeler(mode=feature) on {n_fit} weighted samples")

    import sklearn

    recommended_threshold = THRESHOLD
    if cpcv_summary and not cpcv_summary.get("error"):
        recommended_threshold = float(
            cpcv_summary.get("recommended_threshold") or THRESHOLD
        )

    # Artifact uses contract default 0.55 unless we embed recommended for ops visibility
    artifact_threshold = THRESHOLD
    feature_cols = list(FEATURE_COLS) + ["regime", "primary_side"]
    windows = [per_symbol[s] for s in per_symbol]
    train_start = min(w["train_window_start"] for w in windows)
    train_end = max(w["train_window_end"] for w in windows)
    total_bars = sum(int(w["n_bars"]) for w in windows)

    meta = {
        "brain_id": BASELINE_ID,
        "symbols": list(per_symbol.keys()),
        "symbol_feature": None,
        "symbol_strategy": (
            "concat_identical_12_features_no_symbol_id "
            "(preserves live_gate frozen schema)"
        ),
        "interval": args.interval,
        "threshold": artifact_threshold,
        "recommended_threshold": recommended_threshold,
        "mode": "feature",
        "feature_cols": feature_cols,
        "frozen_feature_cols": list(FEATURE_COLS),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "vertical_bars": VERTICAL_BARS,
        "fee_pad": args.fee_pad,
        "train_window_start": train_start,
        "train_window_end": train_end,
        "n_bars_total": total_bars,
        "per_symbol": per_symbol,
        "n_samples": len(meta_y),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "n_fit_weighted": n_fit,
        "sklearn_version": sklearn.__version__,
        "cpcv": cpcv_summary,
        "bootstrap_reference": {
            "n_samples": BOOTSTRAP_N_SAMPLES,
            "mean_accuracy": BOOTSTRAP_MEAN_ACC,
        },
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary": "A4 ENTRY only (BUY=+1, SELL=-1)",
        "data_source": "binance.public:multi",
        "candidate": True,
    }

    out_path = args.out
    meta_path = _meta_path_for(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(
        {
            "model": model,
            "feature_cols": feature_cols,
            "threshold": artifact_threshold,
            "mode": "feature",
            "brain_id": BASELINE_ID,
        },
        out_path,
    )
    meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Wrote {meta_path}")

    promote = False
    promote_reason = "not_requested"
    if args.force_promote or args.promote:
        promote, promote_reason = decide_promote(
            cpcv_summary, force=args.force_promote
        )
        if promote:
            import shutil

            shutil.copy2(out_path, DEFAULT_LIVE)
            live_meta = dict(meta)
            live_meta["candidate"] = False
            live_meta["promoted_from"] = str(out_path)
            live_meta["promote_reason"] = promote_reason
            _meta_path_for(DEFAULT_LIVE).write_text(
                json.dumps(live_meta, indent=2, default=str), encoding="utf-8"
            )
            print(f"Promoted -> {DEFAULT_LIVE}")
        else:
            print(f"Promote skipped: {promote_reason}")

    print_summary(
        symbols=list(per_symbol.keys()),
        per_symbol=per_symbol,
        n_samples=len(meta_y),
        n_pos=n_pos,
        n_neg=n_neg,
        cpcv=cpcv_summary,
        out_path=out_path,
        meta_path=meta_path,
        promoted=promote,
        promote_reason=promote_reason,
        recommended_threshold=recommended_threshold,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
