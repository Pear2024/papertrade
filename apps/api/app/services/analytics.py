"""Analytics calculations for paper trading performance and discipline."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.money import money, percent, to_decimal
from app.models import (
    AccountReset,
    Order,
    OrderSide,
    OrderStatus,
    Trade,
    TradingAccount,
    TradingJournal,
    User,
)
from app.schemas.analytics import (
    AnalyticsOverview,
    AssetPerformance,
    DisciplineStats,
    EmotionPerformance,
)
from app.services.trading import get_paper_account_for_user


def _last_reset_at(db: Session, account_id: int):
    reset = db.scalar(
        select(AccountReset)
        .where(AccountReset.trading_account_id == account_id)
        .order_by(AccountReset.reset_at.desc(), AccountReset.id.desc())
        .limit(1)
    )
    return reset.reset_at if reset else None


def _current_trades(db: Session, account: TradingAccount) -> list[Trade]:
    reset_at = _last_reset_at(db, account.id)
    stmt = (
        select(Trade)
        .options(joinedload(Trade.asset), joinedload(Trade.order))
        .where(Trade.trading_account_id == account.id)
        .order_by(Trade.executed_at.asc(), Trade.id.asc())
    )
    if reset_at is not None:
        stmt = stmt.where(Trade.executed_at >= reset_at)
    return list(db.scalars(stmt).unique().all())


def _current_journals(db: Session, account: TradingAccount) -> list[TradingJournal]:
    reset_at = _last_reset_at(db, account.id)
    stmt = (
        select(TradingJournal)
        .options(joinedload(TradingJournal.asset), joinedload(TradingJournal.order))
        .where(TradingJournal.trading_account_id == account.id)
    )
    if reset_at is not None:
        stmt = stmt.where(TradingJournal.created_at >= reset_at)
    return list(db.scalars(stmt).unique().all())


def _sell_trades(trades: list[Trade]) -> list[Trade]:
    return [t for t in trades if t.side == OrderSide.sell]


def get_overview(db: Session, user: User) -> AnalyticsOverview:
    account = get_paper_account_for_user(db, user)
    trades = _current_trades(db, account)
    sells = _sell_trades(trades)
    journals = _current_journals(db, account)

    wins = [t for t in sells if to_decimal(t.realized_pnl) > 0]
    losses = [t for t in sells if to_decimal(t.realized_pnl) < 0]
    win_rate = (
        percent((Decimal(len(wins)) / Decimal(len(sells))) * Decimal("100"))
        if sells
        else money(0)
    )
    avg_win = (
        money(sum((to_decimal(t.realized_pnl) for t in wins), Decimal("0")) / len(wins))
        if wins
        else money(0)
    )
    avg_loss = (
        money(sum((to_decimal(t.realized_pnl) for t in losses), Decimal("0")) / len(losses))
        if losses
        else money(0)
    )
    gross_profit = sum((to_decimal(t.realized_pnl) for t in wins), Decimal("0"))
    gross_loss = abs(sum((to_decimal(t.realized_pnl) for t in losses), Decimal("0")))
    profit_factor = (
        money(gross_profit / gross_loss) if gross_loss > 0 else None
    )
    largest_win = money(max((to_decimal(t.realized_pnl) for t in wins), default=Decimal("0")))
    largest_loss = money(min((to_decimal(t.realized_pnl) for t in losses), default=Decimal("0")))

    # Approximate max drawdown from cumulative realized sell PnL path
    equity = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for trade in sells:
        equity += to_decimal(trade.realized_pnl)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    risk_samples: list[Decimal] = []
    for trade in trades:
        if trade.side != OrderSide.buy or trade.order is None:
            continue
        stop = trade.order.stop_loss_price
        if stop is None:
            continue
        risk_amount = (to_decimal(trade.price) - to_decimal(stop)) * to_decimal(trade.quantity)
        if to_decimal(account.starting_balance) > 0:
            risk_samples.append(
                (risk_amount / to_decimal(account.starting_balance)) * Decimal("100")
            )
    average_risk = (
        percent(sum(risk_samples, Decimal("0")) / len(risk_samples)) if risk_samples else None
    )

    followed = [j for j in journals if j.followed_plan is not None]
    followed_true = [j for j in followed if j.followed_plan]
    followed_rate = (
        percent((Decimal(len(followed_true)) / Decimal(len(followed))) * Decimal("100"))
        if followed
        else None
    )

    note = None
    if len(sells) < 20:
        note = (
            f"ช่วงนี้มีข้อมูลไม่เพียงพอสำหรับสรุปแน่นหนา "
            f"(sell trades = {len(sells)}; แนะนำอย่างน้อย 20)"
        )

    return AnalyticsOverview(
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate=win_rate,
        average_win=avg_win,
        average_loss=avg_loss,
        profit_factor=profit_factor,
        largest_win=largest_win,
        largest_loss=largest_loss,
        maximum_drawdown=money(max_dd),
        average_risk_per_trade=average_risk,
        followed_plan_count=len(followed_true),
        followed_plan_total=len(followed),
        followed_plan_rate=followed_rate,
        sample_size_note=note,
    )


def get_performance(db: Session, user: User) -> AnalyticsOverview:
    return get_overview(db, user)


def get_discipline(db: Session, user: User) -> DisciplineStats:
    account = get_paper_account_for_user(db, user)
    journals = _current_journals(db, account)
    reset_at = _last_reset_at(db, account.id)

    order_stmt = select(Order).where(
        Order.trading_account_id == account.id,
        Order.side == OrderSide.buy,
        Order.status == OrderStatus.filled,
    )
    if reset_at is not None:
        order_stmt = order_stmt.where(Order.filled_at >= reset_at)
    buys = list(db.scalars(order_stmt).all())
    with_sl = [o for o in buys if o.stop_loss_price is not None]

    followed = [j for j in journals if j.followed_plan is not None]
    followed_true = [j for j in followed if j.followed_plan]
    confidences = [j.confidence_score for j in journals if j.confidence_score is not None]

    return DisciplineStats(
        followed_plan_count=len(followed_true),
        followed_plan_total=len(followed),
        followed_plan_rate=(
            percent((Decimal(len(followed_true)) / Decimal(len(followed))) * Decimal("100"))
            if followed
            else None
        ),
        stop_loss_usage_rate=(
            percent((Decimal(len(with_sl)) / Decimal(len(buys))) * Decimal("100"))
            if buys
            else None
        ),
        average_confidence=(
            percent(sum((Decimal(c) for c in confidences), Decimal("0")) / len(confidences))
            if confidences
            else None
        ),
        trades_with_stop_loss=len(with_sl),
        buy_orders=len(buys),
    )


def get_by_asset(db: Session, user: User) -> list[AssetPerformance]:
    account = get_paper_account_for_user(db, user)
    sells = _sell_trades(_current_trades(db, account))
    by_symbol: dict[str, list[Trade]] = {}
    for trade in sells:
        by_symbol.setdefault(trade.asset.symbol, []).append(trade)

    rows: list[AssetPerformance] = []
    for symbol, items in sorted(by_symbol.items()):
        wins = [t for t in items if to_decimal(t.realized_pnl) > 0]
        rows.append(
            AssetPerformance(
                symbol=symbol,
                trades=len(items),
                realized_pnl=money(
                    sum((to_decimal(t.realized_pnl) for t in items), Decimal("0"))
                ),
                win_rate=(
                    percent((Decimal(len(wins)) / Decimal(len(items))) * Decimal("100"))
                    if items
                    else money(0)
                ),
            )
        )
    return rows


def get_by_emotion(db: Session, user: User) -> list[EmotionPerformance]:
    account = get_paper_account_for_user(db, user)
    journals = _current_journals(db, account)
    sells = {t.order_id: t for t in _sell_trades(_current_trades(db, account))}

    buckets: dict[str, list[TradingJournal]] = {}
    for journal in journals:
        if journal.emotional_state is None:
            continue
        buckets.setdefault(journal.emotional_state.value, []).append(journal)

    rows: list[EmotionPerformance] = []
    for emotion, items in sorted(buckets.items()):
        linked_pnls: list[Decimal] = []
        for journal in items:
            if journal.order_id and journal.order_id in sells:
                linked_pnls.append(to_decimal(sells[journal.order_id].realized_pnl))
        followed = [j for j in items if j.followed_plan is not None]
        followed_true = [j for j in followed if j.followed_plan]
        rows.append(
            EmotionPerformance(
                emotional_state=emotion,
                journals=len(items),
                linked_sells=len(linked_pnls),
                average_realized_pnl=(
                    money(sum(linked_pnls, Decimal("0")) / len(linked_pnls))
                    if linked_pnls
                    else None
                ),
                followed_plan_rate=(
                    percent(
                        (Decimal(len(followed_true)) / Decimal(len(followed))) * Decimal("100")
                    )
                    if followed
                    else None
                ),
            )
        )
    return rows
