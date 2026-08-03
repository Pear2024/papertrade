"""Import Google Chat alert history with seq_from_entry + pnl vs ENTRY."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.money import money, to_decimal
from app.models import CoachSignalEvent

TZ = timezone(timedelta(hours=-7))

# Every Chat alert (deduped by bar). Keep ALL for “Nth alert still profitable?” analysis.
RAW: list[tuple[str, str, str, str, str]] = [
    ("2026-08-01T12:00:00", "SELL", "62390.01", "62709.42", "62859.66"),
    ("2026-08-01T12:15:00", "SELL", "62578.00", "62679.94", "62832.40"),
    ("2026-08-01T12:30:00", "SELL", "62580.01", "62660.36", "62809.67"),
    ("2026-08-01T12:45:00", "SELL", "62548.45", "62633.18", "62783.43"),
    ("2026-08-01T13:00:00", "SELL", "62472.00", "62600.94", "62755.12"),
    ("2026-08-01T13:15:00", "SELL", "62529.81", "62586.71", "62734.63"),
    ("2026-08-01T19:15:00", "SELL", "62558.00", "62580.97", "62718.58"),
    ("2026-08-01T19:30:00", "BUY", "63366.60", "62966.67", "62856.33"),
    ("2026-08-01T19:45:00", "BUY", "63353.90", "63046.29", "62902.69"),
    ("2026-08-01T20:00:00", "BUY", "63315.80", "63099.13", "62939.70"),
    ("2026-08-01T20:15:00", "BUY", "63377.80", "63154.87", "62979.53"),
    ("2026-08-01T20:30:00", "BUY", "63346.00", "63193.09", "63012.84"),
    ("2026-08-01T20:45:00", "BUY", "63362.80", "63227.04", "63044.66"),
    ("2026-08-01T21:00:00", "BUY", "63429.80", "63267.59", "63079.67"),
    ("2026-08-01T21:15:00", "BUY", "63392.70", "63292.61", "63108.13"),
    ("2026-08-01T21:30:00", "BUY", "63475.10", "63329.11", "63141.49"),
    ("2026-08-01T21:45:00", "BUY", "63472.30", "63357.75", "63171.56"),
    ("2026-08-01T22:00:00", "BUY", "63455.10", "63377.22", "63197.34"),
    ("2026-08-01T22:15:00", "BUY", "63523.90", "63406.55", "63227.02"),
    ("2026-08-01T22:30:00", "BUY", "63413.70", "63406.53", "63243.24"),
    ("2026-08-01T23:30:00", "BUY", "63427.30", "63397.84", "63299.35"),
    ("2026-08-01T23:45:00", "BUY", "63423.40", "63402.84", "63310.57"),
    ("2026-08-02T00:00:00", "BUY", "63425.70", "63408.45", "63321.58"),
    ("2026-08-02T00:15:00", "BUY", "63414.60", "63408.96", "63329.66"),
    ("2026-08-02T00:30:00", "BUY", "63414.90", "63410.15", "63337.41"),
    ("2026-08-02T00:45:00", "BUY", "63471.40", "63422.40", "63349.59"),
    ("2026-08-02T01:00:00", "BUY", "63427.40", "63423.40", "63356.67"),
    ("2026-08-02T04:15:00", "SELL", "63072.80", "63147.35", "63213.16"),
    ("2026-08-02T04:30:00", "SELL", "63085.30", "63138.44", "63203.35"),
    ("2026-08-02T04:45:00", "SELL", "63049.70", "63120.71", "63189.39"),
    ("2026-08-02T05:00:00", "SELL", "62965.80", "63089.97", "63169.19"),
]


def _pnl(side: str, entry_px: Decimal, px: Decimal) -> tuple[Decimal, bool]:
    if entry_px <= 0:
        return money(0), False
    if side == "BUY":
        pct = (px - entry_px) / entry_px * Decimal("100")
    else:
        pct = (entry_px - px) / entry_px * Decimal("100")
    return money(pct), pct > 0


def main() -> None:
    db = SessionLocal()
    inserted = 0
    updated = 0
    prev_side: str | None = None
    seq = 0
    entry_px: Decimal | None = None
    try:
        for close_iso, side, price_s, ema9_s, ema21_s in RAW:
            close_local = datetime.fromisoformat(close_iso).replace(tzinfo=TZ)
            bar_open = int(close_local.timestamp()) - 15 * 60
            price = money(Decimal(price_s))
            ema9 = money(Decimal(ema9_s))
            ema21 = money(Decimal(ema21_s))

            if side != prev_side:
                seq = 1
                entry_px = to_decimal(price)
                entry = "ENTRY_BUY" if side == "BUY" else "ENTRY_SELL"
            else:
                seq += 1
                entry = "NONE"
            prev_side = side
            trend = "BUY_TREND" if side == "BUY" else "SELL_TREND"
            # Keep alert_side = Chat notification side; actionable signal only on ENTRY.
            signal = "BUY" if entry == "ENTRY_BUY" else "SELL" if entry == "ENTRY_SELL" else "WAIT"
            assert entry_px is not None
            pnl_pct, still = _pnl(side, entry_px, to_decimal(price))

            reason = (
                f"Chat alert #{seq} from ENTRY · {side} · "
                f"pnl_vs_entry={float(pnl_pct):+.4f}% · still_profit={still} · "
                f"close={price_s}"
            )
            short = f"{side} #{seq} · {float(pnl_pct):+.3f}% vs ENTRY"

            existing = db.scalar(
                select(CoachSignalEvent).where(
                    CoachSignalEvent.symbol == "BTC",
                    CoachSignalEvent.interval == "15m",
                    CoachSignalEvent.evaluated_bar_time == bar_open,
                    CoachSignalEvent.brain == "DayTradeCryptoCoach",
                )
            )
            fields = dict(
                symbol="BTC",
                interval="15m",
                brain="DayTradeCryptoCoach",
                signal=signal,
                entry=entry,
                trend=trend,
                alert_side=side,
                seq_from_entry=seq,
                entry_price=money(entry_px),
                pnl_pct_vs_entry=pnl_pct,
                still_profit=still if seq > 1 else False,
                confidence=100,
                reason=reason,
                short_reason=short[:500],
                cofr=f"C:100 | O:chat-import | F:{side}#{seq} | R:pnl {float(pnl_pct):+.3f}%",
                price=price,
                ema9=ema9,
                ema21=ema21,
                source="google_chat_import",
                bar_closed=True,
                evaluated_bar_time=bar_open,
            )
            if existing is None:
                db.add(CoachSignalEvent(**fields))
                inserted += 1
            else:
                for k, v in fields.items():
                    setattr(existing, k, v)
                updated += 1
        db.commit()

        # Summary: last profitable seq per run
        rows = list(
            db.scalars(
                select(CoachSignalEvent)
                .where(CoachSignalEvent.source == "google_chat_import")
                .order_by(CoachSignalEvent.evaluated_bar_time.asc())
            ).all()
        )
        print(f"import ok inserted={inserted} updated={updated} total={len(rows)}")
        run = None
        for r in rows:
            if r.seq_from_entry == 1:
                if run:
                    print(
                        f"  run {run['side']} ENTRY@{run['entry']} "
                        f"alerts={run['n']} last_profit_seq={run['last_ok']} "
                        f"final_pnl={run['final']:+.3f}%"
                    )
                run = {
                    "side": r.alert_side,
                    "entry": str(r.price),
                    "n": 1,
                    "last_ok": 1,
                    "final": float(r.pnl_pct_vs_entry or 0),
                }
            elif run:
                run["n"] = r.seq_from_entry or run["n"]
                run["final"] = float(r.pnl_pct_vs_entry or 0)
                if r.still_profit:
                    run["last_ok"] = r.seq_from_entry
        if run:
            print(
                f"  run {run['side']} ENTRY@{run['entry']} "
                f"alerts={run['n']} last_profit_seq={run['last_ok']} "
                f"final_pnl={run['final']:+.3f}%"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
