"""Observability helpers for coach signals — reasons, regime labels, hold metrics.

Does not change strategy thresholds; display / audit only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.money import to_decimal

REGIME_LABELS: dict[int, str] = {
    0: "RANGE",
    1: "TREND",
    2: "HIGH VOLATILITY",
}


def regime_label(regime: int | None) -> str | None:
    if regime is None:
        return None
    return REGIME_LABELS.get(int(regime))


def build_entry_reasons(
    *,
    side: str,
    uptrend: bool,
    downtrend: bool,
    close_above_ema9: bool,
    close_below_ema9: bool,
    separation_ok: bool,
    separation_pct: float,
    sep_min: float,
    meta_take: bool | None = None,
    meta_reason: str | None = None,
    regime: int | None = None,
) -> list[str]:
    """Human-readable entry reason bullets from A4 + MetaAlpha checks."""
    reasons: list[str] = []
    longish = side.upper() in {"BUY", "LONG", "ENTRY_BUY"}
    if longish:
        reasons.append(
            "EMA9 above EMA21" if uptrend else "EMA9 not above EMA21"
        )
        reasons.append(
            "Candle closed above EMA9"
            if close_above_ema9
            else "Candle not closed above EMA9"
        )
    else:
        reasons.append(
            "EMA9 below EMA21" if downtrend else "EMA9 not below EMA21"
        )
        reasons.append(
            "Candle closed below EMA9"
            if close_below_ema9
            else "Candle not closed below EMA9"
        )
    if separation_ok:
        reasons.append(f"EMA gap above {sep_min:g}% ({separation_pct:.3f}%)")
    else:
        reasons.append(f"EMA gap ≤ {sep_min:g}% ({separation_pct:.3f}%)")

    if meta_take is True:
        reasons.append("MetaAlpha filter passed")
    elif meta_take is False:
        reasons.append(
            f"MetaAlpha filter rejected"
            + (f" ({meta_reason})" if meta_reason else "")
        )
    elif meta_reason == "meta_alpha_disabled":
        reasons.append("MetaAlpha off — primary-only")
    elif meta_reason:
        reasons.append(f"MetaAlpha: {meta_reason}")

    label = regime_label(regime)
    if label:
        pretty = {
            "RANGE": "Range",
            "TREND": "Trend",
            "HIGH VOLATILITY": "High Volatility",
        }.get(label, label)
        reasons.append(f"Market regime: {pretty}")
    return reasons


def map_final_action(
    *,
    phase: str,
    auto_action: str | None = None,
    signal: str | None = None,
) -> str:
    """Normalize to ENTRY | HOLD | EXIT | SKIP for audit rows."""
    if auto_action:
        a = auto_action.lower()
        if a.startswith("open_") or a.startswith("flip_"):
            return "ENTRY"
        if a.startswith("close_"):
            return "EXIT"
        if a in {
            "skip_meta_filter",
            "skip_same_candle",
            "skip_same_signal",
            "locked",
            "wait",
            "none",
        }:
            return "SKIP"
        if a in {"hold", "hold_until_exit"}:
            return "HOLD"
    phase = (phase or "NONE").upper()
    if phase in {"ENTRY_BUY", "ENTRY_SELL", "FLIP_TO_LONG", "FLIP_TO_SHORT"}:
        return "ENTRY"
    if phase in {"HOLD_LONG", "HOLD_SHORT"}:
        return "HOLD"
    if phase in {"EXIT_BUY", "EXIT_SELL"}:
        return "EXIT"
    if signal in {"BUY", "SELL"}:
        return "ENTRY"
    return "SKIP"


def signal_candidate_from_phase(phase: str, buy_ok: bool, sell_ok: bool) -> str:
    """What the primary would do before position/state filtering."""
    phase = (phase or "NONE").upper()
    if phase in {"ENTRY_BUY", "HOLD_LONG", "FLIP_TO_LONG", "EXIT_BUY"}:
        return "BUY"
    if phase in {"ENTRY_SELL", "HOLD_SHORT", "FLIP_TO_SHORT", "EXIT_SELL"}:
        return "SELL"
    if buy_ok:
        return "BUY"
    if sell_ok:
        return "SELL"
    return "NONE"


def tp_progress_pct(
    *,
    side: str,
    entry: Decimal | float | str,
    current: Decimal | float | str,
    take_profit: Decimal | float | str | None,
) -> float | None:
    """How far price moved from entry toward TP (0–100, clamped)."""
    if take_profit is None:
        return None
    e = to_decimal(entry)
    c = to_decimal(current)
    tp = to_decimal(take_profit)
    if e <= 0:
        return None
    side_u = side.upper()
    if side_u in {"LONG", "BUY", "ENTRY_BUY", "HOLD_LONG"}:
        span = tp - e
        if span <= 0:
            return None
        moved = c - e
    elif side_u in {"SHORT", "SELL", "ENTRY_SELL", "HOLD_SHORT"}:
        span = e - tp
        if span <= 0:
            return None
        moved = e - c
    else:
        return None
    pct = float(moved / span * Decimal("100"))
    return max(0.0, min(100.0, pct))


def hold_pnl(
    *,
    side: str,
    entry: Decimal | float | str,
    current: Decimal | float | str,
    quantity: Decimal | float | str | None = None,
) -> tuple[float, float | None]:
    """Return (pnl_pct, pnl_usd or None)."""
    e = to_decimal(entry)
    c = to_decimal(current)
    if e <= 0:
        return 0.0, None
    side_u = side.upper()
    if side_u in {"LONG", "BUY"}:
        pct = float((c - e) / e * Decimal("100"))
        usd = None
        if quantity is not None:
            q = abs(to_decimal(quantity))
            usd = float((c - e) * q)
        return pct, usd
    if side_u in {"SHORT", "SELL"}:
        pct = float((e - c) / e * Decimal("100"))
        usd = None
        if quantity is not None:
            q = abs(to_decimal(quantity))
            usd = float((e - c) * q)
        return pct, usd
    return 0.0, None


def display_confidence(
    *,
    primary_confidence: int,
    rf_proba: float | None,
    meta_enabled: bool,
) -> tuple[int | None, str]:
    """Map MetaAlpha RF proba → confidence % when available.

    Returns (confidence_or_none, confidence_source).
    When MetaAlpha is off/skipped, confidence stays primary; RF shown as N/A.
    """
    if meta_enabled and rf_proba is not None:
        return int(round(float(rf_proba) * 100)), "meta_alpha_rf"
    return int(primary_confidence), "primary"


def gate_to_public(gate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not gate:
        return None
    regime = gate.get("regime")
    return {
        "take": int(gate.get("take") or 0),
        "proba": gate.get("proba"),
        "regime": int(regime) if regime is not None else None,
        "regime_label": regime_label(int(regime) if regime is not None else None),
        "reason": str(gate.get("reason") or ""),
        "warm": bool(gate.get("warm", False)),
    }
