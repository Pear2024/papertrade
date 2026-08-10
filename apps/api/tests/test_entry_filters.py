from dataclasses import dataclass
from decimal import Decimal

from app.services.entry_filters import evaluate_buy_filters


@dataclass
class Candle:
    open: Decimal
    close: Decimal


def _results(enabled: dict[str, bool], *, entry_signal: str = "ccr", bar_time: int = 1_704_074_401):
    candles = [
        Candle(Decimal("10"), Decimal("9")),
        Candle(Decimal("9"), Decimal("8")),
        Candle(Decimal("8"), Decimal("7")),
        Candle(Decimal("7"), Decimal("6")),
        Candle(Decimal("6"), Decimal("8")),
    ]
    return evaluate_buy_filters(
        entry_signal=entry_signal,
        enabled=enabled,
        candles=candles,
        confirmation_idx=4,
        ema9=Decimal("9"),
        ema21=Decimal("10"),
        volume=Decimal("120"),
        volume_avg20=Decimal("100"),
        bar_time=bar_time,
    )


def test_each_enabled_filter_passes_with_closed_bar_data() -> None:
    results, blocked, set_id = _results(
        {
            "volumeConfirmGtAvg20": True,
            "bearishStreakMin4": True,
            "belowBothEma": True,
            "afterBangkok0800": True,
        }
    )
    assert not blocked
    assert all(item.passed for item in results)
    assert set_id.startswith("ccr:")


def test_volume_filter_failure_blocks_only_when_enabled() -> None:
    results, blocked, _ = _results({"volumeConfirmGtAvg20": True})
    # Make a direct failing case with average above current volume.
    assert next(item for item in results if item.id == "volumeConfirmGtAvg20").passed
    candles = [Candle(Decimal("10"), Decimal("9"))] * 5
    results, blocked, _ = evaluate_buy_filters(
        entry_signal="ccr", enabled={"volumeConfirmGtAvg20": True}, candles=candles,
        confirmation_idx=4, ema9=Decimal("9"), ema21=Decimal("10"),
        volume=Decimal("99"), volume_avg20=Decimal("100"), bar_time=1_704_074_401,
    )
    assert blocked
    assert not results[0].passed


def test_bearish_streak_is_ccr_only_and_a4_passes_through() -> None:
    results, blocked, _ = _results({"bearishStreakMin4": True}, entry_signal="a4")
    streak = next(item for item in results if item.id == "bearishStreakMin4")
    assert streak.applicable is False
    assert streak.passed is True
    assert blocked is False


def test_short_ccr_bearish_streak_blocks_but_disabled_filter_does_not() -> None:
    candles = [
        Candle(Decimal("10"), Decimal("9")),
        Candle(Decimal("9"), Decimal("8")),
        Candle(Decimal("8"), Decimal("10")),
    ]
    results, blocked, _ = evaluate_buy_filters(
        entry_signal="ccr", enabled={"bearishStreakMin4": True}, candles=candles,
        confirmation_idx=2, ema9=Decimal("11"), ema21=Decimal("12"),
        volume=Decimal("2"), volume_avg20=Decimal("1"), bar_time=1_704_074_401,
    )
    assert blocked
    assert not next(item for item in results if item.id == "bearishStreakMin4").passed
    _, disabled_blocked, _ = evaluate_buy_filters(
        entry_signal="ccr", enabled={}, candles=candles, confirmation_idx=2,
        ema9=Decimal("11"), ema21=Decimal("12"), volume=Decimal("2"),
        volume_avg20=Decimal("1"), bar_time=1_704_074_401,
    )
    assert disabled_blocked is False


def test_below_ema_and_bangkok_time_fail() -> None:
    candles = [Candle(Decimal("7"), Decimal("8"))] * 5
    results, blocked, _ = evaluate_buy_filters(
        entry_signal="ccr",
        enabled={"belowBothEma": True, "afterBangkok0800": True},
        candles=candles,
        confirmation_idx=4,
        ema9=Decimal("7"),
        ema21=Decimal("7"),
        volume=Decimal("1"),
        volume_avg20=Decimal("1"),
        bar_time=1_704_070_800,  # 08:00:00 Asia/Bangkok exactly
    )
    assert blocked
    assert all(not item.passed for item in results if item.enabled)
