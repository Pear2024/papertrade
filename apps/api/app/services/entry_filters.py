"""Pure, closed-bar BUY entry filter evaluation for paper experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

FILTER_VERSION = "buy-filters-v1"
FILTER_IDS = (
    "volumeConfirmGtAvg20",
    "bearishStreakMin4",
    "belowBothEma",
    "afterBangkok0800",
)


@dataclass(frozen=True)
class FilterResult:
    id: str
    label: str
    enabled: bool
    passed: bool
    applicable: bool = True
    reason: str = ""

    def snapshot(self) -> dict:
        return asdict(self)


def enabled_filter_ids(filters: dict[str, bool] | None) -> list[str]:
    filters = filters or {}
    return [filter_id for filter_id in FILTER_IDS if bool(filters.get(filter_id, False))]


def filter_set_id(entry_signal: str | None, filters: dict[str, bool] | None) -> str:
    enabled = enabled_filter_ids(filters)
    suffix = "+".join(enabled) if enabled else "baseline"
    return f"{(entry_signal or 'unknown').lower()}:{suffix}:{FILTER_VERSION}"


def _bearish_streak_before(
    candles: list[object], confirmation_idx: int
) -> int:
    count = 0
    # Excludes the confirmation bar; CCR's bearish run must precede it.
    for candle in reversed(candles[:confirmation_idx]):
        if Decimal(str(candle.close)) < Decimal(str(candle.open)):
            count += 1
        else:
            break
    return count


def evaluate_buy_filters(
    *,
    entry_signal: str | None,
    enabled: dict[str, bool] | None,
    candles: list[object],
    confirmation_idx: int,
    ema9: Decimal | None,
    ema21: Decimal | None,
    volume: Decimal | None,
    volume_avg20: Decimal | None,
    bar_time: int | None,
) -> tuple[list[FilterResult], bool, str]:
    """Evaluate each filter from data available on the selected closed bar only."""
    enabled = enabled or {}
    is_ccr = entry_signal == "ccr"
    close = Decimal(str(candles[confirmation_idx].close))
    streak = _bearish_streak_before(candles, confirmation_idx)
    bangkok_time = (
        datetime.fromtimestamp(bar_time, tz=timezone.utc).astimezone(ZoneInfo("Asia/Bangkok"))
        if bar_time is not None
        else None
    )
    after_0800 = bool(
        bangkok_time
        and (bangkok_time.hour, bangkok_time.minute, bangkok_time.second) > (8, 0, 0)
    )
    values = {
        "volumeConfirmGtAvg20": (
            volume is not None
            and volume_avg20 is not None
            and volume_avg20 > 0
            and volume > volume_avg20,
            f"confirmation volume {volume or 'n/a'} > prior-20 average {volume_avg20 or 'n/a'}",
        ),
        "bearishStreakMin4": (
            streak >= 4,
            f"{streak} consecutive bearish candles before confirmation (need ≥4)",
        ),
        "belowBothEma": (
            ema9 is not None and ema21 is not None and close < ema9 and close < ema21,
            f"closed price {close} below EMA9 {ema9} and EMA21 {ema21}",
        ),
        "afterBangkok0800": (
            after_0800,
            f"signal time {bangkok_time.strftime('%H:%M:%S ICT') if bangkok_time else 'n/a'} > 08:00 ICT",
        ),
    }
    labels = {
        "volumeConfirmGtAvg20": "Confirmation volume > prior 20-bar average",
        "bearishStreakMin4": "CCR: ≥4 bearish candles before confirmation",
        "belowBothEma": "Closed reference price below EMA9 and EMA21",
        "afterBangkok0800": "Signal after 08:00 Asia/Bangkok",
    }
    results: list[FilterResult] = []
    for filter_id in FILTER_IDS:
        applicable = filter_id != "bearishStreakMin4" or is_ccr
        passed, reason = values[filter_id]
        if not applicable:
            passed, reason = True, "N/A for A4 BUY — pass-through"
        results.append(
            FilterResult(
                id=filter_id,
                label=labels[filter_id],
                enabled=bool(enabled.get(filter_id, False)),
                passed=passed,
                applicable=applicable,
                reason=reason,
            )
        )
    blocked = any(item.enabled and not item.passed for item in results)
    return results, blocked, filter_set_id(entry_signal, enabled)
