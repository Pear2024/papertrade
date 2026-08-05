"""Frozen v1 feature schema for MetaAlpha train/infer (12 columns).

All features are causal: bar ``t`` uses only OHLC(V) data at or before ``t``.
"""

from __future__ import annotations

from typing import Any, Sequence

FEATURE_COLS: tuple[str, ...] = (
    "ret_1",
    "ret_4",
    "ret_16",
    "vol_20",
    "vol_z_100",
    "adx_14",
    "di_spread_14",
    "ema_sep_pct",
    "close_vs_ema9_pct",
    "ema9_slope_4",
    "volume_rel_20",
    "hl_range_pct",
)


def candles_to_ohlcv(candles: Sequence[Any]):
    """Build an OHLCV DataFrame from CandleBar-like objects (``.time``, OHLC, optional volume)."""
    import pandas as pd

    rows = []
    for c in candles:
        rows.append(
            {
                "time": int(c.time),
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume) if getattr(c, "volume", None) is not None else float("nan"),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).drop_duplicates(subset=["time"]).sort_values("time")
    df = df.set_index(pd.to_datetime(df["time"], unit="s", utc=True))
    return df[["open", "high", "low", "close", "volume"]]


def _ema_sma_seed(close, period: int):
    """Match ``coach._ema``: SMA seed then recursive EMA (k = 2/(period+1))."""
    import numpy as np
    import pandas as pd

    values = close.astype(float).to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(out, index=close.index)
    k = 2.0 / (period + 1.0)
    prev = float(np.mean(values[:period]))
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return pd.Series(out, index=close.index)


def _adx_and_di_spread(high, low, close, window: int = 14):
    """ADX / DI spread using the same rolling family as ``compute_regime``."""
    import numpy as np
    import pandas as pd

    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(window).mean()
    plus_di = 100 * pd.Series(plus_dm, index=close.index).rolling(window).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=close.index).rolling(window).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8) * 100
    adx = dx.rolling(window).mean()
    di_spread = plus_di - minus_di
    return adx, di_spread


def build_features_frame(ohlcv) -> "Any":
    """Return a DataFrame with the frozen v1 12 feature columns (aligned to ``ohlcv`` index)."""
    import numpy as np
    import pandas as pd

    if not isinstance(ohlcv, pd.DataFrame):
        raise TypeError("ohlcv must be a pandas DataFrame")
    close = ohlcv["close"].astype(float)
    high = ohlcv["high"].astype(float)
    low = ohlcv["low"].astype(float)
    volume = ohlcv["volume"].astype(float) if "volume" in ohlcv.columns else pd.Series(np.nan, index=ohlcv.index)

    ret_1 = np.log(close / close.shift(1))
    ret_4 = np.log(close / close.shift(4))
    ret_16 = np.log(close / close.shift(16))
    vol_20 = ret_1.rolling(20).std()
    vol_mean = vol_20.rolling(100).mean()
    vol_std = vol_20.rolling(100).std()
    vol_z_100 = (vol_20 - vol_mean) / vol_std.replace(0, np.nan)

    adx_14, di_spread_14 = _adx_and_di_spread(high, low, close, 14)

    ema9 = _ema_sma_seed(close, 9)
    ema21 = _ema_sma_seed(close, 21)
    ema_sep_pct = (ema9 - ema21).abs() / close * 100.0
    close_vs_ema9_pct = (close - ema9) / close * 100.0
    ema9_slope_4 = (ema9 - ema9.shift(4)) / close * 100.0

    vol_sma = volume.rolling(20).mean()
    volume_rel_20 = volume / vol_sma.replace(0, np.nan)
    # Missing volume → neutral 1.0 (contract)
    volume_rel_20 = volume_rel_20.where(volume.notna() & vol_sma.notna(), 1.0)

    hl_range_pct = (high - low) / close * 100.0

    frame = pd.DataFrame(
        {
            "ret_1": ret_1,
            "ret_4": ret_4,
            "ret_16": ret_16,
            "vol_20": vol_20,
            "vol_z_100": vol_z_100,
            "adx_14": adx_14,
            "di_spread_14": di_spread_14,
            "ema_sep_pct": ema_sep_pct,
            "close_vs_ema9_pct": close_vs_ema9_pct,
            "ema9_slope_4": ema9_slope_4,
            "volume_rel_20": volume_rel_20,
            "hl_range_pct": hl_range_pct,
        },
        index=ohlcv.index,
    )
    return frame[list(FEATURE_COLS)]


def latest_feature_row(ohlcv) -> "Any":
    """Return the last feature row as a one-row DataFrame (may contain NaNs if not warm)."""
    frame = build_features_frame(ohlcv)
    if frame.empty:
        return frame
    return frame.iloc[[-1]]
