"""Phase 5 tests: journal, analytics, settings, reset."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountReset, Position, RiskRule, TradingAccount
from app.services.prices import clear_price_cache, get_price_sync_for_tests


def _quote(symbol: str, price: str):
    return get_price_sync_for_tests(symbol, Decimal(price))


def test_journal_crud(client: TestClient, auth_header: dict[str, str], seeded_assets) -> None:
    _ = seeded_assets
    create = client.post(
        "/journal",
        headers=auth_header,
        json={
            "symbol": "BTC",
            "entry_reason": "Breakout practice",
            "emotional_state": "calm",
            "confidence_score": 4,
            "followed_plan": True,
            "lesson_learned": "Wait for confirmation",
        },
    )
    assert create.status_code == 201, create.text
    journal_id = create.json()["id"]

    listed = client.get("/journal", headers=auth_header)
    assert listed.status_code == 200
    assert any(j["id"] == journal_id for j in listed.json())

    patched = client.patch(
        f"/journal/{journal_id}",
        headers=auth_header,
        json={"exit_reason": "Hit target", "followed_plan": True},
    )
    assert patched.status_code == 200
    assert patched.json()["exit_reason"] == "Hit target"

    deleted = client.delete(f"/journal/{journal_id}", headers=auth_header)
    assert deleted.status_code == 204
    assert client.get(f"/journal/{journal_id}", headers=auth_header).status_code == 404


def test_analytics_overview_empty(client: TestClient, auth_header: dict[str, str]) -> None:
    response = client.get("/analytics/overview", headers=auth_header)
    assert response.status_code == 200
    body = response.json()
    assert body["total_trades"] == 0
    assert body["sample_size_note"] is not None


def test_update_risk_rules(
    client: TestClient, auth_header: dict[str, str], db_session: Session
) -> None:
    response = client.patch(
        "/account/settings",
        headers=auth_header,
        json={
            "starting_balance": "10.00",
            "risk_rules": {
                "max_trades_per_day": 3,
                "require_stop_loss": False,
                "max_risk_percent_per_trade": "5",
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["max_trades_per_day"] == 3
    assert response.json()["require_stop_loss"] is False

    rules = db_session.scalar(select(RiskRule))
    assert rules is not None
    assert rules.max_trades_per_day == 3


def test_reset_account(
    client: TestClient,
    auth_header: dict[str, str],
    db_session: Session,
) -> None:
    clear_price_cache()
    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(return_value=_quote("BTC", "100")),
    ):
        buy = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "BTC", "usd_amount": "2", "stop_loss_price": "90"},
        )
        assert buy.status_code == 201, buy.text

    denied = client.post(
        "/account/reset",
        headers=auth_header,
        json={"confirm": False, "reason": "oops"},
    )
    assert denied.status_code == 400

    reset = client.post(
        "/account/reset",
        headers=auth_header,
        json={"confirm": True, "reason": "Fresh start"},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["reset_balance"] == "10.00000000"

    db_session.expire_all()
    account = db_session.scalar(select(TradingAccount))
    assert account is not None
    assert account.cash_balance == Decimal("10.00000000")
    assert account.realized_pnl == Decimal("0E-8") or account.realized_pnl == Decimal("0")
    assert db_session.scalars(select(Position)).first() is None
    assert db_session.scalars(select(AccountReset)).first() is not None

    history = client.get("/account/reset-history", headers=auth_header)
    assert history.status_code == 200
    assert len(history.json()) >= 1
