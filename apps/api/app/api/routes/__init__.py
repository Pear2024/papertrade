from fastapi import APIRouter

from app.api.routes import (
    account,
    analytics,
    assets,
    auth,
    coach,
    health,
    hypothesis_lab,
    journal,
    orders,
    positions,
    prices,
    trades,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(assets.router)
api_router.include_router(prices.router)
api_router.include_router(account.router)
api_router.include_router(orders.router)
api_router.include_router(positions.router)
api_router.include_router(trades.router)
api_router.include_router(journal.router)
api_router.include_router(analytics.router)
api_router.include_router(coach.router)
api_router.include_router(hypothesis_lab.router)
