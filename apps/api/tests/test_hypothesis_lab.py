import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AccountMode, Asset, RiskRule, TradingAccount, User
from app.research.experiment_engine.runner import Candle
from app.services import hypothesis_lab, lab_auto
from app.services.hypothesis_lab import parse_prompt
from app.services.prices import CandleBar


def test_parser_maps_english_filters_and_risk() -> None:
    rules = parse_prompt(
        "BTCUSDT 15m EMA cross with 1h EMA200, volume > 1.5x MA, RSI 50-70, ADX > 25, stop ATR 1.5x and 2R"
    )
    assert rules["symbol"] == "BTCUSDT"
    assert rules["interval"] == "15m"
    assert rules["htf"] == "1h"
    assert rules["filters"]["ema_trend"] is True
    assert rules["filters"]["htf_ema200"] is True
    assert rules["filters"]["volume_multiple"] == 1.5
    assert rules["filters"]["rsi_min"] == 50
    assert rules["filters"]["rsi_max"] == 70
    assert rules["filters"]["adx_min"] == 25
    assert rules["stop"]["atr_multiple"] == 1.5
    assert rules["r_target"] == 2
    assert rules["chart_emas"] == [9, 21, 200]


def test_parser_respects_btc_1h_primary_interval() -> None:
    """Regression: 'BTC 1h' must not stay on default 15m/1h."""
    rules = parse_prompt("BTC 1h EMA cross, volume 1.5x, Stop 3 ATR, target 3R")
    assert rules["symbol"] == "BTCUSDT"
    assert rules["interval"] == "1h"
    assert rules["htf"] == "4h"  # bumped above primary when HTF unspecified
    assert rules["stop"]["atr_multiple"] == 3.0
    assert rules["r_target"] == 3.0


def test_parser_interval_1h_with_explicit_htf_4h() -> None:
    rules = parse_prompt(
        "BTCUSDT interval 1h, HTF 4h close above EMA200, EMA9/21 trend, volume 1.5x, 2R"
    )
    assert rules["interval"] == "1h"
    assert rules["htf"] == "4h"
    assert rules["filters"]["htf_ema200"] is True


def test_parser_overrides_llm_default_timeframes() -> None:
    """Deterministic overlay must win when LLM left schema defaults."""
    llm_defaults = hypothesis_lab.normalize_rules({"interval": "15m", "htf": "1h"})
    rules = parse_prompt(
        "BTC 1h HTF 4h EMA trend, Stop 3 ATR, target 3R",
        llm_defaults,
    )
    assert rules["interval"] == "1h"
    assert rules["htf"] == "4h"
    assert rules["stop"]["atr_multiple"] == 3.0
    assert rules["r_target"] == 3.0


def test_parser_thai_timeframes() -> None:
    rules = parse_prompt("BTC ไทม์เฟรม 1h เทรนด์ใหญ่ 4h EMA200 volume 1.5x 2R")
    assert rules["interval"] == "1h"
    assert rules["htf"] == "4h"
    assert rules["filters"]["htf_ema200"] is True


def test_parser_bare_1h_is_not_enough_for_htf_ema200() -> None:
    rules = parse_prompt("BTC 1h EMA9 cross EMA21 volume 1.5x 2R")
    assert rules["interval"] == "1h"
    assert rules["filters"]["htf_ema200"] is False


def test_parser_defaults_when_timeframe_unspecified() -> None:
    rules = parse_prompt("EMA cross volume 1.5x 2R")
    assert rules["interval"] == "15m"
    assert rules["htf"] == "1h"


def test_parser_maps_thai_template() -> None:
    rules = parse_prompt("ซื้อเมื่อ EMA9 ตัด EMA21 และ volume 2 เท่า RSI 45 ถึง 65 target 3R")
    assert rules["filters"]["ema_trend"] is True
    assert rules["filters"]["volume_multiple"] == 2
    assert rules["filters"]["rsi_min"] == 45
    assert rules["filters"]["rsi_max"] == 65
    assert rules["r_target"] == 3
    assert rules["chart_emas"] == [9, 21]


