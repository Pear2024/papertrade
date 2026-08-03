"""Paper trading buy/sell engine with Decimal math and DB transactions."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.money import (
    buy_cost,
    calculate_fee,
    clamp_leverage,
    margin_locked,
    mark_market_value,
    market_value,
    money,
    position_side_from_qty,
    quantity,
    quantity_from_usd,
    realized_pnl_on_cover,
    realized_pnl_on_sell,
    sell_proceeds,
    to_decimal,
    unrealized_pnl,
    weighted_average_entry,
)
from app.models import (
    AccountMode,
    EmotionalState,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PriceSource,
    RiskRule,
    Trade,
    TradingAccount,
    TradingJournal,
    User,
)
from app.schemas.orders import OrderRequest, OrderResponse, TradePreview
from app.services.prices import PriceQuote, get_price_quote, record_price_snapshot, require_asset


def _paper_fee(gross: Decimal) -> Decimal:
    """Flat USD fee when configured; otherwise percent of notional."""
    s = get_settings()
    return calculate_fee(gross, s.paper_trading_fee_percent, s.paper_trading_fee_usd)


# Parallel paper A/B accounts (same user). Default resolver stays on A / first account.
PAPER_A_ACCOUNT_NAME = "Paper A Locked"
PAPER_B_ACCOUNT_NAME = "Paper B Experiment"


def get_paper_account_for_user(db: Session, user: User) -> TradingAccount:
    """Main / locked Version A paper account (prefer named A, else oldest active)."""
    named = db.scalar(
        select(TradingAccount)
        .options(joinedload(TradingAccount.risk_rules))
        .where(
            TradingAccount.user_id == user.id,
            TradingAccount.is_active.is_(True),
            TradingAccount.account_mode == AccountMode.paper,
            TradingAccount.account_name == PAPER_A_ACCOUNT_NAME,
        )
        .order_by(TradingAccount.id.asc())
    )
    if named is not None:
        return named

    account = db.scalar(
        select(TradingAccount)
        .options(joinedload(TradingAccount.risk_rules))
        .where(
            TradingAccount.user_id == user.id,
            TradingAccount.is_active.is_(True),
            TradingAccount.account_mode == AccountMode.paper,
        )
        .order_by(TradingAccount.id.asc())
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active paper trading account found",
        )
    if account.account_mode != AccountMode.paper:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only paper trading accounts are supported",
        )
    return account


def ensure_ab_paper_accounts(db: Session, user: User) -> tuple[TradingAccount, TradingAccount]:
    """Ensure dual paper books for simultaneous A/B ticks. Does not change A rules."""
    balance = money(get_settings().paper_starting_balance)
    account_a = get_paper_account_for_user(db, user)
    if account_a.account_name != PAPER_A_ACCOUNT_NAME:
        # Keep existing main book as locked A without wiping history.
        account_a.account_name = PAPER_A_ACCOUNT_NAME

    account_b = db.scalar(
        select(TradingAccount)
        .options(joinedload(TradingAccount.risk_rules))
        .where(
            TradingAccount.user_id == user.id,
            TradingAccount.is_active.is_(True),
            TradingAccount.account_mode == AccountMode.paper,
            TradingAccount.account_name == PAPER_B_ACCOUNT_NAME,
        )
        .order_by(TradingAccount.id.asc())
    )
    if account_b is None:
        account_b = TradingAccount(
            user_id=user.id,
            account_name=PAPER_B_ACCOUNT_NAME,
            account_mode=AccountMode.paper,
            starting_balance=balance,
            cash_balance=balance,
            realized_pnl=Decimal("0"),
            currency="USD",
            is_active=True,
        )
        db.add(account_b)
        db.flush()
        db.add(
            RiskRule(
                trading_account_id=account_b.id,
                max_risk_percent_per_trade=Decimal("2"),
                max_daily_loss_percent=Decimal("5"),
                max_trades_per_day=100,
                require_stop_loss=True,
                trading_enabled=True,
            )
        )
        db.flush()
        account_b = db.scalar(
            select(TradingAccount)
            .options(joinedload(TradingAccount.risk_rules))
            .where(TradingAccount.id == account_b.id)
        )
        assert account_b is not None

    db.commit()
    db.refresh(account_a)
    db.refresh(account_b)
    return account_a, account_b


def get_strategy_paper_account(db: Session, user: User, strategy: str) -> TradingAccount:
    key = strategy.strip().upper()
    account_a, account_b = ensure_ab_paper_accounts(db, user)
    if key == "B":
        return account_b
    if key == "A":
        return account_a
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="strategy must be A or B",
    )


def get_risk_rules(db: Session, account: TradingAccount) -> RiskRule:
    rules = account.risk_rules
    if rules is None:
        rules = db.scalar(
            select(RiskRule).where(RiskRule.trading_account_id == account.id)
        )
    if rules is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Risk rules are not configured for this account",
        )
    return rules


def get_position(
    db: Session, account_id: int, asset_id: int
) -> Position | None:
    return db.scalar(
        select(Position).where(
            Position.trading_account_id == account_id,
            Position.asset_id == asset_id,
        )
    )


def count_trades_today(db: Session, account_id: int) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    value = db.scalar(
        select(func.count(Trade.id)).where(
            Trade.trading_account_id == account_id,
            Trade.executed_at >= start,
        )
    )
    return int(value or 0)


def daily_realized_pnl(db: Session, account_id: int) -> Decimal:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    value = db.scalar(
        select(func.coalesce(func.sum(Trade.realized_pnl), 0)).where(
            Trade.trading_account_id == account_id,
            Trade.executed_at >= start,
        )
    )
    return money(value or 0)


def portfolio_equity(account: TradingAccount, positions: list[Position]) -> Decimal:
    positions_value = sum((to_decimal(p.market_value) for p in positions), Decimal("0"))
    return money(to_decimal(account.cash_balance) + positions_value)


def _resolve_size(
    payload: OrderRequest,
    price: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (qty, margin, notional, leverage).

    When usd_amount is set, it is treated as margin and notional = margin × leverage.
    Leverage 1 keeps classic spot cash accounting (full notional).
    """
    leverage = clamp_leverage(payload.leverage)
    if payload.quantity is not None and payload.usd_amount is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either quantity or usd_amount, not both",
        )
    if payload.quantity is not None:
        qty = quantity(payload.quantity)
        notional = market_value(qty, price)
        margin = (
            money(to_decimal(notional) / leverage)
            if leverage > 1
            else money(notional)
        )
    elif payload.usd_amount is not None:
        margin = money(payload.usd_amount)
        notional = money(to_decimal(margin) * leverage)
        qty = quantity_from_usd(notional, price)
        # Recompute notional from rounded qty for fee consistency.
        notional = market_value(qty, price)
        if leverage > 1:
            margin = money(to_decimal(notional) / leverage)
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either quantity or usd_amount is required",
        )
    if qty <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Quantity must be greater than zero",
        )
    return qty, margin, notional, leverage


