import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from app.services import hypothesis_lab, lab_auto
from app.services.hypothesis_lab import parse_prompt
from app.research.experiment_engine.runner import Candle
from app.services.prices import CandleBar


def test_parser_maps_english_filters_and_risk() -> None:
    rules = parse_prompt(
        "BTCUSDT 15m EMA cross with 1h EMA200, volume > 1.5x MA, RSI 50-70, ADX > 25, stop ATR 1.5x and 2R"
    )
    assert rules["symbol"] == "BTCUSDT"
    assert rules["filters"]["ema_trend"] is True
    assert rules["filters"]["htf_ema200"] is True
    assert rules["filters"]["volume_multiple"] == 1.5
    assert rules["filters"]["rsi_min"] == 50
    assert rules["filters"]["rsi_max"] == 70
    assert rules["filters"]["adx_min"] == 25
    assert rules["stop"]["atr_multiple"] == 1.5
    assert rules["r_target"] == 2


def test_parser_maps_thai_template() -> None:
    rules = parse_prompt("ซื้อเมื่อ EMA9 ตัด EMA21 และ volume 2 เท่า RSI 45 ถึง 65 target 3R")
    assert rules["filters"]["ema_trend"] is True
    assert rules["filters"]["volume_multiple"] == 2
    assert rules["filters"]["rsi_min"] == 45
    assert rules["filters"]["rsi_max"] == 65
    assert rules["r_target"] == 3


def test_create_hypothesis_records_ollama_parser(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(hypothesis_lab, "STORE_PATH", tmp_path / "hypotheses.json")
    monkeypatch.setattr(
        hypothesis_lab,
        "_parse_prompt_with_llm_provider",
        lambda prompt: (hypothesis_lab.normalize_rules({"symbol": "ETHUSDT"}), "ollama"),
    )

    row = hypothesis_lab.create_hypothesis(1, "ETHUSDT trend continuation", None, None)

    assert row["parser"] == "ollama"
    assert row["structured_rules"]["symbol"] == "ETHUSDT"


def test_create_hypothesis_falls_back_to_rules_engine(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(hypothesis_lab, "STORE_PATH", tmp_path / "hypotheses.json")

    def unavailable(prompt: str) -> tuple[dict, str]:
        raise RuntimeError("Ollama is unavailable")

    monkeypatch.setattr(hypothesis_lab, "_parse_prompt_with_llm_provider", unavailable)
    row = hypothesis_lab.create_hypothesis(1, "BTCUSDT volume 2x and 3R", None, None)

    assert row["parser"] == "regex"
    assert row["structured_rules"]["filters"]["volume_multiple"] == 2
    assert row["structured_rules"]["r_target"] == 3


def test_llm_output_is_limited_to_supported_rules() -> None:
    rules = hypothesis_lab._parse_json_content(
        """{"symbol":"DOGEUSDT","interval":"invalid","filters":{"volume_multiple":99,
        "rsi_min":90,"rsi_max":10,"unknown":true},"stop":{"type":"anything",
        "atr_multiple":99},"r_target":99,"extra":"ignored"}"""
    )

    assert rules["symbol"] == "BTCUSDT"
    assert rules["interval"] == "15m"
    assert rules["filters"]["volume_multiple"] == 10
    assert (rules["filters"]["rsi_min"], rules["filters"]["rsi_max"]) == (10, 90)
    assert rules["stop"] == {"type": "atr", "atr_multiple": 10}
    assert rules["r_target"] == 2


def test_lab_signal_requires_closed_rule_filters_before_entry() -> None:
    rules = hypothesis_lab.normalize_rules({
        "filters": {"ema_trend": True, "volume_multiple": 1.5},
    })
    bars = [
        Candle(i * 900, 100 + i, 101 + i, 99 + i, 100 + i, 10)
        for i in range(210)
    ]
    bars[-1] = Candle(209 * 900, 309, 311, 308, 310, 20)
    htf = [
        Candle(i * 3600, 100 + i, 101 + i, 99 + i, 100 + i, 10)
        for i in range(210)
    ]

    signals, reasons = hypothesis_lab.lab_signals(rules, bars, htf)

    assert signals[-1] is True
    assert "EMA9>EMA21" in reasons[-1]
    assert "volume>1.5x" in reasons[-1]


def test_promoted_lab_signal_becomes_next_open_entry(monkeypatch) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    start = (now // 900 - 209) * 900
    candles = [
        CandleBar(start + i * 900, Decimal(100 + i), Decimal(101 + i), Decimal(99 + i), Decimal(100 + i), Decimal("10"))
        for i in range(210)
    ]
    # The final candle is forming; only candle 208 may decide the entry at 209 open.
    candles[208] = CandleBar(candles[208].time, Decimal(308), Decimal(310), Decimal(307), Decimal(309), Decimal("20"))
    htf = [
        CandleBar((now // 3600 - 209 + i) * 3600, Decimal(100 + i), Decimal(101 + i), Decimal(99 + i), Decimal(100 + i), Decimal("10"))
        for i in range(210)
    ]
    profile = {
        "id": "lab-entry", "version": "1.0.0", "promoted_at": "2026-01-01T00:00:00Z",
        "structured_rules": hypothesis_lab.normalize_rules({
            "filters": {"volume_multiple": 1.5},
            "stop": {"type": "atr", "atr_multiple": 5},
        }),
    }

    async def candles_for_test(*_args, **_kwargs):
        return "BTC", "15m", "test", candles if _args[2] == "15m" else htf

    monkeypatch.setattr(lab_auto, "promoted_profile", lambda *_args, **_kwargs: profile)
    monkeypatch.setattr(lab_auto, "get_candles", candles_for_test)
    monkeypatch.setattr(lab_auto, "require_asset", lambda *_args: object())

    verdict, used = asyncio.run(lab_auto.evaluate_promoted_lab(
        None, 1, "BTC", "15m", hypothesis_id="lab-entry", min_net_rr=0.1,
        slippage_bps=3, spread_bps=2, notional_usd=Decimal("1000"),
    ))

    assert used["id"] == "lab-entry"
    assert verdict.signal == "BUY"
    assert verdict.phase == "ENTRY_BUY"
    assert verdict.entry_fill == "next_open"
    assert verdict.entry_fill_price == candles[209].open
