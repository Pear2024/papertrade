"""Causal, versioned BTCUSDT spot-hypothesis experiment engine.

Run from ``apps/api``:
  .venv\\Scripts\\python.exe -m app.research.experiment_engine.runner --bars 70000

The engine intentionally has no production dependencies.  It downloads Binance
spot candles, excludes incomplete bars, emits closed-bar signals, and fills at
the following 15-minute open.  It is research only and never places orders.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

BINANCE_URLS = (
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
)
SECONDS = {"15m": 900, "1h": 3600}
ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = ROOT / "research_outputs" / "experiment_engine"


@dataclass(frozen=True)
class Candle:
    time: int  # Unix seconds; candle open time
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Costs:
    """Spot model: Kraken-aligned percentage fees, no funding."""

    fee_rate: float = 0.008
    spread_bps: float = 2.0
    slippage_bps_side: float = 3.0
    funding_rate: float = 0.0

    @property
    def impact_rate(self) -> float:
        return (self.spread_bps / 2 + self.slippage_bps_side) / 10_000


@dataclass(frozen=True)
class Strategy:
    """Immutable rules. Any rule alteration must introduce a new id/version."""

    id: str
    version: str
    name: str
    description: str


STRATEGIES = (
    Strategy("H1", "1.0.0", "EMA Trend", "EMA9 > EMA21 and close > EMA9."),
    Strategy("H2", "1.0.0", "EMA + HTF", "H1 plus last completed 1h close > EMA200."),
    Strategy("H3", "1.0.0", "EMA + Volume", "H1 plus volume > 1.5 × preceding VolMA20."),
    Strategy("H4", "1.0.0", "EMA + RSI", "H1 plus RSI14 in [50, 70]."),
    Strategy("H5", "1.0.0", "EMA Pullback", "EMA trend; preceding close above EMA9, signal low <= EMA9 and close > EMA9."),
    Strategy("H6", "1.0.0", "Breakout", "Close > maximum high of preceding 20 completed candles."),
    Strategy("H7", "1.0.0", "Breakout + Volume", "H6 plus volume > 1.5 × preceding VolMA20."),
    Strategy("H8", "1.0.0", "Breakout Retest", "Causal breakout/retest/confirmation state machine."),
    Strategy("H9", "1.0.0", "ADX Trend", "EMA9 > EMA21 and ADX14 > 25."),
    Strategy("H10", "1.0.0", "Multi-Filter", "Completed 1h trend plus EMA, volume, RSI and ADX filters."),
)
R_TARGETS = (1.5, 2.0, 2.5, 3.0)


@dataclass
class Trade:
    hypothesis_id: str
    version: str
    r_target: float
    trigger_reason: str
    signal_time: int
    entry_time: int
    exit_time: int
    entry_raw: float
    entry_fill: float
    stop_raw: float
    target_raw: float
    exit_raw: float
    exit_fill: float
    quantity: float
    exit_reason: str
    gross_pnl: float
    net_pnl: float
    entry_fee: float
    exit_fee: float
    spread_slippage_cost: float
    funding_cost: float
    total_cost: float
    equity_before: float
    equity_after: float
    r_multiple: float

    def row(self) -> dict[str, object]:
        data = asdict(self)
        for key in ("signal_time", "entry_time", "exit_time"):
            data[key] = datetime.fromtimestamp(data[key], timezone.utc).isoformat()
        return data


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    value = sum(values[:period]) / period
    out[period - 1] = value
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        value += alpha * (values[i] - value)
        out[i] = value
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i] - values[i - 1], 0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0) for i in range(1, len(values))]
    gain, loss = sum(gains[:period]) / period, sum(losses[:period]) / period
    out[period] = 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    for i in range(period + 1, len(values)):
        gain = (gain * (period - 1) + gains[i - 1]) / period
        loss = (loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def atr(bars: list[Candle], period: int = 14) -> list[float | None]:
    tr = [0.0] * len(bars)
    for i, bar in enumerate(bars):
        previous = bars[i - 1].close if i else bar.close
        tr[i] = max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))
    out: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return out
    value = sum(tr[1:period + 1]) / period
    out[period] = value
    for i in range(period + 1, len(bars)):
        value = (value * (period - 1) + tr[i]) / period
        out[i] = value
    return out


def adx(bars: list[Candle], period: int = 14) -> list[float | None]:
    """Wilder ADX; values are known only after the candle closes."""
    out: list[float | None] = [None] * len(bars)
    if len(bars) < period * 2 + 1:
        return out
    trs, plus, minus = [], [], []
    for i in range(1, len(bars)):
        up, down = bars[i].high - bars[i - 1].high, bars[i - 1].low - bars[i].low
        trs.append(max(bars[i].high - bars[i].low, abs(bars[i].high - bars[i - 1].close), abs(bars[i].low - bars[i - 1].close)))
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    smooth_tr, smooth_p, smooth_m = sum(trs[:period]), sum(plus[:period]), sum(minus[:period])
    dxs: list[float] = []
    for k in range(period - 1, len(trs)):
        if k > period - 1:
            smooth_tr = smooth_tr - smooth_tr / period + trs[k]
            smooth_p = smooth_p - smooth_p / period + plus[k]
            smooth_m = smooth_m - smooth_m / period + minus[k]
        pdi, mdi = 100 * smooth_p / smooth_tr, 100 * smooth_m / smooth_tr
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
        if len(dxs) == period:
            value = sum(dxs) / period
            out[k + 1] = value
        elif len(dxs) > period:
            value = (value * (period - 1) + dxs[-1]) / period
            out[k + 1] = value
    return out


async def fetch_bars(interval: str, target: int, symbol: str = "BTCUSDT") -> tuple[list[Candle], str]:
    errors: list[str] = []
    for url in BINANCE_URLS:
        try:
            bars: list[Candle] = []
            end_time: int | None = None
            async with httpx.AsyncClient(timeout=30) as client:
                while len(bars) < target:
                    params: dict[str, int | str] = {"symbol": symbol.upper(), "interval": interval, "limit": 1000}
                    if end_time is not None:
                        params["endTime"] = end_time
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    rows = response.json()
                    if not rows:
                        break
                    bars = [Candle(int(r[0]) // 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows] + bars
                    end_time = int(rows[0][0]) - 1
                    if len(rows) < 1000:
                        break
                    await asyncio.sleep(0.08)
            closed_before = int(datetime.now(timezone.utc).timestamp())
            unique = {b.time: b for b in bars}
            result = [b for b in sorted(unique.values(), key=lambda x: x.time) if b.time + SECONDS[interval] <= closed_before][-target:]
            if result:
                return result, url.split("//", 1)[1].split("/", 1)[0]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Unable to fetch Binance data: " + "; ".join(errors))


def completed_h1_map(bars15: list[Candle], bars1h: list[Candle]) -> list[int | None]:
    """For each 15m signal close, return the final 1h bar completed then."""
    result: list[int | None] = []
    pointer = -1
    for bar in bars15:
        signal_close = bar.time + SECONDS["15m"]
        while pointer + 1 < len(bars1h) and bars1h[pointer + 1].time + SECONDS["1h"] <= signal_close:
            pointer += 1
        result.append(pointer if pointer >= 0 else None)
    return result


def signals_for(strategy: Strategy, bars: list[Candle], htf: list[Candle]) -> tuple[list[bool], list[str]]:
    closes = [b.close for b in bars]
    e9, e21, rsi14, adx14 = ema(closes, 9), ema(closes, 21), rsi(closes), adx(bars)
    htf_close, htf_ema200 = [b.close for b in htf], ema([b.close for b in htf], 200)
    htf_index = completed_h1_map(bars, htf)
    out, reasons = [False] * len(bars), [""] * len(bars)
    # H8: state created only at a closed breakout signal, then consumed by a
    # later low <= fixed breakout level and later bullish close above it.
    retest_level: float | None = None
    retest_seen = False
    for i in range(200, len(bars)):
        b = bars[i]
        volma = sum(x.volume for x in bars[i - 20:i]) / 20
        trend = bool(e9[i] and e21[i] and e9[i] > e21[i])
        h1_ok = htf_index[i] is not None and htf_ema200[htf_index[i]] is not None and htf_close[htf_index[i]] > htf_ema200[htf_index[i]]
        breakout_level = max(x.high for x in bars[i - 20:i])
        breakout = b.close > breakout_level
        if strategy.id == "H1":
            out[i], reasons[i] = trend and b.close > e9[i], "EMA9>EMA21; close>EMA9"
        elif strategy.id == "H2":
            out[i], reasons[i] = trend and b.close > e9[i] and h1_ok, "H1; completed 1h close>EMA200"
        elif strategy.id == "H3":
            out[i], reasons[i] = trend and b.close > e9[i] and b.volume > 1.5 * volma, "H1; volume>1.5*priorVolMA20"
        elif strategy.id == "H4":
            out[i], reasons[i] = trend and b.close > e9[i] and rsi14[i] is not None and 50 <= rsi14[i] <= 70, "H1; RSI14 50..70"
        elif strategy.id == "H5":
            prior_above = e9[i - 1] is not None and bars[i - 1].close > e9[i - 1]
            out[i], reasons[i] = trend and prior_above and b.low <= e9[i] and b.close > e9[i], "EMA trend; prior close>EMA9; low<=EMA9; close>EMA9"
        elif strategy.id == "H6":
            out[i], reasons[i] = breakout, "close>highest high of prior 20 completed candles"
        elif strategy.id == "H7":
            out[i], reasons[i] = breakout and b.volume > 1.5 * volma, "breakout; volume>1.5*priorVolMA20"
        elif strategy.id == "H8":
            if retest_level is None and breakout:
                retest_level, retest_seen = breakout_level, False
            elif retest_level is not None and not retest_seen and b.low <= retest_level:
                retest_seen = True
            elif retest_level is not None and retest_seen and b.close > b.open and b.close > retest_level:
                out[i], reasons[i] = True, f"retest level {retest_level:.2f}; bullish close back above"
                retest_level, retest_seen = None, False
            # A fresh close below the level invalidates a waiting retest setup.
            if retest_level is not None and b.close < retest_level:
                retest_level, retest_seen = None, False
        elif strategy.id == "H9":
            out[i], reasons[i] = trend and adx14[i] is not None and adx14[i] > 25, "EMA9>EMA21; ADX14>25"
        elif strategy.id == "H10":
            out[i], reasons[i] = bool(h1_ok and trend and b.volume > 1.5 * volma and rsi14[i] is not None and 50 <= rsi14[i] <= 70 and adx14[i] is not None and adx14[i] > 25), "completed 1h trend; EMA; volume; RSI; ADX"
    return out, reasons


def simulate(strategy: Strategy, bars: list[Candle], signals: list[bool], reasons: list[str], r_target: float, costs: Costs, starting_equity: float, risk_fraction: float, max_hold: int, start_index: int = 200, end_index: int | None = None, atr_multiple: float = 1.0, stop_prices: list[float | None] | None = None) -> list[Trade]:
    """ATR or absolute structure stop; brackets active at next-open entry; SL first."""
    atr14 = atr(bars)
    trades: list[Trade] = []
    end_index = end_index if end_index is not None else len(bars)
    equity, i = starting_equity, max(200, start_index)
    while i < end_index - 1:
        # A strategy that exhausts its dedicated period capital cannot keep
        # opening fictional microscopic positions.
        if equity <= 1e-8:
            break
        structure_stop = stop_prices[i] if stop_prices and i < len(stop_prices) else None
        if not signals[i]:
            i += 1
            continue
        if structure_stop is None and atr14[i] is None:
            i += 1
            continue
        entry_i, entry_raw = i + 1, bars[i + 1].open
        if structure_stop is not None:
            stop_raw = float(structure_stop)
        else:
            risk_distance = atr14[i] * atr_multiple  # frozen signal-bar ATR; never future data
            stop_raw = entry_raw - risk_distance
        target_raw = entry_raw + r_target * (entry_raw - stop_raw)
        if stop_raw <= 0 or stop_raw >= entry_raw:
            i += 1
            continue
        entry_fill = entry_raw * (1 + costs.impact_rate)
        stop_fill = stop_raw * (1 - costs.impact_rate)
        quantity = equity * risk_fraction / (entry_fill - stop_fill)
        exit_i, exit_raw, exit_reason = min(entry_i + max_hold - 1, end_index - 1), bars[min(entry_i + max_hold - 1, end_index - 1)].close, "timeout"
        for j in range(entry_i, min(entry_i + max_hold, end_index)):
            hit_sl, hit_tp = bars[j].low <= stop_raw, bars[j].high >= target_raw
            if hit_sl or hit_tp:  # stop is deliberately first if both occur
                exit_i, exit_raw, exit_reason = j, (stop_raw if hit_sl else target_raw), ("stop" if hit_sl else "target")
                break
        exit_fill = exit_raw * (1 - costs.impact_rate)
        entry_notional, exit_notional = quantity * entry_fill, quantity * exit_fill
        entry_fee, exit_fee = entry_notional * costs.fee_rate, exit_notional * costs.fee_rate
        gross = quantity * (exit_raw - entry_raw)
        net = quantity * (exit_fill - entry_fill) - entry_fee - exit_fee
        impact_cost = quantity * ((entry_fill - entry_raw) + (exit_raw - exit_fill))
        funding = 0.0  # Explicit spot model. Funding is not applicable.
        before = equity
        equity += net - funding
        trades.append(Trade(strategy.id, strategy.version, r_target, reasons[i], bars[i].time, bars[entry_i].time, bars[exit_i].time, entry_raw, entry_fill, stop_raw, target_raw, exit_raw, exit_fill, quantity, exit_reason, gross, net, entry_fee, exit_fee, impact_cost, funding, entry_fee + exit_fee + impact_cost + funding, before, equity, net / (before * risk_fraction)))
        i = exit_i + 1
    return trades


def partition_index(bars: list[Candle], development: float, oos: float) -> tuple[int, int]:
    first = int(len(bars) * development)
    return bars[first].time, bars[first + int(len(bars) * oos)].time


def split_trades(trades: list[Trade], dev_end: int, oos_end: int) -> dict[str, list[Trade]]:
    # Classification uses signal time: each experimental decision belongs to the
    # period in which it was made, avoiding post-exit contamination.
    return {
        "development": [t for t in trades if t.signal_time < dev_end],
        "oos": [t for t in trades if dev_end <= t.signal_time < oos_end],
        "paper": [t for t in trades if t.signal_time >= oos_end],
    }


def metrics(trades: list[Trade]) -> dict[str, float | int | None]:
    if not trades:
        return dict(trades=0, win_rate=0.0, gross_pnl=0.0, net_pnl=0.0, avg_net_profit=0.0, expectancy=0.0, profit_factor=None, max_drawdown=0.0, average_r=0.0, sharpe=None, total_trading_costs=0.0)
    net = [t.net_pnl for t in trades]
    wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
    peak = equity = trades[0].equity_before
    worst_dd = 0.0
    for t in trades:
        equity = t.equity_after
        peak = max(peak, equity)
        worst_dd = min(worst_dd, (equity / peak - 1) if peak else 0)
    std = statistics.stdev(net) if len(net) > 1 else 0
    return dict(
        trades=len(trades), win_rate=len(wins) / len(trades), gross_pnl=sum(t.gross_pnl for t in trades),
        net_pnl=sum(net), avg_net_profit=statistics.mean(net), expectancy=statistics.mean(t.r_multiple for t in trades),
        profit_factor=(sum(wins) / abs(sum(losses))) if losses and sum(losses) else None,
        max_drawdown=worst_dd, average_r=statistics.mean(t.r_multiple for t in trades),
        sharpe=(statistics.mean(net) / std * math.sqrt(len(net))) if std else None,
        total_trading_costs=sum(t.total_cost for t in trades),
    )


def verdict(dev: dict[str, float | int | None], oos: dict[str, float | int | None]) -> str:
    """Selection only sees development and OOS. Paper metrics are intentionally absent."""
    if dev["gross_pnl"] > 0 and dev["net_pnl"] <= 0 or oos["gross_pnl"] > 0 and oos["net_pnl"] <= 0:
        return "REJECT"
    if int(oos["trades"]) < 30:
        return "NEED MORE DATA"
    if float(dev["expectancy"]) <= 0 or float(oos["expectancy"]) <= 0 or (oos["profit_factor"] or 0) < 1:
        return "REJECT"
    if int(oos["trades"]) >= 60 and (oos["profit_factor"] or 0) >= 1.15 and float(oos["max_drawdown"]) >= -0.20:
        return "PAPER TRADE"
    return "PROMISING"


def write_outputs(run_dir: Path, trades: list[Trade], report: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "trades.csv").open("w", newline="", encoding="utf-8") as f:
        rows = [t.row() for t in trades]
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else list(Trade.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(rows)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    lines = ["# BTCUSDT Experiment Engine", "", report["methodology"], "", "## OOS ranking", "", "| Rank | Hypothesis | R | Verdict | Expectancy (R) | PF | Max DD | Trades |", "|---:|---|---:|---|---:|---:|---:|---:|"]
    for rank, row in enumerate(report["ranking"], 1):
        oos = row["periods"]["oos"]
        lines.append(f"| {rank} | {row['hypothesis_id']} v{row['version']} | {row['r_target']:.1f} | {row['verdict']} | {oos['expectancy']:.3f} | {oos['profit_factor'] or 0:.2f} | {oos['max_drawdown']:.1%} | {oos['trades']} |")
    lines += ["", "## Period metrics", ""]
    for row in report["results"]:
        lines.append(f"### {row['hypothesis_id']} v{row['version']} — {row['r_target']:.1f}R — {row['verdict']}")
        lines.append("| Period | Trades | Win rate | Gross P&L | Net P&L | Avg net/trade | Expectancy (R) | PF | Max DD | Avg R | Sharpe | Costs |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for period, m in row["periods"].items():
            lines.append(f"| {period} | {m['trades']} | {m['win_rate']:.1%} | ${m['gross_pnl']:.2f} | ${m['net_pnl']:.2f} | ${m['avg_net_profit']:.2f} | {m['expectancy']:.3f} | {m['profit_factor'] or 0:.2f} | {m['max_drawdown']:.1%} | {m['average_r']:.3f} | {m['sharpe'] or 0:.2f} | ${m['total_trading_costs']:.2f} |")
        lines.append("")
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def run(args: argparse.Namespace) -> Path:
    bars15, source15 = await fetch_bars("15m", args.bars)
    # Enough 1h history for its EMA200 and the matching oldest 15m candle.
    required_h1 = max(500, math.ceil(args.bars / 4) + 250)
    bars1h, source1h = await fetch_bars("1h", required_h1)
    costs = Costs(args.fee_rate, args.spread_bps, args.slippage_bps, 0.0)
    dev_end, oos_end = partition_index(bars15, args.development, args.oos)
    dev_end_index = int(len(bars15) * args.development)
    oos_end_index = dev_end_index + int(len(bars15) * args.oos)
    all_trades: list[Trade] = []
    results = []
    for strategy in STRATEGIES:
        signals, reasons = signals_for(strategy, bars15, bars1h)
        for target in R_TARGETS:
            # Each chronological period receives the same configured starting
            # capital. This makes its return/drawdown self-contained and keeps
            # an exhausted development account from masking OOS/paper metrics.
            period_trades = {
                "development": simulate(strategy, bars15, signals, reasons, target, costs, args.equity, args.risk_fraction, args.max_hold, 200, dev_end_index),
                "oos": simulate(strategy, bars15, signals, reasons, target, costs, args.equity, args.risk_fraction, args.max_hold, dev_end_index, oos_end_index),
                "paper": simulate(strategy, bars15, signals, reasons, target, costs, args.equity, args.risk_fraction, args.max_hold, oos_end_index, len(bars15)),
            }
            periods = {key: metrics(value) for key, value in period_trades.items()}
            row = {"hypothesis_id": strategy.id, "version": strategy.version, "name": strategy.name, "description": strategy.description, "r_target": target, "verdict": verdict(periods["development"], periods["oos"]), "periods": periods}
            results.append(row)
            all_trades.extend(trade for values in period_trades.values() for trade in values)
    # Zero/insufficient-trade rows remain reported but cannot outrank a tested
    # candidate merely because their empty expectancy is numerically zero.
    ranking = sorted(
        results,
        key=lambda x: (
            int(x["periods"]["oos"]["trades"]) >= 30,
            x["periods"]["oos"]["expectancy"],
            x["periods"]["oos"]["profit_factor"] or 0,
            x["periods"]["oos"]["max_drawdown"],
        ),
        reverse=True,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = OUTPUT_ROOT / stamp
    report = {
        "generated_at": stamp, "sources": {"15m": source15, "1h": source1h}, "symbol": "BTCUSDT", "bars_15m": len(bars15),
        "periods": {"development_end": datetime.fromtimestamp(dev_end, timezone.utc).isoformat(), "oos_end": datetime.fromtimestamp(oos_end, timezone.utc).isoformat(), "paper_end": datetime.fromtimestamp(bars15[-1].time + 900, timezone.utc).isoformat()},
        "costs": asdict(costs), "methodology": "Spot long-only. Closed 15m signals, next-15m-open entries, only last completed 1h bar, ATR14×1 stop, targets 1.5/2/2.5/3R, SL-first collision rule, 48-bar timeout, one position at a time, 0.5% equity risk/trade. Fees are 0.80% each fill; spread 2bps and slippage 3bps/side; funding is 0 for spot. Development 55%, OOS 22.5%, paper 22.5%; paper is reported but excluded from ranking/verdict.",
        "results": results, "ranking": ranking,
    }
    write_outputs(run_dir, all_trades, report)
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run immutable BTC spot hypothesis experiments.")
    parser.add_argument("--bars", type=int, default=70_000, help="Closed 15m bars to fetch (default: 70000).")
    parser.add_argument("--equity", type=float, default=10_000)
    parser.add_argument("--risk-fraction", type=float, default=0.005)
    parser.add_argument("--max-hold", type=int, default=48)
    parser.add_argument("--development", type=float, default=0.55)
    parser.add_argument("--oos", type=float, default=0.225)
    parser.add_argument("--fee-rate", type=float, default=0.008)
    parser.add_argument("--spread-bps", type=float, default=2.0)
    parser.add_argument("--slippage-bps", type=float, default=3.0)
    args = parser.parse_args()
    if args.bars < 1_000 or not 0 < args.development < 1 or not 0 < args.oos < 1 or args.development + args.oos >= 1:
        parser.error("Require --bars >=1000 and development + oos < 1.")
    return args


if __name__ == "__main__":
    output = asyncio.run(run(parse_args()))
    print(f"Experiment complete. Outputs: {output}")
