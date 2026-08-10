"""Coach preference API schemas."""

from typing import Any

from pydantic import BaseModel, Field


class CoachPrefsResponse(BaseModel):
    settings: dict[str, Any]
    auto_session_enabled: bool | None = None


class CoachPrefsUpdate(BaseModel):
    settings: dict[str, Any] | None = None
    auto_session_enabled: bool | None = None
    clear_auto_session: bool = False
