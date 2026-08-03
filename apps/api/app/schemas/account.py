"""Account schemas."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_name: str
    account_mode: str
    starting_balance: Decimal
    cash_balance: Decimal
    realized_pnl: Decimal
    currency: str
    is_active: bool
    trading_enabled: bool
    require_stop_loss: bool
    max_risk_percent_per_trade: Decimal
    max_daily_loss_percent: Decimal
    max_trades_per_day: int


class PositionSummary(BaseModel):
    symbol: str
    quantity: Decimal
    average_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal


class AccountSummaryResponse(BaseModel):
    account: AccountResponse
    portfolio_value: Decimal
    cash_balance: Decimal
    positions_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    daily_pnl: Decimal
    trades_today: int
    positions: list[PositionSummary] = Field(default_factory=list)
    paper_mode_banner: str
