"""Configurable BUY Confidence Score (0–10) with causal, closed-bar inputs only.

Look-ahead rules:
- Indicators use data through closed bar ``i`` only.
- Higher Low / resistance use confirmed pivots via ``structure_setup_at``
  (pivot needs ``lookback`` bars AFTER the pivot and BEFORE/AT ``i``).
- Volume average uses prior bars ``[i-20:i]`` (excludes the signal bar).
- Bullish candle patterns use bars ``i`` and ``i-1`` only.
- Execution still fills at the *next* open (caller / simulator).
"""
from __future__ import annotations

from typing import Any, Callable

BUY_CONFIDENCE_DEFAULT: dict[str, Any] = {
    "enabled": False,
    "weights": {
        "ema200_uptrend": 2,
        "price_above_ema200": 1,
        "ema9_above_ema21": 1,
        "higher_low": 2,
        "break_resistance": 1,
        "volume_surge": 2,
        "bullish_candle": 1,
    },
    "thresholds": {
        "no_buy_max": 4,
        "wait_max": 7,
        "strong_min": 8,
    },
    "execute_min_score": 8,
    "require_closed_bar": True,
    "volume_multiple": 1.5,
    "ema200_slope_bars": 5,
    "swing_lookback": 3,
    "bullish_close_body_pct": 0.55,
}


