"""Stripe billing endpoint tests (mocked Stripe SDK)."""

from decimal import Decimal

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import AccountMode, RiskRule, TradingAccount, User
from app.services import billing as billing_service


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def stripe_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_dummy")
    monkeypatch.setenv("STRIPE_PRICE_ID_PRO", "price_test_pro")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_dummy")
    monkeypatch.setenv("WEB_APP_URL", "https://example.test")
    get_settings.cache_clear()


def _seed_user(db: Session, email: str = "bill@example.com") -> User:
    user = User(
        email=email,
        password_hash=hash_password("SecurePass1!"),
        display_name="Biller",
        subscription_plan="free",
    )
    db.add(user)
    db.flush()
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
    db.add(account)
    db.flush()
    db.add(
        RiskRule(
            trading_account_id=account.id,
            max_risk_percent_per_trade=Decimal("50"),
            max_daily_loss_percent=Decimal("50"),
            max_trades_per_day=5,
            require_stop_loss=True,
            trading_enabled=True,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _auth(client: TestClient, email: str = "bill@example.com") -> dict[str, str]:
    login = client.post("/auth/login", json={"email": email, "password": "SecurePass1!"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_billing_status_disabled_without_keys(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID_PRO", raising=False)
    get_settings.cache_clear()
    _seed_user(db_session)
    headers = _auth(client)
    response = client.get("/billing/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["billing_enabled"] is False
    assert data["plan"] == "free"
    assert data["message"]


def test_checkout_returns_503_when_disabled(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID_PRO", raising=False)
    get_settings.cache_clear()
    _seed_user(db_session)
    headers = _auth(client)
    response = client.post("/billing/checkout", headers=headers, json={})
    assert response.status_code == 503


def test_checkout_creates_session(
    client: TestClient, db_session: Session, stripe_env: None
) -> None:
    user = _seed_user(db_session)
    headers = _auth(client)
    fake_session = SimpleNamespace(url="https://checkout.stripe.test/session", id="cs_test_1")
    with patch("app.services.billing.stripe.checkout.Session.create", return_value=fake_session) as create:
        response = client.post("/billing/checkout", headers=headers, json={})
    assert response.status_code == 200
    data = response.json()
    assert data["checkout_url"].startswith("https://checkout.stripe.test/")
    assert data["session_id"] == "cs_test_1"
    kwargs = create.call_args.kwargs
    assert kwargs["mode"] == "subscription"
    assert kwargs["client_reference_id"] == str(user.id)
    assert kwargs["metadata"]["user_id"] == str(user.id)
    assert kwargs["subscription_data"]["metadata"]["user_id"] == str(user.id)


def test_webhook_checkout_completed_sets_pro(
    client: TestClient, db_session: Session, stripe_env: None
) -> None:
    user = _seed_user(db_session)
    session_obj = SimpleNamespace(
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id)},
        customer="cus_test_123",
        payment_status="paid",
    )
    event = {"type": "checkout.session.completed", "data": {"object": session_obj}}

    with patch(
        "app.services.billing.stripe.Webhook.construct_event",
        return_value=event,
    ):
        response = client.post(
            "/billing/stripe/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=fake"},
        )
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.subscription_plan == "pro"
    assert user.stripe_customer_id == "cus_test_123"


def test_webhook_subscription_deleted_sets_free(
    client: TestClient, db_session: Session, stripe_env: None
) -> None:
    user = _seed_user(db_session)
    user.subscription_plan = "pro"
    user.stripe_customer_id = "cus_del_1"
    db_session.commit()

    sub = SimpleNamespace(
        metadata={"user_id": str(user.id)},
        customer="cus_del_1",
        status="canceled",
    )
    event = {"type": "customer.subscription.deleted", "data": {"object": sub}}
    with patch(
        "app.services.billing.stripe.Webhook.construct_event",
        return_value=event,
    ):
        response = client.post(
            "/billing/stripe/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=fake"},
        )
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.subscription_plan == "free"


def test_webhook_subscription_updated_unpaid_sets_free(
    client: TestClient, db_session: Session, stripe_env: None
) -> None:
    user = _seed_user(db_session)
    user.subscription_plan = "pro"
    user.stripe_customer_id = "cus_unpaid"
    db_session.commit()

    sub = SimpleNamespace(
        metadata={"user_id": str(user.id)},
        customer="cus_unpaid",
        status="unpaid",
    )
    event = {"type": "customer.subscription.updated", "data": {"object": sub}}
    with patch(
        "app.services.billing.stripe.Webhook.construct_event",
        return_value=event,
    ):
        assert (
            client.post(
                "/billing/stripe/webhook",
                content=b"{}",
                headers={"stripe-signature": "t=1,v1=fake"},
            ).status_code
            == 200
        )
    db_session.refresh(user)
    assert user.subscription_plan == "free"


def test_webhook_rejects_bad_signature(client: TestClient, stripe_env: None) -> None:
    import stripe

    with patch(
        "app.services.billing.stripe.Webhook.construct_event",
        side_effect=stripe.error.SignatureVerificationError("bad", "sig"),
    ):
        response = client.post(
            "/billing/stripe/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=bad"},
        )
    assert response.status_code == 400


def test_portal_requires_customer(
    client: TestClient, db_session: Session, stripe_env: None
) -> None:
    _seed_user(db_session)
    headers = _auth(client)
    response = client.post("/billing/portal", headers=headers, json={})
    assert response.status_code == 400


def test_portal_creates_session(
    client: TestClient, db_session: Session, stripe_env: None
) -> None:
    user = _seed_user(db_session)
    user.stripe_customer_id = "cus_portal"
    db_session.commit()
    headers = _auth(client)
    fake = SimpleNamespace(url="https://billing.stripe.test/session")
    with patch(
        "app.services.billing.stripe.billing_portal.Session.create",
        return_value=fake,
    ):
        response = client.post("/billing/portal", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["portal_url"].startswith("https://billing.stripe.test/")


def test_status_enabled(client: TestClient, db_session: Session, stripe_env: None) -> None:
    _seed_user(db_session)
    headers = _auth(client)
    data = client.get("/billing/status", headers=headers).json()
    assert data["billing_enabled"] is True
    assert data["publishable_key"] == "pk_test_dummy"
    assert billing_service.stripe_configured()
