"""Offline-first, immutable hypothesis parsing and causal backtests for the Lab."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import LabBacktest, LabHypothesis, User
from app.research.experiment_engine.runner import (
    Costs,
    Strategy,
    adx,
    atr,
    ema,
    fetch_bars,
    metrics,
    rsi,
    simulate,
    verdict,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "research_outputs" / "hypothesis_lab"
STORE_PATH = OUTPUT_ROOT / "hypotheses.json"
# Paper practice philosophy: quality setups only; WAIT/NO TRADE when incomplete.
ASSISTANT_DEFAULT: dict[str, Any] = {
    "philosophy": None,  # "trade_to_live" when template/keywords apply
    "prefer_wait": True,
    "min_rr": 2.0,
    "max_trades_per_week_hint": 3,
    "require_ltf_confirmation": True,
    "steps": ["trend", "sr_zones", "confirmation", "risk_reward", "decision"],
}
DEFAULT_SWING_LOOKBACK = 3
SUPPORTED_STOP_TYPES = {"atr", "bar_low", "structure", "higher_low"}
DEFAULT_RULES: dict[str, Any] = {
    "symbol": "BTCUSDT", "interval": "15m", "htf": "1h",
    "filters": {
        "ema_trend": True,
        "htf_ema200": False,
        "volume_multiple": None,
        "rsi_min": None,
        "rsi_max": None,
        "adx_min": None,
        "breakout_bars": None,
        # Structure: confirmed higher low + close above prior swing high (not Donchian).
        "higher_low": False,
        "break_swing_high": False,
        "swing_lookback": DEFAULT_SWING_LOOKBACK,
    },
    "stop": {"type": "atr", "atr_multiple": 1.0, "buffer_pct": 0.0},
    "r_target": 2.0,
    # Chart overlay periods (visual only). Empty → Market chart falls back to 9+21.
    "chart_emas": [],
    "assistant": dict(ASSISTANT_DEFAULT),
}
# Ready-made Lab prompt (English). Practice goals only — not income promises.
TRADE_TO_LIVE_PROMPT = (
    "BTCUSDT 15m Trade-to-Live single setup: LONG only in a clear uptrend "
    "(EMA9 above EMA21 and close above EMA9; 1h close above EMA200). "
    "Treat support/resistance as zones — never enter only because price touches a level. "
    "Confirm on the closed 15m bar (bullish rejection / reclaim of EMA9, buyers defending the zone, "
    "volume at least 1.5x). ATR 1x stop below structure; take profit at least 2R (prefer 2.5–3R). "
    "If trend is unclear, no closed-bar confirmation, or RR below 1:2 → WAIT / NO TRADE. "
    "Quality over quantity (~1–3 high-quality paper setups per week)."
)
SUPPORTED_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT"}
SUPPORTED_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}
SUPPORTED_HTF_INTERVALS = {"1h", "4h", "1d"}
SUPPORTED_R_TARGETS = {1.5, 2.0, 2.5, 3.0}
MAX_CHART_EMAS = 5
EMA_PERIOD_MIN = 2
EMA_PERIOD_MAX = 500
logger = logging.getLogger(__name__)

LLM_SYSTEM_PROMPT = """Extract a trading hypothesis into JSON only. This is parsing,
not investment advice: do not add commentary, explanations, profitability claims, or
new rules. Return only this supported shape:
{"symbol":"BTCUSDT","interval":"15m","htf":"1h","filters":{"ema_trend":true,
"htf_ema200":false,"volume_multiple":null,"rsi_min":null,"rsi_max":null,
"adx_min":null,"breakout_bars":null,"higher_low":false,"break_swing_high":false,
"swing_lookback":3},"stop":{"type":"atr","atr_multiple":1.0,"buffer_pct":0.0},
"r_target":2.0,"chart_emas":[9,21],
"assistant":{"philosophy":null,"prefer_wait":true,"min_rr":2.0,
"max_trades_per_week_hint":3,"require_ltf_confirmation":true,
"steps":["trend","sr_zones","confirmation","risk_reward","decision"]}}
Supported symbols: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ADAUSDT.
Intervals: 1m, 5m, 15m, 1h, 4h, 1d. HTF intervals: 1h, 4h, 1d.
CRITICAL: Extract primary interval and HTF from the user text when present.
Examples: "BTC 1h" or "interval 1h" → interval "1h"; "htf 4h" / "4h" as higher TF
→ htf "4h". Do NOT keep the schema example defaults (15m/1h) when the prompt
specifies other timeframes. "Stop 3 ATR, target 3R" → atr_multiple 3.0, r_target 3.0.
Use only EMA trend, HTF EMA200, volume multiple, RSI min/max, ADX minimum,
breakout_bars (Donchian N-bar high ONLY when user says N-bar / Donchian breakout),
higher_low (confirmed higher low / HL), break_swing_high (close above prior swing high),
stop type atr | bar_low | structure | higher_low, optional buffer_pct under HL,
R targets 1.5, 2, 2.5, or 3, and chart_emas (up to 5 distinct periods 2–500).
When the user says higher low + swing high breakout, set higher_low and
break_swing_high true and do NOT set breakout_bars. Stop below HL / structure →
stop.type "structure" (or "higher_low"). ATR wording → stop.type "atr".
Closed-bar / no entry before breakout candle closes → prefer_wait true and
require_ltf_confirmation true.
When the user mentions EMA periods (e.g. EMA9, EMA 50, EMA200), include them in
chart_emas. If ema_trend is true include 9 and 21; if htf_ema200 is true include 200.
If the prompt mentions Trade-to-Live, single setup, quality over quantity, WAIT/NO TRADE,
or min RR 1:2, set assistant.philosophy to "trade_to_live", prefer_wait true, min_rr 2.0,
and r_target to at least 2.0. Never invent trades when filters are incomplete.
Leave unspecified values at the defaults shown above."""

# Rank for comparing primary vs higher timeframe (larger = slower).
_INTERVAL_RANK = {"1m": 1, "5m": 2, "15m": 3, "1h": 4, "4h": 5, "1d": 6}
_TF_TOKEN = r"(1m|5m|15m|1h|4h|1d)"


def _fresh_defaults() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_RULES))


def _number(value: Any, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_ema_periods(values: Any) -> list[int]:
    """Dedupe, bound, and cap EMA periods for chart overlays."""
    if not isinstance(values, (list, tuple)):
        return []
    periods: list[int] = []
    seen: set[int] = set()
    for raw in values:
        if isinstance(raw, bool):
            continue
        try:
            period = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
        if period < EMA_PERIOD_MIN or period > EMA_PERIOD_MAX or period in seen:
            continue
        seen.add(period)
        periods.append(period)
    # Prefer shorter periods when over the overlay budget.
    return sorted(periods)[:MAX_CHART_EMAS]


def extract_ema_periods_from_text(prompt: str) -> list[int]:
    """Pull EMA periods from English/Thai natural language (chart overlay config)."""
    if not prompt:
        return []
    text = prompt.lower()
    found: list[int] = []
    # EMA9 · EMA 21 · EMA 12 and 26 · อีเอ็มเอ 50, 200
    for match in re.finditer(
        r"(?:ema|อีเอ็มเอ)\s*[-_]?\s*(\d{1,3})"
        r"((?:\s*(?:,|and|และ|&|/)\s*(?:(?:ema|อีเอ็มเอ)\s*[-_]?)?\d{1,3})*)",
        text,
        re.I,
    ):
        found.append(int(match.group(1)))
        for num in re.findall(r"\d{1,3}", match.group(2) or ""):
            found.append(int(num))
    return normalize_ema_periods(found)


def resolve_chart_emas(
    rules: dict[str, Any],
    prompt: str = "",
    *,
    explicit: list[int] | None = None,
) -> list[int]:
    """Merge explicit periods, prompt mentions, and filter-derived EMAs (max 5)."""
    periods: list[int] = []
    if explicit is not None:
        periods.extend(explicit)
    else:
        periods.extend(rules.get("chart_emas") or [])
    periods.extend(extract_ema_periods_from_text(prompt))
    filters = rules.get("filters") or {}
    if filters.get("ema_trend"):
        periods.extend([9, 21])
    if filters.get("htf_ema200"):
        periods.append(200)
    return normalize_ema_periods(periods)


def normalize_rules(candidate: dict[str, Any] | None, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Accept only the Lab's supported schema and safe bounded values."""
    normalized = _fresh_defaults()
    for source in (base, candidate):
        if not isinstance(source, dict):
            continue
        symbol = str(source.get("symbol", "")).upper()
        if symbol in SUPPORTED_SYMBOLS:
            normalized["symbol"] = symbol
        interval = source.get("interval")
        if isinstance(interval, str) and interval in SUPPORTED_INTERVALS:
            normalized["interval"] = interval
        htf = source.get("htf")
        if isinstance(htf, str) and htf in SUPPORTED_HTF_INTERVALS:
            normalized["htf"] = htf
        if _number(source.get("r_target"), 0, 10) in SUPPORTED_R_TARGETS:
            normalized["r_target"] = float(source["r_target"])

        filters = source.get("filters")
        if isinstance(filters, dict):
            for name in ("ema_trend", "htf_ema200", "higher_low", "break_swing_high"):
                if isinstance(filters.get(name), bool):
                    normalized["filters"][name] = filters[name]
            for name, minimum, maximum in (
                ("volume_multiple", 0.1, 10.0),
                ("rsi_min", 0.0, 100.0),
                ("rsi_max", 0.0, 100.0),
                ("adx_min", 0.0, 100.0),
            ):
                if filters.get(name) is None:
                    normalized["filters"][name] = None
                else:
                    value = _number(filters.get(name), minimum, maximum)
                    if value is not None:
                        normalized["filters"][name] = value
            breakout = _number(filters.get("breakout_bars"), 2, 200)
            if filters.get("breakout_bars") is None:
                normalized["filters"]["breakout_bars"] = None
            elif breakout is not None:
                normalized["filters"]["breakout_bars"] = int(round(breakout))
            swing_lb = _number(filters.get("swing_lookback"), 2, 20)
            if swing_lb is not None:
                normalized["filters"]["swing_lookback"] = int(round(swing_lb))

        stop = source.get("stop")
        if isinstance(stop, dict):
            if isinstance(stop.get("type"), str) and stop["type"] in SUPPORTED_STOP_TYPES:
                normalized["stop"]["type"] = stop["type"]
            multiplier = _number(stop.get("atr_multiple"), 0.1, 10.0)
            if multiplier is not None:
                normalized["stop"]["atr_multiple"] = multiplier
            buffer_pct = _number(stop.get("buffer_pct"), 0.0, 5.0)
            if buffer_pct is not None:
                normalized["stop"]["buffer_pct"] = float(buffer_pct)
            elif "buffer_pct" not in normalized["stop"]:
                normalized["stop"]["buffer_pct"] = 0.0

        if "chart_emas" in source:
            normalized["chart_emas"] = normalize_ema_periods(source.get("chart_emas"))

        assistant = source.get("assistant")
        if isinstance(assistant, dict):
            out_assistant = dict(normalized.get("assistant") or ASSISTANT_DEFAULT)
            philosophy = assistant.get("philosophy")
            if philosophy in {None, "trade_to_live"}:
                out_assistant["philosophy"] = philosophy
            if isinstance(assistant.get("prefer_wait"), bool):
                out_assistant["prefer_wait"] = assistant["prefer_wait"]
            min_rr = _number(assistant.get("min_rr"), 1.0, 10.0)
            if min_rr is not None:
                out_assistant["min_rr"] = float(min_rr)
            week_hint = _number(assistant.get("max_trades_per_week_hint"), 1, 20)
            if week_hint is not None:
                out_assistant["max_trades_per_week_hint"] = int(round(week_hint))
            if isinstance(assistant.get("require_ltf_confirmation"), bool):
                out_assistant["require_ltf_confirmation"] = assistant["require_ltf_confirmation"]
            steps = assistant.get("steps")
            if isinstance(steps, list) and steps:
                out_assistant["steps"] = [str(step) for step in steps[:8]]
            normalized["assistant"] = out_assistant

    low, high = normalized["filters"]["rsi_min"], normalized["filters"]["rsi_max"]
    if low is not None and high is not None and low > high:
        normalized["filters"]["rsi_min"], normalized["filters"]["rsi_max"] = high, low
    # Additive overlays: explicit periods + filter-derived 9/21 and/or 200.
    normalized["chart_emas"] = resolve_chart_emas(
        normalized,
        explicit=list(normalized.get("chart_emas") or []),
    )
    # Trade-to-Live / assistant gate: never allow planned R below min_rr (default 2.0).
    assistant = normalized.get("assistant") or ASSISTANT_DEFAULT
    min_rr = float(assistant.get("min_rr") or 2.0)
    if float(normalized.get("r_target") or 0) < min_rr:
        # Snap up to the smallest supported target meeting min_rr.
        eligible = sorted(r for r in SUPPORTED_R_TARGETS if r >= min_rr)
        normalized["r_target"] = float(eligible[0] if eligible else 2.0)
    return normalized


