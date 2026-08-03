"""Price endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.market import CandleBar, CandleResponse, PriceResponse
from app.services import kraken_market
from app.services import prices as price_service

router = APIRouter(prefix="/prices", tags=["prices"])


@router.get("/feed/status")
async def market_feed_status() -> dict:
    """Kraken PUBLIC feed status. Never includes credentials or private balances."""
    return kraken_market.get_feed_status()


@router.get("", response_model=list[PriceResponse])
async def list_prices(db: Session = Depends(get_db)) -> list[PriceResponse]:
    quotes = await price_service.get_price_quotes(db)
    return [
        PriceResponse(
            symbol=q.symbol,
            price=q.price,
            change_24h_percent=q.change_24h_percent,
            source=q.source,
            captured_at=q.captured_at,
        )
        for q in quotes
    ]


@router.get("/{symbol}/candles", response_model=CandleResponse)
async def get_candles(
    symbol: str,
    interval: str = Query(default="15m", description="1m, 5m, 15m, 1h, 4h, 1d"),
    limit: int = Query(default=200, ge=20, le=500),
    db: Session = Depends(get_db),
) -> CandleResponse:
    sym, iv, source, candles = await price_service.get_candles(db, symbol, interval, limit)
    return CandleResponse(
        symbol=sym,
        interval=iv,
        source=source,
        candles=[
            CandleBar(
                time=c.time,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in candles
        ],
    )


@router.get("/{symbol}", response_model=PriceResponse)
async def get_price(symbol: str, db: Session = Depends(get_db)) -> PriceResponse:
    quote = await price_service.get_price_quote(db, symbol)
    return PriceResponse(
        symbol=quote.symbol,
        price=quote.price,
        change_24h_percent=quote.change_24h_percent,
        source=quote.source,
        captured_at=quote.captured_at,
    )
