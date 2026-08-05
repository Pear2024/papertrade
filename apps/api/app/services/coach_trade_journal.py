"""Build Trade Journal rows from closed paper fills + optional decision audit."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Order, Trade, User
from app.models.enums import OrderSide, OrderStatus
from app.services.coach_decision_audit import list_decision_audits
from app.services.trading import get_paper_account_for_user, get_strategy_paper_account


def build_trade_journal(
    db: Session,
    user: User,
    *,
    symbol: str | None = None,
    strategy: str = "A",
    limit: int = 50,
) -> list[dict]:
    """Completed trades with net P/L after fees, exit reason, confidence, regime."""
    try:
        account = get_strategy_paper_account(db, user, strategy.upper())
    except Exception:  # noqa: BLE001
        account = get_paper_account_for_user(db, user)

    q = (
        select(Trade)
        .options(
            joinedload(Trade.asset),
            joinedload(Trade.order).joinedload(Order.journal),
        )
        .where(
            Trade.trading_account_id == account.id,
            Trade.realized_pnl != 0,
        )
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
        .limit(limit * 2)
    )
    trades = list(db.scalars(q).unique().all())
    if symbol:
        sym = symbol.upper()
        trades = [t for t in trades if t.asset and t.asset.symbol == sym]

    # Lookup recent ENTRY audits for confidence / regime by symbol.
    audits = list_decision_audits(
        db, symbol=symbol, strategy=strategy, limit=200
    )
    entry_audits = [
        a
        for a in audits
        if (a.final_action == "ENTRY" or (a.phase or "").startswith("ENTRY"))
    ]

    items: list[dict] = []
    for t in trades[:limit]:
        journal = t.order.journal if t.order else None
        exit_reason = journal.exit_reason if journal else None
        # SHORT cover is a buy fill with realized pnl; LONG close is sell.
        side = "LONG" if str(t.side.value).lower() == "sell" else "SHORT"
        exit_time = t.executed_at
        entry_time = None
        entry_price = None
        duration_sec = None
        confidence = None
        regime_label = None

        # Pair with prior opposite-side entry fill on same asset when possible.
        if t.order and t.asset_id:
            entry_side = OrderSide.buy if side == "LONG" else OrderSide.sell
            prior = db.scalar(
                select(Order)
                .where(
                    Order.trading_account_id == account.id,
                    Order.asset_id == t.asset_id,
                    Order.status == OrderStatus.filled,
                    Order.side == entry_side,
                    Order.filled_at.is_not(None),
                    Order.filled_at < (t.order.filled_at or exit_time),
                )
                .order_by(Order.filled_at.desc())
                .limit(1)
            )
            if prior is not None:
                entry_time = prior.filled_at
                entry_price = str(prior.filled_price) if prior.filled_price is not None else None
                if entry_time and exit_time:
                    et = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
                    xt = exit_time if exit_time.tzinfo else exit_time.replace(tzinfo=timezone.utc)
                    duration_sec = max(0, int((xt - et).total_seconds()))

        # Match nearest ENTRY audit at/before exit bar.
        exit_ts = int(exit_time.timestamp()) if isinstance(exit_time, datetime) else None
        best = None
        if exit_ts is not None:
            for a in entry_audits:
                if a.symbol != (t.asset.symbol if t.asset else ""):
                    continue
                if a.evaluated_bar_time <= exit_ts:
                    best = a
                    break
        if best is not None:
            confidence = best.confidence
            regime_label = best.regime_label

        items.append(
            {
                "id": t.id,
                "symbol": t.asset.symbol if t.asset else "",
                "side": side,
                "entry_time": entry_time.isoformat() if entry_time else None,
                "exit_time": exit_time.isoformat() if exit_time else None,
                "entry_price": entry_price,
                "exit_price": str(t.price),
                "net_pnl": str(t.realized_pnl),
                "exit_reason": exit_reason,
                "confidence": confidence,
                "regime_label": regime_label,
                "duration_sec": duration_sec,
                "order_id": t.order_id,
            }
        )
    return items
