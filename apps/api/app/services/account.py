"""Account summary helpers."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.money import money, to_decimal
from app.models import Position, TradingAccount, User
from app.schemas.account import AccountResponse, AccountSummaryResponse, PositionSummary
from app.services.prices import PriceQuote, get_price_quotes
from app.services.trading import (
    apply_position_mark,
    count_trades_today,
    daily_realized_pnl,
    get_paper_account_for_user,
    get_risk_rules,
)


async def refresh_positions_mark_to_market(
    db: Session,
    account: TradingAccount,
    quotes: dict[str, PriceQuote],
) -> list[Position]:
    positions = list(
        db.scalars(
            select(Position)
            .options(joinedload(Position.asset))
            .where(Position.trading_account_id == account.id)
        )
    )
    for position in positions:
        quote = quotes.get(position.asset.symbol)
        if quote is None:
            continue
        apply_position_mark(position, quote.price)
    db.flush()
    return positions


def account_to_response(account: TradingAccount) -> AccountResponse:
    rules = account.risk_rules
    return AccountResponse(
        id=account.id,
        account_name=account.account_name,
        account_mode=account.account_mode.value,
        starting_balance=account.starting_balance,
        cash_balance=account.cash_balance,
        realized_pnl=account.realized_pnl,
        currency=account.currency,
        is_active=account.is_active,
        trading_enabled=rules.trading_enabled if rules else True,
        require_stop_loss=rules.require_stop_loss if rules else True,
        max_risk_percent_per_trade=rules.max_risk_percent_per_trade if rules else Decimal("2"),
        max_daily_loss_percent=rules.max_daily_loss_percent if rules else Decimal("5"),
        max_trades_per_day=rules.max_trades_per_day if rules else 100,
    )


async def get_account_summary(db: Session, user: User) -> AccountSummaryResponse:
    account = get_paper_account_for_user(db, user)
    get_risk_rules(db, account)
    quotes_list = await get_price_quotes(db)
    quotes = {q.symbol: q for q in quotes_list}
    positions = await refresh_positions_mark_to_market(db, account, quotes)
    db.commit()

    unrealized = money(
        sum((to_decimal(p.unrealized_pnl) for p in positions), Decimal("0"))
    )
    positions_value = money(
        sum((to_decimal(p.market_value) for p in positions), Decimal("0"))
    )
    portfolio_value = money(to_decimal(account.cash_balance) + positions_value)
    day_pnl = daily_realized_pnl(db, account.id)
    trades_today = count_trades_today(db, account.id)

    position_rows = [
        PositionSummary(
            symbol=p.asset.symbol,
            quantity=p.quantity,
            average_entry_price=p.average_entry_price,
            current_price=p.current_price,
            market_value=p.market_value,
            unrealized_pnl=p.unrealized_pnl,
        )
        for p in positions
    ]

    return AccountSummaryResponse(
        account=account_to_response(account),
        portfolio_value=portfolio_value,
        cash_balance=account.cash_balance,
        positions_value=positions_value,
        unrealized_pnl=unrealized,
        realized_pnl=account.realized_pnl,
        daily_pnl=day_pnl,
        trades_today=trades_today,
        positions=position_rows,
        paper_mode_banner=(
            "Paper Trading Mode — all balances are simulated; no real trading occurs."
        ),
    )
