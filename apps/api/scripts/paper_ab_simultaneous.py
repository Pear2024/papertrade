"""Simultaneous paper A vs B on the same markets and bar times.

Uses identical candle streams for both versions (paper-style bookkeeping).
Does NOT modify locked coach_brain.py / Version A production code.

Run:
  python scripts/paper_ab_simultaneous.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.coach import _ema  # noqa: E402
from app.services.coach_baseline import promotion_status  # noqa: E402
from app.services.coach_experiment_b import (  # noqa: E402
    B_MIN_HOLD_BARS,
    B_SL_PCT,
    B_TP_PCT,
    VERSION_B_NOTES,
)

MIN_CONF = 70
A_SL = 0.02
A_TP = 0.03
FEE = 0.001  # paper fee 0.10%
START_CASH = 100.0
RISK_PCT = 0.02
INTERVAL_SEC = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
HTF = {"5m": "1h", "15m": "1h", "1h": "4h"}
PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
MARKETS = [
    ("BTC", "15m"),
    ("BTC", "1h"),
    ("BTC", "5m"),
    ("ETH", "15m"),
    ("ETH", "1h"),
    ("ETH", "5m"),
    ("SOL", "15m"),
    ("SOL", "1h"),
    ("SOL", "5m"),
]


@dataclass
class Bar:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Metrics:
    name: str
    trades: int
    win_rate: float
    profit_factor: float | None
    net_pnl: float
    max_dd: float
    avg_win: float
    avg_loss: float
    sep_sl: int
    sep_tp: int
    sep_sell: int


async def fetch_klines(pair: str, interval: str, target: int = 2500) -> list[Bar]:
    url = "https://data-api.binance.vision/api/v3/klines"
    out: list[Bar] = []
    end = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while len(out) < target:
            params: dict = {"symbol": pair, "interval": interval, "limit": 1000}
            if end is not None:
                params["endTime"] = end
            r = await client.get(url, params=params)
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            chunk = [
                Bar(
                    int(row[0]) // 1000,
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                )
                for row in rows
            ]
            out = chunk + out
            end = int(rows[0][0]) - 1
            if len(rows) < 1000:
                break
            await asyncio.sleep(0.1)
    seen: set[int] = set()
    uniq: list[Bar] = []
    for b in out:
        if b.time in seen:
            continue
        seen.add(b.time)
        uniq.append(b)
    uniq.sort(key=lambda x: x.time)
    return uniq[-target:]


def closed(bar: Bar, interval: str, now_ts: int) -> bool:
    return now_ts >= bar.time + INTERVAL_SEC[interval]


def metrics_from(name: str, trades: list[dict]) -> Metrics:
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    wr = (len(wins) / n * 100) if n else 0.0
    gw = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = (gw / gl) if gl > 0 else None
    net = sum(t["pnl"] for t in trades)
    eq = peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit"]):
        eq += t["pnl"]
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    sep = {"SL": 0, "TP": 0, "SELL": 0}
    for t in trades:
        sep[t["result"]] += 1
    return Metrics(
        name=name,
        trades=n,
        win_rate=wr,
        profit_factor=pf,
        net_pnl=net,
        max_dd=max_dd,
        avg_win=(gw / len(wins)) if wins else 0.0,
        avg_loss=(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0.0,
        sep_sl=sep["SL"],
        sep_tp=sep["TP"],
        sep_sell=sep["SELL"],
    )


def simulate_paper(
    *,
    variant: str,
    symbol: str,
    interval: str,
    candles: list[Bar],
    htf: list[Bar],
    htf_iv: str,
) -> list[dict]:
    """Paper-style simultaneous book: cash + one position, fee on entry/exit."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    he9 = _ema([c.close for c in htf], 9)
    he21 = _ema([c.close for c in htf], 21)
    e9 = _ema([c.close for c in candles], 9)
    e21 = _ema([c.close for c in candles], 21)
    sl_pct = A_SL if variant == "A" else B_SL_PCT
    tp_pct = A_TP if variant == "A" else B_TP_PCT

    def htf_bull(ts: int) -> bool | None:
        elig = [i for i, c in enumerate(htf) if c.time <= ts and closed(c, htf_iv, now_ts)]
        if not elig:
            return None
        i = elig[-1]
        if he9[i] is None or he21[i] is None:
            return None
        return he9[i] > he21[i] and htf[i].close > he9[i]

    trades: list[dict] = []
    cash = START_CASH
    open_t: dict | None = None

    for i in range(1, len(candles)):
        c = candles[i]
        if not closed(c, interval, now_ts):
            continue
        if e9[i] is None or e21[i] is None or e9[i - 1] is None or e21[i - 1] is None:
            continue
        green = c.close >= c.open
        red = c.close < c.open
        vols = [x.volume for x in candles[max(0, i - 20) : i]]
        vol_avg = (sum(vols) / len(vols)) if vols else None
        volume_ok = vol_avg is not None and vol_avg > 0 and c.volume > vol_avg
        crossed_up = e9[i - 1] <= e21[i - 1] and e9[i] > e21[i]
        crossed_down = e9[i - 1] >= e21[i - 1] and e9[i] < e21[i]
        hb = htf_bull(c.time)
        buy_score = 30 * crossed_up + 20 * green + 25 * volume_ok + 25 * (hb is True)
        sell_score = 40 * crossed_down + 30 * red + 30 * volume_ok
        buy_ok = (
            crossed_up
            and green
            and volume_ok
            and hb is True
            and buy_score >= MIN_CONF
        )
        sell_a = crossed_down and red and sell_score >= MIN_CONF
        bars_held = 0 if open_t is None else (i - open_t["entry_idx"])
        sell_b = (
            crossed_down
            and red
            and sell_score >= MIN_CONF
            and bars_held >= B_MIN_HOLD_BARS
            and hb is not True
        )
        sell_ok = sell_a if variant == "A" else sell_b

        # Manage open paper position with same bar high/low (SL/TP first).
        if open_t is not None:
            entry = open_t["entry"]
            qty = open_t["qty"]
            sl = open_t["sl"]
            tp = open_t["tp"]
            exit_px = None
            result = None
            if c.low <= sl:
                exit_px = sl
                result = "SL"
            elif c.high >= tp:
                exit_px = tp
                result = "TP"
            elif sell_ok:
                exit_px = c.close
                result = "SELL"
            if exit_px is not None and result is not None:
                proceeds = qty * exit_px * (1 - FEE)
                cost = open_t["cost"]
                pnl = proceeds - cost
                cash += proceeds
                trades.append(
                    {
                        "symbol": symbol,
                        "iv": interval,
                        "pnl": pnl,
                        "pnl_pct": (exit_px / entry - 1) * 100,
                        "exit": c.time,
                        "result": result,
                    }
                )
                open_t = None

        if open_t is None and buy_ok:
            risk_budget = cash * RISK_PCT
            stake = min(risk_budget / sl_pct, cash * 0.99)
            if stake < 0.5:
                continue
            entry = c.close
            fee = stake * FEE
            qty = (stake - fee) / entry if entry > 0 else 0
            if qty <= 0:
                continue
            cash -= stake
            open_t = {
                "entry": entry,
                "entry_idx": i,
                "qty": qty,
                "cost": stake,
                "sl": entry * (1 - sl_pct),
                "tp": entry * (1 + tp_pct),
            }

    return trades


