"""Order request/response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: Decimal | None = None
    usd_amount: Decimal | None = None
    # Paper futures-lite: usd_amount is margin; notional = margin × leverage.
    leverage: Decimal = Field(default=Decimal("1"), ge=1, le=50)
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    setup_name: str | None = Field(default=None, max_length=120)
    entry_reason: str | None = None
    exit_reason: str | None = None
    emotional_state: (
        Literal["calm", "confident", "fearful", "greedy", "impatient", "unsure"] | None
    ) = None
    confidence_score: int | None = Field(default=None, ge=1, le=5)
    followed_plan: bool | None = None
    lesson_learned: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def require_size(self) -> "OrderRequest":
        if self.quantity is None and self.usd_amount is None:
            raise ValueError("Either quantity or usd_amount is required")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.usd_amount is not None and self.usd_amount <= 0:
            raise ValueError("usd_amount must be > 0")
        return self


class TradePreview(BaseModel):
    side: Literal["buy", "sell"]
    symbol: str
    quantity: Decimal
    estimated_price: Decimal
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    cash_after: Decimal
    estimated_max_loss: Decimal | None = None
    estimated_realized_pnl: Decimal | None = None
    risk_percent: Decimal | None = None
    leverage: Decimal = Decimal("1")
    margin_amount: Decimal | None = None
    notional_amount: Decimal | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    side: str
    order_type: str
    status: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    requested_price: Decimal | None
    filled_price: Decimal | None
    stop_loss_price: Decimal | None
    take_profit_price: Decimal | None
    fee_amount: Decimal
    rejection_reason: str | None
    created_at: datetime
    filled_at: datetime | None
    cancelled_at: datetime | None
