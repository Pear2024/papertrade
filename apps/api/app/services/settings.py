"""Account settings and reset service."""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.money import money
from app.models import AccountReset, Position, User
from app.schemas.analytics import (
    AccountResetHistoryItem,
    AccountResetRequest,
    AccountResetResponse,
    AccountSettingsResponse,
    AccountSettingsUpdate,
)
from app.services.trading import get_paper_account_for_user, get_risk_rules, portfolio_equity


def get_settings_response(db: Session, user: User) -> AccountSettingsResponse:
    account = get_paper_account_for_user(db, user)
    rules = get_risk_rules(db, account)
    cfg = get_settings()
    fee = Decimal(cfg.paper_trading_fee_percent)
    fee_usd = Decimal(cfg.paper_trading_fee_usd)
    return AccountSettingsResponse(
        starting_balance=account.starting_balance,
        cash_balance=account.cash_balance,
        trading_fee_percent=fee,
        trading_fee_usd=fee_usd,
        trading_fee_editable=False,
        max_risk_percent_per_trade=rules.max_risk_percent_per_trade,
        max_daily_loss_percent=rules.max_daily_loss_percent,
        max_trades_per_day=rules.max_trades_per_day,
        require_stop_loss=rules.require_stop_loss,
        trading_enabled=rules.trading_enabled,
        paper_mode_banner=(
            "PAPER MODE — NO REAL ORDERS. "
            "เงินทั้งหมดเป็นเงินจำลอง — Kraken public market data only, no API keys, no real orders."
        ),
    )


def update_settings(
    db: Session, user: User, payload: AccountSettingsUpdate
) -> AccountSettingsResponse:
    account = get_paper_account_for_user(db, user)
    rules = get_risk_rules(db, account)

    if payload.starting_balance is not None:
        account.starting_balance = money(payload.starting_balance)

    if payload.risk_rules is not None:
        rr = payload.risk_rules
        if rr.max_risk_percent_per_trade is not None:
            rules.max_risk_percent_per_trade = money(rr.max_risk_percent_per_trade)
        if rr.max_daily_loss_percent is not None:
            rules.max_daily_loss_percent = money(rr.max_daily_loss_percent)
        if rr.max_trades_per_day is not None:
            rules.max_trades_per_day = rr.max_trades_per_day
        if rr.require_stop_loss is not None:
            rules.require_stop_loss = rr.require_stop_loss
        if rr.trading_enabled is not None:
            rules.trading_enabled = rr.trading_enabled

    db.commit()
    return get_settings_response(db, user)


def reset_account(
    db: Session, user: User, payload: AccountResetRequest
) -> AccountResetResponse:
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset requires confirm=true",
        )

    account = get_paper_account_for_user(db, user)
    if account.account_mode.value != "paper":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only paper accounts can be reset",
        )

    positions = list(
        db.scalars(select(Position).where(Position.trading_account_id == account.id))
    )
    previous = portfolio_equity(account, positions)
    reset_balance = money(account.starting_balance)

    try:
        for position in positions:
            db.delete(position)

        account.cash_balance = reset_balance
        account.realized_pnl = money(0)

        record = AccountReset(
            trading_account_id=account.id,
            previous_balance=previous,
            reset_balance=reset_balance,
            reason=payload.reason or "User requested paper account reset",
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        return AccountResetResponse(
            id=record.id,
            previous_balance=record.previous_balance,
            reset_balance=record.reset_balance,
            reason=record.reason,
            reset_at=record.reset_at,
            message=(
                f"Paper account reset to {reset_balance} USD. "
                "Open positions cleared. Prior trades remain for history; "
                "analytics focus on activity after this reset."
            ),
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account reset failed and was rolled back",
        ) from exc


def reset_history(db: Session, user: User) -> list[AccountResetHistoryItem]:
    account = get_paper_account_for_user(db, user)
    rows = db.scalars(
        select(AccountReset)
        .where(AccountReset.trading_account_id == account.id)
        .order_by(AccountReset.reset_at.desc(), AccountReset.id.desc())
    ).all()
    return [
        AccountResetHistoryItem(
            id=r.id,
            previous_balance=r.previous_balance,
            reset_balance=r.reset_balance,
            reason=r.reason,
            reset_at=r.reset_at,
        )
        for r in rows
    ]
