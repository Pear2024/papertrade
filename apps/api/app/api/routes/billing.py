"""Stripe billing endpoints (Checkout, Customer Portal, webhook)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models import User
from app.schemas.billing import (
    BillingStatusResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PortalSessionRequest,
    PortalSessionResponse,
)
from app.services import billing as billing_service

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/status", response_model=BillingStatusResponse)
def get_billing_status(
    current_user: User = Depends(get_current_user),
) -> BillingStatusResponse:
    return BillingStatusResponse(**billing_service.billing_status(current_user))


@router.post("/checkout", response_model=CheckoutSessionResponse)
def create_checkout(
    payload: CheckoutSessionRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckoutSessionResponse:
    body = payload or CheckoutSessionRequest()
    result = billing_service.create_checkout_session(
        db,
        current_user,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
    )
    return CheckoutSessionResponse(**result)


@router.post("/portal", response_model=PortalSessionResponse)
def create_portal(
    payload: PortalSessionRequest | None = None,
    current_user: User = Depends(get_current_user),
) -> PortalSessionResponse:
    body = payload or PortalSessionRequest()
    result = billing_service.create_portal_session(
        current_user,
        return_url=body.return_url,
    )
    return PortalSessionResponse(**result)


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Stripe webhook — verifies signature; raw body required."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    return billing_service.construct_and_handle_webhook(
        db,
        payload,
        signature,
        settings=get_settings(),
    )