def print_m(m: Metrics) -> None:
    pf = f"{m.profit_factor:.3f}" if m.profit_factor is not None else "n/a"
    print(
        f"{m.name}: n={m.trades} win_rate={m.win_rate:.2f}% pf={pf} "
        f"net=${m.net_pnl:.2f} max_dd=${m.max_dd:.2f} "
        f"avg_win=${m.avg_win:.2f} avg_loss=${m.avg_loss:.2f} "
        f"sep SL/TP/SELL={m.sep_sl}/{m.sep_tp}/{m.sep_sell}"
    )


def b_beats(a: Metrics, b: Metrics) -> bool:
    if a.trades < 5 or b.trades < 5:
        return False
    score = 0
    if b.win_rate > a.win_rate:
        score += 1
    if (b.profit_factor or 0) > (a.profit_factor or 0):
        score += 1
    if b.net_pnl > a.net_pnl:
        score += 1
    if b.max_dd > a.max_dd:  # less negative / closer to 0
        score += 1
    return score >= 3


async def main() -> None:
    print("=== SIMULTANEOUS PAPER A (LOCKED) vs B (EXPERIMENT) ===")
    print("Same markets, same bar times, paper fee 0.10%, start $100.")
    print("Main strategy remains Version A. B is research-only.")
    print(VERSION_B_NOTES)
    print("---")

    cache: dict[tuple[str, str], list[Bar]] = {}
    all_a: list[dict] = []
    all_b: list[dict] = []
    market_wins_b = 0
    markets_tested = 0

    for symbol, interval in MARKETS:
        htf_iv = HTF[interval]
        key = (symbol, interval)
        hkey = (symbol, htf_iv)
        if key not in cache:
            cache[key] = await fetch_klines(PAIRS[symbol], interval, 2500)
            print(f"loaded {symbol} {interval} bars={len(cache[key])}")
        if hkey not in cache:
            cache[hkey] = await fetch_klines(PAIRS[symbol], htf_iv, 2000)
            print(f"loaded {symbol} {htf_iv} bars={len(cache[hkey])}")

        ta = simulate_paper(
            variant="A",
            symbol=symbol,
            interval=interval,
            candles=cache[key],
            htf=cache[hkey],
            htf_iv=htf_iv,
        )
        tb = simulate_paper(
            variant="B",
            symbol=symbol,
            interval=interval,
            candles=cache[key],
            htf=cache[hkey],
            htf_iv=htf_iv,
        )
        for t in ta:
            t["market"] = f"{symbol}-{interval}"
        for t in tb:
            t["market"] = f"{symbol}-{interval}"
        all_a.extend(ta)
        all_b.extend(tb)

        ma = metrics_from(f"A_{symbol}_{interval}", ta)
        mb = metrics_from(f"B_{symbol}_{interval}", tb)
        print_m(ma)
        print_m(mb)
        if ma.trades >= 5 and mb.trades >= 5:
            markets_tested += 1
            if b_beats(ma, mb):
                market_wins_b += 1
                print(f"  -> B better on {symbol} {interval}")
            else:
                print(f"  -> A holds or mixed on {symbol} {interval}")
        else:
            print(f"  -> sample too small on {symbol} {interval}")

    print("--- COMBINED (all markets, same-time streams) ---")
    ma = metrics_from("A_PAPER_ALL", all_a)
    mb = metrics_from("B_PAPER_ALL", all_b)
    print_m(ma)
    print_m(mb)

    promo = promotion_status(
        paper_b_better_markets=market_wins_b,
        markets_tested=markets_tested,
    )
    print("--- EVIDENCE / BASELINE ---")
    print(f"markets_tested={markets_tested}")
    print(f"b_better_markets={market_wins_b}")
    print(f"promotion={promo}")
    print(f"active_baseline=A (LOCKED — not auto-changed)")
    if promo["evidence_clear_for_human_review"]:
        print(
            "conclusion=B_HAS_MULTI_MARKET_PAPER_EDGE — "
            "human may carefully promote to a NEW baseline; do not edit lock in place."
        )
    else:
        print("conclusion=KEEP_A_LOCKED_NO_AUTO_PROMOTE_B")


if __name__ == "__main__":
    asyncio.run(main())