def _resolve_quantity(
    payload: OrderRequest,
    price: Decimal,
) -> Decimal:
    qty, _margin, _notional, _leverage = _resolve_size(payload, price)
    return qty


def _position_leverage(position: Position | None) -> Decimal:
    if position is None:
        return Decimal("1")
    return clamp_leverage(getattr(position, "leverage", None) or 1)


def apply_position_mark(position: Position, price: Decimal) -> None:
    """Update mark price, unrealized PnL, and equity contribution."""
    position.current_price = price
    position.unrealized_pnl = unrealized_pnl(
        position.quantity, position.average_entry_price, price
    )
    position.market_value = mark_market_value(
        position.quantity,
        position.average_entry_price,
        price,
        _position_leverage(position),
    )

def _validate_common(
    account: TradingAccount,
    rules: RiskRule,
    trades_today: int,
) -> None:
    if account.account_mode != AccountMode.paper:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only paper trading is allowed",
        )
    if not rules.trading_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trading is disabled for this account",
        )
    if trades_today >= rules.max_trades_per_day:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Daily trade limit reached ({rules.max_trades_per_day})",
        )


def _validate_daily_loss(db: Session, account: TradingAccount, rules: RiskRule) -> None:
    day_pnl = daily_realized_pnl(db, account.id)
    if day_pnl >= 0:
        return
    baseline = to_decimal(account.starting_balance)
    if baseline <= 0:
        return
    loss_percent = (abs(day_pnl) / baseline) * Decimal("100")
    if loss_percent >= to_decimal(rules.max_daily_loss_percent):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Daily loss limit reached "
                f"({rules.max_daily_loss_percent}% of starting balance)"
            ),
        )


