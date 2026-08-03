"""Shared pytest fixtures for API tests."""

from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import (
    AccountMode,
    Asset,
    AssetType,
    RiskRule,
    TradingAccount,
    User,
)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_assets(db_session: Session) -> dict[str, Asset]:
    assets = {
        "BTC": Asset(
            symbol="BTC",
            name="Bitcoin",
            asset_type=AssetType.crypto,
            price_precision=2,
            quantity_precision=8,
            is_active=True,
        ),
        "ETH": Asset(
            symbol="ETH",
            name="Ethereum",
            asset_type=AssetType.crypto,
            price_precision=2,
            quantity_precision=8,
            is_active=True,
        ),
        "SOL": Asset(
            symbol="SOL",
            name="Solana",
            asset_type=AssetType.crypto,
            price_precision=2,
            quantity_precision=6,
            is_active=True,
        ),
    }
    for asset in assets.values():
        db_session.add(asset)
    db_session.commit()
    for symbol, asset in assets.items():
        db_session.refresh(asset)
        assets[symbol] = asset
    return assets


@pytest.fixture()
def auth_header(client: TestClient, db_session: Session, seeded_assets: dict[str, Asset]) -> dict[str, str]:
    _ = seeded_assets
    user = User(
        email="trader@example.com",
        password_hash=hash_password("SecurePass1!"),
        display_name="Trader",
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
            max_risk_percent_per_trade=Decimal("50"),
            max_daily_loss_percent=Decimal("50"),
            max_trades_per_day=5,
            require_stop_loss=True,
            trading_enabled=True,
        )
    )
    db_session.commit()

    login = client.post(
        "/auth/login",
        json={"email": "trader@example.com", "password": "SecurePass1!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
