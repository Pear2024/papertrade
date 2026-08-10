r"""Study A4 BUY entries held for a fixed number of closed bars.

The study uses the production A4 EMA implementation and state-machine semantics:
the A4 entry bar fills at that bar's close.  It then sells at the close exactly
``--hold-bars`` completed 15-minute bars later, ignoring candles and A4 exits.

Example:
    .venv\Scripts\python.exe scripts\analyze_a4_first_daily_streak.py --bars 20000
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services.coach import _a4_side_ok, _ema  # noqa: E402
from app.services.coach_brain import EMA_SEPARATION_PCT_MIN  # noqa: E402

BINANCE_URLS = (
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
    "https://api.binance.com/api/v3/klines",
)
INTERVAL_SECONDS = {"15m": 900}
BANGKOK = ZoneInfo("Asia/Bangkok")


@dataclass(frozen=True)
class Bar:
    time: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class A4Entry:
    index: int
    time: int
    price: float
    side: str
    phase: str
    buy_streak: int


@dataclass(frozen=True)
class Trade:
    entry: A4Entry
    exit_time: int
    exit_price: float
    gross_pct: float
    net_pct: float


async def fetch_bars(pair: str, interval: str, target: int) -> tuple[list[Bar], str]:
    """Fetch historical public Binance candles, paginating backwards."""
    errors: list[str] = []
    for url in BINANCE_URLS:
        try:
            bars: list[Bar] = []
            end_time: int | None = None
            async with httpx.AsyncClient(timeout=30.0) as client:
                while len(bars) < target:
                    params: dict[str, str | int] = {"symbol": pair, "interval": interval, "limit": 1000}
                    if end_time is not None:
                        params["endTime"] = end_time
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    rows = response.json()
                    if not rows:
                        break
                    chunk = [
                        Bar(
                            time=int(row[0]) // 1000,
                            open=float(row[1]),
                            high=float(row[2]),
                            low=float(row[3]),
                            close=float(row[4]),
                        )
                        for row in rows
                    ]
                    bars = chunk + bars
                    end_time = int(rows[0][0]) - 1
                    if len(rows) < 1000:
                        break
                    await asyncio.sleep(0.08)
            deduped = {bar.time: bar for bar in bars}
            result = [deduped[t] for t in sorted(deduped)][-target:]
            if result:
                return result, url.split("//", 1)[1].split("/", 1)[0]
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Unable to fetch Binance candles: " + "; ".join(errors))


def a4_entry_events(bars: list[Bar], sep_min_pct: float) -> list[A4Entry]:
    """Mirror A4-only production position transitions on each closed bar."""
    closes = [bar.close for bar in bars]
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    position = "NEUTRAL"
    buy_streak = 0
    entries: list[A4Entry] = []

    for i in range(21, len(bars)):
        e9, e21 = ema9[i], ema21[i]
        if e9 is None or e21 is None:
            continue
        buy_ok, sell_ok, _ = _a4_side_ok(
            ema9=e9, ema21=e21, close=bars[i].close, sep_min=sep_min_pct
        )
        phase: str | None = None
        side: str | None = None

        if position == "NEUTRAL":
            if buy_ok:
                phase, position, side = "ENTRY_BUY", "LONG", "BUY"
            elif sell_ok:
                phase, position, side = "ENTRY_SELL", "SHORT", "SELL"
        elif position == "LONG":
            if sell_ok:
                phase, position, side = "FLIP_TO_SHORT", "SHORT", "SELL"
            elif not buy_ok:
                position = "NEUTRAL"
        elif position == "SHORT":
            if buy_ok:
                phase, position, side = "FLIP_TO_LONG", "LONG", "BUY"
            elif not sell_ok:
                position = "NEUTRAL"

        # Streak applies to the production A4 *entry-event* timeline.  Exit-only
        # bars do not reset it; a SELL entry/flip does.
        if side == "BUY":
            buy_streak += 1
            entries.append(
                A4Entry(
                    index=i,
                    time=bars[i].time,
                    price=bars[i].close,
                    side=side,
                    phase=phase or "ENTRY_BUY",
                    buy_streak=buy_streak,
                )
            )
        elif side == "SELL":
            buy_streak = 0
    return entries


def entry_fill_datetime(entry: A4Entry, interval_seconds: int) -> datetime:
    """A4 fills at the signal candle close, while Binance timestamps its open."""
    return datetime.fromtimestamp(entry.time + interval_seconds, tz=timezone.utc)


def first_buy_entry_each_day(
    entries: list[A4Entry], interval_seconds: int, tz: ZoneInfo
) -> list[A4Entry]:
    seen_days: set[str] = set()
    first: list[A4Entry] = []
    for entry in entries:
        day = entry_fill_datetime(entry, interval_seconds).astimezone(tz).date().isoformat()
        if day not in seen_days:
            seen_days.add(day)
            first.append(entry)
    return first


def after_local_time(
    entries: list[A4Entry], interval_seconds: int, tz: ZoneInfo, hour: int
) -> list[A4Entry]:
    """Strictly after HH:00 at the actual close/fill time, not candle open."""
    return [
        entry
        for entry in entries
        if (local := entry_fill_datetime(entry, interval_seconds).astimezone(tz)).hour > hour
        or (local.hour == hour and (local.minute > 0 or local.second > 0))
    ]


def make_trades(entries: list[A4Entry], bars: list[Bar], hold_bars: int, fee_rate: float) -> list[Trade]:
    trades: list[Trade] = []
    for entry in entries:
        exit_index = entry.index + hold_bars
        if exit_index >= len(bars):
            continue
        exit_bar = bars[exit_index]
        gross_return = exit_bar.close / entry.price - 1
        net_return = (exit_bar.close * (1 - fee_rate)) / (entry.price * (1 + fee_rate)) - 1
        trades.append(
            Trade(
                entry=entry,
                exit_time=exit_bar.time,
                exit_price=exit_bar.close,
                gross_pct=gross_return * 100,
                net_pct=net_return * 100,
            )
        )
    return trades


def value_or_na(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def metric_line(label: str, returns: list[float]) -> None:
    if not returns:
        print(f"{label}: no completed trades")
        return
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss else None
    compounded = (math.prod(1 + value / 100 for value in returns) - 1) * 100
    equity = peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1 + value / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
    print(
        f"{label}: win_rate={len(wins) / len(returns) * 100:.2f}% "
        f"({len(wins)}W/{len(losses)}L/{len(returns) - len(wins) - len(losses)} flat) | "
        f"avg_pnl={sum(returns) / len(returns):+.3f}% | compounded={compounded:+.3f}% | "
        f"PF={value_or_na(pf)} | max_DD={max_drawdown:.3f}%"
    )


def report_group(name: str, entries: list[A4Entry], bars: list[Bar], hold_bars: int, fee_rate: float) -> None:
    trades = make_trades(entries, bars, hold_bars, fee_rate)
    skipped = len(entries) - len(trades)
    print(f"\n--- {name} ---")
    print(f"signals={len(entries)} completed_trades={len(trades)} incomplete_last_{hold_bars}_bars={skipped}")
    metric_line("gross", [trade.gross_pct for trade in trades])
    metric_line("net  ", [trade.net_pct for trade in trades])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=20_000, help="Historical candles requested.")
    parser.add_argument("--hold-bars", type=int, default=10)
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Fee per side; 10 = 0.10%.")
    args = parser.parse_args()
    if args.bars < 100 or args.hold_bars < 1 or args.fee_bps < 0:
        parser.error("--bars >= 100, --hold-bars >= 1, and --fee-bps >= 0 are required")

    bars, source = await fetch_bars(args.symbol, args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    # Binance's newest candle can still be forming, so exclude it.
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    if len(bars) < 22 + args.hold_bars:
        raise RuntimeError("Not enough closed bars after removing the forming candle.")

    entries = a4_entry_events(bars, EMA_SEPARATION_PCT_MIN)
    interval_seconds = INTERVAL_SECONDS[args.interval]
    first_daily = first_buy_entry_each_day(entries, interval_seconds, BANGKOK)
    streak4 = [entry for entry in entries if entry.buy_streak == 4]
    after_0800_times = {
        entry.time for entry in after_local_time(entries, interval_seconds, BANGKOK, 8)
    }
    first_daily_after_0800 = [entry for entry in first_daily if entry.time in after_0800_times]
    streak4_after_0800 = [entry for entry in streak4 if entry.time in after_0800_times]
    first_daily_times = {entry.time for entry in first_daily_after_0800}
    intersection = [entry for entry in streak4_after_0800 if entry.time in first_daily_times]
    fee_rate = args.fee_bps / 10_000
    start = datetime.fromtimestamp(bars[0].time, tz=timezone.utc).isoformat()
    end = datetime.fromtimestamp(
        bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc
    ).isoformat()

    print("=== A4 BUY: FIRST BANGKOK-DAILY ENTRY + 4-BUY ENTRY STREAK, FIXED HOLD ===")
    print(
        f"source=binance:{source} pair={args.symbol} interval={args.interval} "
        f"closed_bars={len(bars)} period={start} to {end}"
    )
    print(
        "A4=EMA9>EMA21 AND close>EMA9 AND abs(EMA9-EMA21)/close*100 > "
        f"{EMA_SEPARATION_PCT_MIN:.2f}% (production _a4_side_ok)."
    )
    print(
        "Signals=production A4 BUY entry events (ENTRY_BUY or FLIP_TO_LONG), "
        "filled at that closed signal bar's close. BUY streak counts successive BUY "
        "entry events; an A4 SELL entry/flip resets it; exit-only bars do not."
    )
    print(
        f"Day=Asia/Bangkok (UTC+7), based on A4 close/fill time. Time filter is strictly "
        f"after 08:00 Bangkok (after 01:00 UTC); an 08:00-open 15m candle fills at 08:15 and qualifies."
    )
    print(
        f"Exit=close of entry index + {args.hold_bars} (exactly {args.hold_bars} completed bars "
        f"after entry); no SL/TP/A4 exit/candle-color filter. fee={args.fee_bps:.1f} bps per side."
    )
    print("Compounded return and max DD sequence overlapping study trades chronologically; not a portfolio simulation.")

    report_group(
        "MAIN: first A4 BUY entry of Bangkok day AND after 08:00 AND streak reaches 4",
        intersection,
        bars,
        args.hold_bars,
        fee_rate,
    )
    report_group(
        "SEPARATE: first A4 BUY entry of Bangkok day AND after 08:00",
        first_daily_after_0800,
        bars,
        args.hold_bars,
        fee_rate,
    )
    report_group(
        "SEPARATE: fourth successive A4 BUY entry event AND after 08:00",
        streak4_after_0800,
        bars,
        args.hold_bars,
        fee_rate,
    )
    print(
        "\nสรุป: ดู MAIN เป็นคำตอบหลัก; ถ้าจำนวนน้อยหรือไม่มี ให้ใช้สองกลุ่ม SEPARATE "
        "เป็นบริบท ไม่ควรสรุปความได้เปรียบจากตัวอย่างที่น้อยเกินไป."
    )


if __name__ == "__main__":
    asyncio.run(main())
