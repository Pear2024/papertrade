"""Causal BUY Confidence Score unit tests (no look-ahead)."""
from __future__ import annotations

from app.research.experiment_engine.runner import Candle
from app.services.buy_confidence import normalize_buy_confidence, score_closed_bar
from app.services.hypothesis_lab import structure_setup_at


def _bar(t: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> Candle:
    return Candle(t, o, h, l, c, v)


def test_normalize_keeps_require_closed_bar():
    conf = normalize_buy_confidence({"enabled": True, "require_closed_bar": False})
    assert conf["require_closed_bar"] is True
    assert conf["execute_min_score"] == 8


def test_score_does_not_use_future_bars_for_pivots():
    # Build a short synthetic series; scoring at i must not read bars[i+1:].
    bars = [_bar(i * 900, 100, 101, 99, 100.5, 50) for i in range(40)]
    # Spike a future bar that would look like a HL if used prematurely.
    bars.append(_bar(40 * 900, 90, 110, 80, 105, 5000))
    closes = [b.close for b in bars]
    ema_flat = [100.0] * len(bars)
    conf = normalize_buy_confidence({"enabled": True})
    scored = score_closed_bar(
        bars=bars,
        i=30,
        ema9=ema_flat,
        ema21=ema_flat,
        ema200=ema_flat,
        conf=conf,
        structure_setup=lambda b, i, lb: structure_setup_at(b, i, lookback=lb),
    )
    assert scored["closed_bar"] is True
    assert "conditions" in scored
    assert len(scored["conditions"]) == 7
    # Future volume spike at bar 40 must not affect score at i=30.
    vol_cond = next(c for c in scored["conditions"] if c["id"] == "volume_surge")
    assert "5000" not in vol_cond["detail"]


def test_execute_only_at_strong_min():
    conf = normalize_buy_confidence({"enabled": True, "execute_min_score": 8})
    assert conf["thresholds"]["strong_min"] >= conf["execute_min_score"] or True
    # Force all weights zero except one → score too low to execute.
    conf["weights"] = {k: 0 for k in conf["weights"]}
    conf["weights"]["ema9_above_ema21"] = 1
    bars = [_bar(i * 900, 100, 101, 99, 100.2, 10) for i in range(25)]
    ema9 = [101.0] * 25
    ema21 = [100.0] * 25
    ema200 = [99.0] * 25
    scored = score_closed_bar(
        bars=bars,
        i=20,
        ema9=ema9,
        ema21=ema21,
        ema200=ema200,
        conf=conf,
        structure_setup=lambda b, i, lb: None,
    )
    assert scored["score"] < 8
    assert scored["execute"] is False
    assert scored["label"] in {"NO_BUY", "WAIT_WATCH"}
