"""Compare CCR BUY exit rules on identical Binance candles.

Entries: a closed CCR(n) confirmation -> BUY at the following candle's open.
Only one position may be open per variant; signals while it is open are skipped.

Examples:
  .venv\\Scripts\\python.exe scripts\\analyze_ccr_exits.py --symbol BTC --interval 15m
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
    volume: float = 0.0


@dataclass(frozen=True)
class Trade:
    gross: float
    net: float


@dataclass(frozen=True)
class Metrics:
    trades: int
    win_rate: float
    avg: float
    total: float
    profit_factor: float | None
    max_drawdown: float


async def fetch_bars(pair: str, interval: str, target: int) -> tuple[list[Bar], str]:
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
                    bars = [
                        Bar(
                            int(row[0]) // 1000,
                            float(row[1]),
                            float(row[2]),
                            float(row[3]),
                            float(row[4]),
                            float(row[5]),
                        )
                        for row in rows
                    ] + bars
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


def make_trade(entry: float, exit_price: float, fee_rate: float) -> Trade:
    gross = exit_price / entry - 1
    net = exit_price * (1 - fee_rate) / (entry * (1 + fee_rate)) - 1
    return Trade(gross, net)


def hold_trades(bars: list[Bar], consecutive: int, fee_rate: float, hold_bars: int) -> list[Trade]:
    """Exit at the close of entry bar plus (hold_bars - 1) later candles."""
    ohlc = [OHLC(b.open, b.high, b.low, b.close) for b in bars]
    trades: list[Trade] = []
    confirmation_idx = 0
    while confirmation_idx + hold_bars < len(bars):
        if not ccr_buy_at(ohlc, confirmation_idx, consecutive):
            confirmation_idx += 1
            continue
        entry_idx = confirmation_idx + 1
        exit_idx = entry_idx + hold_bars - 1
        trades.append(make_trade(bars[entry_idx].open, bars[exit_idx].close, fee_rate))
        # No overlapping positions: the exit candle has closed before a new confirmation.
        confirmation_idx = exit_idx
    return trades


def sl_tp_trades(
    bars: list[Bar],
    consecutive: int,
    fee_rate: float,
    sl_pct: float,
    tp_pct: float,
    max_hold: int,
    both_hit: str,
) -> list[Trade]:
    """Check SL/TP from the first full candle after entry; force close after max_hold bars."""
    ohlc = [OHLC(b.open, b.high, b.low, b.close) for b in bars]
    trades: list[Trade] = []
    confirmation_idx = 0
    while confirmation_idx + max_hold + 1 < len(bars):
        if not ccr_buy_at(ohlc, confirmation_idx, consecutive):
            confirmation_idx += 1
            continue
        entry_idx = confirmation_idx + 1
        entry = bars[entry_idx].open
        sl = entry * (1 - sl_pct)
        # The app's default configuration uses a flat USD fee, so its 3% TP is not padded.
        tp = entry * (1 + tp_pct)
        exit_idx = entry_idx + max_hold
        exit_price = bars[exit_idx].close
        for idx in range(entry_idx + 1, exit_idx + 1):
            bar = bars[idx]
            hit_sl, hit_tp = bar.low <= sl, bar.high >= tp
            if hit_sl or hit_tp:
                if hit_sl and hit_tp:
                    exit_price = sl if both_hit == "sl-first" else tp
                else:
                    exit_price = sl if hit_sl else tp
                exit_idx = idx
                break
        trades.append(make_trade(entry, exit_price, fee_rate))
        confirmation_idx = exit_idx
    return trades


def metrics(values: list[float]) -> Metrics:
    if not values:
        return Metrics(0, 0, 0, 0, None, 0)
    winners = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit, gross_loss = sum(winners), abs(sum(losses))
    equity = peak = 1.0
    max_drawdown = 0.0
    for value in values:
        equity *= 1 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    return Metrics(
        len(values),
        len(winners) / len(values),
        sum(values) / len(values),
        math.prod(1 + value for value in values) - 1,
        gross_profit / gross_loss if gross_loss else None,
        max_drawdown,
    )


def fmt_pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def fmt_pf(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "inf"


def print_row(name: str, trades: list[Trade]) -> None:
    gross, net = metrics([trade.gross for trade in trades]), metrics([trade.net for trade in trades])
    print(
        f"{name:<25} {net.trades:>5}  {gross.win_rate * 100:>5.1f}/{net.win_rate * 100:>5.1f}  "
        f"{fmt_pct(gross.avg):>8}/{fmt_pct(net.avg):>8}  {fmt_pct(gross.total):>9}/{fmt_pct(net.total):>9}  "
        f"{fmt_pf(gross.profit_factor):>5}/{fmt_pf(net.profit_factor):>5}  "
        f"{fmt_pct(gross.max_drawdown):>8}/{fmt_pct(net.max_drawdown):>8}"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=BINANCE_PAIRS, default="BTC")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=10_000)
    parser.add_argument("--consecutive", type=int, default=CCR_CONSECUTIVE_DEFAULT)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--max-hold", type=int, default=20)
    args = parser.parse_args()
    if args.bars < 100 or args.fee_bps < 0 or args.max_hold < 1:
        parser.error("--bars >= 100, --fee-bps >= 0, and --max-hold >= 1 are required")

    bars, source = await fetch_bars(BINANCE_PAIRS[args.symbol], args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    fee_rate = args.fee_bps / 10_000
    consecutive = clamp_ccr_consecutive(args.consecutive)
    start = datetime.fromtimestamp(bars[0].time, tz=timezone.utc).date()
    end = datetime.fromtimestamp(bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc).date()

    print("=== CCR BUY EXIT COMPARISON ===")
    print(
        f"source=binance:{source} pair={BINANCE_PAIRS[args.symbol]} interval={args.interval} "
        f"bars={len(bars)} period={start} to {end}; CCR(n={consecutive}); fee={args.fee_bps:.1f} bps/side"
    )
    print("Each variant permits one open position. G/N = gross / net after entry+exit fees.")
    print("variant                    trades  WR G/N       avg G/N          compounded G/N       PF G/N     max DD G/N")
    for hold in (1, 2, 3, 4, 6, 9):
        label = "1-bar (entry close)" if hold == 1 else f"{hold}-bar (close +{hold - 1})"
        print_row(label, hold_trades(bars, consecutive, fee_rate, hold))
    print(
        f"SL/TP: default app SL=2.00%, TP=3.00%; "
        f"scan starts bar after entry; timeout=close +{args.max_hold}."
    )
    print_row("SL/TP 20-bar, SL first", sl_tp_trades(bars, consecutive, fee_rate, 0.02, 0.03, args.max_hold, "sl-first"))
    print_row("SL/TP 20-bar, TP first", sl_tp_trades(bars, consecutive, fee_rate, 0.02, 0.03, args.max_hold, "tp-first"))


if __name__ == "__main__":
    asyncio.run(main())
