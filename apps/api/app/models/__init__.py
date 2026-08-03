"""SQLAlchemy ORM models for Paper Crypto Coach."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    AccountMode,
    AssetType,
    EmotionalState,
    OrderSide,
    OrderStatus,
    OrderType,
    PriceSource,
)

# Money / quantity precision (Decimal — never float for balances)
MONEY = Numeric(20, 8)
PRICE = Numeric(20, 8)
QTY = Numeric(28, 12)
PERCENT = Numeric(8, 4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    trading_accounts: Mapped[list[TradingAccount]] = relationship(back_populates="user")
    journals: Mapped[list[TradingJournal]] = relationship(back_populates="user")


class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_mode: Mapped[AccountMode] = mapped_column(
        Enum(AccountMode), nullable=False, default=AccountMode.paper
    )
    starting_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="trading_accounts")
    positions: Mapped[list[Position]] = relationship(back_populates="trading_account")
    orders: Mapped[list[Order]] = relationship(back_populates="trading_account")
    trades: Mapped[list[Trade]] = relationship(back_populates="trading_account")
    risk_rules: Mapped[Optional[RiskRule]] = relationship(
        back_populates="trading_account", uselist=False
    )
    resets: Mapped[list[AccountReset]] = relationship(back_populates="trading_account")
    journals: Mapped[list[TradingJournal]] = relationship(back_populates="trading_account")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(
        Enum(AssetType), nullable=False, default=AssetType.crypto
    )
    price_precision: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    quantity_precision: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    price_snapshots: Mapped[list[PriceSnapshot]] = relationship(back_populates="asset")
    positions: Mapped[list[Position]] = relationship(back_populates="asset")
    orders: Mapped[list[Order]] = relationship(back_populates="asset")
    trades: Mapped[list[Trade]] = relationship(back_populates="asset")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    source: Mapped[PriceSource] = mapped_column(
        Enum(PriceSource), nullable=False, default=PriceSource.trade_fill
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    asset: Mapped[Asset] = relationship(back_populates="price_snapshots")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType), nullable=False, default=OrderType.market
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), nullable=False, default=OrderStatus.pending
    )
    requested_quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=Decimal("0"))
    requested_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    filled_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    stop_loss_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    take_profit_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    fee_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    trading_account: Mapped[TradingAccount] = relationship(back_populates="orders")
    asset: Mapped[Asset] = relationship(back_populates="orders")
    trades: Mapped[list[Trade]] = relationship(back_populates="order")
    journal: Mapped[Optional[TradingJournal]] = relationship(
        back_populates="order", uselist=False
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    trading_account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    net_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    order: Mapped[Order] = relationship(back_populates="trades")
    trading_account: Mapped[TradingAccount] = relationship(back_populates="trades")
    asset: Mapped[Asset] = relationship(back_populates="trades")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("trading_account_id", "asset_id", name="uq_position_account_asset"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    average_entry_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    current_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    market_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    # Paper futures-lite: 1 = spot-style cash; >1 = margin × leverage notional.
    leverage: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, default=Decimal("1"), server_default="1"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    trading_account: Mapped[TradingAccount] = relationship(back_populates="positions")
    asset: Mapped[Asset] = relationship(back_populates="positions")


class TradingJournal(Base):
    __tablename__ = "trading_journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    trading_account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id"), nullable=False, index=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id"), nullable=True, unique=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    setup_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    entry_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    emotional_state: Mapped[Optional[EmotionalState]] = mapped_column(
        Enum(EmotionalState), nullable=True
    )
    confidence_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    followed_plan: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    lesson_learned: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="journals")
    trading_account: Mapped[TradingAccount] = relationship(back_populates="journals")
    order: Mapped[Optional[Order]] = relationship(back_populates="journal")
    asset: Mapped[Asset] = relationship()


class RiskRule(Base):
    __tablename__ = "risk_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id"), nullable=False, unique=True
    )
    max_risk_percent_per_trade: Mapped[Decimal] = mapped_column(
        PERCENT, nullable=False, default=Decimal("2")
    )
    max_daily_loss_percent: Mapped[Decimal] = mapped_column(
        PERCENT, nullable=False, default=Decimal("5")
    )
    max_trades_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    require_stop_loss: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    trading_account: Mapped[TradingAccount] = relationship(back_populates="risk_rules")


class CoachSignalEvent(Base):
    """Persisted coach verdicts for hypothesis analysis (paper only)."""

    __tablename__ = "coach_signal_events"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "interval",
            "evaluated_bar_time",
            "brain",
            name="uq_coach_signal_bar",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    interval: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    brain: Mapped[str] = mapped_column(String(80), nullable=False, default="DayTradeCryptoCoach")
    # BUY | SELL | WAIT (actionable ENTRY maps to BUY/SELL)
    signal: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # ENTRY_BUY | ENTRY_SELL | NONE
    entry: Mapped[str] = mapped_column(String(16), nullable=False, default="NONE", index=True)
    # HOLD_LONG | HOLD_SHORT | NONE (legacy: BUY_TREND / SELL_TREND)
    trend: Mapped[str] = mapped_column(String(16), nullable=False, default="NONE", index=True)
    # ENTRY_BUY | HOLD_LONG | EXIT_BUY | … (single story label)
    phase: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    # NEUTRAL | LONG | SHORT after this bar
    position_state: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    # EXIT_BUY | EXIT_SELL | NONE
    exit_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Signal | stop_loss | take_profit
    exit_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Analysis side / phase alias: ENTRY_BUY | HOLD_LONG | EXIT_BUY | WAIT …
    alert_side: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    # 1 = ENTRY bar of this run, 2+ = later alerts in same BUY/SELL streak
    seq_from_entry: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    # Mark-to-entry %: LONG (p-e)/e*100 · SHORT (e-p)/e*100
    pnl_pct_vs_entry: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    still_profit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    short_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cofr: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    ema9: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    ema21: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    take_profit: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    risk_reward: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bar_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evaluated_bar_time: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AccountReset(Base):
    __tablename__ = "account_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id"), nullable=False, index=True
    )
    previous_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reset_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    trading_account: Mapped[TradingAccount] = relationship(back_populates="resets")
