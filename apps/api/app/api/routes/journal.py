"""Journal routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.journal import JournalCreate, JournalResponse, JournalUpdate
from app.services import journal as journal_service

router = APIRouter(prefix="/journal", tags=["journal"])


@router.get("", response_model=list[JournalResponse])
def list_journals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JournalResponse]:
    return journal_service.list_journals(db, current_user)


@router.post("", response_model=JournalResponse, status_code=201)
def create_journal(
    payload: JournalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JournalResponse:
    return journal_service.create_journal(db, current_user, payload)


@router.get("/{journal_id}", response_model=JournalResponse)
def get_journal(
    journal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JournalResponse:
    return journal_service.get_journal(db, current_user, journal_id)


@router.patch("/{journal_id}", response_model=JournalResponse)
def update_journal(
    journal_id: int,
    payload: JournalUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JournalResponse:
    return journal_service.update_journal(db, current_user, journal_id, payload)


@router.delete("/{journal_id}", status_code=204)
def delete_journal(
    journal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    journal_service.delete_journal(db, current_user, journal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
