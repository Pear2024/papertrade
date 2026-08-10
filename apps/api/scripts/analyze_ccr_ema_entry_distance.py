r"""Compare EMA9/EMA21 entry distances for CCR 2-bar-hold winners and losers.

CCR(n) confirms at a candle close, enters at the next candle's open, and exits
at the close of the following candle.  EMAs at entry use only the confirmation
close (the latest data available before that next open), avoiding look-ahead.

Example:
  .venv\Scripts\python.exe scripts\analyze_ccr_ema_entry_distance.py --symbol BTC --interval 15m
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from analyze_ccr_exits import (
    BINANCE_PAIRS,
    INTERVAL_SECONDS,
    Bar,
    fetch_bars,
    make_trade,
)
from app.services.coach import _ema
from app.services.coach_ccr import CCR_CONSECUTIVE_DEFAULT, OHLC, clamp_ccr_consecutive, ccr_buy_at


@dataclass(frozen=True)
class EntryObservation:
    gross_pct: float
    net_pct: float
    dist_ema9_pct: float
    dist_ema21_pct: float
    ema_gap_pct: float
    above_ema9: bool
    above_ema21: bool
    bucket: str
    confirmation_body_pct: float
    confirmation_range_pct: float
    confirmation_prior_high_margin_pct: float
    entry_gap_from_confirmation_pct: float
    volume_vs_avg20: float | None
    bearish_streak: int
    entry_above_prior_n_low_pct: float
    entry_above_20bar_low_pct: float
    ema9_below_ema21: bool
    ema9_slope_3bar_pct: float
    ema21_slope_3bar_pct: float
    entry_hour_utc: int
    mfe_pct: float
    mae_pct: float


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile, matching the common spreadsheet method."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    index = (len(ordered) - 1) * p
    lo, hi = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def pct(value: float) -> str:
    return f"{value:+.3f}%"


def stat_values(values: list[float]) -> tuple[float, float, float, float]:
    return sum(values) / len(values), percentile(values, .50), percentile(values, .25), percentile(values, .75)


def actual_bearish_streak(bars: list[Bar], confirmation_idx: int) -> int:
    """Count the full bearish run immediately before the confirmation candle."""
    streak = 0
    for idx in range(confirmation_idx - 1, -1, -1):
        if bars[idx].close >= bars[idx].open:
            break
        streak += 1
    return streak


def build_observations(
    bars: list[Bar], consecutive: int, fee_rate: float, hold_bars: int
) -> list[EntryObservation]:
    """Return non-overlapping CCR trades with causally available EMA values."""
    closes = [bar.close for bar in bars]
    ema9, ema21 = _ema(closes, 9), _ema(closes, 21)
    ohlc = [OHLC(bar.open, bar.high, bar.low, bar.close) for bar in bars]
    observations: list[EntryObservation] = []
    confirmation_idx = 0

    while confirmation_idx + hold_bars < len(bars):
        if not ccr_buy_at(ohlc, confirmation_idx, consecutive):
            confirmation_idx += 1
            continue

        entry_idx = confirmation_idx + 1
        exit_idx = entry_idx + hold_bars - 1
        e9, e21 = ema9[confirmation_idx], ema21[confirmation_idx]
        # A CCR confirmation needs only 4 bars, but EMA21 first exists at index 20.
        if e9 is not None and e21 is not None:
            entry = bars[entry_idx].open
            result = make_trade(entry, bars[exit_idx].close, fee_rate)
            low_ema, high_ema = min(e9, e21), max(e9, e21)
            confirmation = bars[confirmation_idx]
            previous = bars[confirmation_idx - 1]
            prior_n_lows = [bar.low for bar in bars[confirmation_idx - consecutive : confirmation_idx]]
            prior_20_lows = [bar.low for bar in bars[max(0, confirmation_idx - 20) : confirmation_idx]]
            previous_volumes = [bar.volume for bar in bars[max(0, confirmation_idx - 20) : confirmation_idx]]
            avg_volume = sum(previous_volumes) / len(previous_volumes) if previous_volumes else 0.0
            e9_3 = ema9[confirmation_idx - 3]
            e21_3 = ema21[confirmation_idx - 3]
            held_bars = bars[entry_idx : exit_idx + 1]
            bucket = (
                "below both"
                if entry < low_ema
                else "above both"
                if entry > high_ema
                else "between"
            )
            observations.append(
                EntryObservation(
                    gross_pct=result.gross * 100,
                    net_pct=result.net * 100,
                    dist_ema9_pct=(entry - e9) / e9 * 100,
                    dist_ema21_pct=(entry - e21) / e21 * 100,
                    ema_gap_pct=(e9 - e21) / e21 * 100,
                    above_ema9=entry > e9,
                    above_ema21=entry > e21,
                    bucket=bucket,
                    confirmation_body_pct=(confirmation.close - confirmation.open) / confirmation.open * 100,
                    confirmation_range_pct=(confirmation.high - confirmation.low) / confirmation.open * 100,
                    confirmation_prior_high_margin_pct=(confirmation.close - previous.high) / previous.high * 100,
                    entry_gap_from_confirmation_pct=(entry - confirmation.close) / confirmation.close * 100,
                    volume_vs_avg20=confirmation.volume / avg_volume if avg_volume else None,
                    bearish_streak=actual_bearish_streak(bars, confirmation_idx),
                    entry_above_prior_n_low_pct=(entry - min(prior_n_lows)) / min(prior_n_lows) * 100,
                    entry_above_20bar_low_pct=(entry - min(prior_20_lows)) / min(prior_20_lows) * 100,
                    ema9_below_ema21=e9 < e21,
                    ema9_slope_3bar_pct=(e9 - e9_3) / e9_3 * 100 if e9_3 else 0.0,
                    ema21_slope_3bar_pct=(e21 - e21_3) / e21_3 * 100 if e21_3 is not None else 0.0,
                    entry_hour_utc=datetime.fromtimestamp(bars[entry_idx].time, tz=timezone.utc).hour,
                    mfe_pct=(max(bar.high for bar in held_bars) - entry) / entry * 100,
                    mae_pct=(min(bar.low for bar in held_bars) - entry) / entry * 100,
                )
            )

        # Match analyze_ccr_exits.py: do not overlap positions.
        confirmation_idx = exit_idx
    return observations


def print_comparison(wins: list[EntryObservation], losses: list[EntryObservation]) -> None:
    print(f"\n--- GROSS WIN (n={len(wins)}) vs GROSS LOSS (n={len(losses)}) ---")
    print("metric             WIN: mean  median     p25     p75 | LOSS: mean  median     p25     p75")
    for label, field in (
        ("Entry vs EMA9", "dist_ema9_pct"),
        ("Entry vs EMA21", "dist_ema21_pct"),
        ("EMA9 vs EMA21", "ema_gap_pct"),
    ):
        win_stats = stat_values([getattr(row, field) for row in wins])
        loss_stats = stat_values([getattr(row, field) for row in losses])
        win_formatted = " ".join(f"{pct(value):>8}" for value in win_stats)
        loss_formatted = " ".join(f"{pct(value):>8}" for value in loss_stats)
        print(f"{label:<18} {win_formatted} | {loss_formatted}")
    print(
        f"Above EMA9         WIN {sum(row.above_ema9 for row in wins) / len(wins) * 100:5.1f}%"
        f"                 | LOSS {sum(row.above_ema9 for row in losses) / len(losses) * 100:5.1f}%"
    )
    print(
        f"Above EMA21        WIN {sum(row.above_ema21 for row in wins) / len(wins) * 100:5.1f}%"
        f"                 | LOSS {sum(row.above_ema21 for row in losses) / len(losses) * 100:5.1f}%"
    )
    for bucket in ("below both", "between", "above both"):
        print(
            f"{bucket.title():<18} WIN {sum(row.bucket == bucket for row in wins) / len(wins) * 100:5.1f}%"
            f"                 | LOSS {sum(row.bucket == bucket for row in losses) / len(losses) * 100:5.1f}%"
        )


def print_below_both_comparison(wins: list[EntryObservation], losses: list[EntryObservation]) -> None:
    """Compare only the setup the user circled, using entry-time information."""
    print(f"\n=== BELOW BOTH EMAs: GROSS WIN (n={len(wins)}) vs GROSS LOSS (n={len(losses)}) ===")
    print("metric                         WIN mean / median       | LOSS mean / median")
    fields = (
        ("Entry below EMA9 %", "dist_ema9_pct"),
        ("Entry below EMA21 %", "dist_ema21_pct"),
        ("EMA9 - EMA21 gap %", "ema_gap_pct"),
        ("Confirmation body %", "confirmation_body_pct"),
        ("Confirmation range / ATR proxy %", "confirmation_range_pct"),
        ("Close above prior high %", "confirmation_prior_high_margin_pct"),
        ("Entry gap from confirmation %", "entry_gap_from_confirmation_pct"),
        ("Volume / prior 20 average", "volume_vs_avg20"),
        ("Actual bearish streak", "bearish_streak"),
        ("Entry above prior N low %", "entry_above_prior_n_low_pct"),
        ("Entry above prior 20 low %", "entry_above_20bar_low_pct"),
        ("EMA9 3-bar slope %", "ema9_slope_3bar_pct"),
        ("EMA21 3-bar slope %", "ema21_slope_3bar_pct"),
    )
    for label, field in fields:
        win_values = [getattr(row, field) for row in wins if getattr(row, field) is not None]
        loss_values = [getattr(row, field) for row in losses if getattr(row, field) is not None]
        if not win_values or not loss_values:
            continue
        win_mean, win_median, *_ = stat_values(win_values)
        loss_mean, loss_median, *_ = stat_values(loss_values)
        suffix = "x" if field == "volume_vs_avg20" else "" if field == "bearish_streak" else "%"
        print(
            f"{label:<31} {win_mean:+.3f}{suffix} / {win_median:+.3f}{suffix}"
            f" | {loss_mean:+.3f}{suffix} / {loss_median:+.3f}{suffix}"
        )

    print("\nrate / threshold                    WIN                  | LOSS")
    rate_tests = (
        ("EMA9 < EMA21 (bearish stack)", lambda row: row.ema9_below_ema21),
        ("Entry <= -0.15% below EMA21", lambda row: row.dist_ema21_pct <= -0.15),
        ("Entry <= -0.25% below EMA21", lambda row: row.dist_ema21_pct <= -0.25),
        ("Volume > 1.0x prior 20", lambda row: row.volume_vs_avg20 is not None and row.volume_vs_avg20 > 1),
        ("Confirmation range >= 0.40%", lambda row: row.confirmation_range_pct >= 0.40),
        ("Entry gap-up from confirm", lambda row: row.entry_gap_from_confirmation_pct > 0),
        ("Extra bearish candles (>= 4)", lambda row: row.bearish_streak >= 4),
        ("EMA9 slope down over 3 bars", lambda row: row.ema9_slope_3bar_pct < 0),
        ("EMA21 slope down over 3 bars", lambda row: row.ema21_slope_3bar_pct < 0),
    )
    for label, test in rate_tests:
        print(
            f"{label:<37} {sum(test(row) for row in wins) / len(wins) * 100:5.1f}%"
            f" ({sum(test(row) for row in wins):>2}/{len(wins):>2})"
            f" | {sum(test(row) for row in losses) / len(losses) * 100:5.1f}%"
            f" ({sum(test(row) for row in losses):>2}/{len(losses):>2})"
        )

    def hour_bucket(row: EntryObservation) -> int:
        return row.entry_hour_utc // 4

    print("\nentry hour UTC bucket                 WIN                  | LOSS")
    for bucket in range(6):
        label = f"{bucket * 4:02d}:00-{bucket * 4 + 3:02d}:59"
        win_count = sum(hour_bucket(row) == bucket for row in wins)
        loss_count = sum(hour_bucket(row) == bucket for row in losses)
        print(
            f"{label:<37} {win_count / len(wins) * 100:5.1f}% ({win_count:>2}/{len(wins):>2})"
            f" | {loss_count / len(losses) * 100:5.1f}% ({loss_count:>2}/{len(losses):>2})"
        )

    print("\npost-entry path (descriptive only; not a usable entry filter)")
    for label, field in (("MFE within 2-bar hold %", "mfe_pct"), ("MAE within 2-bar hold %", "mae_pct")):
        win_mean, win_median, *_ = stat_values([getattr(row, field) for row in wins])
        loss_mean, loss_median, *_ = stat_values([getattr(row, field) for row in losses])
        print(
            f"{label:<37} {win_mean:+.3f}% / {win_median:+.3f}%"
            f" | {loss_mean:+.3f}% / {loss_median:+.3f}%"
        )


def print_in_sample_filter(name: str, observations: list[EntryObservation]) -> None:
    """Show a deliberately simple in-sample filter without claiming validation."""
    if not observations:
        print(f"{name:<55} no trades")
        return
    gross = [row.gross_pct / 100 for row in observations]
    compounded = 1.0
    for value in gross:
        compounded *= 1 + value
    wins = sum(value > 0 for value in gross)
    print(
        f"{name:<55} n={len(gross):>2}  WR={wins / len(gross) * 100:5.1f}%"
        f"  avg={sum(gross) / len(gross) * 100:+.3f}%  compounded={((compounded - 1) * 100):+.2f}%"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=BINANCE_PAIRS, default="BTC")
    parser.add_argument("--interval", choices=INTERVAL_SECONDS, default="15m")
    parser.add_argument("--bars", type=int, default=10_000)
    parser.add_argument("--consecutive", type=int, default=CCR_CONSECUTIVE_DEFAULT)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    args = parser.parse_args()
    if args.bars < 100 or args.fee_bps < 0:
        parser.error("--bars must be >= 100 and --fee-bps must be >= 0")

    bars, source = await fetch_bars(BINANCE_PAIRS[args.symbol], args.interval, args.bars)
    now = int(datetime.now(timezone.utc).timestamp())
    bars = [bar for bar in bars if bar.time + INTERVAL_SECONDS[args.interval] <= now]
    observations = build_observations(
        bars, clamp_ccr_consecutive(args.consecutive), args.fee_bps / 10_000, hold_bars=2
    )
    wins = [row for row in observations if row.gross_pct > 0]
    losses = [row for row in observations if row.gross_pct < 0]
    flats = [row for row in observations if row.gross_pct == 0]
    net_wins = [row for row in observations if row.net_pct > 0]
    start = datetime.fromtimestamp(bars[0].time, tz=timezone.utc).date()
    end = datetime.fromtimestamp(bars[-1].time + INTERVAL_SECONDS[args.interval], tz=timezone.utc).date()

    print("=== CCR 2-BAR HOLD: ENTRY DISTANCE TO EMA ===")
    print(
        f"source=binance:{source} pair={BINANCE_PAIRS[args.symbol]} interval={args.interval} "
        f"bars={len(bars)} period={start} to {end}; CCR(n={args.consecutive}); fee={args.fee_bps:.1f} bps/side"
    )
    print("Rule: confirmation close -> enter next open -> exit close +1.")
    print("EMA snapshot is the confirmation-close EMA (known before entry open; no look-ahead).")
    print(
        f"Completed trades with EMA21={len(observations)}; gross wins={len(wins)} "
        f"({len(wins) / len(observations) * 100:.1f}%); gross losses={len(losses)} "
        f"({len(losses) / len(observations) * 100:.1f}%); flat={len(flats)}."
    )
    print(f"Net-of-fee wins={len(net_wins)} ({len(net_wins) / len(observations) * 100:.1f}%).")
    if wins and losses:
        print_comparison(wins, losses)
    below_both = [row for row in observations if row.bucket == "below both"]
    below_wins = [row for row in below_both if row.gross_pct > 0]
    below_losses = [row for row in below_both if row.gross_pct < 0]
    if below_wins and below_losses:
        print_below_both_comparison(below_wins, below_losses)
        print("\n=== IN-SAMPLE ONLY: FILTER APPLIED TO THE FULL CCR SAMPLE ===")
        print_in_sample_filter("All CCR 2-bar trades", observations)
        print_in_sample_filter("Below both EMAs", below_both)
        print_in_sample_filter(
            "Below both + confirmation volume > prior-20 average",
            [
                row
                for row in observations
                if row.bucket == "below both"
                and row.volume_vs_avg20 is not None
                and row.volume_vs_avg20 > 1
            ],
        )
        print_in_sample_filter(
            "Below both + actual bearish streak >= 4",
            [row for row in observations if row.bucket == "below both" and row.bearish_streak >= 4],
        )
        print_in_sample_filter(
            "Below both + entry <= -0.15% below EMA21 + EMA9 < EMA21",
            [
                row
                for row in observations
                if row.bucket == "below both"
                and row.dist_ema21_pct <= -0.15
                and row.ema9_below_ema21
            ],
        )


if __name__ == "__main__":
    asyncio.run(main())
