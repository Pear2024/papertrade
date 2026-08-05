"""Live ENTRY gate: pretrained meta-labeler → take / skip.

When ``META_ALPHA_ENABLED`` is false, this is an identity filter (always take).
When enabled, missing model / warm-up / NaN / import errors fail closed by default.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[str, tuple[float, Any]] = {}


def _resolve_model_path(model_path: str | Path | None) -> Path:
    if model_path is None or str(model_path).strip() == "":
        return Path(__file__).resolve().parent / "artifacts" / "meta_labeler.joblib"
    path = Path(model_path)
    if path.is_absolute():
        return path
    # Try CWD, then repo root (parents: meta_alpha → services → app → api → apps → root)
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate
    repo_root = Path(__file__).resolve().parents[5]
    return repo_root / path


def _fail(
    *,
    reason: str,
    fail_closed: bool,
    warm: bool = False,
    proba: float | None = None,
    regime: int | None = None,
) -> dict[str, Any]:
    return {
        "take": 0 if fail_closed else 1,
        "proba": proba,
        "regime": regime,
        "reason": reason,
        "warm": warm,
    }


def _load_artifact(path: Path) -> Any:
    key = str(path.resolve())
    mtime = path.stat().st_mtime
    cached = _MODEL_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    import joblib

    obj = joblib.load(path)
    _MODEL_CACHE[key] = (mtime, obj)
    return obj


def _unwrap_model(obj: Any, mode: str) -> Any:
    """Accept a raw RegimeSwitchingMetaLabeler or a dict artifact."""
    if isinstance(obj, dict):
        model = obj.get("model") or obj.get("labeler")
        if model is None:
            raise ValueError("artifact dict missing 'model' / 'labeler'")
        return model
    return obj


def decide_take_trade(
    *,
    ohlcv=None,
    candles: Sequence[Any] | None = None,
    primary_side: int,
    enabled: bool = False,
    threshold: float = 0.75,
    model_path: str | Path | None = None,
    mode: str = "feature",
    fail_closed: bool = True,
    min_bars: int = 120,
) -> dict[str, Any]:
    """Decide whether to take a primary ENTRY.

    Returns ``{take: 0|1, proba, regime, reason, warm}``.

    ``primary_side``: ``+1`` BUY / LONG, ``-1`` SELL / SHORT.
    """
    if not enabled:
        return {
            "take": 1,
            "proba": None,
            "regime": None,
            "reason": "meta_alpha_disabled",
            "warm": True,
        }

    try:
        import pandas as pd

        from app.services.meta_alpha.features import (
            FEATURE_COLS,
            build_features_frame,
            candles_to_ohlcv,
        )
        from app.services.meta_alpha.regime_meta_cpcv import compute_regime
    except ImportError as exc:
        logger.warning("meta_alpha import failed (enabled): %s", exc)
        return _fail(reason=f"import_error:{exc}", fail_closed=fail_closed)

    if primary_side not in (1, -1, 1.0, -1.0):
        return _fail(reason="invalid_primary_side", fail_closed=fail_closed)

    side = int(primary_side)

    try:
        if ohlcv is None:
            if candles is None:
                return _fail(reason="no_ohlcv", fail_closed=fail_closed)
            ohlcv = candles_to_ohlcv(candles)
        if not isinstance(ohlcv, pd.DataFrame) or ohlcv.empty:
            return _fail(reason="empty_ohlcv", fail_closed=fail_closed)
        if len(ohlcv) < int(min_bars):
            return _fail(
                reason=f"warmup_bars:{len(ohlcv)}<{min_bars}",
                fail_closed=fail_closed,
                warm=False,
            )

        features = build_features_frame(ohlcv)
        row = features.iloc[[-1]]
        if bool(row.isna().to_numpy().any()):
            return _fail(reason="feature_nan", fail_closed=fail_closed, warm=False)

        close = ohlcv["close"].astype(float)
        high = ohlcv["high"].astype(float)
        low = ohlcv["low"].astype(float)
        regime_s = compute_regime(close, high=high, low=low)
        regime_val = regime_s.iloc[-1]
        if pd.isna(regime_val):
            return _fail(reason="regime_nan", fail_closed=fail_closed, warm=False)
        regime_i = int(regime_val)

        path = _resolve_model_path(model_path)
        if not path.exists():
            return _fail(
                reason=f"no_model:{path.name}",
                fail_closed=fail_closed,
                regime=regime_i,
                warm=True,
            )

        artifact = _load_artifact(path)
        model = _unwrap_model(artifact, mode)

        meta_x = row[list(FEATURE_COLS)].copy()
        meta_x["regime"] = float(regime_i)
        meta_x["primary_side"] = float(side)

        # Optional column filter from artifact metadata
        if isinstance(artifact, dict) and artifact.get("feature_cols"):
            cols = list(artifact["feature_cols"])
            missing = [c for c in cols if c not in meta_x.columns]
            if missing:
                return _fail(
                    reason=f"missing_cols:{','.join(missing)}",
                    fail_closed=fail_closed,
                    regime=regime_i,
                    warm=True,
                )
            meta_x = meta_x[cols]

        proba_s = model.predict_proba(meta_x)
        if hasattr(proba_s, "iloc"):
            proba = float(proba_s.iloc[-1])
        else:
            proba = float(proba_s[-1])

        if proba != proba:  # NaN
            return _fail(
                reason="proba_nan",
                fail_closed=fail_closed,
                regime=regime_i,
                warm=True,
            )

        take = 1 if proba >= float(threshold) else 0
        return {
            "take": take,
            "proba": proba,
            "regime": regime_i,
            "reason": "take" if take else "below_threshold",
            "warm": True,
        }
    except Exception as exc:  # noqa: BLE001 — gate must never crash AUTO
        logger.exception("meta_alpha decide_take_trade failed")
        return _fail(reason=f"error:{type(exc).__name__}", fail_closed=fail_closed)


def clear_model_cache() -> None:
    """Drop cached joblib models (tests / hot-reload)."""
    _MODEL_CACHE.clear()
