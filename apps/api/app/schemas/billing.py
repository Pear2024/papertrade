"""Billing / Stripe subscription schemas."""

from pydantic import BaseModel, Field


class BillingStatusResponse(BaseModel):
    plan: str = "free"
    billing_enabled: bool = False
    stripe_customer_id: str | None = None
    can_manage_billing: bool = False
    publishable_key: str | None = None
    message: str | None = None


class CheckoutSessionRequest(BaseModel):
    success_url: str | None = Field(
        default=None,
        description="Optional override; defaults to WEB_APP_URL/settings?billing=success",
    )
    cancel_url: str | None = Field(
        default=None,
        description="Optional override; defaults to WEB_APP_URL/settings?billing=cancel",
    )


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalSessionRequest(BaseModel):
    return_url: str | None = Field(
        default=None,
        description="Optional override; defaults to WEB_APP_URL/settings",
    )


class PortalSessionResponse(BaseModel):
    portal_url: str
