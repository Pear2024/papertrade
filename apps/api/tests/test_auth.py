"""Auth endpoint tests (register, login, me)."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AccountMode, RiskRule, TradingAccount, User


def test_register_creates_paper_account(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={
            "email": "newbie@example.com",
            "password": "SecurePass1!",
            "display_name": "Newbie",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "newbie@example.com"
    assert data["user"]["trading_account"]["account_mode"] == "paper"
    assert data["user"]["trading_account"]["cash_balance"] == "10.00000000"


def test_register_duplicate_email(client: TestClient) -> None:
    payload = {
        "email": "dup@example.com",
        "password": "SecurePass1!",
        "display_name": "Dup",
    }
    assert client.post("/auth/register", json=payload).status_code == 201
    again = client.post("/auth/register", json=payload)
    assert again.status_code == 409


def test_login_and_me(client: TestClient, db_session: Session) -> None:
    user = User(
        email="login@example.com",
        password_hash=hash_password("SecurePass1!"),
        display_name="Login User",
    )
    db_session.add(user)
    db_session.flush()
    account = TradingAccount(
        user_id=user.id,
        account_name="Paper Account",
        account_mode=AccountMode.paper,
        starting_balance=Decimal("10.00"),
        cash_balance=Decimal("10.00"),
        realized_pnl=Decimal("0"),
        currency="USD",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(
        RiskRule(
            trading_account_id=account.id,
            max_risk_percent_per_trade=Decimal("2"),
            max_daily_loss_percent=Decimal("5"),
            max_trades_per_day=5,
            require_stop_loss=True,
            trading_enabled=True,
        )
    )
    db_session.commit()

    login = client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "SecurePass1!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"
    assert me.json()["trading_account"]["account_mode"] == "paper"


def test_login_invalid_password(client: TestClient, db_session: Session) -> None:
    db_session.add(
        User(
            email="badpass@example.com",
            password_hash=hash_password("SecurePass1!"),
            display_name="Bad",
        )
    )
    db_session.commit()
    response = client.post(
        "/auth/login",
        json={"email": "badpass@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_me_requires_auth(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401
