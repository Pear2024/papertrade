"""Public crypto price service (CoinGecko) with snapshot fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.money import money, percent
from app.core.assets_catalog import symbol_to_binance, symbol_to_coingecko
from app.models import Asset, PriceSnapshot, PriceSource

SYMBOL_TO_COINGECKO_ID: dict[str, str] = symbol_to_coingecko()

# Public spot pairs for chart candles only (display). Orders use live quotes.
SYMBOL_TO_BINANCE: dict[str, str] = symbol_to_binance()

ALLOWED_CANDLE_INTERVALS = frozenset(
    {"1m", "5m", "15m", "1h", "4h", "1d"}
)

_CACHE_TTL = timedelta(seconds=30)
_CANDLE_CACHE_TTL = timedelta(seconds=45)
_price_cache: dict[str, tuple[datetime, "PriceQuote"]] = {}
_candle_cache: dict[str, tuple[datetime, list["CandleBar"]]] = {}


@dataclass(frozen=True)
class CandleBar:
    time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


class PriceUnavailableError(Exception):
    """Raised when neither live API nor snapshot prices are available."""


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    price: Decimal
    change_24h_percent: Decimal | None
    source: str
    captured_at: datetime


def clear_price_cache() -> None:
    _price_cache.clear()
    _candle_cache.clear()


def get_active_assets(db: Session) -> list[Asset]:
    return list(
        db.scalars(select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.symbol))
    )


def get_asset_by_symbol(db: Session, symbol: str) -> Asset | None:
    return db.scalar(select(Asset).where(Asset.symbol == symbol.upper()))


def require_asset(db: Session, symbol: str) -> Asset:
    asset = get_asset_by_symbol(db, symbol)
    if asset is None or not asset.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset '{symbol.upper()}' not found",
        )
    return asset


def latest_snapshot(db: Session, asset_id: int) -> PriceSnapshot | None:
    return db.scalar(
        select(PriceSnapshot)
        .where(PriceSnapshot.asset_id == asset_id)
        .order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc())
        .limit(1)
    )


def record_price_snapshot(
    db: Session,
    asset_id: int,
    price: Decimal,
    source: PriceSource,
) -> PriceSnapshot:
    snapshot = PriceSnapshot(
        asset_id=asset_id,
        price=money(price),
        source=source,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


async def _fetch_coingecko_prices(symbols: list[str]) -> dict[str, PriceQuote]:
    settings = get_settings()
    ids = []
    symbol_by_id: dict[str, str] = {}
    for symbol in symbols:
        cg_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
        if cg_id:
            ids.append(cg_id)
            symbol_by_id[cg_id] = symbol.upper()

    if not ids:
        return {}

    url = f"{settings.public_price_api_url.rstrip('/')}/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

    now = datetime.now(timezone.utc)
    quotes: dict[str, PriceQuote] = {}
    for cg_id, data in payload.items():
        symbol = symbol_by_id.get(cg_id)
        if symbol is None:
            continue
        usd = data.get("usd")
        if usd is None:
            continue
        change = data.get("usd_24h_change")
        quotes[symbol] = PriceQuote(
            symbol=symbol,
            price=money(usd),
            change_24h_percent=percent(change) if change is not None else None,
            source="public_api",
            captured_at=now,
        )
    return quotes


def _quote_from_snapshot(asset: Asset, snapshot: PriceSnapshot) -> PriceQuote:
    captured = snapshot.captured_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return PriceQuote(
        symbol=asset.symbol,
        price=money(snapshot.price),
        change_24h_percent=None,
        source=f"snapshot:{snapshot.source.value}",
        captured_at=captured,
    )


async def get_price_quote(db: Session, symbol: str) -> PriceQuote:
    """Live quote for paper marks/fills.

    Prefers Kraken PUBLIC ticker (no API key). Falls back to CoinGecko / snapshot.
    Never touches Kraken private endpoints.
    """
    from app.services import kraken_market

    asset = require_asset(db, symbol)
    symbol_key = asset.symbol
    now = datetime.now(timezone.utc)

    # 1) Live Kraken WS ticker — never freeze behind the REST/CG TTL cache.
    cached_px = kraken_market.get_cached_ticker_price(symbol_key)
    if cached_px is not None:
        quote = PriceQuote(
            symbol=symbol_key,
            price=money(cached_px),
            change_24h_percent=None,
            source="kraken:ws:public",
            captured_at=now,
        )
        _price_cache[symbol_key] = (now, quote)
        return quote

    cached = _price_cache.get(symbol_key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    # 2) Kraken REST public ticker
    try:
        px = await kraken_market.fetch_rest_ticker(symbol_key)
        quote = PriceQuote(
            symbol=symbol_key,
            price=money(px),
            change_24h_percent=None,
            source="kraken:rest:public",
            captured_at=now,
        )
        _price_cache[symbol_key] = (now, quote)
        return quote
    except Exception:
        pass

    try:
        live = await _fetch_coingecko_prices([symbol_key])
        quote = live.get(symbol_key)
        if quote is not None:
            _price_cache[symbol_key] = (now, quote)
            return quote
    except Exception:
        pass

    snapshot = latest_snapshot(db, asset.id)
    if snapshot is not None:
        quote = _quote_from_snapshot(asset, snapshot)
        _price_cache[symbol_key] = (now, quote)
        return quote

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            f"Price feed unavailable for {symbol_key}. "
            "Public market API failed and no local snapshot exists."
        ),
    )


async def get_price_quotes(db: Session, symbols: list[str] | None = None) -> list[PriceQuote]:
    assets = get_active_assets(db)
    if symbols:
        wanted = {s.upper() for s in symbols}
        assets = [a for a in assets if a.symbol in wanted]

    if not assets:
        return []

    now = datetime.now(timezone.utc)
    result: list[PriceQuote] = []
    missing: list[str] = []

    for asset in assets:
        # Prefer live WS ticker so list marks move every poll.
        from app.services import kraken_market

        if asset.symbol == "BTC":
            cached_px = kraken_market.get_cached_ticker_price("BTC")
            if cached_px is not None:
                quote = PriceQuote(
                    symbol="BTC",
                    price=money(cached_px),
                    change_24h_percent=None,
                    source="kraken:ws:public",
                    captured_at=now,
                )
                _price_cache["BTC"] = (now, quote)
                result.append(quote)
                continue

        cached = _price_cache.get(asset.symbol)
        if cached and now - cached[0] < _CACHE_TTL:
            result.append(cached[1])
        else:
            missing.append(asset.symbol)

    if missing:
        live: dict[str, PriceQuote] = {}
        from app.services import kraken_market

        for symbol in list(missing):
            if symbol == "BTC":
                try:
                    cached_px = kraken_market.get_cached_ticker_price("BTC")
                    px = cached_px if cached_px is not None else await kraken_market.fetch_rest_ticker("BTC")
                    live["BTC"] = PriceQuote(
                        symbol="BTC",
                        price=money(px),
                        change_24h_percent=None,
                        source="kraken:public",
                        captured_at=now,
                    )
                    missing.remove("BTC")
                except Exception:
                    pass

        try:
            if missing:
                live.update(await _fetch_coingecko_prices(missing))
        except Exception:
            pass

        for symbol in missing:
            asset = next(a for a in assets if a.symbol == symbol)
            quote = live.get(symbol)
            if quote is None:
                snapshot = latest_snapshot(db, asset.id)
                if snapshot is None:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=(
                            f"Price feed unavailable for {symbol}. "
                            "Public market API failed and no local snapshot exists."
                        ),
                    )
                quote = _quote_from_snapshot(asset, snapshot)
            _price_cache[symbol] = (now, quote)
            result.append(quote)

    result.sort(key=lambda q: q.symbol)
    return result


def get_price_sync_for_tests(symbol: str, price: Decimal) -> PriceQuote:
    """Helper for unit tests to build a quote without HTTP."""
    return PriceQuote(
        symbol=symbol.upper(),
        price=money(price),
        change_24h_percent=None,
        source="test",
        captured_at=datetime.now(timezone.utc),
    )


async def _fetch_binance_klines(
    pair: str,
    interval: str,
    limit: int,
) -> tuple[list[CandleBar], str]:
    """Try public Binance data hosts (chart display only — no trading keys)."""
    urls = (
        "https://data-api.binance.vision/api/v3/klines",
        "https://api.binance.us/api/v3/klines",
        "https://api.binance.com/api/v3/klines",
    )
    params = {"symbol": pair, "interval": interval, "limit": limit}
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=12.0) as client:
        for url in urls:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                rows: list[Any] = response.json()
                candles: list[CandleBar] = []
                for row in rows:
                    candles.append(
                        CandleBar(
                            time=int(row[0]) // 1000,
                            open=money(Decimal(str(row[1]))),
                            high=money(Decimal(str(row[2]))),
                            low=money(Decimal(str(row[3]))),
                            close=money(Decimal(str(row[4]))),
                            volume=money(Decimal(str(row[5]))),
                        )
                    )
                if candles:
                    host = url.split("//", 1)[1].split("/", 1)[0]
                    return candles, host
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")
    raise PriceUnavailableError("; ".join(errors) or "Binance klines failed")


# Interval → CoinGecko OHLC days (resolution is coarse but works as fallback).
_COINGECKO_DAYS_FOR_INTERVAL: dict[str, int] = {
    "1m": 1,
    "5m": 1,
    "15m": 1,
    "1h": 7,
    "4h": 30,
    "1d": 90,
}


async def _fetch_coingecko_ohlc(symbol: str, interval: str) -> list[CandleBar]:
    settings = get_settings()
    coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if not coin_id:
        raise PriceUnavailableError(f"No CoinGecko id for {symbol}")
    days = _COINGECKO_DAYS_FOR_INTERVAL.get(interval, 1)
    url = f"{settings.public_price_api_url.rstrip('/')}/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": days}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        rows: list[Any] = response.json()
    candles: list[CandleBar] = []
    for row in rows:
        # [timestamp_ms, open, high, low, close]
        candles.append(
            CandleBar(
                time=int(row[0]) // 1000,
                open=money(Decimal(str(row[1]))),
                high=money(Decimal(str(row[2]))),
                low=money(Decimal(str(row[3]))),
                close=money(Decimal(str(row[4]))),
                volume=None,
            )
        )
    return candles


async def get_candles(
    db: Session,
    symbol: str,
    interval: str = "15m",
    limit: int = 200,
) -> tuple[str, str, str, list[CandleBar]]:
    """Fetch OHLC candles for chart + coach.

    Prefers Kraken PUBLIC REST/WS cache (BTC/USD 15m). Falls back to Binance / CoinGecko.
    A4 coach logic is unchanged — it only consumes CandleBar lists.
    Paper orders never hit Kraken private APIs.
    """
    from app.services import kraken_market

    asset = require_asset(db, symbol)
    symbol_key = asset.symbol.upper()
    interval_key = interval.strip().lower()
    if interval_key not in ALLOWED_CANDLE_INTERVALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported interval. Allowed: {', '.join(sorted(ALLOWED_CANDLE_INTERVALS))}",
        )
    limit = max(20, min(int(limit), 500))

    cache_key = f"{symbol_key}:{interval_key}:{limit}"
    now = datetime.now(timezone.utc)
    cached = _candle_cache.get(cache_key)
    if cached and now - cached[0] < _CANDLE_CACHE_TTL:
        return symbol_key, interval_key, "cache", cached[1]

    source = "unknown"
    candles: list[CandleBar] = []

    # 1) Kraken public
    # WS OHLC cache is BTC-only — never reuse it for ETH/SOL/etc.
    try:
        k_bars = []
        if symbol_key == "BTC":
            k_bars = kraken_market.get_cached_ohlc(interval_key, limit)
            if len(k_bars) < max(30, min(limit, 80)):
                k_bars = await kraken_market.fetch_rest_ohlc(symbol_key, interval_key, limit)
                if k_bars:
                    kraken_market.set_ohlc_bars(interval_key, k_bars)
        elif symbol_key in kraken_market.SYMBOL_TO_KRAKEN_REST:
            k_bars = await kraken_market.fetch_rest_ohlc(symbol_key, interval_key, limit)
        if k_bars:
            candles = [
                CandleBar(
                    time=b.time,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                )
                for b in k_bars[-limit:]
            ]
            source = "kraken:public"
    except Exception:  # noqa: BLE001
        candles = []

    # 2) Binance public fallback (all catalog pairs)
    if not candles:
        pair = SYMBOL_TO_BINANCE.get(symbol_key)
        if pair:
            try:
                candles, host = await _fetch_binance_klines(pair, interval_key, limit)
                source = f"binance:{host}"
            except Exception:  # noqa: BLE001
                candles = []

    # 3) CoinGecko fallback
    if not candles:
        try:
            candles = await _fetch_coingecko_ohlc(symbol_key, interval_key)
            if len(candles) > limit:
                candles = candles[-limit:]
            source = "coingecko:ohlc"
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Chart data unavailable ({exc})",
            ) from exc

    if not candles:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chart data unavailable",
        )

    # Deduplicate by candle open time
    dedup: dict[int, CandleBar] = {}
    for c in candles:
        dedup[c.time] = c
    candles = [dedup[t] for t in sorted(dedup)]

    _candle_cache[cache_key] = (now, candles)
    return symbol_key, interval_key, source, candles
