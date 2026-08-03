"""Journal schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EmotionalStateLiteral = Literal[
    "calm", "confident", "fearful", "greedy", "impatient", "unsure"
]


class JournalCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    order_id: int | None = None
    setup_name: str | None = Field(default=None, max_length=120)
    entry_reason: str | None = None
    exit_reason: str | None = None
    emotional_state: EmotionalStateLiteral | None = None
    confidence_score: int | None = Field(default=None, ge=1, le=5)
    followed_plan: bool | None = None
    lesson_learned: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class JournalUpdate(BaseModel):
    setup_name: str | None = Field(default=None, max_length=120)
    entry_reason: str | None = None
    exit_reason: str | None = None
    emotional_state: EmotionalStateLiteral | None = None
    confidence_score: int | None = Field(default=None, ge=1, le=5)
    followed_plan: bool | None = None
    lesson_learned: str | None = None


class JournalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    order_id: int | None
    setup_name: str | None
    entry_reason: str | None
    exit_reason: str | None
    emotional_state: str | None
    confidence_score: int | None
    followed_plan: bool | None
    lesson_learned: str | None
    created_at: datetime
    updated_at: datetime
