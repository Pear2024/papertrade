"""Consecutive Candle Reversal (CCR) — BUY-only primary entry setup.

BUY (after confirmation candle closes; fill on next open):
  - At least N consecutive bearish candles (close < open)
  - Confirmation candle bullish (close > open)
  - Confirmation close > previous candle high

Causal / no leakage: only uses bars at index <= confirmation index.
No repaint: pattern is fixed once the confirmation bar is closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# Default streak length (configurable 2–6 via API / settings).
CCR_CONSECUTIVE_DEFAULT = 3
CCR_CONSECUTIVE_MIN = 2
CCR_CONSECUTIVE_MAX = 6


@dataclass(frozen=True)
class OHLC:
    open: float
    high: float
    low: float
    close: float


def clamp_ccr_consecutive(n: int | None) -> int:
    if n is None:
        return CCR_CONSECUTIVE_DEFAULT
    try:
        v = int(n)
    except (TypeError, ValueError):
        return CCR_CONSECUTIVE_DEFAULT
    return max(CCR_CONSECUTIVE_MIN, min(CCR_CONSECUTIVE_MAX, v))


def _bearish(c: OHLC) -> bool:
    return c.close < c.open


def _bullish(c: OHLC) -> bool:
    return c.close > c.open


def ccr_buy_at(bars: Sequence[OHLC], i: int, consecutive: int) -> bool:
    """True if bar i is a closed CCR BUY confirmation (causal)."""
    n = clamp_ccr_consecutive(consecutive)
    # Need n bearish bars before i, plus confirmation at i → indices i-n .. i
    if i < n or i >= len(bars):
        return False
    conf = bars[i]
    prev = bars[i - 1]
    if not _bullish(conf):
        return False
    if not (conf.close > prev.high):
        return False
    for j in range(i - n, i):
        if not _bearish(bars[j]):
            return False
    return True


