"""Google Chat webhook alerts for DayTradeCryptoCoach (Thai messages, paper only)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.coach import CoachVerdict
from app.services.coach_brain import DEFAULT_AUTO_USD, SL_PCT, TP_PCT

logger = logging.getLogger(__name__)

# Dedupe: one alert per symbol+interval+phase+bar (avoid spam from UI polling).
_last_notified_key: str | None = None


def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _phase_of(verdict: CoachVerdict) -> str:
    phase = getattr(verdict, "phase", None) or "NONE"
    if phase and phase != "NONE":
        return phase
    entry = getattr(verdict, "entry", None) or "NONE"
    if entry in {"ENTRY_BUY", "ENTRY_SELL"}:
        return entry
    exit_kind = getattr(verdict, "exit", None) or "NONE"
    if exit_kind in {"EXIT_BUY", "EXIT_SELL"}:
        return exit_kind
    return "NONE"


def _thai_phase_title(phase: str) -> str:
    titles = {
        "ENTRY_BUY": "ENTRY BUY → เปิด LONG",
        "ENTRY_SELL": "ENTRY SELL → เปิด SHORT",
        "EXIT_BUY": "EXIT BUY → ปิด LONG",
        "EXIT_SELL": "EXIT SELL → ปิด SHORT",
        "FLIP_TO_SHORT": "EXIT LONG → ENTRY SHORT",
        "FLIP_TO_LONG": "EXIT SHORT → ENTRY LONG",
    }
    return titles.get(phase, f"สถานะ: {phase}")


def format_thai_signal_message(
    verdict: CoachVerdict,
    *,
    suggested_usd: float | None = None,
    paper_note: bool = True,
) -> str:
    phase = _phase_of(verdict)
    stake = float(suggested_usd) if suggested_usd is not None else float(DEFAULT_AUTO_USD)
    sl_pct = float(SL_PCT) * 100
    tp_pct = float(TP_PCT) * 100
    exit_reason = getattr(verdict, "exit_reason", None) or "Signal"
    lines = [
        f"*{_thai_phase_title(phase)}* — {verdict.symbol} · {verdict.interval}",
        f"ความมั่นใจ: *{verdict.confidence}%*",
        f"ราคาปิดแท่ง: ${_fmt_money(verdict.price)}",
    ]
    if verdict.ema9 is not None:
        lines.append(f"EMA9: ${_fmt_money(verdict.ema9)} · EMA21: ${_fmt_money(verdict.ema21)}")

    if phase == "ENTRY_BUY":
        lines.append("*ENTRY BUY* (ครั้งเดียว) → paper LONG")
        lines.append(f"ขนาด (paper): *${stake:.2f}* USD")
        lines.append(f"แผน: SL *{sl_pct:.0f}%* / TP *{tp_pct:.0f}%*")
        if verdict.stop_loss is not None:
            lines.append(f"Stop Loss: ${_fmt_money(verdict.stop_loss)}")
        if verdict.take_profit is not None:
            lines.append(f"Take Profit: ${_fmt_money(verdict.take_profit)}")
        if verdict.risk_reward:
            lines.append(f"Risk:Reward: {verdict.risk_reward}")
        lines.append("ต่อไป: *HOLD LONG* จนกว่า EXIT (สัญญาณตรงข้าม / SL / TP) — ไม่สั่งซ้ำ")
    elif phase == "ENTRY_SELL":
        lines.append("*ENTRY SELL* (ครั้งเดียว) → paper SHORT")
        lines.append(f"ขนาด (paper): *${stake:.2f}* USD")
        lines.append(f"แผน: SL *{sl_pct:.0f}%* / TP *{tp_pct:.0f}%*")
        if verdict.stop_loss is not None:
            lines.append(f"Stop Loss: ${_fmt_money(verdict.stop_loss)}")
        if verdict.take_profit is not None:
            lines.append(f"Take Profit: ${_fmt_money(verdict.take_profit)}")
        lines.append("ต่อไป: *HOLD SHORT* จนกว่า EXIT (สัญญาณตรงข้าม / SL / TP) — ไม่สั่งซ้ำ")
    elif phase == "EXIT_BUY":
        lines.append(f"*EXIT BUY* ปิด LONG · เหตุผล: *{exit_reason}*")
        lines.append("สถานะถัดไป: NEUTRAL (รอ ENTRY ใหม่)")
    elif phase == "EXIT_SELL":
        lines.append(f"*EXIT SELL* ปิด SHORT · เหตุผล: *{exit_reason}*")
        lines.append("สถานะถัดไป: NEUTRAL (รอ ENTRY ใหม่)")
    elif phase == "FLIP_TO_SHORT":
        lines.append("*EXIT LONG → ENTRY SHORT* (แท่งเดียวกัน)")
        lines.append(f"ขนาด SHORT (paper): *${stake:.2f}* USD")
        lines.append(f"แผน: SL *{sl_pct:.0f}%* / TP *{tp_pct:.0f}%*")
        if verdict.stop_loss is not None:
            lines.append(f"Stop Loss: ${_fmt_money(verdict.stop_loss)}")
        if verdict.take_profit is not None:
            lines.append(f"Take Profit: ${_fmt_money(verdict.take_profit)}")
    elif phase == "FLIP_TO_LONG":
        lines.append("*EXIT SHORT → ENTRY LONG* (แท่งเดียวกัน)")
        lines.append(f"ขนาด LONG (paper): *${stake:.2f}* USD")
        lines.append(f"แผน: SL *{sl_pct:.0f}%* / TP *{tp_pct:.0f}%*")
        if verdict.stop_loss is not None:
            lines.append(f"Stop Loss: ${_fmt_money(verdict.stop_loss)}")
        if verdict.take_profit is not None:
            lines.append(f"Take Profit: ${_fmt_money(verdict.take_profit)}")

    lines.append(f"เหตุผล: {verdict.reason}")
    lines.append(f"COFR: `{verdict.cofr}`")
    if paper_note:
        lines.append("_โหมด Paper เท่านั้น — ไม่ใช่คำสั่งซื้อขายเงินจริง_")
    return "\n".join(lines)


def _dedupe_key(verdict: CoachVerdict) -> str:
    phase = _phase_of(verdict)
    return (
        f"{verdict.symbol}|{verdict.interval}|{phase}|"
        f"{verdict.evaluated_bar_time}|{getattr(verdict, 'exit_reason', None) or ''}"
    )


async def notify_coach_signal(
    verdict: CoachVerdict,
    *,
    suggested_usd: float | None = None,
    force: bool = False,
) -> bool:
    """Post ENTRY / EXIT (closed bar) to Google Chat — never HOLD spam."""
    global _last_notified_key

    phase = _phase_of(verdict)
    if phase not in {
        "ENTRY_BUY",
        "ENTRY_SELL",
        "EXIT_BUY",
        "EXIT_SELL",
        "FLIP_TO_SHORT",
        "FLIP_TO_LONG",
    }:
        return False
    if not verdict.bar_closed:
        return False

    settings = get_settings()
    url = (settings.google_chat_webhook_url or "").strip()
    if not url:
        return False

    key = _dedupe_key(verdict)
    if not force and key == _last_notified_key:
        return False

    stake = float(suggested_usd) if suggested_usd is not None else float(DEFAULT_AUTO_USD)
    text = format_thai_signal_message(verdict, suggested_usd=stake)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json={"text": text})
            response.raise_for_status()
        _last_notified_key = key
        logger.info(
            "Google Chat coach alert sent: %s phase=%s",
            verdict.symbol,
            phase,
        )
        return True
    except Exception:
        logger.exception("Failed to post Google Chat coach alert")
        return False


async def notify_google_chat_text(text: str) -> bool:
    """Send a plain text message (setup / test)."""
    settings = get_settings()
    url = (settings.google_chat_webhook_url or "").strip()
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json={"text": text})
            response.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to post Google Chat text")
        return False
