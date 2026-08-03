"""Compare locked Version A vs experimental Version B on the same candle data.

Does not modify locked coach_brain.py. Run:
  python scripts/compare_ab_backtest.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path  # noqa: I001

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.coach import _ema  # noqa: E402
from app.services.coach_experiment_b import (  # noqa: E402
    B_MIN_HOLD_BARS,
    B_SL_PCT,
    B_TP_PCT,
    VERSION_B_NAME,
    VERSION_B_NOTES,
)

MIN_CONF = 70
A_SL = 0.02
A_TP = 0.03
INTERVAL_SEC = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
HTF = {"5m": "1h", "15m": "1h", "1h": "4h"}
PAIRS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


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
    wins: int
    losses: int
    win_rate: float
    profit_factor: float | None
    net_pnl_pct: float
    max_dd_pct: float
    avg_win: float
    avg_loss: float
    sep_sl: int
    sep_tp: int
    sep_sell: int


async def fetch_klines(pair: str, interval: str, target: int = 3500) -> list[Bar]:
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
            await asyncio.sleep(0.12)
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
        wins=len(wins),
        losses=len(losses),
        win_rate=wr,
        profit_factor=pf,
        net_pnl_pct=net,
        max_dd_pct=max_dd,
        avg_win=(gw / len(wins)) if wins else 0.0,
        avg_loss=(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0.0,
        sep_sl=sep["SL"],
        sep_tp=sep["TP"],
        sep_sell=sep["SELL"],
    )


def simulate(
    *,
    variant: str,
    symbol: str,
    interval: str,
    candles: list[Bar],
    htf: list[Bar],
    htf_iv: str,
) -> list[dict]:
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
        # Version A technical sell
        sell_a = crossed_down and red and sell_score >= MIN_CONF
        # Version B: same cross/red/score, but HTF must no longer be bullish + min hold
        bars_held = 0 if open_t is None else (i - open_t["entry_idx"])
        sell_b = (
            crossed_down
            and red
            and sell_score >= MIN_CONF
            and hb is not True
            and bars_held >= B_MIN_HOLD_BARS
        )
        sell_ok = sell_a if variant == "A" else sell_b
        iso = datetime.fromtimestamp(c.time, tz=timezone.utc).isoformat()

        if open_t is not None:
            sl_hit = c.low <= open_t["sl"]
            tp_hit = c.high >= open_t["tp"]
            if sl_hit and tp_hit:
                exit_price, reason = open_t["sl"], "SL"
            elif sl_hit:
                exit_price, reason = open_t["sl"], "SL"
            elif tp_hit:
                exit_price, reason = open_t["tp"], "TP"
            elif sell_ok:
                exit_price, reason = c.close, "SELL"
            else:
                exit_price, reason = None, None
            if reason:
                pnl = (exit_price / open_t["entry"] - 1) * 100
                trades.append(
                    {
                        "symbol": symbol,
                        "iv": interval,
                        "entry": open_t["time"],
                        "exit": iso,
                        "result": reason,
                        "pnl": pnl,
                    }
                )
                open_t = None
                continue

        if open_t is None and buy_ok:
            open_t = {
                "time": iso,
                "entry_idx": i,
                "entry": c.close,
                "sl": c.close * (1 - sl_pct),
                "tp": c.close * (1 + tp_pct),
            }
    return trades


def print_metrics(m: Metrics) -> None:
    pf = f"{m.profit_factor:.3f}" if m.profit_factor is not None else "n/a"
    print(
        f"{m.name}: n={m.trades} win_rate={m.win_rate:.2f}% "
        f"pf={pf} net={m.net_pnl_pct:.2f}% max_dd={m.max_dd_pct:.2f}% "
        f"avg_win={m.avg_win:.3f}% avg_loss={m.avg_loss:.3f}% "
        f"sep SL/TP/SELL={m.sep_sl}/{m.sep_tp}/{m.sep_sell}"
    )


async def main() -> None:
    print("=== A (LOCKED) vs B (EXPERIMENTAL) SAME-DATA BACKTEST ===")
    print(VERSION_B_NAME)
    print(VERSION_B_NOTES)
    print("---")
    trades_a: list[dict] = []
    trades_b: list[dict] = []
    cache: dict[tuple[str, str], tuple[list[Bar], list[Bar], str]] = {}

    for symbol, pair in PAIRS.items():
        for interval in ("15m", "1h", "5m"):
            htf_iv = HTF[interval]
            key = (pair, interval)
            if key not in cache:
                target = 2500 if interval == "1h" else 3500
                candles = await fetch_klines(pair, interval, target)
                htf = await fetch_klines(pair, htf_iv, 2500)
                cache[key] = (candles, htf, htf_iv)
                print(f"loaded {symbol} {interval} bars={len(candles)} htf={len(htf)}")
            candles, htf, htf_iv = cache[key]
            trades_a.extend(
                simulate(
                    variant="A",
                    symbol=symbol,
                    interval=interval,
                    candles=candles,
                    htf=htf,
                    htf_iv=htf_iv,
                )
            )
            trades_b.extend(
                simulate(
                    variant="B",
                    symbol=symbol,
                    interval=interval,
                    candles=candles,
                    htf=htf,
                    htf_iv=htf_iv,
                )
            )

    ma = metrics_from("A_LOCKED", trades_a)
    mb = metrics_from("B_EXPERIMENT", trades_b)
    print("--- RESULTS ---")
    print_metrics(ma)
    print_metrics(mb)

    # BTC 15m only (primary focus)
    a15 = metrics_from(
        "A_BTC_15m",
        [t for t in trades_a if t["symbol"] == "BTC" and t["iv"] == "15m"],
    )
    b15 = metrics_from(
        "B_BTC_15m",
        [t for t in trades_b if t["symbol"] == "BTC" and t["iv"] == "15m"],
    )
    print("--- BTC 15m FOCUS ---")
    print_metrics(a15)
    print_metrics(b15)

    # Evidence gate
    better = 0
    checks = []
    if mb.trades >= 50 and ma.trades >= 50:
        checks.append(("sample_size_ok", True))
    else:
        checks.append(("sample_size_ok", False))
    if mb.profit_factor is not None and ma.profit_factor is not None:
        checks.append(("pf_better", mb.profit_factor > ma.profit_factor))
        if mb.profit_factor > ma.profit_factor:
            better += 1
    if mb.net_pnl_pct > ma.net_pnl_pct:
        better += 1
        checks.append(("net_better", True))
    else:
        checks.append(("net_better", False))
    if mb.max_dd_pct > ma.max_dd_pct:  # less negative is better
        better += 1
        checks.append(("dd_better", True))
    else:
        checks.append(("dd_better", False))
    if mb.win_rate > ma.win_rate:
        better += 1
        checks.append(("wr_better", True))
    else:
        checks.append(("wr_better", False))

    clear = better >= 3 and checks[0][1] and mb.profit_factor and mb.profit_factor > 1.0
    print("--- EVIDENCE ---")
    for k, v in checks:
        print(f"{k}={v}")
    print(f"score_b_better_metrics={better}/4")
    print(
        "conclusion="
        + (
            "B_HAS_CLEAR_EDGE_OVER_A"
            if clear
            else "KEEP_A_LOCKED_NO_AUTO_PROMOTE_B"
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
