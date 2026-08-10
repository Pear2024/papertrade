r"""Reproducible, conservative BTCUSDT 15m long-hypothesis research suite.

Run from apps/api:
  .venv\Scripts\python.exe scripts\research_hypotheses_suite.py --bars 140000

Signals use completed candles only. CCR fills at the following open; production
A4 fills at the signal close. Every trade includes 80 bps/side fee, 3 bps/side
slippage, and 2 bps total spread (168 bps round trip). ``TP-first WR`` is the
price-path outcome (the target is reached before the stop, with SL priority on
an intrabar collision); it is intentionally separate from ``net-positive WR``.
The suite is research only; it deliberately does not place orders or alter app
configuration.
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
from app.services.coach import _a4_side_ok, _ema  # noqa: E402
from app.services.coach_ccr import OHLC, ccr_buy_at  # noqa: E402

FEE_BPS_SIDE, SLIP_BPS_SIDE, SPREAD_BPS_TOTAL = 80.0, 3.0, 2.0
SIDE_COST = (FEE_BPS_SIDE + SLIP_BPS_SIDE + SPREAD_BPS_TOTAL / 2) / 10_000
ROUND_TRIP_COST_BPS = 2 * SIDE_COST * 10_000


@dataclass(frozen=True)
class Trade:
    entry_time: int
    exit_time: int
    gross: float
    net: float
    kind: str


@dataclass(frozen=True)
class Summary:
    n: int
    tp_first_wr: float
    net_positive_wr: float
    avg_win: float
    avg_loss: float
    expectancy: float
    pf: float | None
    compounded: float
    sharpe: float | None
    max_dd: float


def ema(values: list[float], period: int) -> list[float | None]:
    """Production-seeded EMA, unlike the old exploratory first-close EMA."""
    return _ema(values, period)


def volume_avg(bars: list[Bar], i: int, n: int = 20) -> float | None:
    if i < n:
        return None
    return sum(b.volume for b in bars[i - n:i]) / n


def bearish_streak_before(bars: list[Bar], i: int) -> int:
    result = 0
    for j in range(i - 1, -1, -1):
        if bars[j].close >= bars[j].open:
            break
        result += 1
    return result


def ccr_signal(bars: list[Bar], ohlc: list[OHLC], i: int, n: int, volume: bool, streak4: bool,
               below_both: bool, e9: list[float | None], e21: list[float | None]) -> bool:
    if not ccr_buy_at(ohlc, i, n):
        return False
    if volume:
        avg = volume_avg(bars, i)
        if avg is None or bars[i].volume <= avg:
            return False
    if streak4 and bearish_streak_before(bars, i) < 4:
        return False
    if below_both and (e9[i] is None or e21[i] is None or not (bars[i].close < e9[i] and bars[i].close < e21[i])):
        return False
    return True


def simulate(
    bars: list[Bar], signals: list[bool], *, fill: str, sl_pct: float, tp_pct: float,
    hold: int | None, dynamic_stop: list[float | None] | None = None,
) -> list[Trade]:
    """One concurrent long; ``hold=None`` keeps the bracket live until SL or TP."""
    trades: list[Trade] = []
    i = 21
    while i < len(bars) - 2:
        if not signals[i]:
            i += 1
            continue
        entry_i = i if fill == "close" else i + 1
        entry = bars[entry_i].close if fill == "close" else bars[entry_i].open
        stop = dynamic_stop[i] if dynamic_stop is not None and dynamic_stop[i] else entry * (1 - sl_pct)
        stop = min(stop, entry * (1 - 0.001))  # Do not admit invalid/zero-risk stops.
        risk = entry - stop
        target = entry + risk * (tp_pct / sl_pct) if dynamic_stop is not None else entry * (1 + tp_pct)
        last = len(bars) if hold is None else min(entry_i + hold, len(bars))
        exit_i = exit_px = None
        kind = "unresolved"
        # A close-fill signal cannot know that candle's high/low, so start next candle.
        first = entry_i + 1 if fill == "close" else entry_i
        for j in range(first, last):
            hit_stop, hit_target = bars[j].low <= stop, bars[j].high >= target
            if hit_stop or hit_target:
                exit_i, exit_px = j, stop if hit_stop else target  # stop-first when both
                kind = "sl" if hit_stop else "tp"
                break
        if exit_i is None:
            if hold is None:
                # The final bracket remains open at the end of available data;
                # exclude it instead of turning its last mark into a false loss.
                break
            exit_i, exit_px, kind = last - 1, bars[last - 1].close, "timeout"
        gross = exit_px / entry - 1
        net = exit_px * (1 - SIDE_COST) / (entry * (1 + SIDE_COST)) - 1
        trades.append(Trade(bars[entry_i].time, bars[exit_i].time, gross, net, kind))
        i = exit_i + 1
    return trades


def summarize(trades: list[Trade]) -> Summary:
    xs = [t.net for t in trades]
    if not xs:
        return Summary(0, 0, 0, 0, 0, 0, None, 0, None, 0)
    wins, losses = [x for x in xs if x > 0], [x for x in xs if x <= 0]
    tp_first = sum(t.kind == "tp" for t in trades)
    equity = peak = 1.0
    dd = 0.0
    for x in xs:
        equity *= 1 + x
        peak = max(peak, equity)
        dd = min(dd, equity / peak - 1)
    std = statistics.stdev(xs) if len(xs) > 1 else 0
    return Summary(
        len(xs), tp_first / len(xs), len(wins) / len(xs), statistics.mean(wins) if wins else 0,
        statistics.mean(losses) if losses else 0, statistics.mean(xs),
        sum(wins) / abs(sum(losses)) if losses and sum(losses) else None,
        equity - 1, statistics.mean(xs) / std * math.sqrt(len(xs)) if std else None, dd,
    )


def text(s: Summary) -> str:
    pf = f"{s.pf:.2f}" if s.pf is not None else "n/a"
    sh = f"{s.sharpe:.2f}" if s.sharpe is not None else "n/a"
    return (f"n={s.n}; TP-first WR={s.tp_first_wr:.1%}; net-positive WR={s.net_positive_wr:.1%}; "
            f"avg net win/loss={s.avg_win:.2%}/{s.avg_loss:.2%}; "
            f"E={s.expectancy:.3%}; PF={pf}; Sharpe(trade)={sh}; maxDD={s.max_dd:.1%}; net={s.compounded:.1%}")


def verdict(ins: Summary, oos: Summary) -> str:
    """Conservative labels based only on the predeclared IS/OOS split."""
    if oos.n < 30:
        return "NEED MORE DATA"
    if oos.expectancy <= 0 or (oos.pf or 0) < 1:
        return "REJECT"
    if ins.expectancy > 0 and (ins.pf or 0) >= 1 and (oos.pf or 0) >= 1.15 and oos.n >= 60:
        return "PAPER TRADE"
    return "PROMISING"


def objective_regimes(bars: list[Bar]) -> list[str]:
    closes = [b.close for b in bars]
    sma200 = [None] * len(bars)
    rv = [None] * len(bars)
    for i in range(199, len(bars)):
        sma200[i] = sum(closes[i - 199:i + 1]) / 200
    returns = [math.log(closes[i] / closes[i - 1]) if i else 0 for i in range(len(bars))]
    vols = []
    for i in range(96, len(bars)):
        value = statistics.pstdev(returns[i - 95:i + 1])
        vols.append(value)
        rv[i] = value
    lo, hi = sorted(vols)[int(.25 * len(vols))], sorted(vols)[int(.75 * len(vols))]
    labels = []
    for i in range(len(bars)):
        if sma200[i] is None or i < 219:
            labels.append("warmup")
        elif rv[i] >= hi:
            labels.append("high-vol")
        elif rv[i] <= lo:
            labels.append("low-vol")
        else:
            slope = (sma200[i] / sma200[i - 20] - 1) if sma200[i - 20] else 0
            labels.append("bull" if slope > .01 else "bear" if slope < -.01 else "sideways")
    return labels


def by_regime(trades: list[Trade], bars: list[Bar], labels: list[str]) -> str:
    lookup = {b.time: labels[i] for i, b in enumerate(bars)}
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        groups[lookup[t.entry_time]].append(t)
    return "; ".join(f"{k}:{text(summarize(v))}" for k, v in sorted(groups.items()) if k != "warmup")


def split(trades: list[Trade], boundary: int) -> tuple[list[Trade], list[Trade]]:
    return [t for t in trades if t.entry_time < boundary], [t for t in trades if t.entry_time >= boundary]


def parameter_sensitivity(name: str, bars: list[Bar], ohlc: list[OHLC], e9: list[float | None],
                          e21: list[float | None], split_at: int) -> str:
    """Local perturbations; only reports OOS expectancy/PF to prevent IS selection."""
    rows = []
    for sl, tp, hold in ((.018, .045, 16), (.02, .05, 20), (.022, .055, 24)):
        sig = build_signals(name, bars, ohlc, e9, e21, compression=12)
        trades = simulate(bars, sig, fill="close" if name == "H3 A4 EMA gap" else "next_open",
                          sl_pct=sl, tp_pct=tp, hold=hold)
        _, oos = split(trades, split_at)
        s = summarize(oos)
        rows.append(f"{sl:.1%}/{tp:.1%}/{hold}: E {s.expectancy:.3%}, PF {s.pf or 0:.2f}, n {s.n}")
    return " | ".join(rows)


def build_signals(name: str, bars: list[Bar], ohlc: list[OHLC], e9: list[float | None],
                  e21: list[float | None], compression: int = 12) -> list[bool]:
    out = [False] * len(bars)
    for i in range(21, len(bars)):
        if name == "H1 CCR confirm+volume+streak>=4":
            out[i] = ccr_signal(bars, ohlc, i, 4, True, True, False, e9, e21)
        elif name == "H1b H1 + below EMA9/21":
            out[i] = ccr_signal(bars, ohlc, i, 4, True, True, True, e9, e21)
        elif name == "H2 CCR bare":
            out[i] = ccr_signal(bars, ohlc, i, 4, False, False, False, e9, e21)
        elif name == "H3 A4 EMA gap":
            if e9[i] is not None and e21[i] is not None:
                out[i] = _a4_side_ok(ema9=e9[i], ema21=e21[i], close=bars[i].close, sep_min=.10)[0]
        elif name == "H4 Trend pullback":
            # EMA9>EMA21; prior 3 bars stayed above EMA9; current low reaches EMA9
            # (within 0.15%) and bullish close finishes above it.
            out[i] = bool(e9[i] and e21[i] and e9[i] > e21[i] and
                          all(bars[j].close > e9[j] for j in range(i - 3, i)) and
                          bars[i].low <= e9[i] * 1.0015 and bars[i].close > bars[i].open and bars[i].close > e9[i])
        elif name == "H5 Compression breakout":
            if i >= compression:
                prior = bars[i - compression:i]
                high, low = max(x.high for x in prior), min(x.low for x in prior)
                avg = volume_avg(bars, i)
                out[i] = ((high - low) / low <= .012 and bars[i].close > high and
                          avg is not None and bars[i].volume > avg)
    return out


def buy_hold(bars: list[Bar], start: int, end: int) -> float:
    return bars[end].close * (1 - SIDE_COST) / (bars[start].open * (1 + SIDE_COST)) - 1


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=tuple(BINANCE_PAIRS), default="BTC")
    parser.add_argument("--bars", type=int, default=140_000)
    parser.add_argument("--secondary-eth", action="store_true", help="run identical suite on ETH after BTC")
    args = parser.parse_args()
    if args.bars < 20_000:
        parser.error("--bars must be at least 20,000 for meaningful IS/OOS results")
    bars, source = await fetch_bars(BINANCE_PAIRS[args.symbol], "15m", args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [b for b in bars if b.time + 900 <= now]
    closes, ohlc = [b.close for b in bars], [OHLC(b.open, b.high, b.low, b.close) for b in bars]
    e9, e21 = ema(closes, 9), ema(closes, 21)
    split_at = bars[int(len(bars) * .70)].time
    regimes = objective_regimes(bars)
    names = (
        "H1 CCR confirm+volume+streak>=4",
        "H1b H1 + below EMA9/21",
        "H2 CCR bare",
        "H3 A4 EMA gap",
        "H4 Trend pullback",
        "H5 Compression breakout",
    )
    print("=== LONG HYPOTHESIS SUITE (RESEARCH ONLY; NOT LIVE-TRADING EVIDENCE) ===")
    print(f"source=Binance {source}; {BINANCE_PAIRS[args.symbol]} 15m; {len(bars):,} bars; "
          f"{datetime.fromtimestamp(bars[0].time, timezone.utc):%F}..{datetime.fromtimestamp(bars[-1].time, timezone.utc):%F}")
    print(f"IS first 70% before {datetime.fromtimestamp(split_at, timezone.utc):%F}; OOS final 30%. "
          f"costs={ROUND_TRIP_COST_BPS:.1f}bps round trip (80 fee + 3 slip per side, 2 spread total).")
    net_rr_2_5 = (.05 - ROUND_TRIP_COST_BPS / 10_000) / (.02 + ROUND_TRIP_COST_BPS / 10_000)
    min_tp_for_net_rr_2 = 2 * (.02 + ROUND_TRIP_COST_BPS / 10_000) + ROUND_TRIP_COST_BPS / 10_000
    print(
        f"SL 2% / TP 5% net R:R={net_rr_2_5:.2f}; below the 2.00 production gate, "
        "so this is an explicitly ungated research comparison."
    )
    print(
        f"At this friction, TP >= {min_tp_for_net_rr_2:.2%} clears the conservative net R:R >=2 "
        "calculation; the second comparison uses TP 9.1%."
    )
    print("Regimes: bull/bear when SMA200 20-bar slope >+1%/<-1%; otherwise sideways; "
          "high/low-vol override at 96-bar realized-vol top/bottom quartile.")
    # TP-first WR is never inferred from P&L. This prevents high transaction
    # costs from relabelling an exit outcome as a path-based loss.
    results: list[tuple[str, str, Summary, Summary]] = []
    comparisons = (
        ("SL 2.0% / TP 5.0% (ungated)", .05),
        ("SL 2.0% / TP 9.1% (net R:R >=2)", .091),
    )
    for bracket_label, tp_pct in comparisons:
        print(f"\n## A4 vs CCR — {bracket_label}; bracket held until SL or TP; one concurrent long")
        print("Strategy                              IS: TP-first / net+ WR (n)       OOS: TP-first / net+ WR (n)       OOS expectancy")
        for name in names:
            signals = build_signals(name, bars, ohlc, e9, e21)
            trades = simulate(
                bars,
                signals,
                fill="close" if name == "H3 A4 EMA gap" else "next_open",
                sl_pct=.02,
                tp_pct=tp_pct,
                hold=None,
            )
            ins, oos = split(trades, split_at)
            s_all, s_is, s_oos = summarize(trades), summarize(ins), summarize(oos)
            print(
                f"{name:<37} "
                f"{s_is.tp_first_wr:>6.1%} / {s_is.net_positive_wr:>6.1%} ({s_is.n:>3})     "
                f"{s_oos.tp_first_wr:>6.1%} / {s_oos.net_positive_wr:>6.1%} ({s_oos.n:>3})     "
                f"{s_oos.expectancy:>+8.3%}"
            )
            print(f"  IS: {text(s_is)}\n  OOS: {text(s_oos)}\n  FULL: {text(s_all)}")
            results.append((bracket_label, name, s_is, s_oos))
    start, boundary, end = 0, int(len(bars) * .70), len(bars) - 1
    print(f"\n### Baselines (passive, {ROUND_TRIP_COST_BPS:.0f}bps total transaction friction)")
    print(f"Buy & hold IS/OOS: {buy_hold(bars, start, boundary):+.1%} / {buy_hold(bars, boundary, end):+.1%}")
    primary = [r for r in results if r[0].startswith("SL 2.0% / TP 5.0%")]
    gated = {name: oos for bracket, name, _is, oos in results if "9.1%" in bracket}
    print("\n### FINAL RANKING — PRIMARY: SL 2% / TP 5% (ungated research)")
    print("Rank Strategy                              Verdict          n   TP-first  Expectancy  PF   Sharpe  MaxDD  Net return  TP9.1 E/PF")
    for rank, (_bracket, name, s_is, s_oos) in enumerate(
        sorted(primary, key=lambda r: (r[3].expectancy, r[3].pf or 0), reverse=True), 1
    ):
        g = gated[name]
        pf = f"{s_oos.pf:.2f}" if s_oos.pf is not None else "n/a"
        sh = f"{s_oos.sharpe:.2f}" if s_oos.sharpe is not None else "n/a"
        gpf = f"{g.pf:.2f}" if g.pf is not None else "n/a"
        print(
            f"{rank:>2}   {name:<37} {verdict(s_is, s_oos):<15} {s_oos.n:>3}  "
            f"{s_oos.tp_first_wr:>7.1%}  {s_oos.expectancy:>+8.3%}  {pf:>4}  {sh:>6}  "
            f"{s_oos.max_dd:>6.1%}  {s_oos.compounded:>+8.1%}  {g.expectancy:+.3%}/{gpf}"
        )
    print("Research uses the receipt-backed 0.80% per-fill percent fee; no flat $9/fill model is applied.")


if __name__ == "__main__":
    asyncio.run(main())