def normalize_buy_confidence(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user overrides into safe bounded defaults."""
    out = {
        "enabled": bool(BUY_CONFIDENCE_DEFAULT["enabled"]),
        "weights": dict(BUY_CONFIDENCE_DEFAULT["weights"]),
        "thresholds": dict(BUY_CONFIDENCE_DEFAULT["thresholds"]),
        "execute_min_score": int(BUY_CONFIDENCE_DEFAULT["execute_min_score"]),
        "require_closed_bar": True,  # always causal — never disable for live/backtest
        "volume_multiple": float(BUY_CONFIDENCE_DEFAULT["volume_multiple"]),
        "ema200_slope_bars": int(BUY_CONFIDENCE_DEFAULT["ema200_slope_bars"]),
        "swing_lookback": int(BUY_CONFIDENCE_DEFAULT["swing_lookback"]),
        "bullish_close_body_pct": float(BUY_CONFIDENCE_DEFAULT["bullish_close_body_pct"]),
    }
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("enabled"), bool):
        out["enabled"] = raw["enabled"]
    weights = raw.get("weights")
    if isinstance(weights, dict):
        for key in out["weights"]:
            try:
                value = float(weights[key])
            except (KeyError, TypeError, ValueError):
                continue
            out["weights"][key] = max(0.0, min(10.0, value))
    thresholds = raw.get("thresholds")
    if isinstance(thresholds, dict):
        for key in ("no_buy_max", "wait_max", "strong_min"):
            try:
                out["thresholds"][key] = int(thresholds[key])
            except (KeyError, TypeError, ValueError):
                continue
    try:
        out["execute_min_score"] = int(raw.get("execute_min_score", out["execute_min_score"]))
    except (TypeError, ValueError):
        pass
    out["execute_min_score"] = max(0, min(10, out["execute_min_score"]))
    for name, lo, hi, cast in (
        ("volume_multiple", 0.1, 10.0, float),
        ("ema200_slope_bars", 1, 50, int),
        ("swing_lookback", 2, 20, int),
        ("bullish_close_body_pct", 0.1, 1.0, float),
    ):
        if raw.get(name) is None:
            continue
        try:
            out[name] = cast(max(lo, min(hi, cast(raw[name]))))
        except (TypeError, ValueError):
            continue
    # Keep threshold ordering coherent.
    t = out["thresholds"]
    t["no_buy_max"] = max(0, min(9, int(t["no_buy_max"])))
    t["wait_max"] = max(t["no_buy_max"] + 1, min(9, int(t["wait_max"])))
    t["strong_min"] = max(t["wait_max"] + 1, min(10, int(t["strong_min"])))
    return out


def label_for_score(score: float, thresholds: dict[str, int]) -> str:
    if score <= float(thresholds.get("no_buy_max", 4)):
        return "NO_BUY"
    if score <= float(thresholds.get("wait_max", 7)):
        return "WAIT_WATCH"
    return "STRONG_BUY"


def _bullish_candle(bars: list, i: int, body_pct: float) -> tuple[bool, str]:
    """Causal candle patterns using only bars i and i-1."""
    if i < 1:
        return False, "need prior bar"
    cur, prev = bars[i], bars[i - 1]
    rng = cur.high - cur.low
    if rng <= 0:
        return False, "zero range"
    body = abs(cur.close - cur.open)
    upper = cur.high - max(cur.open, cur.close)
    lower = min(cur.open, cur.close) - cur.low
    bullish = cur.close > cur.open

    # Bullish engulfing (closed bars only).
    engulf = (
        bullish
        and prev.close < prev.open
        and cur.open <= prev.close
        and cur.close >= prev.open
        and body >= abs(prev.close - prev.open)
    )
    if engulf:
        return True, "bullish engulfing"

    # Hammer / rejection: long lower wick, small upper, closes in upper half.
    hammer = (
        bullish
        and lower >= 1.5 * body
        and upper <= body * 0.6
        and (cur.close - cur.low) / rng >= 0.6
    )
    if hammer:
        return True, "hammer/rejection"

    # Strong bullish close: green + close in upper portion of range.
    strong = bullish and (cur.close - cur.low) / rng >= body_pct and body / rng >= 0.35
    if strong:
        return True, "strong bullish close"
    return False, "no bullish confirmation"


def score_closed_bar(
    *,
    bars: list,
    i: int,
    ema9: list[float | None],
    ema21: list[float | None],
    ema200: list[float | None],
    conf: dict[str, Any],
    structure_setup: Callable[[list, int, int], dict[str, Any] | None],
) -> dict[str, Any]:
    """Score one *closed* bar. Never reads bars after ``i``."""
    weights = conf["weights"]
    lookback = int(conf.get("swing_lookback") or 3)
    slope_n = int(conf.get("ema200_slope_bars") or 5)
    vol_mult = float(conf.get("volume_multiple") or 1.5)
    body_pct = float(conf.get("bullish_close_body_pct") or 0.55)
    bar = bars[i]
    conditions: list[dict[str, Any]] = []

    def add(cid: str, passed: bool, detail: str) -> None:
        max_pts = float(weights.get(cid, 0))
        conditions.append(
            {
                "id": cid,
                "passed": bool(passed),
                "points": max_pts if passed else 0.0,
                "max_points": max_pts,
                "detail": detail,
            }
        )

    # 1) EMA200 trending upward (+2)
    e200 = ema200[i] if i < len(ema200) else None
    e200_prev = ema200[i - slope_n] if i >= slope_n and i - slope_n < len(ema200) else None
    uptrend = bool(e200 is not None and e200_prev is not None and e200 > e200_prev)
    add(
        "ema200_uptrend",
        uptrend,
        f"EMA200[{i}]={e200:.4g} vs EMA200[{i - slope_n}]={e200_prev:.4g}"
        if e200 is not None and e200_prev is not None
        else f"need {slope_n} bars of EMA200",
    )

    # 2) Price above EMA200 (+1)
    above = bool(e200 is not None and bar.close > e200)
    add(
        "price_above_ema200",
        above,
        f"close {bar.close:.4g} vs EMA200 {e200:.4g}" if e200 is not None else "EMA200 n/a",
    )

    # 3) EMA9 above EMA21 (+1)
    e9, e21 = (ema9[i] if i < len(ema9) else None), (ema21[i] if i < len(ema21) else None)
    ema_ok = bool(e9 is not None and e21 is not None and e9 > e21)
    add(
        "ema9_above_ema21",
        ema_ok,
        f"EMA9 {e9:.4g} > EMA21 {e21:.4g}" if e9 is not None and e21 is not None else "EMA n/a",
    )

    # 4–5) Confirmed HL + resistance break (causal pivots only)
    setup = structure_setup(bars, i, lookback)
    hl_ok = bool(setup and setup.get("higher_low"))
    add(
        "higher_low",
        hl_ok,
        f"confirmed HL low={setup.get('hl_low')}" if hl_ok else "no confirmed higher low at as_of=i",
    )
    brk = bool(setup and setup.get("break_swing_high"))
    add(
        "break_resistance",
        brk,
        f"close>swing high {setup.get('swing_high')}" if brk else "no resistance break",
    )

    # 6) Volume surge vs prior VolMA20 (+2) — average excludes bar i
    if i >= 20:
        prior_avg = sum(x.volume for x in bars[i - 20 : i]) / 20.0
        vol_ok = prior_avg > 0 and bar.volume > vol_mult * prior_avg
        add(
            "volume_surge",
            vol_ok,
            f"vol {bar.volume:.4g} > {vol_mult:g}× prior VolMA20 {prior_avg:.4g}",
        )
    else:
        add("volume_surge", False, "need 20 prior bars for VolMA")

    # 7) Bullish candle (+1)
    candle_ok, candle_detail = _bullish_candle(bars, i, body_pct)
    add("bullish_candle", candle_ok, candle_detail)

    score = float(sum(c["points"] for c in conditions))
    max_score = float(sum(c["max_points"] for c in conditions)) or 10.0
    # Absolute points (default sum=10). Cap at 10; do not rescale — keeps thresholds stable.
    score_10 = min(10.0, score)
    label = label_for_score(score_10, conf["thresholds"])
    execute = score_10 >= float(conf["execute_min_score"]) and bool(conf.get("require_closed_bar", True))
    return {
        "score": round(score_10, 3),
        "raw_points": round(score, 3),
        "max_points": round(max_score, 3),
        "label": label,
        "execute": execute,
        "conditions": conditions,
        "closed_bar": True,
        "bar_time": int(bar.time),
    }
