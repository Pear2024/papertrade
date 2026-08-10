r"""Reproducible BTCUSDT research: timeframe, exit, and non-CCR hypotheses.

Run from apps/api:
  .venv\Scripts\python.exe scripts\research_hypotheses_v2.py

This is research only: completed-bar signals, next-open fills, one position per
variant, and a pessimistic 28 bps round-trip friction model.  It never alters
production configuration or submits orders.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyze_ccr_exits import BINANCE_PAIRS, INTERVAL_SECONDS, Bar, fetch_bars  # noqa: E402
from app.services.coach import _ema  # noqa: E402
from app.services.coach_ccr import OHLC, ccr_buy_at  # noqa: E402

FEE_BPS_SIDE, SLIP_BPS_SIDE, SPREAD_BPS_TOTAL = 10.0, 3.0, 2.0
SIDE_COST = (FEE_BPS_SIDE + SLIP_BPS_SIDE + SPREAD_BPS_TOTAL / 2) / 10_000
RT_BPS = SIDE_COST * 2 * 10_000


@dataclass(frozen=True)
class Trade:
    entry_time: int
    exit_time: int
    net: float
    kind: str


@dataclass(frozen=True)
class Stats:
    n: int
    wr: float
    win: float
    loss: float
    expectancy: float
    pf: float | None
    net: float
    sharpe: float | None
    dd: float


def ema(xs: list[float], n: int) -> list[float | None]:
    return _ema(xs, n)


def atr(bars: list[Bar], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    tr = [0.0] * len(bars)
    for i, bar in enumerate(bars):
        previous = bars[i - 1].close if i else bar.close
        tr[i] = max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))
    if len(bars) <= n:
        return out
    value = sum(tr[1:n + 1]) / n
    out[n] = value
    for i in range(n + 1, len(bars)):
        value = (value * (n - 1) + tr[i]) / n
        out[i] = value
    return out


def mean_before(bars: list[Bar], i: int, n: int, attr: str) -> float | None:
    if i < n:
        return None
    return sum(getattr(x, attr) for x in bars[i - n:i]) / n


def stdev_before(xs: list[float], i: int, n: int) -> float | None:
    return statistics.pstdev(xs[i - n:i]) if i >= n else None


def bearish_streak_before(bars: list[Bar], i: int) -> int:
    result = 0
    for j in range(i - 1, -1, -1):
        if bars[j].close >= bars[j].open:
            return result
        result += 1
    return result


def h1b_signals(bars: list[Bar], e9: list[float | None], e21: list[float | None]) -> list[bool]:
    ohlc = [OHLC(x.open, x.high, x.low, x.close) for x in bars]
    result = [False] * len(bars)
    for i in range(21, len(bars)):
        average_volume = mean_before(bars, i, 20, "volume")
        result[i] = bool(
            ccr_buy_at(ohlc, i, 4) and average_volume is not None and bars[i].volume > average_volume
            and bearish_streak_before(bars, i) >= 4 and e9[i] is not None and e21[i] is not None
            and bars[i].close < e9[i] and bars[i].close < e21[i]
        )
    return result


def breakout_signals(bars: list[Bar], e21: list[float | None], e50: list[float | None],
                     lookback: int = 20) -> list[bool]:
    """Trend family: close breaks prior Donchian high in an established EMA trend."""
    out = [False] * len(bars)
    for i in range(lookback, len(bars)):
        high = max(x.high for x in bars[i - lookback:i])
        avg_vol = mean_before(bars, i, 20, "volume")
        out[i] = bool(e21[i] and e50[i] and e21[i] > e50[i] and bars[i].close > high
                      and avg_vol and bars[i].volume > avg_vol)
    return out


def mean_reversion_signals(bars: list[Bar], e50: list[float | None], bb_n: int = 20,
                           width_limit: float = .035) -> list[bool]:
    """Range family: fade a lower Bollinger excursion only in quiet, flat ranges."""
    closes = [x.close for x in bars]
    out = [False] * len(bars)
    for i in range(bb_n + 20, len(bars)):
        mid, sd = mean_before(bars, i, bb_n, "close"), stdev_before(closes, i, bb_n)
        if mid is None or sd is None or e50[i] is None or e50[i - 10] is None:
            continue
        lower, width = mid - 2 * sd, 4 * sd / mid
        flat = abs(e50[i] / e50[i - 10] - 1) < .005
        # Reclaim lower band after touching it: signal only once its candle is closed.
        out[i] = width < width_limit and flat and bars[i].low < lower and bars[i].close > lower
    return out


def momentum_signals(bars: list[Bar], e21: list[float | None], e50: list[float | None],
                     roc_n: int = 10) -> list[bool]:
    """Momentum family: positive ROC and EMA stack, then a one-bar EMA21 pullback reclaim."""
    out = [False] * len(bars)
    for i in range(max(roc_n, 51), len(bars)):
        roc = bars[i].close / bars[i - roc_n].close - 1
        out[i] = bool(e21[i] and e50[i] and e21[i - 1] and e21[i] > e50[i] and roc > .01
                      and bars[i - 1].low <= e21[i - 1] and bars[i].close > e21[i]
                      and bars[i].close > bars[i].open)
    return out


def run_trades(bars: list[Bar], signals: list[bool], *, exit_rule: str,
               atrs: list[float | None], e21: list[float | None], hold: int = 20,
               sl_pct: float = .02, tp_pct: float = .05, atr_mult: float = 1.5,
               reward_r: float = 2.5) -> list[Trade]:
    """Signals are closed bars; fill is following open; brackets are SL-first."""
    trades: list[Trade] = []
    i = 60
    while i < len(bars) - 2:
        if not signals[i] or i + hold >= len(bars):
            i += 1
            continue
        entry_i, entry = i + 1, bars[i + 1].open
        if exit_rule == "fixed":
            stop, target = entry * (1 - sl_pct), entry * (1 + tp_pct)
        elif exit_rule in {"atr", "bracket"}:
            value = atrs[i]
            if not value or value >= entry:
                i += 1
                continue
            stop = entry - atr_mult * value
            target = entry + (entry - stop) * reward_r
        else:
            stop = target = None
        exit_i, exit_px, kind = min(entry_i + hold - 1, len(bars) - 1), bars[min(entry_i + hold - 1, len(bars) - 1)].close, "time"
        # Entry occurs at this candle's open, hence bracket orders are active on it.
        for j in range(entry_i, min(entry_i + hold, len(bars))):
            bar = bars[j]
            if exit_rule in {"fixed", "atr", "bracket"}:
                hit_sl, hit_tp = bar.low <= stop, bar.high >= target
                if hit_sl or hit_tp:
                    exit_i, exit_px, kind = j, stop if hit_sl else target, "sl" if hit_sl else "tp"
                    break
            if exit_rule == "ema" and e21[j] is not None and bar.close < e21[j]:
                exit_i, exit_px, kind = j, bar.close, "ema21"
                break
        net = exit_px * (1 - SIDE_COST) / (entry * (1 + SIDE_COST)) - 1
        trades.append(Trade(bars[entry_i].time, bars[exit_i].time, net, kind))
        i = exit_i + 1
    return trades


def stats(trades: list[Trade]) -> Stats:
    xs = [x.net for x in trades]
    if not xs:
        return Stats(0, 0, 0, 0, 0, None, 0, None, 0)
    wins, losses = [x for x in xs if x > 0], [x for x in xs if x <= 0]
    equity = peak = 1.0
    dd = 0.0
    for x in xs:
        equity *= 1 + x
        peak = max(peak, equity)
        dd = min(dd, equity / peak - 1)
    standard_deviation = statistics.stdev(xs) if len(xs) > 1 else 0
    sharpe = (statistics.mean(xs) / standard_deviation * math.sqrt(len(xs))
              if standard_deviation > 1e-12 else None)
    return Stats(len(xs), len(wins) / len(xs), statistics.mean(wins) if wins else 0,
                 statistics.mean(losses) if losses else 0, statistics.mean(xs),
                 sum(wins) / abs(sum(losses)) if losses and sum(losses) else None, equity - 1,
                 sharpe, dd)


def format_stats(s: Stats) -> str:
    return (f"n={s.n}; WR={s.wr:.1%}; avg W/L={s.win:.2%}/{s.loss:.2%}; E={s.expectancy:.3%}; "
            f"PF={'n/a' if s.pf is None else f'{s.pf:.2f}'}; Sharpe(trade)={'n/a' if s.sharpe is None else f'{s.sharpe:.2f}'}; "
            f"maxDD={s.dd:.1%}; net={s.net:.1%}")


def partition(trades: list[Trade], split_at: int) -> tuple[list[Trade], list[Trade]]:
    return [t for t in trades if t.entry_time < split_at], [t for t in trades if t.entry_time >= split_at]


def regimes(bars: list[Bar], e50: list[float | None]) -> list[str]:
    atrs = atr(bars)
    normalized = [a / b.close for a, b in zip(atrs, bars) if a]
    lo, hi = (sorted(normalized)[int(len(normalized) * q)] for q in (.25, .75))
    out = []
    for i, bar in enumerate(bars):
        if not atrs[i] or not e50[i] or i < 70:
            out.append("warmup")
        elif atrs[i] / bar.close >= hi:
            out.append("high-vol")
        elif atrs[i] / bar.close <= lo:
            out.append("low-vol")
        else:
            slope = e50[i] / e50[i - 20] - 1 if e50[i - 20] else 0
            out.append("bull" if slope > .01 else "bear" if slope < -.01 else "sideways")
    return out


def regime_summary(trades: list[Trade], bars: list[Bar], labels: list[str]) -> str:
    lookup = {bar.time: labels[i] for i, bar in enumerate(bars)}
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        groups[lookup[trade.entry_time]].append(trade)
    return "; ".join(f"{name}: E {stats(group).expectancy:.3%}, PF {stats(group).pf or 0:.2f}, n {len(group)}"
                     for name, group in sorted(groups.items()) if name != "warmup") or "insufficient classified trades"


def walk_forward(trades: list[Trade], bars: list[Bar]) -> str:
    start = bars[0].time
    width = (bars[-1].time - start) // 3
    chunks = []
    for n in range(3):
        sample = [t for t in trades if start + n * width <= t.entry_time < start + (n + 1) * width]
        chunks.append(f"fold{n + 1}: E {stats(sample).expectancy:.3%}, PF {stats(sample).pf or 0:.2f}, n {len(sample)}")
    return " | ".join(chunks)


def verdict(is_: Stats, oos: Stats) -> str:
    if oos.n < 30:
        return "NEED MORE DATA"
    if oos.expectancy <= 0 or (oos.pf or 0) < 1:
        return "REJECT"
    if is_.expectancy > 0 and oos.expectancy > 0 and (oos.pf or 0) >= 1.15 and oos.n >= 60:
        return "PAPER TRADE"
    return "PROMISING"


def buy_hold(bars: list[Bar], first: int, last: int) -> float:
    return bars[last].close * (1 - SIDE_COST) / (bars[first].open * (1 + SIDE_COST)) - 1


async def load(interval: str, target: int) -> list[Bar]:
    bars, source = await fetch_bars(BINANCE_PAIRS["BTC"], interval, target)
    now = int(datetime.now(timezone.utc).timestamp())
    result = [b for b in bars if b.time + INTERVAL_SECONDS[interval] <= now]
    print(f"\nDATA {interval}: Binance {source}; {len(result):,} closed BTCUSDT bars; "
          f"{datetime.fromtimestamp(result[0].time, timezone.utc):%F}..{datetime.fromtimestamp(result[-1].time, timezone.utc):%F}")
    return result


def evaluate(label: str, logic: str, rules: str, bars: list[Bar], signals: list[bool], rule: str,
             atrs: list[float | None], e21: list[float | None], hold: int, split_at: int,
             sensitivity: list[tuple[str, dict]]) -> tuple[str, Stats, str]:
    trades = run_trades(bars, signals, exit_rule=rule, atrs=atrs, e21=e21, hold=hold)
    is_, oos = partition(trades, split_at)
    boundary_i = next(i for i, bar in enumerate(bars) if bar.time >= split_at)
    bh_is, bh_oos = buy_hold(bars, 0, boundary_i), buy_hold(bars, boundary_i, len(bars) - 1)
    print(f"\n### {label}\nLogic: {logic}\nRules: {rules}\nBacktest (IS): {format_stats(stats(is_))}"
          f"\nOOS: {format_stats(stats(oos))}\nWalk-forward: {walk_forward(trades, bars)}"
          f"\nRegimes: {regime_summary(trades, bars, regimes(bars, e21))}\nCosts: {RT_BPS:.0f} bps RT."
          f"\nBuy & hold IS/OOS: {bh_is:+.1%} / {bh_oos:+.1%}."
          f"\nRobustness (OOS):")
    lines = []
    for name, kwargs in sensitivity:
        test = run_trades(bars, signals, exit_rule=rule, atrs=atrs, e21=e21, **kwargs)
        _, test_oos = partition(test, split_at)
        row = f"{name}: E {stats(test_oos).expectancy:.3%}, PF {stats(test_oos).pf or 0:.2f}, n {len(test_oos)}"
        lines.append(row)
        print("  " + row)
    result = verdict(stats(is_), stats(oos))
    print(f"VERDICT: {result}")
    return label, stats(oos), result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars-1h", type=int, default=14000)
    parser.add_argument("--bars-4h", type=int, default=7000)
    args = parser.parse_args()
    print("=== HYPOTHESES V2 - RESEARCH ONLY; NO LIVE RECOMMENDATION ===")
    print("Closed-bar signals, next-open fills, SL-first on same-bar bracket collision, one concurrent long.")
    print(f"Friction: 10 bps fee/side + 3 bps slip/side + 2 bps spread = {RT_BPS:.0f} bps round trip.")
    all_results: list[tuple[str, Stats, str]] = []
    datasets = {"1h": await load("1h", args.bars_1h), "4h": await load("4h", args.bars_4h)}

    # A: Same H1b rule across timeframes. Fixed control mirrors the former SL2/TP5/20-bar protocol.
    print("\n## A) TIMEFRAME TEST - H1b CCR + volume > prior20 + bearish streak >=4 + close below EMA9/21")
    controls: dict[str, tuple[list[Bar], list[bool], list[float | None], list[float | None], int]] = {}
    for tf, bars in datasets.items():
        closes = [b.close for b in bars]
        e9, e21, atrs = ema(closes, 9), ema(closes, 21), atr(bars)
        split_at = bars[int(len(bars) * .7)].time
        signals = h1b_signals(bars, e9, e21)
        controls[tf] = bars, signals, atrs, e21, split_at
        all_results.append(evaluate(f"H1b timeframe control ({tf})", "CCR reversal continuation/rebound after an extended sell sequence.",
            "CCR(4); volume > preceding 20-bar average; prior bearish streak >=4; confirmation close below EMA9 and EMA21; fixed SL 2%, TP 5%, timeout 20 bars.",
            bars, signals, "fixed", atrs, e21, 20, split_at,
            [("SL1.8/TP4.5/16", {"hold": 16, "sl_pct": .018, "tp_pct": .045}), ("SL2.2/TP5.5/24", {"hold": 24, "sl_pct": .022, "tp_pct": .055})]))
        print(f"Buy & hold IS/OOS ({tf}): {buy_hold(bars, 0, int(len(bars)*.7)):+.1%} / {buy_hold(bars, int(len(bars)*.7), len(bars)-1):+.1%}")

    # B: exits on both candidate timeframes: avoids selecting a timeframe on OOS result then testing only it.
    print("\n## B) REDESIGNED H1b EXITS")
    for tf, (bars, signals, atrs, e21, split_at) in controls.items():
        for name, rule, hold, details in (
            ("ATR 1.5 / 2.5R", "atr", 20, "ATR14 stop = 1.5 ATR; target = 2.5R; timeout 20 bars."),
            ("time only 6", "time", 6, "No fixed stop/target; exit close after six bars."),
            ("time only 12", "time", 12, "No fixed stop/target; exit close after twelve bars."),
            ("EMA21 structure", "ema", 20, "Exit close below EMA21, otherwise force exit at 20 bars."),
        ):
            all_results.append(evaluate(f"H1b {tf} exit: {name}", "Same causal H1b entry; only the exit changes.", details,
                bars, signals, rule, atrs, e21, hold, split_at,
                [("hold -20%", {"hold": max(3, int(hold*.8))}), ("hold +20%", {"hold": int(hold*1.2)})]))

    # C: non-CCR entries, all ATR brackets. Both timeframes predeclared to prevent cherry-picking.
    print("\n## C) NEW, NON-CCR HYPOTHESIS FAMILIES")
    for tf, bars in datasets.items():
        closes = [b.close for b in bars]
        e21, e50, atrs = ema(closes, 21), ema(closes, 50), atr(bars)
        split_at = bars[int(len(bars) * .7)].time
        families = [
            ("Trend Donchian breakout", "Trend following: join a high breakout only while the medium trend is aligned.",
             "Close > highest prior 20-bar high; EMA21 > EMA50; volume > preceding 20-bar average; ATR14 1.5 stop, 2.5R target, 20-bar timeout.",
             breakout_signals(bars, e21, e50), 20),
            ("Low-vol Bollinger mean reversion", "Range reversion: buy a lower-band rejection only in compressed, flat conditions.",
             "Prior-20 Bollinger width <3.5%; EMA50 10-bar slope within +/-0.5%; low pierces lower 2-standard-deviation band and close reclaims it; ATR bracket, 12-bar timeout.",
             mean_reversion_signals(bars, e50), 12),
            ("EMA/ROC pullback continuation", "Momentum continuation: resume a verified uptrend after its controlled EMA21 pullback.",
             "EMA21 > EMA50; ROC10 >1%; prior low touches EMA21; current bullish close reclaims EMA21; ATR bracket, 20-bar timeout.",
             momentum_signals(bars, e21, e50), 20),
        ]
        for name, logic, rules, signals, hold in families:
            all_results.append(evaluate(f"{name} ({tf})", logic, rules, bars, signals, "bracket", atrs, e21, hold, split_at,
                [("ATR1.25 / 2.25R", {"hold": hold, "atr_mult": 1.25, "reward_r": 2.25}),
                 ("ATR1.75 / 2.75R", {"hold": hold, "atr_mult": 1.75, "reward_r": 2.75})]))

    print("\n## FINAL RANKING (OOS expectancy; 30-trade minimum remains required for a decision)")
    for rank, (name, oos, result) in enumerate(sorted(all_results, key=lambda x: (x[1].expectancy, x[1].pf or 0), reverse=True), 1):
        print(f"{rank}. {name}: {result}; {format_stats(oos)}")
    viable = [r for r in all_results if r[2] in {"PAPER TRADE", "PROMISING"}]
    if viable:
        print("\nConclusion: candidates above are only eligible for monitored paper trading; backtests alone are not a live recommendation.")
    else:
        print("\nConclusion: all candidates REJECT/NEED MORE DATA. Single next experiment: test the best non-CCR family with a predeclared short-side mirror and US/EU session filter; do not add more filters to CCR.")


if __name__ == "__main__":
    asyncio.run(main())
