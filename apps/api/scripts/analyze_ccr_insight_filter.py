r"""Compare CCR hold lengths for the volume/streak insight filter.

The strategy confirms at a candle close, buys at the next candle's open, and
exits at a configurable close relative to that entry candle. The filter uses
only the confirmation candle and its preceding bars:

    confirmation volume > mean(volume of the prior 20 bars)
    actual immediately preceding bearish streak >= 4

Example:
  .venv\Scripts\python.exe scripts\analyze_ccr_insight_filter.py --bars 29999 --exit-offsets 1 10
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyze_ccr_ema_entry_distance import EntryObservation, build_observations
from analyze_ccr_exits import BINANCE_PAIRS, INTERVAL_SECONDS, fetch_bars
from app.services.coach_ccr import CCR_CONSECUTIVE_DEFAULT, clamp_ccr_consecutive


@dataclass(frozen=True)
class Summary:
    count: int
    win_rate: float
    avg: float
    compounded: float
    profit_factor: float | None
    max_drawdown: float


def summarize(values: list[float]) -> Summary:
    if not values:
        return Summary(0, 0.0, 0.0, 0.0, None, 0.0)
    winners = [value for value in values if value > 0]
    losers = [value for value in values if value < 0]
    equity = peak = 1.0
    drawdown = 0.0
    for value in values:
        equity *= 1 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    gross_loss = abs(sum(losers))
    return Summary(
        count=len(values),
        win_rate=len(winners) / len(values),
        avg=sum(values) / len(values),
        compounded=math.prod(1 + value for value in values) - 1,
        profit_factor=sum(winners) / gross_loss if gross_loss else None,
        max_drawdown=drawdown,
    )


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lo, hi = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def fmt_percent(value: float) -> str:
    return f"{value * 100:+.2f}%"


def fmt_pf(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "inf"


def print_summary(name: str, rows: list[EntryObservation]) -> None:
    gross = summarize([row.gross_pct / 100 for row in rows])
    net = summarize([row.net_pct / 100 for row in rows])
    print(f"\n{name} (n={gross.count})")
    print("                        gross       net (0.10%/side)")
    print(f"Win rate               {gross.win_rate * 100:>6.1f}%       {net.win_rate * 100:>6.1f}%")
    print(f"Average PnL            {fmt_percent(gross.avg):>7}       {fmt_percent(net.avg):>7}")
    print(f"Compounded return      {fmt_percent(gross.compounded):>7}       {fmt_percent(net.compounded):>7}")
    print(f"Profit factor          {fmt_pf(gross.profit_factor):>7}       {fmt_pf(net.profit_factor):>7}")
    print(f"Max drawdown           {fmt_percent(gross.max_drawdown):>7}       {fmt_percent(net.max_drawdown):>7}")
    if rows:
        print(
            f"Median MFE / MAE       {percentile([row.mfe_pct for row in rows], .5):+.2f}%"
            f" / {percentile([row.mae_pct for row in rows], .5):+.2f}%"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=BINANCE_PAIRS, default="BTC")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=20_000)
    parser.add_argument("--consecutive", type=int, default=CCR_CONSECUTIVE_DEFAULT)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument(
        "--exit-offsets",
        nargs="+",
        type=int,
        default=[1, 10],
        help="Exit at close of entry bar + each offset (default: 1 10).",
    )
    args = parser.parse_args()
    if args.bars < 100 or args.fee_bps < 0 or any(offset < 0 for offset in args.exit_offsets):
        parser.error("--bars must be >= 100, --fee-bps >= 0, and exit offsets >= 0")

    bars, source = await fetch_bars(BINANCE_PAIRS[args.symbol], args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    consecutive = clamp_ccr_consecutive(args.consecutive)
    start = datetime.fromtimestamp(bars[0].time, tz=timezone.utc).date()
    end = datetime.fromtimestamp(bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc).date()

    print("=== CCR INSIGHT FILTER — HOLD COMPARISON ===")
    print(
        f"source=binance:{source}; pair={BINANCE_PAIRS[args.symbol]}; interval={args.interval}; "
        f"bars={len(bars)}; period={start} to {end}; CCR detection n={consecutive}"
    )
    print("Entry: next open after confirmation. Each variant allows one open position; overlapping signals are skipped.")
    print("Filter: confirmation volume > prior-20 average AND actual bearish streak >= 4.")
    for exit_offset in args.exit_offsets:
        hold_bars = exit_offset + 1
        observations = build_observations(bars, consecutive, args.fee_bps / 10_000, hold_bars=hold_bars)
        insight = [
            row
            for row in observations
            if row.volume_vs_avg20 is not None and row.volume_vs_avg20 > 1 and row.bearish_streak >= 4
        ]
        print(f"\n--- Exit: close of entry bar +{exit_offset} ({hold_bars} entry-inclusive bars) ---")
        print_summary(f"Unfiltered CCR {hold_bars}-bar baseline", observations)
        print_summary("Insight filter", insight)


if __name__ == "__main__":
    asyncio.run(main())