def _validate_stop_loss_required(
    rules: RiskRule,
    side: OrderSide,
    stop_loss_price: Decimal | None,
    *,
    opening: bool = True,
) -> None:
    if not opening:
        return
    if rules.require_stop_loss and stop_loss_price is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stop loss is required by your risk rules",
        )


def _validate_buy_risk(
    account: TradingAccount,
    positions: list[Position],
    rules: RiskRule,
    qty: Decimal,
    price: Decimal,
    stop_loss: Decimal | None,
) -> Decimal | None:
    """Return estimated risk percent when stop loss is present (LONG)."""
    if stop_loss is None:
        return None
    if stop_loss <= 0 or stop_loss >= price:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stop loss must be greater than 0 and below the buy price",
        )
    equity = portfolio_equity(account, positions)
    if equity <= 0:
        return None
    risk_amount = (to_decimal(price) - to_decimal(stop_loss)) * to_decimal(qty)
    risk_percent = (risk_amount / equity) * Decimal("100")
    if risk_percent > to_decimal(rules.max_risk_percent_per_trade):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Trade risk {risk_percent:.4f}% exceeds max "
                f"{rules.max_risk_percent_per_trade}% per trade"
            ),
        )
    return money(risk_percent)


def _validate_short_risk(
    account: TradingAccount,
    positions: list[Position],
    rules: RiskRule,
    qty: Decimal,
    price: Decimal,
    stop_loss: Decimal | None,
) -> Decimal | None:
    """Return estimated risk percent when stop loss is present (SHORT)."""
    if stop_loss is None:
        return None
    if stop_loss <= price:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Short stop loss must be above the entry (sell) price",
        )
    equity = portfolio_equity(account, positions)
    if equity <= 0:
        return None
    risk_amount = (to_decimal(stop_loss) - to_decimal(price)) * to_decimal(qty)
    risk_percent = (risk_amount / equity) * Decimal("100")
    if risk_percent > to_decimal(rules.max_risk_percent_per_trade):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Trade risk {risk_percent:.4f}% exceeds max "
                f"{rules.max_risk_percent_per_trade}% per trade"
            ),
        )
    return money(risk_percent)

def build_buy_preview(
    account: TradingAccount,
    quote: PriceQuote,
    qty: Decimal,
    fee_percent: str,
    stop_loss: Decimal | None,
    risk_percent: Decimal | None,
    *,
    leverage: Decimal = Decimal("1"),
    margin: Decimal | None = None,
) -> TradePreview:
    price = quote.price
    gross = market_value(qty, price)
    fee = _paper_fee(gross)
    lev = clamp_leverage(leverage)
    if lev > 1:
        locked = margin if margin is not None else margin_locked(qty, price, lev)
        total = money(to_decimal(locked) + to_decimal(fee))
    else:
        locked = None
        total = buy_cost(gross, fee)
    cash_after = money(to_decimal(account.cash_balance) - total)
    max_loss = None
    if stop_loss is not None:
        max_loss = money((to_decimal(price) - to_decimal(stop_loss)) * to_decimal(qty) + fee)
    return TradePreview(
        side="buy",
        symbol=quote.symbol,
        quantity=qty,
        estimated_price=price,
        gross_amount=gross,
        fee_amount=fee,
        net_amount=total,
        cash_after=cash_after,
        estimated_max_loss=max_loss,
        risk_percent=risk_percent,
        leverage=lev,
        margin_amount=locked,
        notional_amount=gross,
    )


def build_sell_preview(
    account: TradingAccount,
    quote: PriceQuote,
    qty: Decimal,
    fee_percent: str,
    average_entry: Decimal,
) -> TradePreview:
    price = quote.price
    gross = market_value(qty, price)
    fee = _paper_fee(gross)
    proceeds = sell_proceeds(gross, fee)
    pnl = realized_pnl_on_sell(qty, price, average_entry, fee)
    cash_after = money(to_decimal(account.cash_balance) + proceeds)
    return TradePreview(
        side="sell",
        symbol=quote.symbol,
        quantity=qty,
        estimated_price=price,
        gross_amount=gross,
        fee_amount=fee,
        net_amount=proceeds,
        cash_after=cash_after,
        estimated_realized_pnl=pnl,
        risk_percent=None,
        estimated_max_loss=None,
    )


