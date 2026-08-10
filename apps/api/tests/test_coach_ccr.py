from app.services.coach_ccr import (
    OHLC,
    clamp_ccr_consecutive,
    ccr_buy_at,
)


def bar(open_: float, high: float, low: float, close: float) -> OHLC:
    return OHLC(open_, high, low, close)


def test_buy_confirms_only_after_required_bearish_streak() -> None:
    bars = [
        bar(10, 11, 8, 9),
        bar(9, 10, 7, 8),
        bar(8, 12, 7.5, 11),
        bar(11.5, 12, 11, 11.75),
    ]

    assert ccr_buy_at(bars, 2, 2)
    # The entry is intentionally the following bar's open, not confirmation close.
    assert bars[3].open == 11.5


def test_bearish_mirror_is_not_a_ccr_entry() -> None:
    bars = [
        bar(8, 10, 7, 9),
        bar(9, 11, 8, 10),
        bar(10, 10.5, 6, 7),
        bar(6.5, 7, 6, 6.25),
    ]

    assert not ccr_buy_at(bars, 2, 2)


def test_confirmation_must_break_the_prior_extreme() -> None:
    buy_bars = [
        bar(10, 11, 8, 9),
        bar(9, 10, 7, 8),
        bar(8, 9.5, 7.5, 9),
    ]
    assert not ccr_buy_at(buy_bars, 2, 2)


def test_forming_bar_is_not_evaluated_until_passed_as_closed() -> None:
    bars = [
        bar(10, 11, 8, 9),
        bar(9, 10, 7, 8),
        bar(8, 12, 7.5, 11),
    ]

    # A caller evaluating only closed bars must use the prior index.
    assert not ccr_buy_at(bars, 1, 2)
    assert ccr_buy_at(bars, 2, 2)


def test_one_confirmation_index_yields_one_signal() -> None:
    bars = [
        bar(10, 11, 8, 9),
        bar(9, 10, 7, 8),
        bar(8, 12, 7.5, 11),
        bar(11, 12, 10, 10.5),
    ]

    assert [i for i in range(len(bars)) if ccr_buy_at(bars, i, 2)] == [2]


def test_consecutive_count_is_clamped() -> None:
    assert clamp_ccr_consecutive(None) == 3
    assert clamp_ccr_consecutive(-1) == 2
    assert clamp_ccr_consecutive(2) == 2
    assert clamp_ccr_consecutive(6) == 6
    assert clamp_ccr_consecutive(99) == 6
