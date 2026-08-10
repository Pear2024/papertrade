r"""Backtest CCR BUY entries closed at the entry bar's close.

Method:
  1. A closed confirmation bar satisfies CCR.
  2. Buy at the following (entry) bar's open.
  3. Sell at that same entry bar's close.

Example:
  .venv\Scripts\python.exe scripts\analyze_ccr_one_bar.py --symbol BTC --interval 15m
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.coach_ccr import (  # noqa: E402
    CCR_CONSECUTIVE_DEFAULT,
    OHLC,
    clamp_ccr_consecutive,
    ccr_buy_at,
)

BINANCE_PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
BINANCE_URLS = (
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
)


@dataclass(frozen=True)
class Bar:
    time: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Trade:
    confirmation_time: int
    entry_time: int
    entry: float
    exit: float
    gross_pct: float
    net_pct: float


async def fetch_bars(pair: str, interval: str, target: int) -> tuple[list[Bar], str]:
    """Fetch historical public Binance candles, trying the app's fallback hosts."""
    errors: list[str] = []
    for url in BINANCE_URLS:
        try:
            bars: list[Bar] = []
            end_time: int | None = None
            async with httpx.AsyncClient(timeout=30.0) as client:
                while len(bars) < target:
                    params: dict[str, str | int] = {"symbol": pair, "interval": interval, "limit": 1000}
                    if end_time is not None:
                        params["endTime"] = end_time
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    rows = response.json()
                    if not rows:
                        break
                    chunk = [
                        Bar(
                            time=int(row[0]) // 1000,
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                        )
                        for row in rows
                    ]
                    bars = chunk + bars
                    end_time = int(rows[0][0]) - 1
                    if len(rows) < 1000:
                        break
                    await asyncio.sleep(0.08)
            deduped = {bar.time: bar for bar in bars}
            result = [deduped[t] for t in sorted(deduped)][-target:]
            if result:
                return result, url.split("//", 1)[1].split("/", 1)[0]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Unable to fetch Binance candles: " + "; ".join(errors))


def run_one_bar_backtest(
    bars: list[Bar], consecutive: int, fee_rate: float
) -> list[Trade]:
    """Return non-overlapping one-entry-bar CCR trades from fully closed candles."""
    ohlc = [OHLC(b.open, b.high, b.low, b.close) for b in bars]
    trades: list[Trade] = []
    for confirmation_idx in range(len(bars) - 1):
        if not ccr_buy_at(ohlc, confirmation_idx, consecutive):
            continue
        entry_bar = bars[confirmation_idx + 1]
        gross_return = entry_bar.close / entry_bar.open - 1
        # Buy costs entry * (1 + fee), sell yields exit * (1 - fee).
        net_return = (entry_bar.close * (1 - fee_rate)) / (entry_bar.open * (1 + fee_rate)) - 1
        trades.append(
            Trade(
                confirmation_time=bars[confirmation_idx].time,
                entry_time=entry_bar.time,
                entry=entry_bar.open,
                exit=entry_bar.close,
                gross_pct=gross_return * 100,
                net_pct=net_return * 100,
            )
        )
    return trades


def pct(value: float) -> str:
    return f"{value:+.3f}%"


def report(trades: list[Trade]) -> None:
    if not trades:
        print("No completed CCR trades in this sample.")
        return
    gross = [trade.gross_pct for trade in trades]
    net = [trade.net_pct for trade in trades]
    winners = [value for value in net if value > 0]
    losers = [value for value in net if value < 0]
    gross_winners = [value for value in gross if value > 0]
    compounded_gross = (math.prod(1 + value / 100 for value in gross) - 1) * 100
    compounded_net = (math.prod(1 + value / 100 for value in net) - 1) * 100
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss else None
    equity = peak = max_drawdown = 1.0
    for value in net:
        equity *= 1 + value / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak)

    print("--- RESULTS (net of stated fees) ---")
    print(f"trades={len(trades)}")
    print(f"win_rate_net={len(winners) / len(trades) * 100:.2f}% ({len(winners)} wins, {len(losers)} losses)")
    print(f"win_rate_gross={len(gross_winners) / len(trades) * 100:.2f}%")
    print(f"avg_pnl_net={pct(sum(net) / len(net))}")
    print(f"total_return_net_compounded={pct(compounded_net)}")
    print(f"total_return_gross_compounded={pct(compounded_gross)}")
    print(f"profit_factor_net={profit_factor:.3f}" if profit_factor is not None else "profit_factor_net=n/a")
    print(f"max_drawdown_net={pct((max_drawdown - 1) * 100)}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=BINANCE_PAIRS, default="BTC")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=10_000, help="Historical candles (max requested).")
    parser.add_argument("--consecutive", type=int, default=CCR_CONSECUTIVE_DEFAULT)
    parser.add_argument(
        "--fee-bps",
        type=float,
        default=10.0,
        help="Fee per side in basis points; app paper backtests use 10 bps.",
    )
    args = parser.parse_args()
    if args.bars < 100:
        parser.error("--bars must be at least 100")
    if args.fee_bps < 0:
        parser.error("--fee-bps cannot be negative")

    pair = BINANCE_PAIRS[args.symbol]
    consecutive = clamp_ccr_consecutive(args.consecutive)
    fee_rate = args.fee_bps / 10_000
    bars, source = await fetch_bars(pair, args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    # Binance includes its forming candle; it is unavailable at a live decision time.
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    start = datetime.fromtimestamp(bars[0].time, tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc).isoformat()

    print("=== CCR BUY: EXIT AT ENTRY-BAR CLOSE ===")
    print(
        f"source=binance:{source} pair={pair} interval={args.interval} "
        f"bars={len(bars)} period={start} to {end}"
    )
    print(
        f"rule=CCR(n={consecutive}) confirmation close -> buy next bar open -> "
        f"sell that same bar close; fee={args.fee_bps:.1f} bps per side"
    )
    report(run_one_bar_backtest(bars, consecutive, fee_rate))


if __name__ == "__main__":
    asyncio.run(main())