def _parse_json_content(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object")
    return normalize_rules(parsed)


def _ollama_rules(prompt: str) -> dict[str, Any]:
    settings = get_settings()
    base_url = settings.ollama_base_url.rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(2.0, read=15.0)) as client:
        client.get(f"{base_url}/api/tags").raise_for_status()
        response = client.post(
            f"{base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "system", "content": LLM_SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
    return _parse_json_content(response.json()["message"]["content"])


def _groq_rules(prompt: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("Groq is not configured")
    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        json={
            "model": settings.groq_model,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": LLM_SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return _parse_json_content(response.json()["choices"][0]["message"]["content"])


def _gemini_rules(prompt: str) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.gemini_api_key or settings.google_api_key
    if not api_key:
        raise RuntimeError("Gemini is not configured")
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
        params={"key": api_key},
        json={
            "systemInstruction": {"parts": [{"text": LLM_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return _parse_json_content(response.json()["candidates"][0]["content"]["parts"][0]["text"])


def _parse_prompt_with_llm_provider(prompt: str) -> tuple[dict[str, Any], str]:
    """Try free providers in order; errors are deliberately handled by the caller."""
    settings = get_settings()
    errors: list[str] = []
    local_first = settings.environment.lower() not in {"production", "prod"}
    providers = [
        ("ollama", _ollama_rules, bool(settings.ollama_base_url)),
        ("groq", _groq_rules, bool(settings.groq_api_key)),
        ("gemini", _gemini_rules, bool(settings.gemini_api_key or settings.google_api_key)),
    ]
    # A deployed API cannot normally reach a visitor's laptop. Prefer its
    # configured Groq key in production, while local development stays Ollama-first.
    if not local_first and settings.groq_api_key:
        providers[0], providers[1] = providers[1], providers[0]
    for provider, parser, configured in providers:
        if not configured:
            continue
        try:
            return parser(prompt), provider
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{provider}: {exc}")
    raise RuntimeError("; ".join(errors) or "No free LLM provider is configured")


def parse_prompt_with_llm(prompt: str) -> dict[str, Any]:
    """Parse with the preferred available free LLM provider."""
    rules, _ = _parse_prompt_with_llm_provider(prompt)
    return rules


def _number_after(pattern: str, text: str, default: float | int | None = None) -> float | int | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return default
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def _normalize_tf_token(raw: str) -> str | None:
    token = raw.strip().lower().replace(" ", "")
    # Thai / prose expansions → canonical intervals.
    prose = {
        "1min": "1m",
        "1minute": "1m",
        "5min": "5m",
        "5minute": "5m",
        "15min": "15m",
        "15minute": "15m",
        "1hour": "1h",
        "1hr": "1h",
        "hourly": "1h",
        "4hour": "4h",
        "4hr": "4h",
        "1day": "1d",
        "daily": "1d",
    }
    token = prose.get(token, token)
    if token in SUPPORTED_INTERVALS:
        return token
    return None


def _next_htf_above(interval: str) -> str | None:
    rank = _INTERVAL_RANK.get(interval, 0)
    for candidate in ("1h", "4h", "1d"):
        if _INTERVAL_RANK[candidate] > rank:
            return candidate
    return None


def _parse_timeframes_from_prompt(text: str) -> tuple[str | None, str | None]:
    """Extract primary interval and HTF from Thai/English prompt text.

    Returns (interval, htf) where None means unspecified (keep defaults / LLM).
    Explicit HTF labels win over ambiguous dual mentions; symbol-adjacent TF
    (e.g. "BTC 1h") is treated as primary.
    """
    lowered = text.lower()
    # Expand common Thai timeframe phrases before token matching.
    lowered = (
        lowered.replace("15 นาที", "15m")
        .replace("15นาที", "15m")
        .replace("5 นาที", "5m")
        .replace("1 นาที", "1m")
        .replace("1 ชั่วโมง", "1h")
        .replace("1ชั่วโมง", "1h")
        .replace("1 ชม", "1h")
        .replace("1ชม", "1h")
        .replace("4 ชั่วโมง", "4h")
        .replace("4ชั่วโมง", "4h")
        .replace("4 ชม", "4h")
        .replace("4ชม", "4h")
        .replace("รายวัน", "1d")
        .replace("วันละครั้ง", "1d")
    )

    explicit_htf: str | None = None
    for pattern in (
        rf"(?:htf|higher\s*(?:time\s*)?frame|higher\s*tf|เทรนด์ใหญ่|ไทม์เฟรมใหญ่)"
        rf"\s*[:=]?\s*{_TF_TOKEN}",
        rf"(?:on|on the)\s+{_TF_TOKEN}\s+(?:close|ema|trend|htf)",
        rf"{_TF_TOKEN}\s+close\s+above\s+ema",
        rf"(?:htf|higher)\s+[^\d]{{0,12}}{_TF_TOKEN}",
    ):
        match = re.search(pattern, lowered, re.I)
        if match:
            token = _normalize_tf_token(match.group(1))
            if token and token in SUPPORTED_HTF_INTERVALS:
                explicit_htf = token
                break

    explicit_interval: str | None = None
    for pattern in (
        rf"(?:interval|timeframe|time\s*frame|primary|entry\s*tf|ltf|"
        rf"ไทม์เฟรม|ช่วงเวลา|แท่ง)\s*[:=]?\s*{_TF_TOKEN}",
        rf"\btf\b\s*[:=]?\s*{_TF_TOKEN}",
        rf"\b(?:btc|eth|sol|xrp|bnb|ada)(?:usdt)?\s+{_TF_TOKEN}\b",
    ):
        match = re.search(pattern, lowered, re.I)
        if match:
            token = _normalize_tf_token(match.group(1))
            if token:
                explicit_interval = token
                break

    # Collect all interval tokens with positions for fallback / dual TF.
    mentions = [
        (_normalize_tf_token(m.group(1)), m.start())
        for m in re.finditer(rf"\b{_TF_TOKEN}\b", lowered, re.I)
    ]
    mentions = [(tf, pos) for tf, pos in mentions if tf]

    interval = explicit_interval
    htf = explicit_htf

    if interval is None and mentions:
        # Prefer first non-HTF-context mention as primary.
        for tf, pos in mentions:
            window = lowered[max(0, pos - 24) : pos]
            if re.search(r"(?:htf|higher|เทรนด์ใหญ่|ไทม์เฟรมใหญ่)\s*$", window):
                continue
            if htf and tf == htf:
                continue
            interval = tf
            break
        if interval is None:
            interval = mentions[0][0]

    if htf is None and mentions:
        # Second distinct slower TF often means HTF (e.g. "15m ... 1h EMA200").
        for tf, _pos in mentions:
            if interval and tf == interval:
                continue
            if tf in SUPPORTED_HTF_INTERVALS and (
                interval is None or _INTERVAL_RANK[tf] > _INTERVAL_RANK.get(interval, 0)
            ):
                htf = tf
                break

    return interval, htf


def _parse_atr_multiple(text: str) -> float | None:
    """Parse ATR stop multiple from phrases like 'ATR 1.5x', 'Stop 3 ATR', '3 ATR stop'."""
    for pattern in (
        r"atr.{0,15}?(\d+(?:\.\d+)?)\s*x",
        r"(?:stop|stoploss|sl|หยุดขาดทุน).{0,24}?(\d+(?:\.\d+)?)\s*atr",
        r"(\d+(?:\.\d+)?)\s*atr(?:\s*(?:stop|x|เท่า|stoploss|sl))?",
        r"atr\s*[:=]?\s*(\d+(?:\.\d+)?)",
    ):
        value = _number_after(pattern, text)
        if value is not None and 0.1 <= float(value) <= 10.0:
            return float(value)
    return None


def _parse_r_target(text: str) -> float | None:
    """Parse R target from '3R', 'target 3R', 'take profit 2.5R'."""
    for pattern in (
        r"(?:target|tp|take\s*profit|เป้า|เป้าหมาย).{0,20}?(\d+(?:\.\d+)?)\s*r\b",
        r"(\d+(?:\.\d+)?)\s*r\b",
        r"(?:rr|r\s*:\s*r|risk\s*reward).{0,12}?(?:1\s*:\s*)?(\d+(?:\.\d+)?)",
    ):
        value = _number_after(pattern, text)
        if value in SUPPORTED_R_TARGETS or value in (1.5, 2, 2.5, 3, 2.0, 3.0):
            return float(value)
    return None


def parse_prompt(prompt: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate common Thai/English terms deterministically; no LLM is required."""
    text = prompt.lower()
    parsed = normalize_rules(rules)
    filters = parsed["filters"]

    interval, htf = _parse_timeframes_from_prompt(text)
    if interval:
        parsed["interval"] = interval
    if htf:
        parsed["htf"] = htf
    elif interval and _INTERVAL_RANK.get(str(parsed.get("htf")), 0) <= _INTERVAL_RANK.get(interval, 0):
        # Primary moved up to/above previous HTF and user did not name HTF → bump.
        bumped = _next_htf_above(interval)
        if bumped:
            parsed["htf"] = bumped

    if any(word in text for word in ("ema cross", "ema9", "ema 9", "ตัด ema", "อีเอ็มเอ")):
        filters["ema_trend"] = True
    # HTF EMA200 filter: require EMA200 / trend language — not bare "1h" as primary TF.
    if any(word in text for word in ("ema200", "ema 200", "เทรนด์ใหญ่")) or re.search(
        r"(?:htf|higher\s*(?:time\s*)?frame).{0,40}(?:ema|close|trend)",
        text,
        re.I,
    ) or re.search(rf"{_TF_TOKEN}\s+close\s+above\s+ema", text, re.I):
        filters["htf_ema200"] = True
    volume = _number_after(r"(?:volume|vol|ปริมาณ).{0,20}?(\d+(?:\.\d+)?)\s*(?:x|เท่า)", text)
    if volume is not None:
        filters["volume_multiple"] = float(volume)
    elif any(word in text for word in ("volume confirm", "volume สูง", "วอลุ่ม")):
        filters["volume_multiple"] = 1.5
    rsi_range = re.search(r"rsi.{0,20}?(\d+(?:\.\d+)?)\s*(?:-|–|to|ถึง)\s*(\d+(?:\.\d+)?)", text, re.I)
    if rsi_range:
        filters["rsi_min"], filters["rsi_max"] = float(rsi_range.group(1)), float(rsi_range.group(2))
    adx_min = _number_after(r"adx.{0,15}?(?:>|มากกว่า|เหนือ)\s*(\d+(?:\.\d+)?)", text)
    if adx_min is not None:
        filters["adx_min"] = float(adx_min)
    breakout = _number_after(r"(?:breakout|เบรก).{0,25}?(\d+)\s*(?:bar|แท่ง)", text)
    structure_break = _mentions_structure_breakout(text)
    if structure_break:
        filters["higher_low"] = True
        filters["break_swing_high"] = True
        # Prefer WAIT until HL + closed breakout candle confirm.
        assistant = dict(parsed.get("assistant") or ASSISTANT_DEFAULT)
        assistant["prefer_wait"] = True
        assistant["require_ltf_confirmation"] = True
        parsed["assistant"] = assistant
    elif breakout is not None:
        filters["breakout_bars"] = int(breakout)
    elif ("breakout" in text or "เบรกเอาท์" in text) and not _mentions_swing_or_hl(text):
        filters["breakout_bars"] = 20
    if _mentions_higher_low(text):
        filters["higher_low"] = True
    if _mentions_swing_high_break(text):
        filters["break_swing_high"] = True
    target = _parse_r_target(text)
    if target in SUPPORTED_R_TARGETS:
        parsed["r_target"] = float(target)
    atr_multiple = _parse_atr_multiple(text)
    if atr_multiple is not None:
        parsed["stop"] = {"type": "atr", "atr_multiple": float(atr_multiple), "buffer_pct": 0.0}
    if "bar low" in text or "low ของแท่ง" in text:
        parsed["stop"] = {"type": "bar_low", "atr_multiple": 1.0, "buffer_pct": 0.0}
    if _mentions_structure_stop(text):
        parsed["stop"] = {
            "type": "structure",
            "atr_multiple": float((parsed.get("stop") or {}).get("atr_multiple") or 1.0),
            "buffer_pct": float((parsed.get("stop") or {}).get("buffer_pct") or 0.0),
        }
    if any(phrase in text for phrase in (
        "no entry before",
        "closed candle only",
        "closed-bar",
        "closed bar",
        "breakout candle closes",
        "candle closes",
        "รอแท่งปิด",
        "ปิดแท่ง",
    )):
        assistant = dict(parsed.get("assistant") or ASSISTANT_DEFAULT)
        assistant["prefer_wait"] = True
        assistant["require_ltf_confirmation"] = True
        parsed["assistant"] = assistant
    symbol = re.search(r"\b(BTC|ETH|SOL|XRP|BNB|ADA)USDT?\b", prompt.upper())
    if symbol:
        parsed["symbol"] = symbol.group(0).replace("USDT", "") + "USDT"
    # Trade-to-Live / quality-assistant keywords → stricter paper filters + WAIT bias.
    if _is_trade_to_live_prompt(text):
        assistant = dict(parsed.get("assistant") or ASSISTANT_DEFAULT)
        assistant["philosophy"] = "trade_to_live"
        assistant["prefer_wait"] = True
        assistant["min_rr"] = max(float(assistant.get("min_rr") or 2.0), 2.0)
        assistant["require_ltf_confirmation"] = True
        parsed["assistant"] = assistant
        filters["ema_trend"] = True
        filters["htf_ema200"] = True
        if filters.get("volume_multiple") is None:
            filters["volume_multiple"] = 1.5
        if float(parsed.get("r_target") or 0) < 2.0:
            parsed["r_target"] = 2.0
    # Chart overlays from explicit periods in the prompt (plus filter mapping in normalize).
    parsed["chart_emas"] = resolve_chart_emas(
        parsed,
        prompt,
        explicit=list(parsed.get("chart_emas") or []),
    )
    return normalize_rules(parsed)


def _mentions_higher_low(text: str) -> bool:
    return bool(
        re.search(r"higher\s*lows?|confirmed\s*hl|\bhl\b|higher\s*low|โลว์สูงขึ้น|ไฮเออร์โลว์", text, re.I)
    )


def _mentions_swing_high_break(text: str) -> bool:
    return bool(
        re.search(
            r"(?:closes?\s+above|break(?:s|ing)?|above).{0,40}swing\s*high|"
            r"swing\s*high.{0,40}(?:break|closes?\s+above)|"
            r"previous\s+swing\s+high|prior\s+swing\s+high|"
            r"สวิงไฮ|เหนือสวิง",
            text,
            re.I,
        )
    )


def _mentions_swing_or_hl(text: str) -> bool:
    return _mentions_higher_low(text) or "swing" in text or "สวิง" in text


def _mentions_structure_breakout(text: str) -> bool:
    """HL + swing-high break language (not Donchian N-bar breakout)."""
    return _mentions_higher_low(text) and _mentions_swing_high_break(text)


def _mentions_structure_stop(text: str) -> bool:
    """True when stop is the HL/structure low — not ATR sized 'below structure'."""
    hl_stop = bool(
        re.search(
            r"stop.{0,40}(?:below|under).{0,40}(?:confirmed\s+)?(?:higher\s*low|\bhl\b)",
            text,
            re.I,
        )
        or re.search(
            r"(?:below|under).{0,20}(?:confirmed\s+)?(?:higher\s*low|\bhl\b).{0,20}stop",
            text,
            re.I,
        )
        or "stop below the confirmed higher low" in text
        or "ใต้ higher low" in text
        or "ใต้ hl" in text
        or "สต็อปใต้โครงสร้าง" in text
    )
    if hl_stop:
        return True
    # Bare "stop below structure" only when ATR is not the sized stop method.
    if "stop below structure" in text or "สต็อปใต้ structure" in text:
        if _parse_atr_multiple(text) is not None or re.search(r"\batr\b", text):
            return False
        return True
    return False


def _is_trade_to_live_prompt(text: str) -> bool:
    needles = (
        "trade-to-live",
        "trade to live",
        "single setup",
        "quality over quantity",
        "wait / no trade",
        "wait/no trade",
        "no trade",
        "rr 1:2",
        "1:2",
        "min rr",
        "เทรดเพื่อใช้ชีวิต",
        "ท่าเทรดเดียว",
        "อิสรภาพ",
    )
    return any(needle in text for needle in needles)


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _loads_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _hypothesis_to_dict(row: LabHypothesis) -> dict[str, Any]:
    backtests: list[dict[str, Any]] = []
    for run in sorted(row.backtests, key=lambda item: item.ran_at or datetime.min.replace(tzinfo=timezone.utc)):
        payload = _loads_json(run.result_json, {})
        if isinstance(payload, dict):
            payload.setdefault("id", run.public_id)
            payload.setdefault("ran_at", _iso(run.ran_at))
            backtests.append(payload)
    return {
        "id": row.public_id,
        "owner_id": row.user_id,
        "version": row.version,
        "name": row.name,
        "natural_language_prompt": row.natural_language_prompt,
        "structured_rules": _loads_json(row.structured_rules_json, _fresh_defaults()),
        "parser": row.parser,
        "created_at": _iso(row.created_at) or "",
        "updated_at": _iso(row.updated_at) or "",
        "backtests": backtests,
        "promoted_at": _iso(row.promoted_at),
        "paper_profile": _loads_json(row.paper_profile_json, None),
    }


def _get_owned(db: Session, owner_id: int, hypothesis_id: str) -> LabHypothesis:
    row = db.scalar(
        select(LabHypothesis)
        .options(selectinload(LabHypothesis.backtests))
        .where(LabHypothesis.public_id == hypothesis_id, LabHypothesis.user_id == owner_id)
    )
    if row is None:
        raise KeyError("Hypothesis not found")
    return row


def migrate_json_store(db: Session) -> int:
    """Best-effort one-time import from the legacy shared JSON file."""
    if not STORE_PATH.exists():
        return 0
    try:
        rows = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Hypothesis Lab JSON migrate skipped: %s", exc)
        return 0
    if not isinstance(rows, list) or not rows:
        return 0

    imported = 0
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        public_id = str(raw.get("id") or "").strip()
        owner_id = raw.get("owner_id")
        if not public_id or not isinstance(owner_id, int):
            continue
        if db.scalar(select(LabHypothesis.id).where(LabHypothesis.public_id == public_id)):
            continue
        if not db.scalar(select(User.id).where(User.id == owner_id)):
            logger.warning("Skipping Lab JSON row %s — owner %s missing", public_id, owner_id)
            continue
        now = datetime.now(timezone.utc)
        hypothesis = LabHypothesis(
            public_id=public_id,
            user_id=owner_id,
            version=str(raw.get("version") or "1.0.0")[:32],
            name=str(raw.get("name") or "Structured hypothesis")[:120],
            natural_language_prompt=str(raw.get("natural_language_prompt") or ""),
            structured_rules_json=json.dumps(
                normalize_rules(raw.get("structured_rules") if isinstance(raw.get("structured_rules"), dict) else None)
            ),
            parser=str(raw.get("parser") or "regex")[:32],
            promoted_at=_parse_dt(raw.get("promoted_at")),
            paper_profile_json=(
                json.dumps(raw["paper_profile"])
                if isinstance(raw.get("paper_profile"), dict)
                else None
            ),
            created_at=_parse_dt(raw.get("created_at")) or now,
            updated_at=_parse_dt(raw.get("updated_at")) or now,
        )
        db.add(hypothesis)
        db.flush()
        for run in raw.get("backtests") or []:
            if not isinstance(run, dict):
                continue
            run_id = str(run.get("id") or f"run-{uuid.uuid4().hex[:10]}")
            if db.scalar(select(LabBacktest.id).where(LabBacktest.public_id == run_id)):
                continue
            db.add(
                LabBacktest(
                    public_id=run_id,
                    hypothesis_id=hypothesis.id,
                    ran_at=_parse_dt(run.get("ran_at")) or now,
                    result_json=json.dumps(run),
                )
            )
        imported += 1
    if imported:
        db.commit()
        logger.info("Migrated %s Hypothesis Lab rows from JSON store", imported)
    return imported


def create_hypothesis(
    db: Session,
    owner_id: int,
    prompt: str,
    name: str | None,
    structured_rules: dict[str, Any] | None,
) -> dict[str, Any]:
    if not prompt.strip() and not structured_rules:
        raise ValueError("Describe a hypothesis or provide structured rules.")
    parser = "regex"
    if prompt.strip():
        try:
            rules, parser = _parse_prompt_with_llm_provider(prompt)
            rules = normalize_rules(structured_rules, rules)
            # LLM may omit chart_emas; always merge periods mentioned in the prompt.
            rules["chart_emas"] = resolve_chart_emas(
                rules,
                prompt,
                explicit=list(rules.get("chart_emas") or []),
            )
            # Re-apply Trade-to-Live / quality gates even when an LLM parsed the shape.
            rules = parse_prompt(prompt, rules)
            # Keep the LLM parser label when the provider succeeded.
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            logger.warning("Hypothesis Lab LLM parsing failed; using rules engine: %s", exc)
            rules = parse_prompt(prompt, structured_rules)
            parser = "regex"
    else:
        rules = normalize_rules(structured_rules)
    now = datetime.now(timezone.utc)
    row = LabHypothesis(
        public_id=f"lab-{uuid.uuid4().hex[:10]}",
        user_id=owner_id,
        version="1.0.0",
        name=(name or prompt.strip()[:80] or "Structured hypothesis")[:120],
        natural_language_prompt=prompt,
        structured_rules_json=json.dumps(rules),
        parser=parser,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _hypothesis_to_dict(row)


def list_hypotheses(db: Session, owner_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LabHypothesis)
        .options(selectinload(LabHypothesis.backtests))
        .where(LabHypothesis.user_id == owner_id)
        .order_by(LabHypothesis.created_at.desc(), LabHypothesis.id.desc())
    ).all()
    return [_hypothesis_to_dict(row) for row in rows]


def get_hypothesis(db: Session, owner_id: int, hypothesis_id: str) -> dict[str, Any]:
    return _hypothesis_to_dict(_get_owned(db, owner_id, hypothesis_id))


def delete_hypothesis(db: Session, owner_id: int, hypothesis_id: str) -> None:
    """Hard-delete an owned hypothesis and its backtests (cascade)."""
    row = _get_owned(db, owner_id, hypothesis_id)
    db.delete(row)
    db.commit()


def _is_pivot_low(bars: list, pivot: int, lookback: int) -> bool:
    low = bars[pivot].low
    left = min(bars[j].low for j in range(pivot - lookback, pivot))
    right = min(bars[j].low for j in range(pivot + 1, pivot + lookback + 1))
    return low < left and low < right


def _is_pivot_high(bars: list, pivot: int, lookback: int) -> bool:
    high = bars[pivot].high
    left = max(bars[j].high for j in range(pivot - lookback, pivot))
    right = max(bars[j].high for j in range(pivot + 1, pivot + lookback + 1))
    return high > left and high > right


def _confirmed_swing_lows(bars: list, as_of: int, lookback: int) -> list[tuple[int, float]]:
    """Swing lows confirmed by `as_of` (pivot needs `lookback` bars after it)."""
    out: list[tuple[int, float]] = []
    for pivot in range(lookback, as_of - lookback + 1):
        if _is_pivot_low(bars, pivot, lookback):
            out.append((pivot, bars[pivot].low))
    return out


def _confirmed_swing_highs(bars: list, as_of: int, lookback: int) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    for pivot in range(lookback, as_of - lookback + 1):
        if _is_pivot_high(bars, pivot, lookback):
            out.append((pivot, bars[pivot].high))
    return out


def structure_setup_at(
    bars: list,
    i: int,
    *,
    lookback: int = DEFAULT_SWING_LOOKBACK,
) -> dict[str, Any] | None:
    """
    Bullish HL → break prior swing high setup at closed bar i.

    Pattern: swing low L1 → swing high H between → swing low L2 (L2.low > L1.low),
    then close[i] above H. Entry is evaluated only on closed bars (caller fills next open).
    """
    if i < lookback * 2 + 2 or i >= len(bars):
        return None
    lows = _confirmed_swing_lows(bars, i, lookback)
    highs = _confirmed_swing_highs(bars, i, lookback)
    if len(lows) < 2:
        return None
    # Prefer the newest higher-low pair that still has a swing high between them.
    for l2_idx in range(len(lows) - 1, 0, -1):
        l2_pivot, l2_low = lows[l2_idx]
        for l1_idx in range(l2_idx - 1, -1, -1):
            l1_pivot, l1_low = lows[l1_idx]
            if l2_low <= l1_low:
                continue
            between = [h for h in highs if l1_pivot < h[0] < l2_pivot]
            if not between:
                continue
            # Break the highest swing high between the two lows (structure resistance).
            swing_pivot, swing_high = max(between, key=lambda item: item[1])
            return {
                "higher_low": True,
                "hl_low": float(l2_low),
                "hl_pivot": l2_pivot,
                "prior_low": float(l1_low),
                "prior_low_pivot": l1_pivot,
                "swing_high": float(swing_high),
                "swing_high_pivot": swing_pivot,
                "break_swing_high": bars[i].close > swing_high,
            }
    return None


def structure_stop_price(
    rules: dict[str, Any],
    bars: list,
    i: int,
) -> float | None:
    """Absolute stop below confirmed HL low when stop.type is structure/higher_low."""
    stop = rules.get("stop") or {}
    if stop.get("type") not in {"structure", "higher_low"}:
        return None
    lookback = int((rules.get("filters") or {}).get("swing_lookback") or DEFAULT_SWING_LOOKBACK)
    setup = structure_setup_at(bars, i, lookback=lookback)
    if not setup or setup.get("hl_low") is None:
        return None
    buffer_pct = float(stop.get("buffer_pct") or 0.0) / 100.0
    level = float(setup["hl_low"]) * (1.0 - buffer_pct)
    return level if level > 0 else None


def lab_signals(rules: dict[str, Any], bars: list, htf: list) -> tuple[list[bool], list[str]]:
    closes = [bar.close for bar in bars]
    e9, e21, rsi14, adx14 = ema(closes, 9), ema(closes, 21), rsi(closes), adx(bars)
    htf_closes, htf_ema200 = [bar.close for bar in htf], ema([bar.close for bar in htf], 200)
    seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    base_seconds, htf_seconds = seconds[rules["interval"]], seconds[rules["htf"]]
    htf_index: list[int | None] = []
    pointer = -1
    for bar in bars:
        signal_close = bar.time + base_seconds
        while pointer + 1 < len(htf) and htf[pointer + 1].time + htf_seconds <= signal_close:
            pointer += 1
        htf_index.append(pointer if pointer >= 0 else None)
    filters = rules["filters"]
    lookback = int(filters.get("swing_lookback") or DEFAULT_SWING_LOOKBACK)
    structure_on = bool(filters.get("higher_low") or filters.get("break_swing_high"))
    signals, reasons = [False] * len(bars), [""] * len(bars)
    warmup = max(200, int(filters.get("breakout_bars") or 0), lookback * 2 + 5, 20)
    for i in range(warmup, len(bars)):
        bar = bars[i]
        checks: list[tuple[bool, str]] = []
        if filters.get("ema_trend"):
            checks.append((bool(e9[i] and e21[i] and e9[i] > e21[i] and bar.close > e9[i]), "EMA9>EMA21; close>EMA9"))
        if filters.get("htf_ema200"):
            hi = htf_index[i]
            checks.append((bool(hi is not None and htf_ema200[hi] and htf_closes[hi] > htf_ema200[hi]), "completed HTF close>EMA200"))
        if filters.get("volume_multiple"):
            multiple = float(filters["volume_multiple"])
            prior_avg = sum(x.volume for x in bars[i - 20:i]) / 20
            checks.append((bar.volume > multiple * prior_avg, f"volume>{multiple:g}x prior VolMA20"))
        if filters.get("rsi_min") is not None or filters.get("rsi_max") is not None:
            low, high = float(filters.get("rsi_min") or 0), float(filters.get("rsi_max") or 100)
            checks.append((rsi14[i] is not None and low <= rsi14[i] <= high, f"RSI14 {low:g}..{high:g}"))
        if filters.get("adx_min") is not None:
            minimum = float(filters["adx_min"])
            checks.append((adx14[i] is not None and adx14[i] >= minimum, f"ADX14>={minimum:g}"))
        if filters.get("breakout_bars"):
            n = int(filters["breakout_bars"])
            checks.append((bar.close > max(x.high for x in bars[i - n:i]), f"close>prior {n}-bar high"))
        if structure_on:
            setup = structure_setup_at(bars, i, lookback=lookback)
            if filters.get("higher_low"):
                checks.append((bool(setup and setup.get("higher_low")), "confirmed higher low"))
            if filters.get("break_swing_high"):
                if setup is not None:
                    checks.append(
                        (
                            bool(setup.get("break_swing_high")),
                            f"close>prior swing high ({setup['swing_high']:.4g})",
                        )
                    )
                else:
                    # No HL pair yet — still require a broken prior swing high when possible.
                    highs = _confirmed_swing_highs(bars, i, lookback)
                    if highs:
                        level = highs[-1][1]
                        checks.append((bar.close > level, f"close>prior swing high ({level:.4g})"))
                    else:
                        checks.append((False, "close>prior swing high"))
        signals[i] = bool(checks) and all(passed for passed, _ in checks)
        if signals[i]:
            reasons[i] = "; ".join(label for _, label in checks)
        elif checks:
            failed = [label for passed, label in checks if not passed]
            reasons[i] = (
                "WAIT — incomplete setup (missing: "
                + "; ".join(failed)
                + "). Prefer NO TRADE until trend + closed-bar confirmation + RR ≥ 1:2."
            )
        else:
            reasons[i] = "WAIT — no Lab filters configured."
    return signals, reasons


def access_status(db: Session, owner_id: int, plan: str) -> dict[str, Any]:
    """Paper path is Free-first while Stripe billing stays optional later."""
    today = datetime.now(timezone.utc).date()
    day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    used = db.scalar(
        select(func.count())
        .select_from(LabBacktest)
        .join(LabHypothesis, LabBacktest.hypothesis_id == LabHypothesis.id)
        .where(LabHypothesis.user_id == owner_id, LabBacktest.ran_at >= day_start)
    ) or 0
    normalized_plan = "pro" if plan == "pro" else "free"
    return {
        "plan": normalized_plan,
        "backtests_today": int(used),
        # Temporarily unlimited for Free so friends can paper-test without Stripe.
        "daily_backtest_limit": None,
        "can_promote": True,
        "upgrade_message": None
        if normalized_plan == "pro"
        else "Pro billing coming later — paper testing is free for now.",
    }


async def run_backtest(
    db: Session,
    owner_id: int,
    plan: str,
    hypothesis_id: str,
    bars_count: int = 3000,
) -> dict[str, Any]:
    status = access_status(db, owner_id, plan)
    if (
        status["daily_backtest_limit"] is not None
        and status["backtests_today"] >= status["daily_backtest_limit"]
    ):
        raise PermissionError(
            f"Free plan limit reached ({status['daily_backtest_limit']} backtests/day). "
            "Upgrade to Pro for unlimited backtests."
        )
    hypothesis_row = _get_owned(db, owner_id, hypothesis_id)
    hypothesis = _hypothesis_to_dict(hypothesis_row)
    rules = hypothesis["structured_rules"]
    bars_count = max(1000, min(bars_count, 10_000))
    bars, source15 = await fetch_bars(rules["interval"], bars_count, rules["symbol"])
    htf_count = max(500, len(bars) // 4 + 250)
    htf, source_htf = await fetch_bars(rules["htf"], htf_count, rules["symbol"])
    signals, reasons = lab_signals(rules, bars, htf)
    dev_end = int(len(bars) * .55)
    oos_end = dev_end + int(len(bars) * .225)
    strategy = Strategy(hypothesis["id"], hypothesis["version"], hypothesis["name"], hypothesis["natural_language_prompt"])
    costs = Costs()
    atr_multiple = float(rules["stop"].get("atr_multiple", 1.0))
    stop_type = str(rules["stop"].get("type") or "atr")
    stop_prices: list[float | None] | None = None
    if stop_type in {"structure", "higher_low"}:
        stop_prices = [structure_stop_price(rules, bars, i) if signals[i] else None for i in range(len(bars))]
    # `bar_low` remains a transparent approximation in this MVP; its simulation
    # uses one ATR until a dedicated bar-low bracket model is added.
    # Structure / higher_low stops use absolute HL lows via stop_prices.
    periods = {
        "development": simulate(
            strategy, bars, signals, reasons, float(rules["r_target"]), costs, 10_000, .005, 48,
            200, dev_end, atr_multiple, stop_prices,
        ),
        "oos": simulate(
            strategy, bars, signals, reasons, float(rules["r_target"]), costs, 10_000, .005, 48,
            dev_end, oos_end, atr_multiple, stop_prices,
        ),
        "paper": simulate(
            strategy, bars, signals, reasons, float(rules["r_target"]), costs, 10_000, .005, 48,
            oos_end, len(bars), atr_multiple, stop_prices,
        ),
    }
    period_metrics = {period: metrics(trades) for period, trades in periods.items()}
    ran_at = datetime.now(timezone.utc)
    result = {
        "id": f"run-{uuid.uuid4().hex[:10]}", "ran_at": ran_at.isoformat(),
        "bars": len(bars), "sources": {"entry": source15, "htf": source_htf},
        "costs": {"fee_rate_per_fill": .008, "spread_bps": 2, "slippage_bps_side": 3},
        "methodology": "Long-only, closed-candle signals, next-open entry, 0.5% risk, 48-bar timeout, stop first if stop/target collide. 0.80% fee per fill plus 2bps spread and 3bps slippage per side. Results are not profitability claims.",
        "periods": period_metrics, "verdict": verdict(period_metrics["development"], period_metrics["oos"]),
        "trade_count": sum(len(value) for value in periods.values()),
    }
    run_dir = OUTPUT_ROOT / hypothesis_id / result["id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (run_dir / "trades.json").write_text(json.dumps([trade.row() for values in periods.values() for trade in values], indent=2), encoding="utf-8")
    db.add(
        LabBacktest(
            public_id=result["id"],
            hypothesis_id=hypothesis_row.id,
            ran_at=ran_at,
            result_json=json.dumps(result),
        )
    )
    hypothesis_row.updated_at = ran_at
    db.commit()
    return result


def promote(db: Session, owner_id: int, plan: str, hypothesis_id: str) -> dict[str, Any]:
    # Free-first: any authenticated owner can save a paper profile for paper AUTO.
    _ = plan
    hypothesis_row = _get_owned(db, owner_id, hypothesis_id)
    rules = _loads_json(hypothesis_row.structured_rules_json, _fresh_defaults())
    now = datetime.now(timezone.utc)
    hypothesis_row.promoted_at = now
    hypothesis_row.paper_profile_json = json.dumps({
        "source": "lab",
        "hypothesis_id": hypothesis_row.public_id,
        "version": hypothesis_row.version,
        "rules": rules,
        "paper_only": True,
    })
    hypothesis_row.updated_at = now
    db.commit()
    db.refresh(hypothesis_row)
    return _hypothesis_to_dict(hypothesis_row)