"""Stripe Checkout + webhook entitlement updates for Pro subscriptions."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import User

logger = logging.getLogger(__name__)

try:
    import stripe
except ImportError:  # pragma: no cover — package listed in requirements.txt
    stripe = None  # type: ignore[assignment]

_ACTIVE_SUB_STATUSES = frozenset({"active", "trialing"})
_DOWNGRADE_SUB_STATUSES = frozenset(
    {"canceled", "unpaid", "incomplete_expired", "paused"}
)


class BillingDisabledError(Exception):
    """Raised when Stripe env vars are incomplete."""


def stripe_configured(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    if stripe is None:
        return False
    return bool(
        cfg.stripe_secret_key
        and cfg.stripe_webhook_secret
        and cfg.stripe_price_id_pro
    )


def require_stripe(settings: Settings | None = None) -> Settings:
    cfg = settings or get_settings()
    if not stripe_configured(cfg):
        raise BillingDisabledError(
            "Stripe billing is not configured. Set STRIPE_SECRET_KEY, "
            "STRIPE_WEBHOOK_SECRET, and STRIPE_PRICE_ID_PRO."
        )
    stripe.api_key = cfg.stripe_secret_key
    return cfg


def _disabled_http() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Stripe billing is not configured on this server. "
            "Ask an admin to set STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, "
            "and STRIPE_PRICE_ID_PRO."
        ),
    )


def billing_status(user: User, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    enabled = stripe_configured(cfg)
    plan = "pro" if user.subscription_plan == "pro" else "free"
    return {
        "plan": plan,
        "billing_enabled": enabled,
        "stripe_customer_id": user.stripe_customer_id,
        "can_manage_billing": bool(enabled and user.stripe_customer_id),
        "publishable_key": cfg.resolved_stripe_publishable_key if enabled else None,
        "message": None
        if enabled
        else "Online upgrades are disabled until Stripe keys are configured.",
    }


def _default_success_url(cfg: Settings) -> str:
    base = (cfg.web_app_url or "http://localhost:3001").rstrip("/")
    return f"{base}/settings?billing=success"


def _default_cancel_url(cfg: Settings) -> str:
    base = (cfg.web_app_url or "http://localhost:3001").rstrip("/")
    return f"{base}/settings?billing=cancel"


def _default_return_url(cfg: Settings) -> str:
    base = (cfg.web_app_url or "http://localhost:3001").rstrip("/")
    return f"{base}/settings"


def create_checkout_session(
    db: Session,
    user: User,
    *,
    success_url: str | None = None,
    cancel_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, str]:
    try:
        cfg = require_stripe(settings)
    except BillingDisabledError as exc:
        raise _disabled_http() from exc

    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": cfg.stripe_price_id_pro, "quantity": 1}],
        "success_url": success_url or _default_success_url(cfg),
        "cancel_url": cancel_url or _default_cancel_url(cfg),
        "client_reference_id": str(user.id),
        "metadata": {"user_id": str(user.id)},
        "subscription_data": {"metadata": {"user_id": str(user.id)}},
        "allow_promotion_codes": True,
    }
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email

    try:
        session = stripe.checkout.Session.create(**params)
    except stripe.error.StripeError as exc:
        logger.exception("Stripe Checkout Session create failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to start Stripe Checkout. Please try again later.",
        ) from exc

    return {"checkout_url": session.url, "session_id": session.id}


def create_portal_session(
    user: User,
    *,
    return_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, str]:
    try:
        cfg = require_stripe(settings)
    except BillingDisabledError as exc:
        raise _disabled_http() from exc

    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer on file. Upgrade to Pro first.",
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url or _default_return_url(cfg),
        )
    except stripe.error.StripeError as exc:
        logger.exception("Stripe Customer Portal create failed for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to open the billing portal. Please try again later.",
        ) from exc

    return {"portal_url": session.url}


def _parse_user_id(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _set_plan(db: Session, user: User, plan: str, customer_id: str | None = None) -> None:
    user.subscription_plan = plan
    if customer_id and user.stripe_customer_id != customer_id:
        user.stripe_customer_id = customer_id
    db.add(user)
    db.commit()
    db.refresh(user)


def _user_from_metadata(db: Session, metadata: dict[str, Any] | None) -> User | None:
    if not metadata:
        return None
    user_id = _parse_user_id(metadata.get("user_id"))
    if user_id is None:
        return None
    return db.get(User, user_id)


def _user_from_customer(db: Session, customer_id: str | None) -> User | None:
    if not customer_id:
        return None
    return (
        db.query(User)
        .filter(User.stripe_customer_id == customer_id)
        .order_by(User.id.asc())
        .first()
    )


def _handle_checkout_completed(db: Session, session_obj: Any) -> None:
    metadata = getattr(session_obj, "metadata", None) or {}
    if isinstance(metadata, dict):
        meta = metadata
    else:
        meta = dict(metadata) if metadata else {}

    user_id = _parse_user_id(getattr(session_obj, "client_reference_id", None))
    if user_id is None:
        user_id = _parse_user_id(meta.get("user_id"))

    if user_id is None:
        logger.warning("checkout.session.completed missing user_id metadata")
        return

    user = db.get(User, user_id)
    if user is None:
        logger.warning("checkout.session.completed unknown user_id=%s", user_id)
        return

    customer_id = getattr(session_obj, "customer", None)
    if isinstance(customer_id, str):
        customer = customer_id
    else:
        customer = getattr(customer_id, "id", None) if customer_id else None

    payment_status = getattr(session_obj, "payment_status", None)
    # Subscription Checkout may report "paid" or "no_payment_required" (trial).
    if payment_status not in (None, "paid", "no_payment_required"):
        logger.info(
            "checkout.session.completed ignored payment_status=%s user_id=%s",
            payment_status,
            user_id,
        )
        return

    _set_plan(db, user, "pro", customer)


def _handle_subscription_change(db: Session, subscription: Any) -> None:
    metadata = getattr(subscription, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = dict(metadata) if metadata else {}

    user = _user_from_metadata(db, metadata)
    customer_id = getattr(subscription, "customer", None)
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    elif customer_id is not None and not isinstance(customer_id, str):
        customer_id = getattr(customer_id, "id", None)

    if user is None:
        user = _user_from_customer(db, customer_id if isinstance(customer_id, str) else None)

    if user is None:
        logger.warning(
            "subscription event could not resolve user (customer=%s)",
            customer_id,
        )
        return

    status_value = getattr(subscription, "status", None) or ""
    if status_value in _ACTIVE_SUB_STATUSES:
        _set_plan(db, user, "pro", customer_id if isinstance(customer_id, str) else None)
    elif status_value in _DOWNGRADE_SUB_STATUSES or status_value == "incomplete":
        # incomplete is checkout abandoned; only downgrade if they were relying on this sub
        if status_value in _DOWNGRADE_SUB_STATUSES:
            _set_plan(db, user, "free", customer_id if isinstance(customer_id, str) else None)
    # past_due / incomplete: leave plan unchanged until unpaid/canceled


def construct_and_handle_webhook(
    db: Session,
    payload: bytes,
    signature_header: str | None,
    settings: Settings | None = None,
) -> dict[str, str]:
    try:
        cfg = require_stripe(settings)
    except BillingDisabledError as exc:
        raise _disabled_http() from exc

    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature_header,
            cfg.stripe_webhook_secret,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook payload",
        ) from exc
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe webhook signature",
        ) from exc

    event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    data_object = (
        event["data"]["object"]
        if isinstance(event, dict)
        else event.data.object
    )

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(db, data_object)
    elif event_type in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        if event_type == "customer.subscription.deleted":
            # Force free on delete regardless of status field
            metadata = getattr(data_object, "metadata", None) or {}
            if not isinstance(metadata, dict):
                metadata = dict(metadata) if metadata else {}
            user = _user_from_metadata(db, metadata)
            customer_id = getattr(data_object, "customer", None)
            if isinstance(customer_id, dict):
                customer_id = customer_id.get("id")
            elif customer_id is not None and not isinstance(customer_id, str):
                customer_id = getattr(customer_id, "id", None)
            if user is None:
                user = _user_from_customer(
                    db, customer_id if isinstance(customer_id, str) else None
                )
            if user is not None:
                _set_plan(
                    db,
                    user,
                    "free",
                    customer_id if isinstance(customer_id, str) else None,
                )
        else:
            _handle_subscription_change(db, data_object)
    else:
        logger.debug("Ignoring Stripe event type=%s", event_type)

    return {"status": "ok"}
