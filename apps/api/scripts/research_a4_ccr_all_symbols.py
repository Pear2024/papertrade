"""Rank the paper-trading catalog's A4 BUY and CCR BUY entries on Binance 15m data.

Research only: this script never submits orders or changes application settings.
It uses production-seeded EMA/A4 helpers, completed candles, the fee-80 fill
model, and a bracket that remains live until its stop or target is reached.

Run from apps/api:
  .venv\\Scripts\\python.exe scripts\\research_a4_ccr_all_symbols.py --bars 50000
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyze_ccr_exits import Bar, fetch_bars  # noqa: E402
from app.core.assets_catalog import ASSETS_CATALOG  # noqa: E402
from app.services.coach import _a4_side_ok, _ema  # noqa: E402
from app.services.coach_ccr import OHLC, ccr_buy_at  # noqa: E402

FEE_BPS_SIDE, SLIP_BPS_SIDE, SPREAD_BPS_TOTAL = 80.0, 3.0, 2.0
SIDE_COST = (FEE_BPS_SIDE + SLIP_BPS_SIDE + SPREAD_BPS_TOTAL / 2) / 10_000
ROUND_TRIP_COST_BPS = 2 * SIDE_COST * 10_000

STRATEGIES = (
    "A4 BUY",
    "CCR bare (H2)",
    "CCR + vol + streak>=4 (H1)",
    "CCR H1b + below EMA9/21",
)


@dataclass(frozen=True)
class Trade:
    entry_time: int
    net: float
    kind: str


@dataclass(frozen=True)
class Summary:
    n: int
    tp_first_wr: float
    expectancy: float
    pf: float | None
    max_dd: float
    compounded: float


@dataclass(frozen=True)
class Result:
    symbol: str
    pair: str
    strategy: str
    bars: int
    start: int
    end: int
    ins: Summary
    oos: Summary


def volume_avg(bars: list[Bar], i: int, n: int = 20) -> float | None:
    if i < n:
        return None
    return sum(b.volume for b in bars[i - n:i]) / n


def bearish_streak_before(bars: list[Bar], i: int) -> int:
    streak = 0
    for j in range(i - 1, -1, -1):
        if bars[j].close >= bars[j].open:
            break
        streak += 1
    return streak


def signals_for(
    strategy: str, bars: list[Bar], ohlc: list[OHLC], ema9: list[float | None], ema21: list[float | None],
) -> list[bool]:
    signals = [False] * len(bars)
    for i in range(21, len(bars)):
        if strategy == "A4 BUY":
            if ema9[i] is not None and ema21[i] is not None:
                signals[i] = _a4_side_ok(
                    ema9=ema9[i], ema21=ema21[i], close=bars[i].close, sep_min=.10
                )[0]
            continue
        if not ccr_buy_at(ohlc, i, 4):
            continue
        if strategy == "CCR bare (H2)":
            signals[i] = True
        else:
            avg = volume_avg(bars, i)
            signals[i] = bool(
                avg is not None
                and bars[i].volume > avg
                and bearish_streak_before(bars, i) >= 4
            )
            if strategy == "CCR H1b + below EMA9/21":
                signals[i] = bool(
                    signals[i]
                    and ema9[i] is not None
                    and ema21[i] is not None
                    and bars[i].close < ema9[i]
                    and bars[i].close < ema21[i]
                )
    return signals


def simulate(bars: list[Bar], signals: list[bool], *, close_fill: bool) -> list[Trade]:
    """One concurrent long; SL wins an intrabar SL/TP collision."""
    trades: list[Trade] = []
    i = 21
    while i < len(bars) - 2:
        if not signals[i]:
            i += 1
            continue
        entry_i = i if close_fill else i + 1
        entry = bars[entry_i].close if close_fill else bars[entry_i].open
        stop, target = entry * .98, entry * 1.05
        first = entry_i + 1 if close_fill else entry_i
        exit_i = None
        exit_price = 0.0
        kind = "unresolved"
        for j in range(first, len(bars)):
            hit_stop, hit_target = bars[j].low <= stop, bars[j].high >= target
            if hit_stop or hit_target:
                exit_i = j
                exit_price = stop if hit_stop else target
                kind = "sl" if hit_stop else "tp"
                break
        if exit_i is None:
            # Do not fabricate a final loss/profit for an open bracket.
            break
        net = exit_price * (1 - SIDE_COST) / (entry * (1 + SIDE_COST)) - 1
        trades.append(Trade(bars[entry_i].time, net, kind))
        i = exit_i + 1
    return trades


def summarize(trades: list[Trade]) -> Summary:
    if not trades:
        return Summary(0, 0.0, 0.0, None, 0.0, 0.0)
    values = [trade.net for trade in trades]
    wins, losses = [v for v in values if v > 0], [v for v in values if v <= 0]
    equity = peak = 1.0
    max_dd = 0.0
    for value in values:
        equity *= 1 + value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) else None
    return Summary(
        n=len(trades),
        tp_first_wr=sum(t.kind == "tp" for t in trades) / len(trades),
        expectancy=statistics.mean(values),
        pf=pf,
        max_dd=max_dd,
        compounded=equity - 1,
    )


def split(trades: list[Trade], boundary: int) -> tuple[list[Trade], list[Trade]]:
    return (
        [trade for trade in trades if trade.entry_time < boundary],
        [trade for trade in trades if trade.entry_time >= boundary],
    )


def verdict(ins: Summary, oos: Summary) -> str:
    if oos.n < 20:
        return "NEED MORE DATA"
    if oos.expectancy <= 0 or (oos.pf or 0) <= 1:
        return "REJECT"
    if ins.expectancy > 0 and (ins.pf or 0) > 1 and oos.n >= 60 and (oos.pf or 0) >= 1.15:
        return "PAPER TRADE"
    return "PROMISING"


async def evaluate(symbol: str, pair: str, requested_bars: int) -> tuple[list[Result], str | None]:
    try:
        bars, _source = await fetch_bars(pair, "15m", requested_bars)
    except Exception as exc:  # Keep coverage visible when a Binance pair is unavailable.
        return [], f"{symbol} ({pair}): {exc}"
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [bar for bar in bars if bar.time + 900 <= now]
    if len(bars) < 5_000:
        return [], f"{symbol} ({pair}): only {len(bars):,} closed 15m bars"
    boundary = bars[int(len(bars) * .70)].time
    closes = [bar.close for bar in bars]
    ema9, ema21 = _ema(closes, 9), _ema(closes, 21)
    ohlc = [OHLC(bar.open, bar.high, bar.low, bar.close) for bar in bars]
    results = []
    for strategy in STRATEGIES:
        trades = simulate(bars, signals_for(strategy, bars, ohlc, ema9, ema21), close_fill=strategy == "A4 BUY")
        ins, oos = split(trades, boundary)
        results.append(Result(symbol, pair, strategy, len(bars), bars[0].time, bars[-1].time, summarize(ins), summarize(oos)))
    return results, None


def fmt_pf(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def print_table(title: str, results: list[Result]) -> None:
    print(f"\n## {title}")
    print("Rank Symbol OOS n  TP-first WR  Expectancy    PF    Max DD  Net return  Verdict")
    ranked = sorted(results, key=lambda item: (item.oos.expectancy, item.oos.pf or 0), reverse=True)
    for rank, item in enumerate(ranked, 1):
        print(
            f"{rank:>2}   {item.symbol:<5} {item.oos.n:>5}  {item.oos.tp_first_wr:>10.1%}  "
            f"{item.oos.expectancy:>+10.3%}  {fmt_pf(item.oos.pf):>5}  {item.oos.max_dd:>7.1%}  "
            f"{item.oos.compounded:>+10.1%}  {verdict(item.ins, item.oos)}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=50_000, help="latest closed 15m bars per catalog pair")
    parser.add_argument("--symbols", nargs="*", help="optional catalog symbols, e.g. BTC ETH SOL")
    parser.add_argument("--pause", type=float, default=.12, help="seconds between pairs after each paginated fetch")
    args = parser.parse_args()
    if args.bars < 5_000:
        parser.error("--bars must be at least 5,000")
    wanted = {symbol.upper() for symbol in args.symbols} if args.symbols else None
    assets = [asset for asset in ASSETS_CATALOG if wanted is None or asset["symbol"] in wanted]
    unknown = sorted(wanted - {asset["symbol"] for asset in ASSETS_CATALOG}) if wanted else []
    if unknown:
        parser.error(f"not in paper-trading catalog: {', '.join(unknown)}")

    print("=== A4 + CCR CATALOG RESEARCH (NOT LIVE-TRADING EVIDENCE) ===")
    print(f"Catalog coverage: {len(assets)} supported paper-trading symbols; Binance USDT 15m; up to {args.bars:,} latest bars/pair.")
    print(f"Costs: {ROUND_TRIP_COST_BPS:.1f}bps round trip (80bps fee + 3bps slip each side, 2bps total spread).")
    print("A4 fills signal close; CCR fills next open. All brackets: SL 2%, TP 5%, held until hit; same-bar collision is SL-first.")
    all_results: list[Result] = []
    skipped: list[str] = []
    for number, asset in enumerate(assets, 1):
        print(f"Fetching {number}/{len(assets)} {asset['symbol']}...", flush=True)
        results, error = await evaluate(asset["symbol"], asset["binance_pair"], args.bars)
        all_results.extend(results)
        if error:
            skipped.append(error)
        await asyncio.sleep(args.pause)

    for strategy in STRATEGIES:
        print_table(strategy, [result for result in all_results if result.strategy == strategy])
    positives = [
        result for result in all_results
        if result.oos.n >= 20 and result.oos.expectancy > 0 and (result.oos.pf or 0) > 1
    ]
    print("\n## OOS positive candidates (screen only; no live recommendation)")
    if positives:
        for result in sorted(positives, key=lambda item: item.oos.expectancy, reverse=True):
            print(f"{result.strategy}: {result.symbol} — {verdict(result.ins, result.oos)}; E={result.oos.expectancy:+.3%}; PF={fmt_pf(result.oos.pf)}; n={result.oos.n}")
    else:
        print("None met n>=20, positive OOS expectancy, and PF>1.")
    if skipped:
        print("\n## Skipped / unavailable")
        print("\n".join(skipped))
    if all_results:
        earliest, latest = min(r.start for r in all_results), max(r.end for r in all_results)
        print(f"\nCompleted: {len({r.symbol for r in all_results})}/{len(assets)} symbols, {len(all_results)} strategy-symbol results; "
              f"data spans {datetime.fromtimestamp(earliest, timezone.utc):%F}..{datetime.fromtimestamp(latest, timezone.utc):%F} (per-symbol starts differ).")


if __name__ == "__main__":
    asyncio.run(main())