def _journal_from_payload(
    db: Session,
    user: User,
    account: TradingAccount,
    order: Order,
    asset_id: int,
    payload: OrderRequest,
) -> None:
    emotion = None
    if payload.emotional_state is not None:
        emotion = EmotionalState(payload.emotional_state)
    db.add(
        TradingJournal(
            user_id=user.id,
            trading_account_id=account.id,
            order_id=order.id,
            asset_id=asset_id,
            setup_name=payload.setup_name,
            entry_reason=payload.entry_reason,
            exit_reason=payload.exit_reason,
            emotional_state=emotion,
            confidence_score=payload.confidence_score,
            followed_plan=payload.followed_plan,
            lesson_learned=payload.lesson_learned,
        )
    )


def order_to_response(order: Order, symbol: str) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        symbol=symbol,
        side=order.side.value,
        order_type=order.order_type.value,
        status=order.status.value,
        requested_quantity=order.requested_quantity,
        filled_quantity=order.filled_quantity,
        requested_price=order.requested_price,
        filled_price=order.filled_price,
        stop_loss_price=order.stop_loss_price,
        take_profit_price=order.take_profit_price,
        fee_amount=order.fee_amount,
        rejection_reason=order.rejection_reason,
        created_at=order.created_at,
        filled_at=order.filled_at,
        cancelled_at=order.cancelled_at,
    )


async def preview_buy(
    db: Session,
    user: User,
    payload: OrderRequest,
) -> TradePreview:
    account = get_paper_account_for_user(db, user)
    rules = get_risk_rules(db, account)
    trades_today = count_trades_today(db, account.id)
    _validate_common(account, rules, trades_today)
    _validate_daily_loss(db, account, rules)
    asset = require_asset(db, payload.symbol)
    quote = await get_price_quote(db, asset.symbol)
    qty, margin, _notional, leverage = _resolve_size(payload, quote.price)
    _validate_stop_loss_required(rules, OrderSide.buy, payload.stop_loss_price, opening=True)
    positions = list(
        db.scalars(select(Position).where(Position.trading_account_id == account.id))
    )
    risk_percent = _validate_buy_risk(
        account, positions, rules, qty, quote.price, payload.stop_loss_price
    )
    fee_percent = get_settings().paper_trading_fee_percent
    preview = build_buy_preview(
        account,
        quote,
        qty,
        fee_percent,
        payload.stop_loss_price,
        risk_percent,
        leverage=leverage,
        margin=margin,
    )
    if preview.net_amount > account.cash_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient cash balance for this buy",
        )
    return preview


async def preview_sell(
    db: Session,
    user: User,
    payload: OrderRequest,
) -> TradePreview:
    account = get_paper_account_for_user(db, user)
    rules = get_risk_rules(db, account)
    trades_today = count_trades_today(db, account.id)
    _validate_common(account, rules, trades_today)
    _validate_daily_loss(db, account, rules)

    asset = require_asset(db, payload.symbol)
    quote = await get_price_quote(db, asset.symbol)
    qty = _resolve_quantity(payload, quote.price)

    position = get_position(db, account.id, asset.id)
    if position is None or to_decimal(position.quantity) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No open position for {asset.symbol}",
        )
    if qty > to_decimal(position.quantity):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sell quantity exceeds held quantity",
        )

    fee_percent = get_settings().paper_trading_fee_percent
    return build_sell_preview(
        account, quote, qty, fee_percent, position.average_entry_price
    )


