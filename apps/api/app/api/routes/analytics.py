"""Analytics routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.analytics import (
    AnalyticsOverview,
    AssetPerformance,
    DisciplineStats,
    EmotionPerformance,
)
from app.services import analytics as analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsOverview:
    return analytics_service.get_overview(db, current_user)


@router.get("/performance", response_model=AnalyticsOverview)
def performance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsOverview:
    return analytics_service.get_performance(db, current_user)


@router.get("/discipline", response_model=DisciplineStats)
def discipline(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DisciplineStats:
    return analytics_service.get_discipline(db, current_user)


@router.get("/by-asset", response_model=list[AssetPerformance])
def by_asset(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AssetPerformance]:
    return analytics_service.get_by_asset(db, current_user)


@router.get("/by-emotion", response_model=list[EmotionPerformance])
def by_emotion(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EmotionPerformance]:
    return analytics_service.get_by_emotion(db, current_user)