def test_trade_to_live_template_sets_assistant_and_min_rr() -> None:
    rules = parse_prompt(hypothesis_lab.TRADE_TO_LIVE_PROMPT)
    assert rules["assistant"]["philosophy"] == "trade_to_live"
    assert rules["assistant"]["prefer_wait"] is True
    assert rules["assistant"]["min_rr"] >= 2.0
    assert rules["assistant"]["require_ltf_confirmation"] is True
    assert rules["filters"]["ema_trend"] is True
    assert rules["filters"]["htf_ema200"] is True
    assert rules["filters"]["volume_multiple"] == 1.5
    assert rules["r_target"] >= 2.0
    assert 9 in rules["chart_emas"] and 21 in rules["chart_emas"] and 200 in rules["chart_emas"]


def test_normalize_enforces_assistant_min_rr() -> None:
    rules = hypothesis_lab.normalize_rules({
        "r_target": 1.5,
        "assistant": {"philosophy": "trade_to_live", "min_rr": 2.0},
    })
    assert rules["r_target"] == 2.0
    assert rules["assistant"]["philosophy"] == "trade_to_live"


def test_parser_extracts_custom_chart_ema_periods() -> None:
    rules = parse_prompt(
        "BTCUSDT draw EMA 12 and 26 on the chart, volume 1.5x, stop ATR 1x, 2R",
        {"filters": {"ema_trend": False, "htf_ema200": False}},
    )
    assert rules["chart_emas"] == [12, 26]


def test_parser_extracts_thai_ema_periods() -> None:
    rules = parse_prompt(
        "ใช้ อีเอ็มเอ 50 และ อีเอ็มเอ200 เป็นเส้นบนชาร์ต volume 1.5x 2R",
        {"filters": {"ema_trend": False, "htf_ema200": False}},
    )
    assert 50 in rules["chart_emas"]
    assert 200 in rules["chart_emas"]


def test_normalize_merges_filter_emas_into_chart_overlays() -> None:
    rules = hypothesis_lab.normalize_rules({
        "filters": {"ema_trend": True, "htf_ema200": True},
        "chart_emas": [50],
    })
    assert rules["chart_emas"] == [9, 21, 50, 200]


def test_normalize_caps_chart_emas_at_five() -> None:
    rules = hypothesis_lab.normalize_rules({
        "filters": {"ema_trend": False, "htf_ema200": False},
        "chart_emas": [9, 12, 21, 26, 50, 100, 200],
    })
    assert rules["chart_emas"] == [9, 12, 21, 26, 50]