async def execute_buy(
    db: Session,
    user: User,
    payload: OrderRequest,
    *,
    account: TradingAccount | None = None,
) -> OrderResponse:
    """Open/add LONG, or buy-to-cover an existing SHORT (paper only)."""
    account = account or get_paper_account_for_user(db, user)
    rules = get_risk_rules(db, account)
    trades_today = count_trades_today(db, account.id)
    _validate_common(account, rules, trades_today)
    _validate_daily_loss(db, account, rules)

    asset = require_asset(db, payload.symbol)
    quote = await get_price_quote(db, asset.symbol)
    qty, margin, _notional, leverage = _resolve_size(payload, quote.price)

    position = get_position(db, account.id, asset.id)
    pos_qty = to_decimal(position.quantity) if position is not None else Decimal("0")

    # Cover SHORT first when short is open.
    if pos_qty < 0:
        return await _execute_cover_short(
            db, user, account, rules, asset, quote, qty, payload, position
        )

    _validate_stop_loss_required(rules, OrderSide.buy, payload.stop_loss_price, opening=True)

    # Adding to an existing LONG keeps that position's leverage.
    if position is not None and pos_qty > 0:
        leverage = _position_leverage(position)
        if payload.usd_amount is not None:
            notional = money(to_decimal(money(payload.usd_amount)) * leverage)
            qty = quantity_from_usd(notional, quote.price)
            _notional = market_value(qty, quote.price)
            margin = money(to_decimal(_notional) / leverage) if leverage > 1 else money(_notional)
        else:
            _notional = market_value(qty, quote.price)
            margin = (
                money(to_decimal(_notional) / leverage)
                if leverage > 1
                else money(_notional)
            )

    positions = list(
        db.scalars(select(Position).where(Position.trading_account_id == account.id))
    )
    risk_percent = _validate_buy_risk(
        account, positions, rules, qty, quote.price, payload.stop_loss_price
    )
    fee_percent = get_settings().paper_trading_fee_percent
    preview = build_buy_preview(
        account,
        quote,
        qty,
        fee_percent,
        payload.stop_loss_price,
        risk_percent,
        leverage=leverage,
        margin=margin,
    )
    if preview.net_amount > account.cash_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient cash balance for this buy",
        )

    try:
        now = datetime.now(timezone.utc)
        order = Order(
            trading_account_id=account.id,
            asset_id=asset.id,
            side=OrderSide.buy,
            order_type=OrderType.market,
            status=OrderStatus.filled,
            requested_quantity=qty,
            filled_quantity=qty,
            requested_price=quote.price,
            filled_price=quote.price,
            stop_loss_price=payload.stop_loss_price,
            take_profit_price=payload.take_profit_price,
            fee_amount=preview.fee_amount,
            filled_at=now,
        )
        db.add(order)
        db.flush()

        db.add(
            Trade(
                order_id=order.id,
                trading_account_id=account.id,
                asset_id=asset.id,
                side=OrderSide.buy,
                quantity=qty,
                price=quote.price,
                gross_amount=preview.gross_amount,
                fee_amount=preview.fee_amount,
                net_amount=preview.net_amount,
                realized_pnl=money(0),
                executed_at=now,
            )
        )

        account.cash_balance = money(to_decimal(account.cash_balance) - preview.net_amount)

        if position is None:
            init_mv = (
                margin
                if leverage > 1
                else preview.gross_amount
            )
            position = Position(
                trading_account_id=account.id,
                asset_id=asset.id,
                quantity=qty,
                average_entry_price=quote.price,
                current_price=quote.price,
                market_value=init_mv,
                unrealized_pnl=money(0),
                leverage=leverage,
            )
            db.add(position)
        else:
            new_avg = weighted_average_entry(
                position.quantity,
                position.average_entry_price,
                qty,
                quote.price,
            )
            new_qty = quantity(to_decimal(position.quantity) + to_decimal(qty))
            position.quantity = new_qty
            position.average_entry_price = new_avg
            position.leverage = leverage
            apply_position_mark(position, quote.price)

        record_price_snapshot(db, asset.id, quote.price, PriceSource.trade_fill)
        _journal_from_payload(db, user, account, order, asset.id, payload)
        db.commit()
        db.refresh(order)
        return order_to_response(order, asset.symbol)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order failed and was rolled back",
        ) from exc


