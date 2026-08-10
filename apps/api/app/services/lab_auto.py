"""Evaluate a promoted Hypothesis Lab profile for paper AUTO execution."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.money import money, to_decimal
from app.research.experiment_engine.runner import Candle, atr
from app.services.coach import CoachVerdict
from app.services.hypothesis_lab import lab_signals, list_hypotheses, normalize_rules
from app.services.prices import ALLOWED_CANDLE_INTERVALS, get_candles, require_asset
from app.services.risk_reward import calculate_net_risk_reward

_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


def promoted_profile(owner_id: int, hypothesis_id: str | None = None) -> dict:
    """Return the requested promoted version, or the most recently promoted one."""
    items = [item for item in list_hypotheses(owner_id) if item.get("paper_profile")]
    if hypothesis_id:
        items = [item for item in items if item["id"] == hypothesis_id]
    if not items:
        raise HTTPException(
            status_code=422,
            detail="Select a promoted Hypothesis Lab paper profile before enabling Lab AUTO.",
        )
    return max(items, key=lambda item: item.get("promoted_at") or "")


def _closed_and_next(candles: list, interval: str) -> tuple[int | None, int | None]:
    """Return signal and following-fill indexes without ever using an open candle."""
    now = int(datetime.now(timezone.utc).timestamp())
    closed = [i for i, candle in enumerate(candles) if candle.time + _SECONDS[interval] <= now]
    if not closed:
        return None, None
    signal_i = closed[-1]
    fill_i = signal_i + 1 if signal_i + 1 < len(candles) else None
    return signal_i, fill_i


async def evaluate_promoted_lab(
    db,
    owner_id: int,
    symbol: str,
    interval: str,
    *,
    hypothesis_id: str | None,
    min_net_rr: float,
    slippage_bps: float,
    spread_bps: float,
    notional_usd: Decimal,
) -> tuple[CoachVerdict, dict]:
    profile = promoted_profile(owner_id, hypothesis_id)
    rules = normalize_rules(profile["structured_rules"])
    requested_symbol, requested_interval = symbol.upper(), interval.lower()
    rule_symbol = rules["symbol"].replace("USDT", "")
    if requested_symbol != rule_symbol or requested_interval != rules["interval"]:
        raise HTTPException(
            status_code=422,
            detail=f"Lab {profile['id']} v{profile['version']} requires {rule_symbol} {rules['interval']}.",
        )
    if rules["htf"] not in ALLOWED_CANDLE_INTERVALS:
        raise HTTPException(status_code=422, detail="Promoted Lab profile has an unsupported HTF interval.")

    sym, iv, source, candles = await get_candles(db, requested_symbol, requested_interval, 500)
    _, _, _, htf_raw = await get_candles(db, requested_symbol, rules["htf"], 500)
    signal_i, fill_i = _closed_and_next(candles, iv)
    asset = require_asset(db, sym)
    if signal_i is None or fill_i is None or len(candles) < 201 or len(htf_raw) < 201:
        return CoachVerdict(
            symbol=sym, interval=iv, signal="WAIT", confidence=0,
            reason="Lab AUTO is waiting for enough closed candle data and a next candle open.",
            cofr="C:0 | O:lab-warmup | F:WAIT | R:closed-bar-only", price=money(0),
            ema9=None, ema21=None, volume=None, volume_avg20=None, bar_closed=False,
            stop_loss=None, take_profit=None, risk_reward=None, source=source,
            evaluated_bar_time=None, brain="Hypothesis Lab",
        ), profile

    bars = [Candle(c.time, float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume or 0)) for c in candles[: signal_i + 1]]
    htf = [Candle(c.time, float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume or 0)) for c in htf_raw]
    signals, reasons = lab_signals(rules, bars, htf)
    signal_bar, fill_bar = bars[-1], candles[fill_i]
    entry = to_decimal(fill_bar.open)
    atr14 = atr(bars)
    triggered = signals[-1] and atr14[-1] is not None
    reason = reasons[-1] or "No Lab entry filters passed."
    if not triggered:
        return CoachVerdict(
            symbol=sym, interval=iv, signal="WAIT", confidence=65,
            reason=f"LAB {profile['id']} v{profile['version']}: WAIT — {reason}",
            cofr="C:65 | O:lab | F:WAIT | R:filters", price=to_decimal(signal_bar.close),
            ema9=None, ema21=None, volume=to_decimal(signal_bar.volume), volume_avg20=None,
            bar_closed=True, stop_loss=None, take_profit=None, risk_reward=None, source=source,
            evaluated_bar_time=signal_bar.time, brain="Hypothesis Lab", entry_setup="lab",
            entry_fill="next_open", entry_fill_price=entry,
        ), profile

    stop = (
        entry - to_decimal(atr14[-1]) * Decimal(str(rules["stop"]["atr_multiple"]))
        if rules["stop"]["type"] == "atr"
        else to_decimal(signal_bar.low)
    )
    if stop <= 0 or stop >= entry:
        raise HTTPException(status_code=422, detail="Lab profile produced an invalid long stop.")
    target = entry + (entry - stop) * Decimal(str(rules["r_target"]))
    settings = get_settings()
    rr = calculate_net_risk_reward(
        entry=entry, stop_loss=stop, take_profit=target,
        fee_percent=to_decimal(settings.paper_trading_fee_percent),
        fee_usd_per_fill=to_decimal(settings.paper_trading_fee_usd),
        notional_usd=notional_usd, slippage_bps_per_side=Decimal(str(slippage_bps)),
        spread_bps=Decimal(str(spread_bps)),
    )
    blocked = rr.net_rr < Decimal(str(min_net_rr))
    return CoachVerdict(
        symbol=sym, interval=iv, signal="WAIT" if blocked else "BUY", confidence=85,
        reason=(
            f"LAB {profile['id']} v{profile['version']} {'blocked by' if blocked else 'ENTRY BUY'}: "
            f"{reason}. Closed bar → next open {entry}; ATR stop {stop}; {rules['r_target']}R target {target}."
        ),
        cofr=f"C:85 | O:lab | F:{'WAIT' if blocked else 'ENTRY_BUY'} | R:closed→next-open",
        price=to_decimal(signal_bar.close), ema9=None, ema21=None, volume=to_decimal(signal_bar.volume),
        volume_avg20=None, bar_closed=True, stop_loss=money(stop), take_profit=money(target),
        risk_reward=f"1:{rr.net_rr:.2f}", source=source, evaluated_bar_time=signal_bar.time,
        brain="Hypothesis Lab", short_reason=f"Lab {profile['id']} v{profile['version']} · {reason}",
        phase="NONE" if blocked else "ENTRY_BUY", position="NEUTRAL" if blocked else "LONG",
        entry="NONE" if blocked else "ENTRY_BUY", entry_setup="lab", entry_fill="next_open",
        entry_fill_price=entry, gross_risk_reward=f"1:{rr.gross_rr:.2f}",
        net_risk_reward=f"1:{rr.net_rr:.2f}", rr_blocked=blocked,
    ), profile
