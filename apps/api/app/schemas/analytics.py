"""Analytics and settings schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AnalyticsOverview(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    average_win: Decimal
    average_loss: Decimal
    profit_factor: Decimal | None
    largest_win: Decimal
    largest_loss: Decimal
    maximum_drawdown: Decimal
    average_risk_per_trade: Decimal | None
    followed_plan_count: int
    followed_plan_total: int
    followed_plan_rate: Decimal | None
    sample_size_note: str | None = None


class AssetPerformance(BaseModel):
    symbol: str
    trades: int
    realized_pnl: Decimal
    win_rate: Decimal


class EmotionPerformance(BaseModel):
    emotional_state: str
    journals: int
    linked_sells: int
    average_realized_pnl: Decimal | None
    followed_plan_rate: Decimal | None


class DisciplineStats(BaseModel):
    followed_plan_count: int
    followed_plan_total: int
    followed_plan_rate: Decimal | None
    stop_loss_usage_rate: Decimal | None
    average_confidence: Decimal | None
    trades_with_stop_loss: int
    buy_orders: int


class RiskRulesUpdate(BaseModel):
    max_risk_percent_per_trade: Decimal | None = Field(default=None, gt=0, le=100)
    max_daily_loss_percent: Decimal | None = Field(default=None, gt=0, le=100)
    max_trades_per_day: int | None = Field(default=None, ge=1, le=1000)
    require_stop_loss: bool | None = None
    trading_enabled: bool | None = None


class AccountSettingsUpdate(BaseModel):
    starting_balance: Decimal | None = Field(default=None, gt=0)
    risk_rules: RiskRulesUpdate | None = None


class AccountSettingsResponse(BaseModel):
    starting_balance: Decimal
    cash_balance: Decimal
    trading_fee_percent: Decimal
    trading_fee_usd: Decimal = Decimal("0")
    trading_fee_editable: bool = False
    max_risk_percent_per_trade: Decimal
    max_daily_loss_percent: Decimal
    max_trades_per_day: int
    require_stop_loss: bool
    trading_enabled: bool
    paper_mode_banner: str


class AccountResetRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    confirm: bool = False


class AccountResetResponse(BaseModel):
    id: int
    previous_balance: Decimal
    reset_balance: Decimal
    reason: str | None
    reset_at: datetime
    message: str


class AccountResetHistoryItem(BaseModel):
    id: int
    previous_balance: Decimal
    reset_balance: Decimal
    reason: str | None
    reset_at: datetime
