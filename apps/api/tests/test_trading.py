"""Paper trading buy/sell integration tests."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, Position, RiskRule, Trade, TradingAccount
from app.services.prices import PriceQuote, clear_price_cache, get_price_sync_for_tests


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_price_cache()


def _quote(symbol: str, price: str) -> PriceQuote:
    return get_price_sync_for_tests(symbol, Decimal(price))


def test_buy_success(
    client: TestClient,
    auth_header: dict[str, str],
    db_session: Session,
) -> None:
    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(return_value=_quote("BTC", "100")),
    ):
        response = client.post(
            "/orders/buy",
            headers=auth_header,
            json={
                "symbol": "BTC",
                "usd_amount": "5",
                "stop_loss_price": "90",
                "entry_reason": "Test buy",
                "emotional_state": "calm",
                "confidence_score": 4,
                "followed_plan": True,
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "filled"
    assert body["side"] == "buy"

    account = db_session.scalar(select(TradingAccount))
    assert account is not None
    assert account.cash_balance < Decimal("10")

    position = db_session.scalar(select(Position))
    assert position is not None
    assert position.quantity > 0

    trade = db_session.scalar(select(Trade))
    assert trade is not None
    assert trade.fee_amount > 0


def test_buy_insufficient_cash(
    client: TestClient,
    auth_header: dict[str, str],
) -> None:
    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(return_value=_quote("BTC", "100")),
    ):
        response = client.post(
            "/orders/buy",
            headers=auth_header,
            json={
                "symbol": "BTC",
                "usd_amount": "50",
                "stop_loss_price": "90",
            },
        )
    assert response.status_code == 400
    assert "Insufficient cash" in response.json()["detail"]


def test_buy_requires_stop_loss(
    client: TestClient,
    auth_header: dict[str, str],
) -> None:
    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(return_value=_quote("BTC", "100")),
    ):
        response = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "BTC", "usd_amount": "1"},
        )
    assert response.status_code == 422
    assert "Stop loss" in response.json()["detail"]


def test_sell_exceeds_position(
    client: TestClient,
    auth_header: dict[str, str],
) -> None:
    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(return_value=_quote("BTC", "100")),
    ):
        buy = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "BTC", "quantity": "0.01", "stop_loss_price": "90"},
        )
        assert buy.status_code == 201
        sell = client.post(
            "/orders/sell",
            headers=auth_header,
            json={"symbol": "BTC", "quantity": "1"},
        )
    assert sell.status_code == 400
    assert "exceeds" in sell.json()["detail"].lower()


def test_average_entry_and_realized_pnl(
    client: TestClient,
    auth_header: dict[str, str],
    db_session: Session,
) -> None:
    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(side_effect=[
            _quote("BTC", "100"),
            _quote("BTC", "200"),
            _quote("BTC", "150"),
        ]),
    ):
        assert client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "BTC", "quantity": "0.02", "stop_loss_price": "80"},
        ).status_code == 201
        assert client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "BTC", "quantity": "0.02", "stop_loss_price": "80"},
        ).status_code == 201

        position = db_session.scalar(select(Position))
        assert position is not None
        db_session.refresh(position)
        assert position.average_entry_price == Decimal("150.00000000")

        sell = client.post(
            "/orders/sell",
            headers=auth_header,
            json={"symbol": "BTC", "quantity": "0.02"},
        )
        assert sell.status_code == 201

    trades = list(db_session.scalars(select(Trade).where(Trade.side == "sell")))
    assert len(trades) == 1
    # Sell 0.02 @ 150, entry 150, fee = 0.02*150*0.0005 = 0.0015 → pnl negative fee
    assert trades[0].realized_pnl == Decimal("-0.00150000")


def test_max_trades_per_day(
    client: TestClient,
    auth_header: dict[str, str],
    db_session: Session,
) -> None:
    rules = db_session.scalar(select(RiskRule))
    assert rules is not None
    rules.max_trades_per_day = 1
    rules.require_stop_loss = False
    db_session.commit()

    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(return_value=_quote("ETH", "10")),
    ):
        first = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "ETH", "usd_amount": "1"},
        )
        second = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "ETH", "usd_amount": "1"},
        )
    assert first.status_code == 201
    assert second.status_code == 403
    assert "Daily trade limit" in second.json()["detail"]


def test_daily_loss_limit(
    client: TestClient,
    auth_header: dict[str, str],
    db_session: Session,
) -> None:
    rules = db_session.scalar(select(RiskRule))
    assert rules is not None
    rules.require_stop_loss = False
    rules.max_daily_loss_percent = Decimal("1")
    db_session.commit()

    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(side_effect=[
            _quote("SOL", "100"),
            _quote("SOL", "50"),
            _quote("SOL", "50"),
        ]),
    ):
        buy = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "SOL", "quantity": "0.05"},
        )
        assert buy.status_code == 201
        sell = client.post(
            "/orders/sell",
            headers=auth_header,
            json={"symbol": "SOL", "quantity": "0.05"},
        )
        assert sell.status_code == 201
        blocked = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "SOL", "usd_amount": "1"},
        )
    assert blocked.status_code == 403
    assert "Daily loss limit" in blocked.json()["detail"]


def test_transaction_rollback_on_failure(
    client: TestClient,
    auth_header: dict[str, str],
    db_session: Session,
) -> None:
    orders_before = db_session.scalars(select(Order)).all()
    assert len(orders_before) == 0

    with patch(
        "app.services.trading.get_price_quote",
        new=AsyncMock(return_value=_quote("BTC", "100")),
    ), patch(
        "app.services.trading.record_price_snapshot",
        side_effect=RuntimeError("boom"),
    ):
        response = client.post(
            "/orders/buy",
            headers=auth_header,
            json={"symbol": "BTC", "usd_amount": "1", "stop_loss_price": "90"},
        )
    assert response.status_code == 500

    db_session.expire_all()
    assert db_session.scalars(select(Order)).first() is None
    account = db_session.scalar(select(TradingAccount))
    assert account is not None
    assert account.cash_balance == Decimal("10.00000000")
