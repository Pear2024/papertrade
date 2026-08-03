from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.database import check_database_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str
    version: str
    mode: str = Field(
        default="paper",
        description="Trading mode. Phase 1+ is paper-only.",
    )


class ReadyResponse(BaseModel):
    status: str = Field(examples=["ready", "not_ready"])
    database: str = Field(examples=["up", "down"])
    detail: str | None = None


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — process is running."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        mode="paper",
    )


@router.get("/ready", response_model=ReadyResponse)
def ready() -> ReadyResponse:
    """Readiness probe — dependencies (MySQL) are reachable."""
    db_up = check_database_connection()
    if not db_up:
        return ReadyResponse(
            status="not_ready",
            database="down",
            detail="MySQL is not reachable yet",
        )
    return ReadyResponse(status="ready", database="up")
