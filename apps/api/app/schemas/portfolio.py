"""Position and trade list schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    updated_at: datetime
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    exit_plan_order_id: int | None = None
    side: str = "flat"  # long | short | flat
    abs_quantity: Decimal | None = None
    leverage: Decimal = Decimal("1")


class PositionExitsUpdate(BaseModel):
    stop_loss_price: Decimal
    take_profit_price: Decimal | None = None


class TradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    realized_pnl: Decimal
    executed_at: datetime