async def _execute_cover_short(
    db: Session,
    user: User,
    account: TradingAccount,
    rules: RiskRule,
    asset,
    quote: PriceQuote,
    qty: Decimal,
    payload: OrderRequest,
    position: Position,
) -> OrderResponse:
    """Buy to cover an open SHORT position (paper only)."""
    short_qty = abs(to_decimal(position.quantity))
    cover_qty = quantity(min(to_decimal(qty), short_qty))
    if cover_qty <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cover quantity must be greater than zero",
        )

    fee_percent = get_settings().paper_trading_fee_percent
    gross = market_value(cover_qty, quote.price)
    fee = _paper_fee(gross)
    lev = _position_leverage(position)
    realized = realized_pnl_on_cover(
        cover_qty, quote.price, position.average_entry_price, fee
    )
    if lev > 1:
        # Release proportional margin + realized (fee already in realized).
        frac = to_decimal(cover_qty) / abs(to_decimal(position.quantity))
        locked_total = margin_locked(
            position.quantity, position.average_entry_price, lev
        )
        release = money(to_decimal(locked_total) * frac)
        cash_delta = money(to_decimal(release) + to_decimal(realized))
        net_amount = cash_delta
        # For leveraged cover, cash must cover a loss larger than released margin.
        if cash_delta < 0 and abs(to_decimal(cash_delta)) > to_decimal(account.cash_balance):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient cash balance to cover short loss",
            )
    else:
        net_amount = buy_cost(gross, fee)
        if net_amount > account.cash_balance:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient cash balance to cover short",
            )
        cash_delta = money(-to_decimal(net_amount))

    try:
        now = datetime.now(timezone.utc)
        order = Order(
            trading_account_id=account.id,
            asset_id=asset.id,
            side=OrderSide.buy,
            order_type=OrderType.market,
            status=OrderStatus.filled,
            requested_quantity=cover_qty,
            filled_quantity=cover_qty,
            requested_price=quote.price,
            filled_price=quote.price,
            stop_loss_price=None,
            take_profit_price=None,
            fee_amount=fee,
            filled_at=now,
        )
        db.add(order)
        db.flush()

        db.add(
            Trade(
                order_id=order.id,
                trading_account_id=account.id,
                asset_id=asset.id,
                side=OrderSide.buy,
                quantity=cover_qty,
                price=quote.price,
                gross_amount=gross,
                fee_amount=fee,
                net_amount=net_amount,
                realized_pnl=realized,
                executed_at=now,
            )
        )

        account.cash_balance = money(to_decimal(account.cash_balance) + to_decimal(cash_delta))
        account.realized_pnl = money(to_decimal(account.realized_pnl) + realized)

        remaining = quantity(to_decimal(position.quantity) + to_decimal(cover_qty))
        # short qty is negative; adding cover_qty moves toward zero.
        # Sweep dust leftovers from usd_amount rounding (notional under $0.05).
        remaining_notional = abs(to_decimal(remaining)) * to_decimal(quote.price)
        if remaining >= 0 or remaining_notional < Decimal("0.05"):
            db.delete(position)
        else:
            position.quantity = remaining
            apply_position_mark(position, quote.price)

        record_price_snapshot(db, asset.id, quote.price, PriceSource.trade_fill)
        _journal_from_payload(db, user, account, order, asset.id, payload)
        db.commit()
        db.refresh(order)
        return order_to_response(order, asset.symbol)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order failed and was rolled back",
        ) from exc


