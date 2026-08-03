"""Version B — EXPERIMENTAL exit filters (paper research only).

IMPORTANT
- Version A (coach_brain.py) remains the locked production strategy.
- This module must NEVER auto-replace A.
- Promote B → new baseline only after clear multi-market paper evidence
  and an explicit human decision (see coach_baseline.py).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.services.coach import (
    INTERVAL_SECONDS,
    CoachVerdict,
    _htf_bias,
    _short_reason,
    evaluate_daytrade_signal,
)
from app.services.coach_brain import HIGHER_TF_FOR_ENTRY
from app.services.prices import get_candles

VERSION_B_NAME = "DayTradeCryptoCoach-Experiment-B"

VERSION_B_NOTES = """
Version B (experiment account) mirrors promoted baseline A2 exit filters.

Entry: identical to locked DayTradeCryptoCoach.
Exit: SL/TP immediate; technical SELL only when HTF is no longer bullish + min hold 2 bars.

Paper B account remains isolated for regression / future experiments.
Do not auto-replace locked coach_brain.py from this module.
""".strip()

# Same distances as A so comparison isolates exit filtering.
B_SL_PCT = 0.02
B_TP_PCT = 0.03
B_MIN_HOLD_BARS = 2


def bars_held_since(entry_ts: datetime | None, interval: str, now: datetime | None = None) -> int:
    """Closed entry-TF bars elapsed since fill (floor)."""
    if entry_ts is None:
        return 0
    now = now or datetime.now(timezone.utc)
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.replace(tzinfo=timezone.utc)
    seconds = INTERVAL_SECONDS.get(interval.strip().lower(), 900)
    elapsed = max(0, int(now.timestamp()) - int(entry_ts.timestamp()))
    return elapsed // seconds


async def evaluate_daytrade_signal_b(
    db: Session,
    symbol: str,
    interval: str = "15m",
    *,
    bars_held: int = 0,
) -> CoachVerdict:
    """Same entry as locked A; filter premature technical SELLs for experiment B."""
    verdict = await evaluate_daytrade_signal(db, symbol, interval)
    if verdict.signal != "SELL" or not verdict.bar_closed:
        return replace(verdict, brain=VERSION_B_NAME)

    now = datetime.now(timezone.utc)
    interval_key = interval.strip().lower()
    htf_key = HIGHER_TF_FOR_ENTRY.get(interval_key, "1h")
    htf_bullish: bool | None = None
    try:
        _s, htf_iv, _src, htf_candles = await get_candles(db, symbol, htf_key, 120)
        htf_bullish, _bear, htf_note = _htf_bias(htf_candles, htf_iv, now)
    except Exception:
        htf_note = "HTF unavailable"
        htf_bullish = None

    hold_ok = bars_held >= B_MIN_HOLD_BARS
    # Technical SELL allowed only when HTF is no longer bullish AND min hold met.
    allow_sell = hold_ok and htf_bullish is not True
    if allow_sell:
        return replace(
            verdict,
            brain=VERSION_B_NAME,
            reason=f"{verdict.reason} | B-filter: HTF not bullish + hold>={B_MIN_HOLD_BARS}",
            short_reason=f"SELL (B) — HTF exit ok; held {bars_held} bars.",
        )

    block_bits: list[str] = []
    if not hold_ok:
        block_bits.append(f"min hold {bars_held}/{B_MIN_HOLD_BARS} bars")
    if htf_bullish is True:
        block_bits.append(f"{htf_note} still bullish")
    blocked = "; ".join(block_bits) or "B exit filter"
    return replace(
        verdict,
        signal="WAIT",
        brain=VERSION_B_NAME,
        reason=(
            f"WAIT (B): technical SELL deferred — {blocked}. "
            "SL/TP still honored immediately."
        ),
        cofr=f"C:{verdict.confidence} | O:b-exit-filter | F:WAIT | R:hold",
        short_reason=_short_reason("WAIT", notes=block_bits, forming=False),
        stop_loss=None,
        take_profit=None,
        risk_reward=None,
    )


def b_allows_technical_sell(*, htf_bullish: bool | None, bars_held: int) -> bool:
    return bars_held >= B_MIN_HOLD_BARS and htf_bullish is not True
