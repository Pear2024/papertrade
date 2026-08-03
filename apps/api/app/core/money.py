"""Decimal helpers for money and quantity — never use float for balances."""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

MONEY_QUANT = Decimal("0.00000001")
QTY_QUANT = Decimal("0.000000000001")
PERCENT_QUANT = Decimal("0.0001")


def to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value: Decimal | int | str) -> Decimal:
    return to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def quantity(value: Decimal | int | str) -> Decimal:
    return to_decimal(value).quantize(QTY_QUANT, rounding=ROUND_DOWN)


def percent(value: Decimal | int | str) -> Decimal:
    return to_decimal(value).quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)


def fee_rate_from_percent(fee_percent: Decimal | str) -> Decimal:
    """Convert 0.10 (meaning 0.10%) into a fractional rate 0.001."""
    return to_decimal(fee_percent) / Decimal("100")


def calculate_fee(
    gross_amount: Decimal,
    fee_percent: Decimal | str,
    fee_usd: Decimal | str | None = None,
) -> Decimal:
    """Paper fee per fill. Prefer flat USD when fee_usd > 0; else percent of gross."""
    if fee_usd is not None and to_decimal(fee_usd) > 0:
        return money(fee_usd)
    return money(to_decimal(gross_amount) * fee_rate_from_percent(fee_percent))


def buy_cost(gross_amount: Decimal, fee_amount: Decimal) -> Decimal:
    """Cash deducted on buy = gross + fee."""
    return money(to_decimal(gross_amount) + to_decimal(fee_amount))


def sell_proceeds(gross_amount: Decimal, fee_amount: Decimal) -> Decimal:
    """Cash credited on sell = gross - fee."""
    return money(to_decimal(gross_amount) - to_decimal(fee_amount))


def quantity_from_usd(usd_amount: Decimal, price: Decimal) -> Decimal:
    if to_decimal(price) <= 0:
        raise ValueError("Price must be positive")
    return quantity(to_decimal(usd_amount) / to_decimal(price))


def clamp_leverage(leverage: Decimal | int | str | None) -> Decimal:
    """Paper futures leverage: 1x–50x (1 = spot-style cash accounting)."""
    lev = to_decimal(leverage if leverage is not None else 1)
    if lev < 1:
        return Decimal("1")
    if lev > 50:
        return Decimal("50")
    return lev.quantize(Decimal("0.01"))


def margin_locked(
    qty: Decimal,
    entry_price: Decimal,
    leverage: Decimal | int | str | None,
) -> Decimal:
    """Initial margin ≈ |qty|×entry / leverage (leverage≤1 → full notional)."""
    notional = abs(to_decimal(qty)) * to_decimal(entry_price)
    lev = clamp_leverage(leverage)
    if lev <= 1:
        return money(notional)
    return money(notional / lev)


def weighted_average_entry(
    existing_qty: Decimal,
    existing_avg: Decimal,
    add_qty: Decimal,
    add_price: Decimal,
) -> Decimal:
    total_qty = to_decimal(existing_qty) + to_decimal(add_qty)
    if total_qty <= 0:
        return money(0)
    total_cost = (to_decimal(existing_qty) * to_decimal(existing_avg)) + (
        to_decimal(add_qty) * to_decimal(add_price)
    )
    return money(total_cost / total_qty)


def realized_pnl_on_sell(
    sell_qty: Decimal,
    sell_price: Decimal,
    average_entry: Decimal,
    fee_amount: Decimal,
) -> Decimal:
    """Realized P&L after fee for closing a LONG (sell fill)."""
    gross = to_decimal(sell_qty) * to_decimal(sell_price)
    cost_basis = to_decimal(sell_qty) * to_decimal(average_entry)
    return money(gross - cost_basis - to_decimal(fee_amount))


def realized_pnl_on_cover(
    cover_qty: Decimal,
    cover_price: Decimal,
    average_entry: Decimal,
    fee_amount: Decimal,
) -> Decimal:
    """Realized P&L after fee for closing a SHORT (buy-to-cover)."""
    # Short profit when cover_price < entry.
    gross = (to_decimal(average_entry) - to_decimal(cover_price)) * to_decimal(cover_qty)
    return money(gross - to_decimal(fee_amount))


def unrealized_pnl(
    qty: Decimal,
    average_entry: Decimal,
    current_price: Decimal,
) -> Decimal:
    """Works for LONG (+qty) and SHORT (−qty)."""
    return money(
        (to_decimal(current_price) - to_decimal(average_entry)) * to_decimal(qty)
    )


def market_value(qty: Decimal, price: Decimal) -> Decimal:
    return money(to_decimal(qty) * to_decimal(price))


def mark_market_value(
    qty: Decimal,
    entry_price: Decimal,
    current_price: Decimal,
    leverage: Decimal | int | str | None,
) -> Decimal:
    """Spot: qty×price. Leveraged paper: locked margin + unrealized PnL."""
    lev = clamp_leverage(leverage)
    upnl = unrealized_pnl(qty, entry_price, current_price)
    if lev <= 1:
        return market_value(qty, current_price)
    return money(margin_locked(qty, entry_price, lev) + upnl)


def position_side_from_qty(qty: Decimal) -> str | None:
    q = to_decimal(qty)
    if q > 0:
        return "long"
    if q < 0:
        return "short"
    return None