async def execute_sell(
    db: Session,
    user: User,
    payload: OrderRequest,
    *,
    account: TradingAccount | None = None,
) -> OrderResponse:
    """Close LONG, or open SHORT when flat (paper only)."""
    account = account or get_paper_account_for_user(db, user)
    rules = get_risk_rules(db, account)
    trades_today = count_trades_today(db, account.id)
    _validate_common(account, rules, trades_today)
    _validate_daily_loss(db, account, rules)

    asset = require_asset(db, payload.symbol)
    quote = await get_price_quote(db, asset.symbol)
    qty, margin, _notional, leverage = _resolve_size(payload, quote.price)

    position = get_position(db, account.id, asset.id)
    pos_qty = to_decimal(position.quantity) if position is not None else Decimal("0")

    if pos_qty < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Already SHORT {asset.symbol} — cover with buy instead of selling more",
        )

    # Open SHORT when flat.
    if position is None or pos_qty == 0:
        return await _execute_open_short(
            db, user, account, rules, asset, quote, qty, payload, margin=margin, leverage=leverage
        )

    if qty > pos_qty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sell quantity exceeds held quantity",
        )

    fee_percent = get_settings().paper_trading_fee_percent
    lev = _position_leverage(position)
    gross = market_value(qty, quote.price)
    fee = _paper_fee(gross)
    realized = realized_pnl_on_sell(qty, quote.price, position.average_entry_price, fee)

    if lev > 1:
        frac = to_decimal(qty) / to_decimal(position.quantity)
        locked_total = margin_locked(
            position.quantity, position.average_entry_price, lev
        )
        release = money(to_decimal(locked_total) * frac)
        cash_credit = money(to_decimal(release) + to_decimal(realized))
        net_amount = cash_credit
    else:
        preview = build_sell_preview(
            account, quote, qty, fee_percent, position.average_entry_price
        )
        cash_credit = preview.net_amount
        net_amount = preview.net_amount
        realized = preview.estimated_realized_pnl or money(0)

    try:
        now = datetime.now(timezone.utc)
        order = Order(
            trading_account_id=account.id,
            asset_id=asset.id,
            side=OrderSide.sell,
            order_type=OrderType.market,
            status=OrderStatus.filled,
            requested_quantity=qty,
            filled_quantity=qty,
            requested_price=quote.price,
            filled_price=quote.price,
            stop_loss_price=payload.stop_loss_price,
            take_profit_price=payload.take_profit_price,
            fee_amount=fee,
            filled_at=now,
        )
        db.add(order)
        db.flush()

        db.add(
            Trade(
                order_id=order.id,
                trading_account_id=account.id,
                asset_id=asset.id,
                side=OrderSide.sell,
                quantity=qty,
                price=quote.price,
                gross_amount=gross,
                fee_amount=fee,
                net_amount=net_amount,
                realized_pnl=realized,
                executed_at=now,
            )
        )

        account.cash_balance = money(to_decimal(account.cash_balance) + to_decimal(cash_credit))
        account.realized_pnl = money(to_decimal(account.realized_pnl) + realized)

        remaining = quantity(to_decimal(position.quantity) - to_decimal(qty))
        remaining_notional = abs(to_decimal(remaining)) * to_decimal(quote.price)
        if remaining <= 0 or remaining_notional < Decimal("0.05"):
            db.delete(position)
        else:
            position.quantity = remaining
            apply_position_mark(position, quote.price)

        record_price_snapshot(db, asset.id, quote.price, PriceSource.trade_fill)
        _journal_from_payload(db, user, account, order, asset.id, payload)
        db.commit()
        db.refresh(order)
        return order_to_response(order, asset.symbol)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order failed and was rolled back",
        ) from exc


async def _execute_open_short(
    db: Session,
    user: User,
    account: TradingAccount,
    rules: RiskRule,
    asset,
    quote: PriceQuote,
    qty: Decimal,
    payload: OrderRequest,
    *,
    margin: Decimal | None = None,
    leverage: Decimal = Decimal("1"),
) -> OrderResponse:
    """Open a paper SHORT: sell without inventory, store negative quantity."""
    _validate_stop_loss_required(rules, OrderSide.sell, payload.stop_loss_price, opening=True)
    if payload.take_profit_price is not None and payload.take_profit_price >= quote.price:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Short take profit must be below the entry (sell) price",
        )

    positions = list(
        db.scalars(select(Position).where(Position.trading_account_id == account.id))
    )
    _validate_short_risk(
        account, positions, rules, qty, quote.price, payload.stop_loss_price
    )

    fee_percent = get_settings().paper_trading_fee_percent
    gross = market_value(qty, quote.price)
    fee = _paper_fee(gross)
    lev = clamp_leverage(leverage)
    signed_qty = quantity(-to_decimal(qty))
    locked = margin if margin is not None else margin_locked(qty, quote.price, lev)

    if lev > 1:
        # Futures-lite: lock margin + fee (do not credit full short proceeds).
        debit = money(to_decimal(locked) + to_decimal(fee))
        if debit > account.cash_balance:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient cash balance for short margin",
            )
        cash_delta = money(-to_decimal(debit))
        net_amount = debit
        init_mv = locked
    else:
        proceeds = sell_proceeds(gross, fee)
        cash_delta = proceeds
        net_amount = proceeds
        init_mv = market_value(signed_qty, quote.price)

    try:
        now = datetime.now(timezone.utc)
        order = Order(
            trading_account_id=account.id,
            asset_id=asset.id,
            side=OrderSide.sell,
            order_type=OrderType.market,
            status=OrderStatus.filled,
            requested_quantity=qty,
            filled_quantity=qty,
            requested_price=quote.price,
            filled_price=quote.price,
            stop_loss_price=payload.stop_loss_price,
            take_profit_price=payload.take_profit_price,
            fee_amount=fee,
            filled_at=now,
        )
        db.add(order)
        db.flush()

        db.add(
            Trade(
                order_id=order.id,
                trading_account_id=account.id,
                asset_id=asset.id,
                side=OrderSide.sell,
                quantity=qty,
                price=quote.price,
                gross_amount=gross,
                fee_amount=fee,
                net_amount=net_amount,
                realized_pnl=money(0),
                executed_at=now,
            )
        )

        account.cash_balance = money(to_decimal(account.cash_balance) + to_decimal(cash_delta))

        position = Position(
            trading_account_id=account.id,
            asset_id=asset.id,
            quantity=signed_qty,
            average_entry_price=quote.price,
            current_price=quote.price,
            market_value=init_mv,
            unrealized_pnl=money(0),
            leverage=lev,
        )
        db.add(position)

        record_price_snapshot(db, asset.id, quote.price, PriceSource.trade_fill)
        _journal_from_payload(db, user, account, order, asset.id, payload)
        db.commit()
        db.refresh(order)
        return order_to_response(order, asset.symbol)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order failed and was rolled back",
        ) from exc


