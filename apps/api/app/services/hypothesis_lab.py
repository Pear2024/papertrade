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
DEFAULT_RULES: dict[str, Any] = {
    "symbol": "BTCUSDT", "interval": "15m", "htf": "1h",
    "filters": {"ema_trend": True, "htf_ema200": False, "volume_multiple": None,
                "rsi_min": None, "rsi_max": None, "adx_min": None, "breakout_bars": None},
    "stop": {"type": "atr", "atr_multiple": 1.0}, "r_target": 2.0,
    # Chart overlay periods (visual only). Empty → Market chart falls back to 9+21.
    "chart_emas": [],
}
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
"adx_min":null,"breakout_bars":null},"stop":{"type":"atr","atr_multiple":1.0},
"r_target":2.0,"chart_emas":[9,21]}
Supported symbols: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ADAUSDT.
Intervals: 1m, 5m, 15m, 1h, 4h, 1d. HTF intervals: 1h, 4h, 1d.
Use only EMA trend, HTF EMA200, volume multiple, RSI min/max, ADX minimum,
breakout bars, stop type atr or bar_low, R targets 1.5, 2, 2.5, or 3, and
chart_emas (up to 5 distinct periods 2–500 for Market chart overlays).
When the user mentions EMA periods (e.g. EMA9, EMA 50, EMA200), include them in
chart_emas. If ema_trend is true include 9 and 21; if htf_ema200 is true include 200.
Leave unspecified values at the defaults shown above."""


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
            for name in ("ema_trend", "htf_ema200"):
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

        stop = source.get("stop")
        if isinstance(stop, dict):
            if isinstance(stop.get("type"), str) and stop["type"] in {"atr", "bar_low"}:
                normalized["stop"]["type"] = stop["type"]
            multiplier = _number(stop.get("atr_multiple"), 0.1, 10.0)
            if multiplier is not None:
                normalized["stop"]["atr_multiple"] = multiplier

        if "chart_emas" in source:
            normalized["chart_emas"] = normalize_ema_periods(source.get("chart_emas"))

    low, high = normalized["filters"]["rsi_min"], normalized["filters"]["rsi_max"]
    if low is not None and high is not None and low > high:
        normalized["filters"]["rsi_min"], normalized["filters"]["rsi_max"] = high, low
    # Additive overlays: explicit periods + filter-derived 9/21 and/or 200.
    normalized["chart_emas"] = resolve_chart_emas(
        normalized,
        explicit=list(normalized.get("chart_emas") or []),
    )
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


def parse_prompt(prompt: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate common Thai/English terms deterministically; no LLM is required."""
    text = prompt.lower()
    parsed = normalize_rules(rules)
    filters = parsed["filters"]
    if any(word in text for word in ("ema cross", "ema9", "ema 9", "ตัด ema", "อีเอ็มเอ")):
        filters["ema_trend"] = True
    if any(word in text for word in ("htf", "1h", "hourly", "ema200", "ema 200", "เทรนด์ใหญ่")):
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
    if breakout is not None:
        filters["breakout_bars"] = int(breakout)
    elif "breakout" in text or "เบรกเอาท์" in text:
        filters["breakout_bars"] = 20
    target = _number_after(r"(\d+(?:\.\d+)?)\s*r\b", text)
    if target in (1.5, 2, 2.5, 3):
        parsed["r_target"] = float(target)
    atr_multiple = _number_after(r"atr.{0,15}?(\d+(?:\.\d+)?)\s*x", text)
    if atr_multiple is not None:
        parsed["stop"] = {"type": "atr", "atr_multiple": float(atr_multiple)}
    if "bar low" in text or "low ของแท่ง" in text:
        parsed["stop"] = {"type": "bar_low", "atr_multiple": 1.0}
    symbol = re.search(r"\b(BTC|ETH|SOL|XRP|BNB|ADA)USDT?\b", prompt.upper())
    if symbol:
        parsed["symbol"] = symbol.group(0).replace("USDT", "") + "USDT"
    # Chart overlays from explicit periods in the prompt (plus filter mapping in normalize).
    parsed["chart_emas"] = resolve_chart_emas(
        parsed,
        prompt,
        explicit=list(parsed.get("chart_emas") or []),
    )
    return normalize_rules(parsed)


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
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            logger.warning("Hypothesis Lab LLM parsing failed; using rules engine: %s", exc)
            rules = parse_prompt(prompt, structured_rules)
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
    signals, reasons = [False] * len(bars), [""] * len(bars)
    warmup = max(200, int(filters.get("breakout_bars") or 0), 20)
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
            lookback = int(filters["breakout_bars"])
            checks.append((bar.close > max(x.high for x in bars[i - lookback:i]), f"close>prior {lookback}-bar high"))
        signals[i] = bool(checks) and all(passed for passed, _ in checks)
        reasons[i] = "; ".join(label for _, label in checks)
    return signals, reasons


def access_status(db: Session, owner_id: int, plan: str) -> dict[str, Any]:
    """Free users receive a small daily quota; Pro unlocks promotion."""
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
        "plan": normalized_plan, "backtests_today": int(used),
        "daily_backtest_limit": None if normalized_plan == "pro" else 3,
        "can_promote": normalized_plan == "pro",
        "upgrade_message": None if normalized_plan == "pro" else "Upgrade to Pro to unlock unlimited tests and paper-profile promotion.",
    }


async def run_backtest(
    db: Session,
    owner_id: int,
    plan: str,
    hypothesis_id: str,
    bars_count: int = 3000,
) -> dict[str, Any]:
    status = access_status(db, owner_id, plan)
    if status["daily_backtest_limit"] is not None and status["backtests_today"] >= status["daily_backtest_limit"]:
        raise PermissionError("Free plan limit reached (3 backtests/day). Upgrade to Pro for unlimited backtests.")
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
    # `bar_low` remains a transparent approximation in this MVP; its simulation
    # uses one ATR until a dedicated bar-low bracket model is added.
    periods = {
        "development": simulate(strategy, bars, signals, reasons, float(rules["r_target"]), costs, 10_000, .005, 48, 200, dev_end, atr_multiple),
        "oos": simulate(strategy, bars, signals, reasons, float(rules["r_target"]), costs, 10_000, .005, 48, dev_end, oos_end, atr_multiple),
        "paper": simulate(strategy, bars, signals, reasons, float(rules["r_target"]), costs, 10_000, .005, 48, oos_end, len(bars), atr_multiple),
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
    if plan != "pro":
        raise PermissionError("Paper-profile promotion is a Pro feature. Upgrade to continue.")
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