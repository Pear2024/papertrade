r"""Report calendar-period performance for the CCR mean-reversion hypotheses.

From apps/api:
  .venv\Scripts\python.exe scripts\analyze_ccr_periods.py --bars 140000

The base setup is CCR BUY n=4 with confirmation volume above the prior 20-bar
mean and an actual bearish streak of at least four.  The second setup additionally
requires the confirmation close below both EMA9 and EMA21.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyze_ccr_exits import BINANCE_PAIRS, INTERVAL_SECONDS, Bar, fetch_bars  # noqa: E402
from analyze_ccr_leverage import ema, eligible  # noqa: E402
from app.services.coach_ccr import OHLC  # noqa: E402


@dataclass(frozen=True)
class Trade:
    entry_time: int
    exit_time: int
    gross: float
    net: float
    exit_kind: str


@dataclass(frozen=True)
class PeriodStats:
    label: str
    trades: int
    win_rate: float
    gross_return: float
    net_return: float
    gross_pf: float | None
    net_pf: float | None


def make_trades(
    bars: list[Bar], *, require_below_both: bool, fee_rate: float, sl_pct: float, tp_pct: float, max_hold: int
) -> list[Trade]:
    """Create non-overlapping, entry-inclusive SL/TP/timeout trades."""
    closes = [bar.close for bar in bars]
    ema9, ema21 = ema(closes, 9), ema(closes, 21)
    ohlc = [OHLC(bar.open, bar.high, bar.low, bar.close) for bar in bars]
    trades: list[Trade] = []
    confirmation_idx = 20
    while confirmation_idx + max_hold < len(bars):
        if not eligible(bars, ohlc, ema9, ema21, confirmation_idx, require_below_both):
            confirmation_idx += 1
            continue
        entry_idx = confirmation_idx + 1
        entry = bars[entry_idx].open
        stop, target = entry * (1 - sl_pct), entry * (1 + tp_pct)
        exit_idx = entry_idx + max_hold - 1
        exit_price, exit_kind = bars[exit_idx].close, "timeout"
        for index in range(entry_idx, exit_idx + 1):
            bar = bars[index]
            hit_sl, hit_tp = bar.low <= stop, bar.high >= target
            if hit_sl or hit_tp:
                exit_price = stop if hit_sl else target  # SL-first if both occur in one bar.
                exit_kind = "sl" if hit_sl else "tp"
                exit_idx = index
                break
        gross = exit_price / entry - 1
        # 0.10% is paid on entry notional and exit notional, per the paper model.
        net = gross - fee_rate - (exit_price / entry) * fee_rate
        trades.append(Trade(bars[entry_idx].time, bars[exit_idx].time, gross, net, exit_kind))
        confirmation_idx = exit_idx + 1
    return trades


def profit_factor(values: list[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    return gains / losses if losses else None


def summarize(label: str, trades: list[Trade]) -> PeriodStats:
    gross = [trade.gross for trade in trades]
    net = [trade.net for trade in trades]
    return PeriodStats(
        label=label,
        trades=len(trades),
        win_rate=sum(value > 0 for value in net) / len(net) if net else 0.0,
        gross_return=math.prod(1 + value for value in gross) - 1 if gross else 0.0,
        net_return=math.prod(1 + value for value in net) - 1 if net else 0.0,
        gross_pf=profit_factor(gross),
        net_pf=profit_factor(net),
    )


def group_by_period(trades: list[Trade], kind: str) -> list[PeriodStats]:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        date = datetime.fromtimestamp(trade.entry_time, tz=timezone.utc)
        if kind == "month":
            key = f"{date:%Y-%m}"
        elif kind == "quarter":
            key = f"{date.year}-Q{(date.month - 1) // 3 + 1}"
        else:
            key = str(date.year)
        groups[key].append(trade)
    return [summarize(key, groups[key]) for key in sorted(groups)]


def pf_text(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "inf"


def print_table(title: str, rows: list[PeriodStats]) -> None:
    print(f"\n--- {title} ---")
    print("period     trades  WR(net)  compounded gross  compounded net   PF gross/net")
    for row in rows:
        print(
            f"{row.label:<10} {row.trades:>6}  {row.win_rate * 100:>6.1f}%  "
            f"{row.gross_return * 100:>+15.2f}%  {row.net_return * 100:>+13.2f}%  "
            f"{pf_text(row.gross_pf):>6}/{pf_text(row.net_pf):<6}"
        )


def print_ranked(title: str, rows: list[PeriodStats], *, key: str, reverse: bool) -> None:
    ordered = sorted(rows, key=lambda row: getattr(row, key), reverse=reverse)[:5]
    print(f"\n{title} (ranked by {'gross' if key == 'gross_return' else 'net after fees'})")
    print("period     trades  WR(net)  gross return  net return  gross $P/L ($100/$1,000)  net $P/L ($100/$1,000)  PF(net)")
    for row in ordered:
        gross_100, gross_1000 = 100 * row.gross_return, 1000 * row.gross_return
        net_100, net_1000 = 100 * row.net_return, 1000 * row.net_return
        print(
            f"{row.label:<10} {row.trades:>6}  {row.win_rate * 100:>6.1f}%  "
            f"{row.gross_return * 100:>+11.2f}%  {row.net_return * 100:>+9.2f}%  "
            f"${gross_100:>+8.2f}/${gross_1000:>+9.2f}       "
            f"${net_100:>+8.2f}/${net_1000:>+9.2f}    {pf_text(row.net_pf):>6}"
        )


def print_hypothesis(name: str, trades: list[Trade]) -> None:
    overall = summarize("full sample", trades)
    start = datetime.fromtimestamp(trades[0].entry_time, tz=timezone.utc).date() if trades else "n/a"
    end = datetime.fromtimestamp(trades[-1].exit_time, tz=timezone.utc).date() if trades else "n/a"
    print(f"\n{'=' * 88}\n{name}")
    print(
        f"completed trades={overall.trades}; entry-to-exit range={start} to {end}; "
        f"compounded gross={overall.gross_return * 100:+.2f}%; net={overall.net_return * 100:+.2f}%; "
        f"net PF={pf_text(overall.net_pf)}"
    )
    months = group_by_period(trades, "month")
    years = group_by_period(trades, "year")
    print_table("Year", years)
    print_table("Month", months)
    print_ranked("TOP 5 months (Gross)", months, key="gross_return", reverse=True)
    print_ranked("TOP 5 months (Net)", months, key="net_return", reverse=True)
    print_ranked("BOTTOM 5 months (Net)", months, key="net_return", reverse=False)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=BINANCE_PAIRS, default="BTC")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=140_000)
    parser.add_argument("--max-hold", type=int, default=20)
    parser.add_argument("--sl-pct", type=float, default=2.0)
    parser.add_argument("--tp-pct", type=float, default=5.0)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    args = parser.parse_args()
    if args.bars < 100 or args.max_hold < 1 or args.sl_pct <= 0 or args.tp_pct <= 0 or args.fee_bps < 0:
        parser.error("--bars >=100; --max-hold, --sl-pct, --tp-pct >0; --fee-bps >=0")

    bars, source = await fetch_bars(BINANCE_PAIRS[args.symbol], args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    fee_rate = args.fee_bps / 10_000
    common = dict(fee_rate=fee_rate, sl_pct=args.sl_pct / 100, tp_pct=args.tp_pct / 100, max_hold=args.max_hold)
    print("=== CCR CALENDAR PROFITABILITY ===")
    print(
        f"source=binance:{source}; pair={BINANCE_PAIRS[args.symbol]}; interval={args.interval}; bars={len(bars)}; "
        f"trade date is next-open entry timestamp."
    )
    print(
        f"CCR BUY n=4; filters=confirmation volume > prior-20 average AND actual bearish streak >=4; "
        f"SL={args.sl_pct:.2f}%, TP={args.tp_pct:.2f}%, timeout={args.max_hold} entry-inclusive bars, "
        f"SL-first; fees={args.fee_bps:.2f}bps/side; leverage=1x."
    )
    print_hypothesis("A) Volume + bearish-streak filter", make_trades(bars, require_below_both=False, **common))
    print_hypothesis(
        "B) Volume + bearish-streak + belowBothEma (confirmation close below EMA9 and EMA21)",
        make_trades(bars, require_below_both=True, **common),
    )


if __name__ == "__main__":
    asyncio.run(main())
