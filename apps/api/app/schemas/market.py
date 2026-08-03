"""Asset and price schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    asset_type: str
    price_precision: int
    quantity_precision: int
    is_active: bool


class PriceResponse(BaseModel):
    symbol: str
    price: Decimal
    change_24h_percent: Decimal | None = None
    source: str
    captured_at: datetime


class CandleBar(BaseModel):
    time: int  # unix seconds (UTC)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


class CandleResponse(BaseModel):
    symbol: str
    interval: str
    source: str
    candles: list[CandleBar]
