"""Trading journal service."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import EmotionalState, Order, TradingJournal, User
from app.schemas.journal import JournalCreate, JournalResponse, JournalUpdate
from app.services.prices import require_asset
from app.services.trading import get_paper_account_for_user


def journal_to_response(journal: TradingJournal) -> JournalResponse:
    return JournalResponse(
        id=journal.id,
        symbol=journal.asset.symbol,
        order_id=journal.order_id,
        setup_name=journal.setup_name,
        entry_reason=journal.entry_reason,
        exit_reason=journal.exit_reason,
        emotional_state=journal.emotional_state.value if journal.emotional_state else None,
        confidence_score=journal.confidence_score,
        followed_plan=journal.followed_plan,
        lesson_learned=journal.lesson_learned,
        created_at=journal.created_at,
        updated_at=journal.updated_at,
    )


def list_journals(db: Session, user: User) -> list[JournalResponse]:
    account = get_paper_account_for_user(db, user)
    journals = db.scalars(
        select(TradingJournal)
        .options(joinedload(TradingJournal.asset))
        .where(TradingJournal.trading_account_id == account.id)
        .order_by(TradingJournal.created_at.desc(), TradingJournal.id.desc())
    ).all()
    return [journal_to_response(j) for j in journals]


def get_journal(db: Session, user: User, journal_id: int) -> JournalResponse:
    account = get_paper_account_for_user(db, user)
    journal = db.scalar(
        select(TradingJournal)
        .options(joinedload(TradingJournal.asset))
        .where(
            TradingJournal.id == journal_id,
            TradingJournal.trading_account_id == account.id,
        )
    )
    if journal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")
    return journal_to_response(journal)


def create_journal(db: Session, user: User, payload: JournalCreate) -> JournalResponse:
    account = get_paper_account_for_user(db, user)
    asset = require_asset(db, payload.symbol)

    if payload.order_id is not None:
        order = db.scalar(
            select(Order).where(
                Order.id == payload.order_id,
                Order.trading_account_id == account.id,
            )
        )
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        existing = db.scalar(
            select(TradingJournal).where(TradingJournal.order_id == payload.order_id)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A journal already exists for this order",
            )

    emotion = (
        EmotionalState(payload.emotional_state) if payload.emotional_state else None
    )
    journal = TradingJournal(
        user_id=user.id,
        trading_account_id=account.id,
        order_id=payload.order_id,
        asset_id=asset.id,
        setup_name=payload.setup_name,
        entry_reason=payload.entry_reason,
        exit_reason=payload.exit_reason,
        emotional_state=emotion,
        confidence_score=payload.confidence_score,
        followed_plan=payload.followed_plan,
        lesson_learned=payload.lesson_learned,
    )
    db.add(journal)
    db.commit()
    db.refresh(journal)
    journal = db.scalar(
        select(TradingJournal)
        .options(joinedload(TradingJournal.asset))
        .where(TradingJournal.id == journal.id)
    )
    assert journal is not None
    return journal_to_response(journal)


def update_journal(
    db: Session, user: User, journal_id: int, payload: JournalUpdate
) -> JournalResponse:
    account = get_paper_account_for_user(db, user)
    journal = db.scalar(
        select(TradingJournal)
        .options(joinedload(TradingJournal.asset))
        .where(
            TradingJournal.id == journal_id,
            TradingJournal.trading_account_id == account.id,
        )
    )
    if journal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")

    data = payload.model_dump(exclude_unset=True)
    if "emotional_state" in data:
        value = data.pop("emotional_state")
        journal.emotional_state = EmotionalState(value) if value is not None else None
    for key, value in data.items():
        setattr(journal, key, value)

    db.commit()
    db.refresh(journal)
    return journal_to_response(journal)


def delete_journal(db: Session, user: User, journal_id: int) -> None:
    account = get_paper_account_for_user(db, user)
    journal = db.scalar(
        select(TradingJournal).where(
            TradingJournal.id == journal_id,
            TradingJournal.trading_account_id == account.id,
        )
    )
    if journal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal not found")
    db.delete(journal)
    db.commit()
