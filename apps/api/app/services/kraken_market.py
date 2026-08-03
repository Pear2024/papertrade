"""Kraken PUBLIC market data only (REST + WebSocket).

SAFETY:
- Public endpoints only (Ticker, OHLC, WebSocket ticker/ohlc).
- NEVER call private Kraken APIs (no Balance, AddOrder, CancelOrder,
  Withdraw, Transfer, or any authenticated REST/WS).
- NEVER request or store API key / API secret.
- Paper trading only — this module feeds simulated prices, not real orders.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

import httpx

from app.core.money import money

logger = logging.getLogger(__name__)

ConnectionState = Literal["connected", "reconnecting", "disconnected"]

KRAKEN_REST = "https://api.kraken.com"
KRAKEN_WS = "wss://ws.kraken.com/v2"

# Public pair names (no auth).
SYMBOL_TO_KRAKEN_REST: dict[str, str] = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
}
SYMBOL_TO_KRAKEN_WS: dict[str, str] = {
    "BTC": "BTC/USD",
    "ETH": "ETH/USD",
    "SOL": "SOL/USD",
}

INTERVAL_TO_KRAKEN_MIN: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


@dataclass
class KrakenCandle:
    time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


@dataclass
class KrakenFeedState:
    status: ConnectionState = "disconnected"
    last_error: str | None = None
    last_ticker_at: datetime | None = None
    last_ohlc_at: datetime | None = None
    ticker_price: Decimal | None = None
    ticker_symbol: str = "BTC"
    # Closed + forming OHLC keyed by interval minutes for BTC/USD
    ohlc_by_interval: dict[int, list[KrakenCandle]] = field(default_factory=dict)
    last_closed_candle_time: dict[int, int] = field(default_factory=dict)
    reconnect_attempts: int = 0
    paper_only: bool = True
    private_api_used: bool = False  # always False by design


_state = KrakenFeedState()
_task: asyncio.Task | None = None
_lock = asyncio.Lock()


def get_feed_status() -> dict[str, Any]:
    """Public status for the dashboard — never includes secrets."""
    return {
        "paper_only": True,
        "exchange": "kraken",
        "mode": "public_market_data_only",
        "private_api_used": False,
        "api_key_required": False,
        "status": _state.status,
        "symbol": "BTC/USD",
        "last_error": _state.last_error,
        "last_ticker_at": _state.last_ticker_at.isoformat() if _state.last_ticker_at else None,
        "last_ohlc_at": _state.last_ohlc_at.isoformat() if _state.last_ohlc_at else None,
        "ticker_price": str(_state.ticker_price) if _state.ticker_price is not None else None,
        "reconnect_attempts": _state.reconnect_attempts,
        "last_closed_candle_time_15m": _state.last_closed_candle_time.get(15),
        "ws_url": KRAKEN_WS,
        "rest_url": KRAKEN_REST,
        "banner": "PAPER MODE — NO REAL ORDERS",
    }


def get_cached_ticker_price(symbol: str = "BTC") -> Decimal | None:
    if symbol.upper() != "BTC":
        return None
    return _state.ticker_price


def get_cached_ohlc(interval: str = "15m", limit: int = 200) -> list[KrakenCandle]:
    mins = INTERVAL_TO_KRAKEN_MIN.get(interval.strip().lower())
    if mins is None:
        return []
    bars = list(_state.ohlc_by_interval.get(mins) or [])
    if len(bars) > limit:
        return bars[-limit:]
    return bars


def get_last_closed_candle_time(interval: str = "15m") -> int | None:
    mins = INTERVAL_TO_KRAKEN_MIN.get(interval.strip().lower())
    if mins is None:
        return None
    return _state.last_closed_candle_time.get(mins)


async def fetch_rest_ticker(symbol: str = "BTC") -> Decimal:
    pair = SYMBOL_TO_KRAKEN_REST.get(symbol.upper())
    if not pair:
        raise ValueError(f"Unsupported Kraken symbol {symbol}")
    url = f"{KRAKEN_REST}/0/public/Ticker"
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(url, params={"pair": pair})
        response.raise_for_status()
        payload = response.json()
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    result = payload.get("result") or {}
    # Result key may be XXBTZUSD etc.
    first = next(iter(result.values()))
    last = first["c"][0]  # last trade closed price
    return money(Decimal(str(last)))


async def fetch_rest_ohlc(
    symbol: str = "BTC",
    interval: str = "15m",
    limit: int = 200,
) -> list[KrakenCandle]:
    pair = SYMBOL_TO_KRAKEN_REST.get(symbol.upper())
    mins = INTERVAL_TO_KRAKEN_MIN.get(interval.strip().lower())
    if not pair or mins is None:
        raise ValueError(f"Unsupported Kraken pair/interval {symbol}/{interval}")
    url = f"{KRAKEN_REST}/0/public/OHLC"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params={"pair": pair, "interval": mins})
        response.raise_for_status()
        payload = response.json()
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    result = payload.get("result") or {}
    rows = None
    for key, value in result.items():
        if key == "last":
            continue
        rows = value
        break
    if not rows:
        return []
    candles: list[KrakenCandle] = []
    for row in rows:
        # [time, open, high, low, close, vwap, volume, count]
        candles.append(
            KrakenCandle(
                time=int(row[0]),
                open=money(Decimal(str(row[1]))),
                high=money(Decimal(str(row[2]))),
                low=money(Decimal(str(row[3]))),
                close=money(Decimal(str(row[4]))),
                volume=money(Decimal(str(row[6]))),
            )
        )
    if len(candles) > limit:
        candles = candles[-limit:]
    return candles


def _upsert_candle(interval_min: int, candle: KrakenCandle, *, closed: bool) -> None:
    bars = _state.ohlc_by_interval.setdefault(interval_min, [])
    if bars and bars[-1].time == candle.time:
        bars[-1] = candle
    else:
        # Deduplicate by time if mid-list insert not needed — append or replace last
        existing_idx = next((i for i, b in enumerate(bars) if b.time == candle.time), None)
        if existing_idx is not None:
            bars[existing_idx] = candle
        else:
            bars.append(candle)
            bars.sort(key=lambda b: b.time)
            if len(bars) > 500:
                del bars[:-500]
    if closed:
        prev = _state.last_closed_candle_time.get(interval_min)
        if prev is None or candle.time >= prev:
            _state.last_closed_candle_time[interval_min] = candle.time
    _state.last_ohlc_at = datetime.now(timezone.utc)


async def seed_rest_cache(symbol: str = "BTC", interval: str = "15m") -> None:
    """Bootstrap OHLC + ticker from public REST (no keys)."""
    try:
        price = await fetch_rest_ticker(symbol)
        _state.ticker_price = price
        _state.ticker_symbol = symbol.upper()
        _state.last_ticker_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kraken REST ticker seed failed: %s", exc)
        _state.last_error = str(exc)

    try:
        candles = await fetch_rest_ohlc(symbol, interval, limit=300)
        set_ohlc_bars(interval, candles)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kraken REST OHLC seed failed: %s", exc)
        _state.last_error = str(exc)


def set_ohlc_bars(interval: str, candles: list[KrakenCandle]) -> None:
    mins = INTERVAL_TO_KRAKEN_MIN.get(interval.strip().lower())
    if mins is None:
        return
    _state.ohlc_by_interval[mins] = list(candles)
    if len(candles) >= 2:
        _state.last_closed_candle_time[mins] = candles[-2].time
    elif candles:
        _state.last_closed_candle_time[mins] = candles[-1].time
    _state.last_ohlc_at = datetime.now(timezone.utc)


async def _ws_loop() -> None:
    """Maintain public WebSocket with auto-reconnect. Never authenticates."""
    try:
        import websockets  # type: ignore
    except ImportError:
        logger.error("websockets package missing — Kraken WS disabled; REST still works")
        _state.status = "disconnected"
        _state.last_error = "websockets package not installed"
        return

    backoff = 1.0
    while True:
        try:
            _state.status = "reconnecting" if _state.reconnect_attempts else "reconnecting"
            _state.reconnect_attempts += 1
            async with websockets.connect(
                KRAKEN_WS,
                ping_interval=20,
                ping_timeout=20,
                max_queue=32,
            ) as ws:
                _state.status = "connected"
                _state.last_error = None
                backoff = 1.0
                logger.info("Kraken public WebSocket connected (paper market data only)")

                # Subscribe ticker + 15m OHLC for BTC/USD — public channels only.
                await ws.send(
                    json.dumps(
                        {
                            "method": "subscribe",
                            "params": {
                                "channel": "ticker",
                                "symbol": [SYMBOL_TO_KRAKEN_WS["BTC"]],
                            },
                        }
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "method": "subscribe",
                            "params": {
                                "channel": "ohlc",
                                "symbol": [SYMBOL_TO_KRAKEN_WS["BTC"]],
                                "interval": 15,
                            },
                        }
                    )
                )

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    await _handle_ws_message(msg)

        except asyncio.CancelledError:
            _state.status = "disconnected"
            raise
        except Exception as exc:  # noqa: BLE001
            _state.status = "reconnecting"
            _state.last_error = str(exc)
            logger.warning("Kraken WS disconnected (%s); reconnecting in %.1fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def _handle_ws_message(msg: dict[str, Any]) -> None:
    channel = msg.get("channel")
    typ = msg.get("type")
    data = msg.get("data")

    if channel == "ticker" and isinstance(data, list):
        for item in data:
            last = item.get("last") or item.get("price")
            if last is None:
                continue
            _state.ticker_price = money(Decimal(str(last)))
            _state.last_ticker_at = datetime.now(timezone.utc)
        return

    if channel == "ohlc" and isinstance(data, list):
        for item in data:
            try:
                interval_min = int(item.get("interval") or 15)
                candle = KrakenCandle(
                    time=_parse_ohlc_time(item),
                    open=money(Decimal(str(item["open"]))),
                    high=money(Decimal(str(item["high"]))),
                    low=money(Decimal(str(item["low"]))),
                    close=money(Decimal(str(item["close"]))),
                    volume=money(Decimal(str(item.get("volume") or 0))),
                )
            except Exception:  # noqa: BLE001
                continue
            bars = _state.ohlc_by_interval.get(interval_min) or []
            if bars and candle.time > bars[-1].time:
                # New interval started → previous bar is closed.
                _upsert_candle(interval_min, bars[-1], closed=True)
            _upsert_candle(interval_min, candle, closed=False)
            updated = _state.ohlc_by_interval.get(interval_min) or []
            if len(updated) >= 2:
                _state.last_closed_candle_time[interval_min] = updated[-2].time
        return


def _parse_ohlc_time(item: dict[str, Any]) -> int:
    """Parse Kraken OHLC interval begin into unix seconds."""
    if "interval_begin" in item:
        raw = item["interval_begin"]
        if isinstance(raw, (int, float)):
            return int(raw)
        # ISO-8601
        text = str(raw).replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).timestamp())
    if "timestamp" in item:
        text = str(item["timestamp"]).replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).timestamp())
    raise ValueError("no ohlc time")


async def start_kraken_feed() -> None:
    """Start background public WS + REST seed. Idempotent."""
    global _task
    async with _lock:
        await seed_rest_cache("BTC", "15m")
        if _task is not None and not _task.done():
            return
        _task = asyncio.create_task(_ws_loop(), name="kraken-public-ws")


async def stop_kraken_feed() -> None:
    global _task
    async with _lock:
        if _task is not None:
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
            _task = None
        _state.status = "disconnected"
