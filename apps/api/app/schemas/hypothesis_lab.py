from typing import Any

from pydantic import BaseModel, Field


class HypothesisCreateRequest(BaseModel):
    prompt: str = ""
    name: str | None = Field(default=None, max_length=120)
    structured_rules: dict[str, Any] | None = None


class HypothesisBacktestRequest(BaseModel):
    bars: int = Field(default=3000, ge=1000, le=10000)


class HypothesisResponse(BaseModel):
    id: str
    version: str
    name: str
    natural_language_prompt: str
    structured_rules: dict[str, Any]
    parser: str = "regex"
    created_at: str
    updated_at: str
    backtests: list[dict[str, Any]] = []
    promoted_at: str | None = None
    paper_profile: dict[str, Any] | None = None


class HypothesisListResponse(BaseModel):
    items: list[HypothesisResponse]
