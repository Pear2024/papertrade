"""Account endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.account import AccountResponse, AccountSummaryResponse
from app.schemas.analytics import (
    AccountResetHistoryItem,
    AccountResetRequest,
    AccountResetResponse,
    AccountSettingsResponse,
    AccountSettingsUpdate,
)
from app.services import account as account_service
from app.services import settings as settings_service
from app.services.trading import get_paper_account_for_user

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=AccountResponse)
def get_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountResponse:
    account = get_paper_account_for_user(db, current_user)
    return account_service.account_to_response(account)


@router.get("/summary", response_model=AccountSummaryResponse)
async def get_account_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountSummaryResponse:
    return await account_service.get_account_summary(db, current_user)


@router.get("/settings", response_model=AccountSettingsResponse)
def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountSettingsResponse:
    return settings_service.get_settings_response(db, current_user)


@router.patch("/settings", response_model=AccountSettingsResponse)
def patch_settings(
    payload: AccountSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountSettingsResponse:
    return settings_service.update_settings(db, current_user, payload)


@router.post("/reset", response_model=AccountResetResponse)
def reset_account(
    payload: AccountResetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccountResetResponse:
    return settings_service.reset_account(db, current_user, payload)


@router.get("/reset-history", response_model=list[AccountResetHistoryItem])
def reset_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AccountResetHistoryItem]:
    return settings_service.reset_history(db, current_user)
