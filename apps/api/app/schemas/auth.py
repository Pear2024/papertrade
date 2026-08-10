"""Auth-related Pydantic schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TradingAccountSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_name: str
    account_mode: str
    starting_balance: Decimal
    cash_balance: Decimal
    realized_pnl: Decimal
    currency: str
    is_active: bool


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    subscription_plan: str = "free"
    created_at: datetime
    trading_account: TradingAccountSummary | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
