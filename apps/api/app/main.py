"""
Paper Crypto Coach API

Paper-trading only. No live exchange orders. No real-money withdrawals/deposits.
Kraken is used for PUBLIC market data only (ticker/OHLC) — never private trading APIs.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.kraken_feed_enabled:
        from app.services.kraken_market import start_kraken_feed, stop_kraken_feed

        await start_kraken_feed()
        try:
            yield
        finally:
            await stop_kraken_feed()
    else:
        yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Paper Crypto Coach — simulated crypto trading for learning. "
            "All balances are fictional. Kraken public market data only — "
            "NO real orders, NO API keys, NO private endpoints."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/", tags=["root"])
    def root() -> dict[str, str]:
        return {
            "message": "Paper Crypto Coach API",
            "mode": "paper",
            "banner": "PAPER MODE — NO REAL ORDERS",
            "docs": "/docs",
            "health": "/health",
            "ready": "/ready",
            "kraken_feed": "/prices/feed/status",
        }

    return app


app = create_app()
