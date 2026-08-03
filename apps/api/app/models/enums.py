"""Shared SQLAlchemy enums for Paper Crypto Coach."""

from enum import Enum


class AccountMode(str, Enum):
    paper = "paper"


class AssetType(str, Enum):
    crypto = "crypto"


class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"


class OrderStatus(str, Enum):
    pending = "pending"
    filled = "filled"
    rejected = "rejected"
    cancelled = "cancelled"


class EmotionalState(str, Enum):
    calm = "calm"
    confident = "confident"
    fearful = "fearful"
    greedy = "greedy"
    impatient = "impatient"
    unsure = "unsure"


class PriceSource(str, Enum):
    public_api = "public_api"
    trade_fill = "trade_fill"
    manual = "manual"