def _seed_user(db_session: Session, email: str, *, plan: str = "free") -> User:
    user = User(
        email=email,
        password_hash=hash_password("SecurePass1!"),
        display_name=email.split("@")[0],
        subscription_plan=plan,
    )
    db_session.add(user)
    db_session.flush()
    account = TradingAccount(
        user_id=user.id,
        account_name="Paper Account",
        account_mode=AccountMode.paper,
        starting_balance=Decimal("10000"),
        cash_balance=Decimal("10000"),
        realized_pnl=Decimal("0"),
        currency="USD",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(
        RiskRule(
            trading_account_id=account.id,
            max_risk_percent_per_trade=Decimal("50"),
            max_daily_loss_percent=Decimal("50"),
            max_trades_per_day=50,
            require_stop_loss=True,
            trading_enabled=True,
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(client: TestClient, email: str) -> dict[str, str]:
    login = client.post("/auth/login", json={"email": email, "password": "SecurePass1!"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_create_hypothesis_records_ollama_parser(db_session: Session, monkeypatch) -> None:
    user = _seed_user(db_session, "lab-ollama@example.com")
    monkeypatch.setattr(
        hypothesis_lab,
        "_parse_prompt_with_llm_provider",
        lambda prompt: (hypothesis_lab.normalize_rules({"symbol": "ETHUSDT"}), "ollama"),
    )

    row = hypothesis_lab.create_hypothesis(
        db_session, user.id, "ETHUSDT trend continuation", None, None
    )

    assert row["parser"] == "ollama"
    assert row["structured_rules"]["symbol"] == "ETHUSDT"
    assert row["owner_id"] == user.id


def test_create_hypothesis_falls_back_to_rules_engine(db_session: Session, monkeypatch) -> None:
    user = _seed_user(db_session, "lab-regex@example.com")

    def unavailable(prompt: str) -> tuple[dict, str]:
        raise RuntimeError("Ollama is unavailable")

    monkeypatch.setattr(hypothesis_lab, "_parse_prompt_with_llm_provider", unavailable)
    row = hypothesis_lab.create_hypothesis(
        db_session, user.id, "BTCUSDT volume 2x and 3R", None, None
    )

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


def test_hypothesis_lab_owner_isolation(
    client: TestClient,
    db_session: Session,
    seeded_assets: dict[str, Asset],
    monkeypatch,
) -> None:
    _ = seeded_assets
    monkeypatch.setattr(
        hypothesis_lab,
        "_parse_prompt_with_llm_provider",
        lambda prompt: (hypothesis_lab.normalize_rules({"symbol": "BTCUSDT"}), "regex"),
    )
    user_a = _seed_user(db_session, "owner-a@example.com", plan="pro")
    user_b = _seed_user(db_session, "owner-b@example.com", plan="pro")
    header_a = _login(client, "owner-a@example.com")
    header_b = _login(client, "owner-b@example.com")

    created = client.post(
        "/hypothesis-lab",
        headers=header_a,
        json={"prompt": "BTCUSDT EMA cross volume 1.5x 2R", "name": "A only"},
    )
    assert created.status_code == 200
    hyp_id = created.json()["id"]

    list_a = client.get("/hypothesis-lab", headers=header_a)
    list_b = client.get("/hypothesis-lab", headers=header_b)
    assert list_a.status_code == 200
    assert list_b.status_code == 200
    assert any(item["id"] == hyp_id for item in list_a.json()["items"])
    assert all(item["id"] != hyp_id for item in list_b.json()["items"])

    get_b = client.get(f"/hypothesis-lab/{hyp_id}", headers=header_b)
    assert get_b.status_code == 404

    promote_b = client.post(f"/hypothesis-lab/{hyp_id}/promote", headers=header_b)
    assert promote_b.status_code == 404

    promote_a = client.post(f"/hypothesis-lab/{hyp_id}/promote", headers=header_a)
    assert promote_a.status_code == 200
    assert promote_a.json()["promoted_at"] is not None
    assert promote_a.json()["paper_profile"]["hypothesis_id"] == hyp_id

    # Promoted profiles on Market/Coach pickers come from owner-scoped list only.
    promoted_b = [
        item for item in client.get("/hypothesis-lab", headers=header_b).json()["items"]
        if item.get("promoted_at")
    ]
    assert promoted_b == []
    assert user_a.id != user_b.id

    delete_b = client.delete(f"/hypothesis-lab/{hyp_id}", headers=header_b)
    assert delete_b.status_code == 404
    assert any(
        item["id"] == hyp_id
        for item in client.get("/hypothesis-lab", headers=header_a).json()["items"]
    )

    delete_a = client.delete(f"/hypothesis-lab/{hyp_id}", headers=header_a)
    assert delete_a.status_code == 204
    assert all(
        item["id"] != hyp_id
        for item in client.get("/hypothesis-lab", headers=header_a).json()["items"]
    )
    assert client.get(f"/hypothesis-lab/{hyp_id}", headers=header_a).status_code == 404


def test_coach_settings_are_per_user(
    client: TestClient,
    db_session: Session,
    seeded_assets: dict[str, Asset],
) -> None:
    _ = seeded_assets
    _seed_user(db_session, "coach-a@example.com")
    _seed_user(db_session, "coach-b@example.com")
    header_a = _login(client, "coach-a@example.com")
    header_b = _login(client, "coach-b@example.com")

    put_a = client.put(
        "/account/coach-settings",
        headers=header_a,
        json={"settings": {"autoStakeUsd": 1234, "labHypothesisId": "lab-aaa"}, "auto_session_enabled": True},
    )
    assert put_a.status_code == 200
    assert put_a.json()["settings"]["autoStakeUsd"] == 1234
    assert put_a.json()["auto_session_enabled"] is True

    get_b = client.get("/account/coach-settings", headers=header_b)
    assert get_b.status_code == 200
    assert get_b.json()["settings"]["autoStakeUsd"] != 1234
    assert get_b.json()["settings"]["labHypothesisId"] is None
    assert get_b.json()["auto_session_enabled"] is None

    get_a = client.get("/account/coach-settings", headers=header_a)
    assert get_a.json()["settings"]["labHypothesisId"] == "lab-aaa"
