r"""Test whether only large CCR confirmation setups overcome trading fees.

The baseline is CCR BUY n=4, volume above the previous-20-bar mean, actual
bearish streak >=4, and confirmation close below EMA9/EMA21. Entries are at
the next open; exits use SL 2%, TP 5%, 20 bars, and conservative SL-first.

The size thresholds are calculated from all baseline-eligible confirmation
bars in the requested sample. They are exploratory in-sample cuts, not
walk-forward rules.

From apps/api:
  .venv\Scripts\python.exe scripts\analyze_ccr_big_setups.py --bars 140000
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from analyze_ccr_exits import BINANCE_PAIRS, INTERVAL_SECONDS, Bar, fetch_bars
from analyze_ccr_leverage import Trade, ema, eligible, pf, summarize
from app.services.coach_ccr import OHLC


@dataclass(frozen=True)
class Signal:
    index: int
    body_pct: float
    range_pct: float
    volume_multiple: float
    below_ema21_pct: float


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def build_signals(bars: list[Bar]) -> list[Signal]:
    closes = [bar.close for bar in bars]
    ema9, ema21 = ema(closes, 9), ema(closes, 21)
    ohlc = [OHLC(bar.open, bar.high, bar.low, bar.close) for bar in bars]
    signals: list[Signal] = []
    for index in range(20, len(bars) - 21):
        if not eligible(bars, ohlc, ema9, ema21, index, require_below_both=True):
            continue
        bar = bars[index]
        avg20 = sum(row.volume for row in bars[index - 20 : index]) / 20
        signals.append(
            Signal(
                index=index,
                body_pct=abs(bar.close - bar.open) / bar.open * 100,
                range_pct=(bar.high - bar.low) / bar.open * 100,
                volume_multiple=bar.volume / avg20,
                below_ema21_pct=(bar.close - ema21[index]) / ema21[index] * 100,  # type: ignore[operator]
            )
        )
    return signals


def make_trades(
    bars: list[Bar],
    signals: list[Signal],
    selected: Callable[[Signal], bool],
    *,
    fee_rate: float,
    sl_pct: float,
    tp_pct: float,
    max_hold: int,
) -> list[Trade]:
    """Trade selected signals sequentially; skipped signals do not reserve time."""
    signal_by_index = {signal.index: signal for signal in signals}
    trades: list[Trade] = []
    confirmation_idx = 20
    while confirmation_idx + max_hold < len(bars):
        signal = signal_by_index.get(confirmation_idx)
        if signal is None or not selected(signal):
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
                exit_price = stop if hit_sl else target
                exit_kind = "sl" if hit_sl else "tp"
                exit_idx = index
                break
        gross = exit_price / entry - 1
        net = gross - fee_rate - (exit_price / entry) * fee_rate
        trades.append(Trade(gross, net, exit_kind))
        confirmation_idx = exit_idx + 1
    return trades


def print_table(
    title: str,
    bars: list[Bar],
    signals: list[Signal],
    cuts: list[tuple[str, Callable[[Signal], bool]]],
    *,
    fee_rate: float,
    sl_pct: float,
    tp_pct: float,
    max_hold: int,
    leverage: float,
) -> None:
    print(f"\n=== {title} ({leverage:g}x) ===")
    print("cut                              trades   WR     avg net   compounded       PF    max DD")
    for label, selected in cuts:
        metrics = summarize(
            make_trades(
                bars, signals, selected, fee_rate=fee_rate, sl_pct=sl_pct, tp_pct=tp_pct, max_hold=max_hold
            ),
            leverage,
        )
        print(
            f"{label:<32} {metrics.trades:>6}  {metrics.win_rate * 100:>5.1f}%  "
            f"{metrics.avg_net_equity * 100:>+7.3f}%  {metrics.compounded_net_equity * 100:>+10.2f}%  "
            f"{pf(metrics.profit_factor):>7}  {metrics.max_drawdown * 100:>+7.2f}%"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=BINANCE_PAIRS, default="BTC")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=140_000)
    parser.add_argument("--short-bars", type=int, default=35_000, help="Newest bars for a one-year robustness view.")
    parser.add_argument("--max-hold", type=int, default=20)
    parser.add_argument("--sl-pct", type=float, default=2.0)
    parser.add_argument("--tp-pct", type=float, default=5.0)
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Per-side percentage fee.")
    parser.add_argument("--leverages", nargs="+", type=float, default=[1, 2])
    args = parser.parse_args()
    if args.bars < 100 or args.short_bars < 0 or args.max_hold < 1:
        parser.error("--bars >=100, --short-bars >=0, and --max-hold >=1 are required")

    fee_rate = args.fee_bps / 10_000
    bars, source = await fetch_bars(BINANCE_PAIRS[args.symbol], args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    signals = build_signals(bars)
    if not signals:
        raise RuntimeError("No baseline-eligible signals found")

    body75, body80 = percentile([s.body_pct for s in signals], .75), percentile([s.body_pct for s in signals], .80)
    range75, range80 = percentile([s.range_pct for s in signals], .75), percentile([s.range_pct for s in signals], .80)
    deep25 = percentile([s.below_ema21_pct for s in signals], .25)
    cuts: list[tuple[str, Callable[[Signal], bool]]] = [
        ("Baseline (all eligible)", lambda s: True),
        (f"Body >= p75 ({body75:.3f}%)", lambda s: s.body_pct >= body75),
        (f"Body >= p80 ({body80:.3f}%)", lambda s: s.body_pct >= body80),
        (f"Range >= p75 ({range75:.3f}%)", lambda s: s.range_pct >= range75),
        (f"Range >= p80 ({range80:.3f}%)", lambda s: s.range_pct >= range80),
        ("Volume / avg20 >= 1.5x", lambda s: s.volume_multiple >= 1.5),
        ("Volume / avg20 >= 2.0x", lambda s: s.volume_multiple >= 2.0),
        (f"Body p75 + volume >= 1.5x", lambda s: s.body_pct >= body75 and s.volume_multiple >= 1.5),
        (f"Range p75 + volume >= 1.5x", lambda s: s.range_pct >= range75 and s.volume_multiple >= 1.5),
        (f"Deeper EMA21 <= p25 ({deep25:.3f}%)", lambda s: s.below_ema21_pct <= deep25),
    ]
    start = datetime.fromtimestamp(bars[0].time, tz=timezone.utc).date()
    end = datetime.fromtimestamp(bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc).date()
    print("=== CCR LARGE-CONFIRMATION SETUP STUDY ===")
    print(
        f"source=binance:{source}; pair={BINANCE_PAIRS[args.symbol]}; interval={args.interval}; "
        f"bars={len(bars)}; period={start} to {end}; baseline-eligible signals={len(signals)}"
    )
    print(
        f"Baseline=CCR BUY n=4 + volume>prior20 average + bearish streak>=4 + close below EMA9/EMA21; "
        f"next-open entry; SL={args.sl_pct:.2f}%, TP={args.tp_pct:.2f}%, {args.max_hold}-bar timeout, SL-first; "
        f"fee={args.fee_bps:.1f}bps/side."
    )
    print("Percentile cutoffs are calculated on this full sample, so treat them as exploratory (not out-of-sample).")
    for leverage in args.leverages:
        print_table("Full sample", bars, signals, cuts, fee_rate=fee_rate, sl_pct=args.sl_pct / 100,
                    tp_pct=args.tp_pct / 100, max_hold=args.max_hold, leverage=leverage)
    if args.short_bars and len(bars) > args.short_bars:
        short_bars = bars[-args.short_bars :]
        short_signals = build_signals(short_bars)
        short_start = datetime.fromtimestamp(short_bars[0].time, tz=timezone.utc).date()
        short_end = datetime.fromtimestamp(short_bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc).date()
        print(f"\nShort-window period={short_start} to {short_end}; baseline-eligible signals={len(short_signals)}.")
        for leverage in args.leverages:
            print_table("Recent short window; full-sample cutoffs", short_bars, short_signals, cuts,
                        fee_rate=fee_rate, sl_pct=args.sl_pct / 100, tp_pct=args.tp_pct / 100,
                        max_hold=args.max_hold, leverage=leverage)


if __name__ == "__main__":
    asyncio.run(main())