def latest_filled_buy_order(
    db: Session, account_id: int, asset_id: int
) -> Order | None:
    return db.scalar(
        select(Order)
        .where(
            Order.trading_account_id == account_id,
            Order.asset_id == asset_id,
            Order.side == OrderSide.buy,
            Order.status == OrderStatus.filled,
        )
        .order_by(Order.id.desc())
        .limit(1)
    )


def latest_entry_order(db: Session, account_id: int, asset_id: int, side: str) -> Order | None:
    """Entry order holding SL/TP: buy for LONG, sell for SHORT."""
    order_side = OrderSide.buy if side == "long" else OrderSide.sell
    return db.scalar(
        select(Order)
        .where(
            Order.trading_account_id == account_id,
            Order.asset_id == asset_id,
            Order.side == order_side,
            Order.status == OrderStatus.filled,
            Order.stop_loss_price.is_not(None),
        )
        .order_by(Order.id.desc())
        .limit(1)
    )


def update_position_exits(
    db: Session,
    user: User,
    symbol: str,
    stop_loss_price: Decimal,
    take_profit_price: Decimal | None,
) -> tuple[Position, Order]:
    """Update Stop Loss / Take Profit on the latest entry order for an open position."""
    from app.services.prices import require_asset

    account = get_paper_account_for_user(db, user)
    asset = require_asset(db, symbol)
    position = db.scalar(
        select(Position)
        .options(joinedload(Position.asset))
        .where(
            Position.trading_account_id == account.id,
            Position.asset_id == asset.id,
        )
    )
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No open position for {symbol.upper()}",
        )

    side = position_side_from_qty(position.quantity)
    if side is None:
        raise HTTPException(status_code=404, detail="Flat position")

    order = latest_entry_order(db, account.id, asset.id, side)
    if order is None:
        # Fallback for legacy longs without filtering by SL present
        order = (
            latest_filled_buy_order(db, account.id, asset.id)
            if side == "long"
            else None
        )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No filled entry order found to attach exits",
        )

    stop = money(stop_loss_price)
    ref_price = to_decimal(position.current_price) or to_decimal(position.average_entry_price)
    if side == "long":
        if stop <= 0 or stop >= ref_price:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Stop Loss must be > 0 and below price for a LONG",
            )
        tp: Decimal | None = None
        if take_profit_price is not None:
            tp = money(take_profit_price)
            if tp <= ref_price:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Take Profit must be above price for a LONG",
                )
    else:
        if stop <= ref_price:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Stop Loss must be above price for a SHORT",
            )
        tp = None
        if take_profit_price is not None:
            tp = money(take_profit_price)
            if tp >= ref_price:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Take Profit must be below price for a SHORT",
                )

    order.stop_loss_price = stop
    order.take_profit_price = tp
    db.commit()
    db.refresh(order)
    db.refresh(position)
    return position, order


def cancel_order(db: Session, user: User, order_id: int) -> OrderResponse:
    account = get_paper_account_for_user(db, user)
    order = db.scalar(
        select(Order)
        .options(joinedload(Order.asset))
        .where(Order.id == order_id, Order.trading_account_id == account.id)
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status != OrderStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only pending orders can be cancelled (status={order.status.value})",
        )
    order.status = OrderStatus.cancelled
    order.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    return order_to_response(order, order.asset.symbol)
