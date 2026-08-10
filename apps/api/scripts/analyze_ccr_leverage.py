r"""Backtest confirmed CCR mean-reversion with SL/TP across leverage levels.

The entry is deliberately production-shaped: a CCR confirmation closes, then the
LONG fills at the following bar's open.  It requires the confirmation volume to
exceed its prior-20-bar mean and the directly preceding bearish streak to be at
least four candles.  The optional ``belowBothEma`` filter is evaluated against
the confirmation close, exactly as ``entry_filters.evaluate_buy_filters`` does.

Examples (from apps/api):
  .venv\Scripts\python.exe scripts\analyze_ccr_leverage.py --bars 140000
  .venv\Scripts\python.exe scripts\analyze_ccr_leverage.py --bars 10000
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

from analyze_ccr_exits import BINANCE_PAIRS, INTERVAL_SECONDS, Bar, fetch_bars  # noqa: E402
from app.services.coach_ccr import OHLC, ccr_buy_at  # noqa: E402


@dataclass(frozen=True)
class Trade:
    gross_notional: float
    net_notional: float
    exit_kind: str


@dataclass(frozen=True)
class Metrics:
    trades: int
    win_rate: float
    avg_gross_notional: float
    avg_net_notional: float
    avg_net_equity: float
    compounded_net_equity: float
    max_drawdown: float
    profit_factor: float | None
    gross_sum: float
    net_sum: float
    wiped: int
    exits_sl: int
    exits_tp: int
    exits_timeout: int


def ema(values: list[float], length: int) -> list[float | None]:
    alpha = 2 / (length + 1)
    result: list[float | None] = [None] * len(values)
    value: float | None = None
    for index, close in enumerate(values):
        value = close if value is None else close * alpha + value * (1 - alpha)
        if index >= length - 1:
            result[index] = value
    return result


def bearish_streak_before(bars: list[Bar], confirmation_idx: int) -> int:
    streak = 0
    for index in range(confirmation_idx - 1, -1, -1):
        if bars[index].close >= bars[index].open:
            break
        streak += 1
    return streak


def eligible(
    bars: list[Bar],
    ohlc: list[OHLC],
    ema9: list[float | None],
    ema21: list[float | None],
    index: int,
    require_below_both: bool,
) -> bool:
    """Use only data known when the confirmation bar has closed."""
    if index < 20 or not ccr_buy_at(ohlc, index, 4):
        return False
    prior_volumes = [bar.volume for bar in bars[index - 20 : index]]
    avg20 = sum(prior_volumes) / len(prior_volumes)
    if not (avg20 > 0 and bars[index].volume > avg20):
        return False
    if bearish_streak_before(bars, index) < 4:
        return False
    if require_below_both:
        e9, e21 = ema9[index], ema21[index]
        if e9 is None or e21 is None or not (bars[index].close < e9 and bars[index].close < e21):
            return False
    return True


def make_trades(
    bars: list[Bar],
    *,
    require_below_both: bool,
    fee_rate: float,
    sl_pct: float,
    tp_pct: float,
    max_hold: int,
) -> list[Trade]:
    """Generate non-overlapping trades, checking the entry bar through timeout.

    The protective orders are live from the fill at entry-bar open.  If a bar
    reaches both levels, the stop is selected first.  A timeout closes at the
    close of the max_hold-th entry-inclusive bar.
    """
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
                exit_price = stop if hit_sl else target  # Conservative SL-first when both hit.
                exit_kind = "sl" if hit_sl else "tp"
                exit_idx = index
                break

        gross = exit_price / entry - 1
        # Both fees are charged from account cash in the paper execution model:
        # entry notional × fee plus exit notional × fee, expressed per entry notional.
        net = gross - fee_rate - (exit_price / entry) * fee_rate
        trades.append(Trade(gross, net, exit_kind))
        confirmation_idx = exit_idx + 1
    return trades


def summarize(trades: list[Trade], leverage: float) -> Metrics:
    gross_values = [trade.gross_notional for trade in trades]
    net_values = [trade.net_notional for trade in trades]
    equity_values = [value * leverage for value in net_values]
    winners = [value for value in equity_values if value > 0]
    losses = [value for value in equity_values if value < 0]
    equity = peak = 1.0
    drawdown = 0.0
    wiped = 0
    for value in equity_values:
        if equity <= 0:
            break
        if value <= -1:
            equity = 0.0
            wiped += 1
            drawdown = -1.0
            break
        equity *= 1 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    gross_loss = abs(sum(losses))
    return Metrics(
        trades=len(trades),
        win_rate=len(winners) / len(trades) if trades else 0.0,
        avg_gross_notional=sum(gross_values) / len(trades) if trades else 0.0,
        avg_net_notional=sum(net_values) / len(trades) if trades else 0.0,
        avg_net_equity=sum(equity_values) / len(trades) if trades else 0.0,
        compounded_net_equity=equity - 1,
        max_drawdown=drawdown,
        profit_factor=sum(winners) / gross_loss if gross_loss else None,
        gross_sum=sum(gross_values),
        net_sum=sum(net_values),
        wiped=wiped,
        exits_sl=sum(trade.exit_kind == "sl" for trade in trades),
        exits_tp=sum(trade.exit_kind == "tp" for trade in trades),
        exits_timeout=sum(trade.exit_kind == "timeout" for trade in trades),
    )


def pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def pf(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "inf"


def print_section(label: str, trades: list[Trade], leverages: list[float]) -> None:
    print(f"\n=== {label} ===")
    print(f"Signals/trades={len(trades)}; exits: SL={sum(t.exit_kind == 'sl' for t in trades)}, "
          f"TP={sum(t.exit_kind == 'tp' for t in trades)}, timeout={sum(t.exit_kind == 'timeout' for t in trades)}")
    print("lev   trades  win%   avg gross/net notional    avg net equity   compounded equity  max DD     PF    gross/net sum    wipes")
    for leverage in leverages:
        m = summarize(trades, leverage)
        print(
            f"{leverage:>3g}x  {m.trades:>6}  {m.win_rate * 100:>5.1f}  "
            f"{pct(m.avg_gross_notional):>8}/{pct(m.avg_net_notional):>8}  "
            f"{pct(m.avg_net_equity):>8}  {pct(m.compounded_net_equity):>14}  "
            f"{pct(m.max_drawdown):>8}  {pf(m.profit_factor):>5}  "
            f"{pct(m.gross_sum):>8}/{pct(m.net_sum):>8}  {m.wiped:>5}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=BINANCE_PAIRS, default="BTC")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=140_000, help="140,000 is about four years of 15m bars.")
    parser.add_argument("--max-hold", type=int, default=20)
    parser.add_argument("--sl-pct", type=float, default=2.0)
    parser.add_argument("--tp-pct", type=float, default=5.0)
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Per-side percentage fee.")
    parser.add_argument("--leverages", nargs="+", type=float, default=[1, 2, 3, 5, 10])
    args = parser.parse_args()
    if args.bars < 100 or args.max_hold < 1 or args.sl_pct <= 0 or args.tp_pct <= 0 or args.fee_bps < 0:
        parser.error("bars >=100; max-hold, SL, TP >0; and fee-bps >=0 are required")
    if any(leverage < 1 for leverage in args.leverages):
        parser.error("all leverage values must be >=1")

    fee_rate = args.fee_bps / 10_000
    # Cost-only net R:R (no slippage/spread): net reward / net risk.
    net_rr = (args.tp_pct / 100 - 2 * fee_rate) / (args.sl_pct / 100 + 2 * fee_rate)
    if net_rr < 2:
        parser.error(f"Rejected: net R:R {net_rr:.3f} is below 2.0 after fees")

    bars, source = await fetch_bars(BINANCE_PAIRS[args.symbol], args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    if len(bars) < 22:
        raise RuntimeError("Not enough closed bars after filtering")
    start = datetime.fromtimestamp(bars[0].time, tz=timezone.utc).date()
    end = datetime.fromtimestamp(bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc).date()
    common = dict(
        bars=bars, fee_rate=fee_rate, sl_pct=args.sl_pct / 100, tp_pct=args.tp_pct / 100, max_hold=args.max_hold
    )
    without_ema = make_trades(require_below_both=False, **common)
    with_ema = make_trades(require_below_both=True, **common)

    print("=== CCR MEAN-REVERSION WITH CONFIRMATION — LEVERAGE STUDY ===")
    print(
        f"source=binance:{source}; pair={BINANCE_PAIRS[args.symbol]}; interval={args.interval}; "
        f"bars={len(bars)}; period={start} to {end}"
    )
    print(
        f"Entry=CCR BUY n=4 confirmation -> next open; filters=volume>prior20 average + actual bearish streak>=4; "
        f"SL={args.sl_pct:.2f}%, TP={args.tp_pct:.2f}%, fee={args.fee_bps:.1f}bps/side."
    )
    print(
        f"Net R:R after percentage fees only={net_rr:.3f} (accepted >=2.0). "
        f"Timeout={args.max_hold} entry-inclusive 15m bars; same-bar SL/TP=SL-first; one position at a time."
    )
    print(
        "Equity return assumes the full current equity is posted as margin each trade; "
        "notional PnL is price return after fees, equity PnL = notional PnL × leverage. "
        "A wipe means a single net equity return <= -100%; the app does not currently model liquidation."
    )
    print_section("Volume + streak filter (no belowBothEma)", without_ema, args.leverages)
    print_section("Volume + streak + belowBothEma (confirmation close)", with_ema, args.leverages)


if __name__ == "__main__":
    asyncio.run(main())
