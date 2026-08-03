"""Unit tests for Decimal money helpers."""

from decimal import Decimal

from app.core.money import (
    calculate_fee,
    realized_pnl_on_sell,
    unrealized_pnl,
    weighted_average_entry,
)


def test_calculate_fee() -> None:
    # 0.10% of 10.00 = 0.01 (percent mode when fee_usd omitted)
    assert calculate_fee(Decimal("10.00"), "0.10") == Decimal("0.01000000")


def test_calculate_fee_flat_usd() -> None:
    assert calculate_fee(Decimal("500.00"), "0.05", "0.04") == Decimal("0.04000000")
    assert calculate_fee(Decimal("10.00"), "0.10", "0") == Decimal("0.01000000")


def test_weighted_average_entry() -> None:
    avg = weighted_average_entry(
        existing_qty=Decimal("1"),
        existing_avg=Decimal("100"),
        add_qty=Decimal("1"),
        add_price=Decimal("200"),
    )
    assert avg == Decimal("150.00000000")


def test_realized_pnl_on_sell() -> None:
    # Bought at 100, sell 1 at 110, fee 0.11 -> pnl 9.89
    pnl = realized_pnl_on_sell(
        sell_qty=Decimal("1"),
        sell_price=Decimal("110"),
        average_entry=Decimal("100"),
        fee_amount=Decimal("0.11"),
    )
    assert pnl == Decimal("9.89000000")


def test_unrealized_pnl() -> None:
    pnl = unrealized_pnl(
        qty=Decimal("2"),
        average_entry=Decimal("50"),
        current_price=Decimal("55"),
    )
    assert pnl == Decimal("10.00000000")
