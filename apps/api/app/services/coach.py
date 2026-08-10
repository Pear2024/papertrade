"""DayTradeCrypto coach brain — rule-based high-probability signals (paper only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.money import money, to_decimal
from app.core.config import get_settings
from app.services.coach_brain import (
    BRAIN_NAME,
    BRAIN_PROMPT,
    DEFAULT_AUTO_USD,
    EMA_SEPARATION_PCT_MIN,
    HIGHER_TF_FOR_ENTRY,
    MIN_CONFIDENCE,
    PRACTICE_TRADES_MIN,
    PRACTICE_TRADES_TARGET,
    SL_PCT,
    TP_PCT,
)
from app.services.coach_ccr import (
    CCR_CONSECUTIVE_DEFAULT,
    OHLC,
    clamp_ccr_consecutive,
    ccr_buy_at,
)
from app.services.entry_filters import FilterResult, evaluate_buy_filters
from app.services.prices import ALLOWED_CANDLE_INTERVALS, CandleBar, get_candles, require_asset
from app.services.risk_reward import calculate_net_risk_reward

INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

_SL = Decimal(SL_PCT)
_TP = Decimal(TP_PCT)


@dataclass
class ChecklistItem:
    id: str
    label: str
    passed: bool


@dataclass
class CoachVerdict:
    symbol: str
    interval: str
    signal: str  # BUY | SELL | WAIT — actionable ENTRY only (auto uses this)
    confidence: int
    reason: str
    cofr: str
    price: Decimal
    ema9: Decimal | None
    ema21: Decimal | None
    volume: Decimal | None
    volume_avg20: Decimal | None
    bar_closed: bool
    stop_loss: Decimal | None
    take_profit: Decimal | None
    risk_reward: str | None
    source: str
    evaluated_bar_time: int | None
    brain: str = BRAIN_NAME
    checklist: list[ChecklistItem] | None = None
    short_reason: str = ""
    # Story markers: ENTRY → HOLD → EXIT (never spam BUY/SELL every bar).
    phase: str = "NONE"  # ENTRY_BUY|ENTRY_SELL|HOLD_LONG|HOLD_SHORT|EXIT_BUY|EXIT_SELL|FLIP_TO_*|NONE
    # Position AFTER this bar's transition:
    position: str = "NEUTRAL"  # NEUTRAL | LONG | SHORT
    # Compat / store mirrors of phase:
    trend: str = "NONE"  # HOLD_LONG | HOLD_SHORT | NONE
    entry: str = "NONE"  # ENTRY_BUY | ENTRY_SELL | NONE
    exit: str = "NONE"  # EXIT_BUY | EXIT_SELL | NONE
    exit_reason: str | None = None  # Signal | stop_loss | take_profit
    # Which primary setup opened (a4 | ccr | None)
    entry_setup: str | None = None
    # CCR: fill at next bar open when set
    entry_fill: str | None = None  # "close" | "next_open"
    entry_fill_price: Decimal | None = None
    gross_risk_reward: str | None = None
    net_risk_reward: str | None = None
    rr_blocked: bool = False
    filter_blocked: bool = False
    filters_enabled: dict[str, bool] | None = None
    filter_results: list[FilterResult] | None = None
    filter_set_id: str | None = None
    filter_version: str | None = None


def _candles_to_ohlc(candles: list[CandleBar]) -> list[OHLC]:
    return [
        OHLC(
            open=float(c.open),
            high=float(c.high),
            low=float(c.low),
            close=float(c.close),
        )
        for c in candles
    ]


def _ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    out: list[float | None] = [None] * len(values)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _a4_side_ok(
    *,
    ema9: float,
    ema21: float,
    close: float,
    sep_min: float,
) -> tuple[bool, bool, float]:
    """Return (buy_ok, sell_ok, separation_pct) for A4 rules on one closed bar."""
    uptrend = ema9 > ema21
    downtrend = ema9 < ema21
    close_above = close > ema9
    close_below = close < ema9
    separation = abs(ema9 - ema21)
    separation_pct = (separation / close * 100.0) if close > 0 else 0.0
    separation_ok = separation_pct > sep_min
    buy_ok = uptrend and close_above and separation_ok
    sell_ok = downtrend and close_below and separation_ok
    return buy_ok, sell_ok, separation_pct


def _step_position_a4(
    position: str,
    *,
    buy_ok: bool,
    sell_ok: bool,
) -> tuple[str, str]:
    """Legacy A4-only step (kept for tests / clarity)."""
    if position == "NEUTRAL":
        if buy_ok:
            return "ENTRY_BUY", "LONG"
        if sell_ok:
            return "ENTRY_SELL", "SHORT"
        return "NONE", "NEUTRAL"
    if position == "LONG":
        if sell_ok:
            return "FLIP_TO_SHORT", "SHORT"
        if not buy_ok:
            return "EXIT_BUY", "NEUTRAL"
        return "HOLD_LONG", "LONG"
    if position == "SHORT":
        if buy_ok:
            return "FLIP_TO_LONG", "LONG"
        if not sell_ok:
            return "EXIT_SELL", "NEUTRAL"
        return "HOLD_SHORT", "SHORT"
    return "NONE", "NEUTRAL"


def _walk_phase_at(
    closes: list[float],
    ema9_series: list[float | None],
    ema21_series: list[float | None],
    *,
    end_idx: int,
    sep_min: float,
    start_idx: int = 21,
    ohlc: list[OHLC] | None = None,
    ccr_consecutive: int = CCR_CONSECUTIVE_DEFAULT,
    a4_enabled: bool = True,
    ccr_enabled: bool = True,
) -> tuple[str, str, str | None, str | None, float | None, str | None]:
    """Simulate position through closed bars; return at end_idx.

    Returns:
      phase, position, entry_setup ("a4"|"ccr"|None), entry_fill ("close"|"next_open"|None),
      entry_fill_price (float|None), pending_ccr ("buy"|None).
    """
    position = "NEUTRAL"
    phase = "NONE"
    entry_setup: str | None = None
    last_fill: str | None = None
    last_fill_px: float | None = None
    pending: str | None = None  # "buy" from CCR confirm → fill next open
    n = clamp_ccr_consecutive(ccr_consecutive)
    bars = ohlc

    for i in range(max(start_idx, 1), end_idx + 1):
        e9 = ema9_series[i]
        e21 = ema21_series[i]
        a4_buy = a4_sell = False
        if a4_enabled and e9 is not None and e21 is not None:
            a4_buy, a4_sell, _ = _a4_side_ok(
                ema9=float(e9), ema21=float(e21), close=closes[i], sep_min=sep_min
            )
        ccr_buy = False
        if ccr_enabled and bars is not None:
            ccr_buy = ccr_buy_at(bars, i, n)

        fill_px = float(bars[i].open) if bars is not None else closes[i]
        bar_phase = "NONE"
        bar_fill: str | None = None
        bar_fill_px: float | None = None
        bar_setup: str | None = None

        # 1) Execute CCR pending entry at this bar's open (confirm was prior closed bar).
        if position == "NEUTRAL" and pending == "buy":
            bar_phase, position = "ENTRY_BUY", "LONG"
            bar_setup, bar_fill, bar_fill_px = "ccr", "next_open", fill_px
            pending = None
        elif position == "NEUTRAL":
            if a4_buy:
                bar_phase, position = "ENTRY_BUY", "LONG"
                bar_setup, bar_fill, bar_fill_px = "a4", "close", closes[i]
            elif a4_sell:
                bar_phase, position = "ENTRY_SELL", "SHORT"
                bar_setup, bar_fill, bar_fill_px = "a4", "close", closes[i]
            elif ccr_buy:
                pending = "buy"
                bar_phase = "NONE"
        elif position == "LONG":
            if a4_sell:
                bar_phase, position = "FLIP_TO_SHORT", "SHORT"
                bar_setup, bar_fill, bar_fill_px = "a4", "close", closes[i]
            elif entry_setup == "a4" and not a4_buy:
                bar_phase, position = "EXIT_BUY", "NEUTRAL"
                entry_setup = None
            else:
                bar_phase, position = "HOLD_LONG", "LONG"
        elif position == "SHORT":
            if a4_buy:
                bar_phase, position = "FLIP_TO_LONG", "LONG"
                bar_setup, bar_fill, bar_fill_px = "a4", "close", closes[i]
            elif entry_setup == "a4" and not a4_sell:
                bar_phase, position = "EXIT_SELL", "NEUTRAL"
                entry_setup = None
            else:
                bar_phase, position = "HOLD_SHORT", "SHORT"

        if bar_setup is not None:
            entry_setup = bar_setup
        if bar_phase.startswith("EXIT") and bar_phase in {"EXIT_BUY", "EXIT_SELL"}:
            if pending is None:
                entry_setup = None
        if bar_phase in {"ENTRY_BUY", "ENTRY_SELL", "FLIP_TO_LONG", "FLIP_TO_SHORT"}:
            last_fill, last_fill_px = bar_fill, bar_fill_px
        phase = bar_phase

    return phase, position, entry_setup, last_fill, last_fill_px, pending


def _step_position(
    position: str,
    *,
    buy_ok: bool,
    sell_ok: bool,
) -> tuple[str, str]:
    return _step_position_a4(position, buy_ok=buy_ok, sell_ok=sell_ok)

def _mirrors_from_phase(phase: str) -> tuple[str, str, str, str]:
    """Map phase → (entry, trend/hold, exit, signal)."""
    if phase == "ENTRY_BUY":
        return "ENTRY_BUY", "NONE", "NONE", "BUY"
    if phase == "ENTRY_SELL":
        return "ENTRY_SELL", "NONE", "NONE", "SELL"
    if phase == "HOLD_LONG":
        return "NONE", "HOLD_LONG", "NONE", "WAIT"
    if phase == "HOLD_SHORT":
        return "NONE", "HOLD_SHORT", "NONE", "WAIT"
    if phase == "EXIT_BUY":
        return "NONE", "NONE", "EXIT_BUY", "WAIT"
    if phase == "EXIT_SELL":
        return "NONE", "NONE", "EXIT_SELL", "WAIT"
    # Same-candle flip: close then open opposite (signal drives new ENTRY).
    if phase == "FLIP_TO_SHORT":
        return "ENTRY_SELL", "NONE", "EXIT_BUY", "SELL"
    if phase == "FLIP_TO_LONG":
        return "ENTRY_BUY", "NONE", "EXIT_SELL", "BUY"
    return "NONE", "NONE", "NONE", "WAIT"


def _is_bar_closed(candle: CandleBar, interval: str, now: datetime) -> bool:
    seconds = INTERVAL_SECONDS.get(interval, 900)
    close_at = candle.time + seconds
    return int(now.timestamp()) >= close_at


def _score_buy(
    *,
    crossed_up: bool,
    green: bool,
    volume_ok: bool,
    htf_bullish: bool,
) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []
    if crossed_up:
        score += 30
        notes.append("EMA9↑EMA21")
    if green:
        score += 20
        notes.append("green PA")
    if volume_ok:
        score += 25
        notes.append("volume>20-avg")
    if htf_bullish:
        score += 25
        notes.append("HTF bullish")
    return min(score, 100), notes


def _score_sell(
    *,
    crossed_down: bool,
    red: bool,
    volume_ok: bool,
) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []
    if crossed_down:
        score += 40
        notes.append("EMA9↓EMA21")
    if red:
        score += 30
        notes.append("red PA")
    if volume_ok:
        score += 30
        notes.append("volume>20-avg")
    return min(score, 100), notes


def _build_checklist(
    *,
    bar_closed: bool,
    uptrend: bool,
    downtrend: bool,
    close_above_ema9: bool,
    close_below_ema9: bool,
    separation_ok: bool,
    separation_pct: float,
    sep_min: float,
    sl_pct: Decimal,
    tp_pct: Decimal,
    crossed_up: bool,
    crossed_down: bool,
) -> list[ChecklistItem]:
    return [
        ChecklistItem("bar_closed", "Closed candle only", bar_closed),
        ChecklistItem("uptrend", "Uptrend: EMA9 > EMA21", uptrend),
        ChecklistItem("close_above_ema9", "Close above EMA9 (BUY)", close_above_ema9),
        ChecklistItem(
            "separation",
            f"|EMA9−EMA21| > {sep_min:g}% of close (now {separation_pct:.3f}%)",
            separation_ok,
        ),
        ChecklistItem(
            "sl_tp_lock",
            f"Lock SL {float(sl_pct)*100:g}% / TP {float(tp_pct)*100:g}% immediately on BUY",
            True,
        ),
        ChecklistItem("downtrend", "Downtrend: EMA9 < EMA21", downtrend),
        ChecklistItem("close_below_ema9", "Close below EMA9 (SELL)", close_below_ema9),
        ChecklistItem("ema_cross_up", "EMA9 crossed above EMA21 (info)", crossed_up),
        ChecklistItem("ema_cross_down", "EMA9 crossed below EMA21 (info)", crossed_down),
    ]


def _short_reason(
    signal: str,
    *,
    notes: list[str],
    forming: bool,
    sep_min: float,
    counter_trend: bool = False,
) -> str:
    bits = ", ".join(notes[:4]) if notes else "no confirms"
    if forming:
        return f"WAIT — candle still open; preview: {bits}."
    if signal == "BUY":
        return f"BUY — uptrend + close above EMA9 + sep>{sep_min:g}% ({bits}); open LONG when flat."
    if signal == "SELL":
        return f"SELL — downtrend + close below EMA9 + sep>{sep_min:g}% ({bits}); open SHORT when flat."
    return f"WAIT — need closed bar, trend, close vs EMA9, sep>{sep_min:g}% ({bits})."


def _quantize_price(price: Decimal, precision: int) -> Decimal:
    digits = max(0, min(int(precision), 8))
    quant = Decimal("1").scaleb(-digits)
    return to_decimal(price).quantize(quant, rounding=ROUND_HALF_UP)


def _round_trip_fee_frac() -> Decimal:
    """Entry + exit paper fee as a price fraction (for TP padding).

    Flat USD fees are not a % of price — skip percent padding in that mode.
    """
    from app.core.config import get_settings

    s = get_settings()
    if to_decimal(s.paper_trading_fee_usd) > 0:
        return Decimal("0")
    fee_pct_points = to_decimal(s.paper_trading_fee_percent)
    return (fee_pct_points / Decimal("100")) * Decimal("2")


def _exits_for_buy(
    price: Decimal, *, sl_pct: Decimal, tp_pct: Decimal, price_precision: int = 8
) -> tuple[Decimal, Decimal, str]:
    """LONG exits: SL below entry, TP above entry (TP padded to cover round-trip fee)."""
    fee_rt = _round_trip_fee_frac()
    tp_eff = tp_pct + fee_rt
    sl = _quantize_price(to_decimal(price) * (Decimal("1") - sl_pct), price_precision)
    tp = _quantize_price(to_decimal(price) * (Decimal("1") + tp_eff), price_precision)
    if sl_pct > 0:
        rr = f"1:{(tp_pct / sl_pct):.2f}"
    else:
        rr = "n/a"
    return sl, tp, rr


def _exits_for_short(
    price: Decimal, *, sl_pct: Decimal, tp_pct: Decimal, price_precision: int = 8
) -> tuple[Decimal, Decimal, str]:
    """SHORT exits: SL above entry, TP below entry (TP padded to cover round-trip fee)."""
    fee_rt = _round_trip_fee_frac()
    tp_eff = tp_pct + fee_rt
    sl = _quantize_price(to_decimal(price) * (Decimal("1") + sl_pct), price_precision)
    tp = _quantize_price(to_decimal(price) * (Decimal("1") - tp_eff), price_precision)
    if sl_pct > 0:
        rr = f"1:{(tp_pct / sl_pct):.2f}"
    else:
        rr = "n/a"
    return sl, tp, rr


def _htf_bias(candles: list[CandleBar], interval: str, now: datetime) -> tuple[bool | None, bool | None, str]:
    """Return (bullish, bearish, note) from last closed HTF bar EMA alignment."""
    if len(candles) < 25:
        return None, None, "HTF warming"
    forming = not _is_bar_closed(candles[-1], interval, now)
    idx = len(candles) - 2 if forming else len(candles) - 1
    closes = [float(c.close) for c in candles]
    e9 = _ema(closes, 9)
    e21 = _ema(closes, 21)
    if e9[idx] is None or e21[idx] is None:
        return None, None, "HTF EMA not ready"
    ema9 = float(e9[idx])
    ema21 = float(e21[idx])
    close = float(candles[idx].close)
    bullish = ema9 > ema21 and close > ema9
    bearish = ema9 < ema21 and close < ema9
    return bullish, bearish, f"HTF:{interval}"



def get_brain_prompt() -> dict[str, str | int]:
    return {
        "name": BRAIN_NAME,
        "prompt": BRAIN_PROMPT,
        "min_confidence": MIN_CONFIDENCE,
        "sl_pct": float(_SL) * 100,
        "tp_pct": float(_TP) * 100,
        "practice_trades_min": PRACTICE_TRADES_MIN,
        "practice_trades_target": PRACTICE_TRADES_TARGET,
        "default_auto_usd": float(DEFAULT_AUTO_USD),
    }


async def evaluate_daytrade_signal(
    db: Session,
    symbol: str,
    interval: str = "15m",
    *,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    ema_sep_pct: float | None = None,
    ccr_consecutive: int | None = None,
    a4_enabled: bool = True,
    ccr_enabled: bool = False,
    buy_filters: dict[str, bool] | None = None,
    min_net_rr: float = 2.0,
    slippage_bps: float = 3.0,
    spread_bps: float = 2.0,
    notional_usd: Decimal | None = None,
) -> CoachVerdict:
    """Evaluate the selected, mutually-exclusive A4 or buy-only CCR entry setup.

    Optional paper overrides (fractions for sl/tp, percent points for ema_sep):
    sl_pct=0.02 → 2% SL, ema_sep_pct=0.10 → |EMA gap| > 0.10% of close.
    ccr_consecutive: 2–6 streak length for CCR (default 3).
    """
    interval_key = interval.strip().lower()
    if interval_key not in ALLOWED_CANDLE_INTERVALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported interval. Allowed: {', '.join(sorted(ALLOWED_CANDLE_INTERVALS))}",
        )

    rule_sl = Decimal(str(sl_pct)) if sl_pct is not None else _SL
    rule_tp = Decimal(str(tp_pct)) if tp_pct is not None else _TP
    if rule_sl <= 0 or rule_sl > Decimal("0.5"):
        raise HTTPException(status_code=422, detail="sl_pct must be between 0 and 0.5 (fraction)")
    if rule_tp <= 0 or rule_tp > Decimal("1"):
        raise HTTPException(status_code=422, detail="tp_pct must be between 0 and 1 (fraction)")
    sep_min = float(ema_sep_pct) if ema_sep_pct is not None else float(EMA_SEPARATION_PCT_MIN)
    if sep_min <= 0 or sep_min > 10:
        raise HTTPException(status_code=422, detail="ema_sep_pct must be between 0 and 10 (percent)")
    min_net_rr_value = Decimal(str(min_net_rr))
    if min_net_rr_value <= 0 or min_net_rr_value > Decimal("20"):
        raise HTTPException(status_code=422, detail="min_net_rr must be between 0 and 20")
    slippage_bps_value = Decimal(str(slippage_bps))
    spread_bps_value = Decimal(str(spread_bps))
    if slippage_bps_value < 0 or slippage_bps_value > Decimal("100"):
        raise HTTPException(status_code=422, detail="slippage_bps must be between 0 and 100")
    if spread_bps_value < 0 or spread_bps_value > Decimal("100"):
        raise HTTPException(status_code=422, detail="spread_bps must be between 0 and 100")
    # Signal callers that do not provide their proposed order size still get an
    # honest flat-fee estimate using the default $100 stake at 5x leverage.
    if notional_usd is None:
        notional_usd = Decimal(DEFAULT_AUTO_USD) * Decimal("5")
    if notional_usd <= 0:
        raise HTTPException(status_code=422, detail="notional_usd must be positive")
    ccr_n = clamp_ccr_consecutive(ccr_consecutive)
    # CCR is an explicit alternate entry mode, never an additional A4 condition.
    # Favor it defensively if an older caller accidentally sends both flags.
    if ccr_enabled:
        a4_enabled = False

    sym, iv, source, candles = await get_candles(db, symbol, interval_key, 120)
    asset = require_asset(db, sym)
    px_prec = int(getattr(asset, "price_precision", 8) or 8)
    if len(candles) < 25:
        return CoachVerdict(
            symbol=sym,
            interval=iv,
            signal="WAIT",
            confidence=0,
            reason="Not enough candle data yet",
            cofr="C:0 | O:insufficient-data | F:WAIT | R:wait",
            price=money(0),
            ema9=None,
            ema21=None,
            volume=None,
            volume_avg20=None,
            bar_closed=False,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            source=source,
            evaluated_bar_time=None,
        )

    now = datetime.now(timezone.utc)
    last = candles[-1]
    forming = not _is_bar_closed(last, iv, now)
    idx = len(candles) - 2 if forming else len(candles) - 1
    bar = candles[idx]

    closes = [float(c.close) for c in candles]
    ema9_series = _ema(closes, 9)
    ema21_series = _ema(closes, 21)
    ema9 = ema9_series[idx]
    ema21 = ema21_series[idx]
    price = to_decimal(bar.close)
    open_ = float(bar.open)
    close = float(bar.close)
    vol = float(bar.volume) if bar.volume is not None else None
    vols = [float(c.volume) for c in candles[max(0, idx - 20) : idx] if c.volume is not None]
    vol_avg = (sum(vols) / len(vols)) if vols else None
    volume_ok = vol is not None and vol_avg is not None and vol_avg > 0 and vol > vol_avg

    htf_key = HIGHER_TF_FOR_ENTRY.get(iv, "1h")
    htf_bullish: bool | None = None
    htf_note = "HTF n/a"
    htf_loaded = False
    try:
        _s, htf_iv, _src, htf_candles = await get_candles(db, symbol, htf_key, 120)
        htf_bullish, _htf_bearish, htf_note = _htf_bias(htf_candles, htf_iv, now)
        htf_loaded = True
    except Exception:
        htf_note = "HTF unavailable"

    if ema9 is None or ema21 is None:
        return CoachVerdict(
            symbol=sym,
            interval=iv,
            signal="WAIT",
            confidence=10,
            reason="EMA not ready on evaluated bar",
            cofr="C:10 | O:ema-warming | F:WAIT | R:wait",
            price=money(price),
            ema9=None,
            ema21=None,
            volume=money(vol) if vol is not None else None,
            volume_avg20=money(vol_avg) if vol_avg is not None else None,
            bar_closed=not forming,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            source=source,
            evaluated_bar_time=bar.time,
        )

    prev9 = ema9_series[idx - 1] if idx > 0 else None
    prev21 = ema21_series[idx - 1] if idx > 0 else None
    crossed_up = (
        prev9 is not None
        and prev21 is not None
        and prev9 <= prev21
        and ema9 > ema21
    )
    crossed_down = (
        prev9 is not None
        and prev21 is not None
        and prev9 >= prev21
        and ema9 < ema21
    )
    uptrend = float(ema9) > float(ema21)
    downtrend = float(ema9) < float(ema21)
    close_above_ema9 = close > float(ema9)
    close_below_ema9 = close < float(ema9)
    separation = abs(float(ema9) - float(ema21))
    separation_pct = (separation / close * 100.0) if close > 0 else 0.0
    separation_ok = separation_pct > sep_min
    sep_cmp = f">{sep_min:g}%" if separation_ok else f"≤{sep_min:g}%"

    buy_notes = [
        n
        for n in (
            "uptrend EMA9>EMA21" if uptrend else "",
            "close>EMA9" if close_above_ema9 else "",
            f"|EMA gap|={separation_pct:.3f}%{sep_cmp}",
            "cross↑ today" if crossed_up else "",
        )
        if n
    ]
    sell_notes = [
        n
        for n in (
            "downtrend EMA9<EMA21" if downtrend else "",
            "close<EMA9" if close_below_ema9 else "",
            f"|EMA gap|={separation_pct:.3f}%{sep_cmp}",
            "cross↓ today" if crossed_down else "",
        )
        if n
    ]

    # A4 side checks on the evaluated closed bar.
    buy_ok, sell_ok, _ = _a4_side_ok(
        ema9=float(ema9), ema21=float(ema21), close=close, sep_min=sep_min
    )

    buy_score = (40 if uptrend else 0) + (35 if close_above_ema9 else 0) + (25 if separation_ok else 0)
    sell_score = (40 if downtrend else 0) + (35 if close_below_ema9 else 0) + (25 if separation_ok else 0)
    checklist = _build_checklist(
        bar_closed=True,
        uptrend=uptrend,
        downtrend=downtrend,
        close_above_ema9=close_above_ema9,
        close_below_ema9=close_below_ema9,
        separation_ok=separation_ok,
        separation_pct=separation_pct,
        sep_min=sep_min,
        sl_pct=rule_sl,
        tp_pct=rule_tp,
        crossed_up=crossed_up,
        crossed_down=crossed_down,
    )

    # Walk the selected setup. CCR is BUY-only and fills at the next open.
    ohlc = _candles_to_ohlc(candles)
    phase, position, entry_setup, entry_fill, entry_fill_px, pending = _walk_phase_at(
        closes,
        ema9_series,
        ema21_series,
        end_idx=idx,
        sep_min=sep_min,
        ohlc=ohlc,
        ccr_consecutive=ccr_n,
        a4_enabled=a4_enabled,
        ccr_enabled=ccr_enabled,
    )
    # CCR: confirmation on last closed → enter at forming bar open (next candle).
    if pending == "buy" and forming and idx + 1 < len(candles):
        phase, position = "ENTRY_BUY", "LONG"
        entry_setup, entry_fill = "ccr", "next_open"
        entry_fill_px = float(candles[idx + 1].open)
        pending = None
    elif pending == "buy" and not forming:
        # Confirmation just closed; next bar not started — wait (no premature fill).
        phase, position = "NONE", "NEUTRAL"
        entry_setup = None
        entry_fill = None
        entry_fill_px = None

    entry, trend, exit_kind, signal = _mirrors_from_phase(phase)
    if phase in {"FLIP_TO_SHORT", "FLIP_TO_LONG"}:
        exit_reason = "Signal"
    elif exit_kind in {"EXIT_BUY", "EXIT_SELL"}:
        exit_reason = "SetupBroken"
    else:
        exit_reason = None

    prefer_buy = phase in {"ENTRY_BUY", "HOLD_LONG", "FLIP_TO_LONG"}
    prefer_sell = phase in {"ENTRY_SELL", "HOLD_SHORT", "FLIP_TO_SHORT"}

    fill_basis = (
        money(Decimal(str(entry_fill_px)))
        if entry_fill_px is not None and phase in {"ENTRY_BUY", "ENTRY_SELL", "FLIP_TO_LONG", "FLIP_TO_SHORT"}
        else money(price)
    )
    sl = tp = None
    rr: str | None = None
    gross_rr: str | None = None
    net_rr: str | None = None
    rr_blocked = False
    if prefer_buy or phase in {"EXIT_BUY", "FLIP_TO_LONG"}:
        sl, tp, rr = _exits_for_buy(
            fill_basis, sl_pct=rule_sl, tp_pct=rule_tp, price_precision=px_prec
        )
    elif prefer_sell or phase in {"EXIT_SELL", "FLIP_TO_SHORT"}:
        sl, tp, rr = _exits_for_short(
            fill_basis, sl_pct=rule_sl, tp_pct=rule_tp, price_precision=px_prec
        )

    if sl is not None and tp is not None:
        settings = get_settings()
        costs = calculate_net_risk_reward(
            entry=fill_basis,
            stop_loss=sl,
            take_profit=tp,
            fee_percent=to_decimal(settings.paper_trading_fee_percent),
            fee_usd_per_fill=to_decimal(settings.paper_trading_fee_usd),
            notional_usd=notional_usd,
            slippage_bps_per_side=slippage_bps_value,
            spread_bps=spread_bps_value,
        )
        gross_rr = f"1:{costs.gross_rr:.2f}"
        net_rr = f"1:{costs.net_rr:.2f}"
        rr_blocked = costs.net_rr < min_net_rr_value
        checklist.append(
            ChecklistItem(
                "net_risk_reward",
                f"Net R:R {costs.net_rr:.2f} ≥ {min_net_rr_value:.2f} after fees/slippage/spread",
                not rr_blocked,
            )
        )

    buy_filter_results, filter_blocked, active_filter_set_id = evaluate_buy_filters(
        entry_signal=entry_setup,
        enabled=buy_filters,
        candles=candles,
        confirmation_idx=idx,
        ema9=money(Decimal(str(ema9))),
        ema21=money(Decimal(str(ema21))),
        volume=money(vol) if vol is not None else None,
        volume_avg20=money(vol_avg) if vol_avg is not None else None,
        bar_time=bar.time,
    )
    for item in buy_filter_results:
        if item.enabled:
            checklist.append(ChecklistItem(f"filter_{item.id}", item.label, item.passed))

    entry_blocked = (rr_blocked or filter_blocked) and phase in {
        "ENTRY_BUY",
        "ENTRY_SELL",
        "FLIP_TO_LONG",
        "FLIP_TO_SHORT",
    }
    if entry_blocked:
        # A rejected flip is an exit only: never leave an existing position
        # exposed merely because the replacement entry failed the gate.
        if phase == "FLIP_TO_LONG":
            phase, position = "EXIT_SELL", "NEUTRAL"
            exit_reason = "Signal"
        elif phase == "FLIP_TO_SHORT":
            phase, position = "EXIT_BUY", "NEUTRAL"
            exit_reason = "Signal"
        else:
            phase, position = "NONE", "NEUTRAL"
            exit_reason = None
        entry_setup = None
        entry_fill = None
        entry_fill_px = None
        entry, trend, exit_kind, signal = _mirrors_from_phase(phase)

    conf = max(buy_score, sell_score, 50) if phase != "NONE" else max(buy_score, sell_score)
    if entry_setup == "ccr":
        conf = max(conf, 70)
    notes = (
        buy_notes
        if prefer_buy or phase in {"EXIT_BUY", "FLIP_TO_LONG"} or (buy_score >= sell_score and not prefer_sell)
        else sell_notes
    )

    if entry_blocked and filter_blocked:
        failed = ", ".join(
            item.label for item in buy_filter_results if item.enabled and not item.passed
        )
        reason = f"WAIT: BUY filter blocked — {failed}."
        cofr = f"C:{conf} | O:buy-filter-gate | F:WAIT | R:{active_filter_set_id}"
        short = f"WAIT — filter blocked: {failed}."
    elif entry_blocked:
        reason = (
            f"WAIT: net R:R {net_rr.removeprefix('1:') if net_rr else 'n/a'} < "
            f"{min_net_rr_value:.2f} after fees, slippage, and spread "
            f"(gross {gross_rr or 'n/a'})."
        )
        cofr = f"C:{conf} | O:net-rr-gate | F:WAIT | R:{net_rr or 'n/a'}"
        short = f"WAIT — net R:R {net_rr or 'n/a'} below {min_net_rr_value:.2f}."
    elif phase == "ENTRY_BUY":
        if entry_setup == "ccr":
            reason = (
                f"ENTRY BUY · Consecutive Candle Reversal (n={ccr_n}): "
                f"{ccr_n} bearish then bullish close above prior high. "
                f"Fill at next open ({entry_fill_px}). "
                f"SL {float(rule_sl)*100:g}% / TP {float(rule_tp)*100:g}% (RR {rr})."
            )
            cofr = f"C:{conf} | O:ccr-entry-buy | F:ENTRY_BUY | R:RR {rr}"
            short = "ENTRY BUY · CCR → LONG"
        else:
            reason = (
                f"ENTRY BUY (once → LONG): {', '.join(buy_notes)}. "
                f"Then HOLD LONG until EXIT (opposite signal / SL / TP). "
                f"SL {float(rule_sl)*100:g}% / TP {float(rule_tp)*100:g}% + round-trip fee cover (RR {rr})."
            )
            cofr = f"C:{conf} | O:entry-buy | F:ENTRY_BUY | R:RR {rr}"
            short = "ENTRY BUY → LONG"
    elif phase == "ENTRY_SELL":
        reason = (
            f"ENTRY SELL (once → SHORT): {', '.join(sell_notes)}. "
            f"Then HOLD SHORT until EXIT (opposite signal / SL / TP). "
            f"SL {float(rule_sl)*100:g}% / TP {float(rule_tp)*100:g}% + round-trip fee cover (RR {rr})."
        )
        cofr = f"C:{conf} | O:entry-sell | F:ENTRY_SELL | R:RR {rr}"
        short = "ENTRY SELL → SHORT"
    elif phase == "HOLD_LONG":
        reason = (
            f"HOLD LONG (no new order): {', '.join(buy_notes)}. "
            "ENTRY BUY already opened this position."
        )
        cofr = f"C:{conf} | O:hold-long | F:HOLD_LONG | R:no-reentry"
        short = "HOLD LONG"
    elif phase == "HOLD_SHORT":
        reason = (
            f"HOLD SHORT (no new order): {', '.join(sell_notes)}. "
            "ENTRY SELL already opened this position."
        )
        cofr = f"C:{conf} | O:hold-short | F:HOLD_SHORT | R:no-reentry"
        short = "HOLD SHORT"
    elif phase == "FLIP_TO_SHORT":
        reason = (
            f"EXIT LONG → ENTRY SHORT (same bar): {', '.join(sell_notes)}. "
            f"Close LONG then open SHORT · SL {float(rule_sl)*100:g}% / TP {float(rule_tp)*100:g}%."
        )
        cofr = f"C:{conf} | O:flip-short | F:FLIP_TO_SHORT | R:Signal"
        short = "EXIT LONG → ENTRY SHORT"
    elif phase == "FLIP_TO_LONG":
        reason = (
            f"EXIT SHORT → ENTRY LONG (same bar): {', '.join(buy_notes)}. "
            f"Close SHORT then open LONG · SL {float(rule_sl)*100:g}% / TP {float(rule_tp)*100:g}%."
        )
        cofr = f"C:{conf} | O:flip-long | F:FLIP_TO_LONG | R:Signal"
        short = "EXIT SHORT → ENTRY LONG"
    elif phase == "EXIT_BUY":
        reason = (
            f"EXIT LONG (setup broken — not A4 long anymore): {', '.join(notes)}. "
            "Position returns to NEUTRAL."
        )
        cofr = f"C:{conf} | O:exit-buy | F:EXIT_BUY | R:SetupBroken"
        short = "EXIT LONG · setup broken"
    elif phase == "EXIT_SELL":
        reason = (
            f"EXIT SHORT (setup broken — not A4 short anymore): {', '.join(notes)}. "
            "Position returns to NEUTRAL."
        )
        cofr = f"C:{conf} | O:exit-sell | F:EXIT_SELL | R:SetupBroken"
        short = "EXIT SHORT · setup broken"
    else:
        reason = (
            "WAIT: need A4 (trend + close vs EMA9 + "
            f"|EMA gap|>{sep_min:g}%) or CCR BUY (n={ccr_n} reversal) "
            f"({', '.join(notes) if notes else 'incomplete'})."
        )
        cofr = f"C:{conf} | O:incomplete | F:WAIT | R:no-trade"
        short = _short_reason("WAIT", notes=notes, forming=False, sep_min=sep_min)

    return CoachVerdict(
        symbol=sym,
        interval=iv,
        signal=signal,
        confidence=conf,
        reason=reason,
        cofr=cofr,
        price=fill_basis if entry_setup == "ccr" and entry_fill_px is not None else money(price),
        ema9=money(Decimal(str(ema9))),
        ema21=money(Decimal(str(ema21))),
        volume=money(vol) if vol is not None else None,
        volume_avg20=money(vol_avg) if vol_avg is not None else None,
        bar_closed=True,
        stop_loss=sl,
        take_profit=tp,
        risk_reward=rr,
        source=source,
        evaluated_bar_time=bar.time,
        checklist=checklist,
        short_reason=short,
        phase=phase,
        position=position,
        trend=trend,
        entry=entry,
        exit=exit_kind,
        exit_reason=exit_reason,
        entry_setup=entry_setup,
        entry_fill=entry_fill,
        entry_fill_price=money(Decimal(str(entry_fill_px))) if entry_fill_px is not None else None,
        gross_risk_reward=gross_rr,
        net_risk_reward=net_rr,
        rr_blocked=rr_blocked,
        filter_blocked=filter_blocked,
        filters_enabled=buy_filters or {},
        filter_results=buy_filter_results,
        filter_set_id=active_filter_set_id,
        filter_version="buy-filters-v1",
    )
