"""Authentication service: register, login, bootstrap paper account."""

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import AccountMode, RiskRule, TradingAccount, User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TradingAccountSummary,
    UserResponse,
)


def _starting_balance() -> Decimal:
    return Decimal(get_settings().paper_starting_balance)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalar(
        select(User)
        .options(
            joinedload(User.trading_accounts).joinedload(TradingAccount.risk_rules),
        )
        .where(User.id == user_id)
    )


def get_active_paper_account(user: User) -> TradingAccount | None:
    for account in user.trading_accounts:
        if account.is_active and account.account_mode == AccountMode.paper:
            return account
    return None


def build_user_response(user: User) -> UserResponse:
    account = get_active_paper_account(user)
    account_summary = None
    if account is not None:
        account_summary = TradingAccountSummary(
            id=account.id,
            account_name=account.account_name,
            account_mode=account.account_mode.value,
            starting_balance=account.starting_balance,
            cash_balance=account.cash_balance,
            realized_pnl=account.realized_pnl,
            currency=account.currency,
            is_active=account.is_active,
        )
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        trading_account=account_summary,
    )


def create_paper_account_for_user(
    db: Session,
    user: User,
    *,
    account_name: str = "Paper Account",
) -> TradingAccount:
    balance = _starting_balance()
    account = TradingAccount(
        user_id=user.id,
        account_name=account_name,
        account_mode=AccountMode.paper,
        starting_balance=balance,
        cash_balance=balance,
        realized_pnl=Decimal("0"),
        currency="USD",
        is_active=True,
    )
    db.add(account)
    db.flush()
    db.add(
        RiskRule(
            trading_account_id=account.id,
            max_risk_percent_per_trade=Decimal("2"),
            max_daily_loss_percent=Decimal("5"),
            max_trades_per_day=100,
            require_stop_loss=True,
            trading_enabled=True,
        )
    )
    return account


def register_user(db: Session, payload: RegisterRequest) -> AuthResponse:
    email = payload.email.lower()
    if get_user_by_email(db, email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
    )
    db.add(user)
    db.flush()
    create_paper_account_for_user(db, user)
    db.commit()

    refreshed = get_user_by_id(db, user.id)
    assert refreshed is not None
    token = create_access_token(str(refreshed.id), extra_claims={"email": refreshed.email})
    return AuthResponse(access_token=token, user=build_user_response(refreshed))


def authenticate_user(db: Session, payload: LoginRequest) -> AuthResponse:
    user = get_user_by_email(db, payload.email.lower())
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    loaded = get_user_by_id(db, user.id)
    assert loaded is not None
    token = create_access_token(str(loaded.id), extra_claims={"email": loaded.email})
    return AuthResponse(access_token=token, user=build_user_response(loaded))
