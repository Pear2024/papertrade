"""Per-user Coach / AUTO preference persistence."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import User, UserCoachSettings

DEFAULT_COACH_SETTINGS: dict[str, Any] = {
    "entrySignal": "lab",
    "labHypothesisId": None,
    "autoStakeUsd": 20000,
    "autoTickSeconds": 60,
    "interval": "15m",
    "autoOnDefault": True,
    "slPct": 2,
    "tpPct": 7.5,
    "tpUsd": 70,
    "leverage": 5,
    "minNetRr": 2,
    "slippageBps": 3,
    "spreadBps": 2,
}

_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}


def _clamp(n: float, minimum: float, maximum: float) -> float:
    if n != n:  # NaN
        return minimum
    return min(maximum, max(minimum, n))


def normalize_coach_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    d = DEFAULT_COACH_SETTINGS
    interval = src.get("interval") if src.get("interval") in _INTERVALS else d["interval"]
    lab_id = src.get("labHypothesisId")
    return {
        "entrySignal": "lab",
        "labHypothesisId": lab_id if isinstance(lab_id, str) else None,
        "autoStakeUsd": _clamp(float(src.get("autoStakeUsd", d["autoStakeUsd"])), 0.5, 20000),
        "autoTickSeconds": int(_clamp(float(src.get("autoTickSeconds", d["autoTickSeconds"])), 15, 600)),
        "interval": interval,
        "autoOnDefault": bool(src.get("autoOnDefault", d["autoOnDefault"])),
        "slPct": _clamp(float(src.get("slPct", d["slPct"])), 0.1, 20),
        "tpPct": _clamp(float(src.get("tpPct", d["tpPct"])), 0.1, 50),
        "tpUsd": _clamp(float(src.get("tpUsd", d["tpUsd"])), 0, 1_000_000),
        "leverage": _clamp(float(src.get("leverage", d["leverage"])), 1, 50),
        "minNetRr": _clamp(float(src.get("minNetRr", d["minNetRr"])), 0.1, 20),
        "slippageBps": _clamp(float(src.get("slippageBps", d["slippageBps"])), 0, 100),
        "spreadBps": _clamp(float(src.get("spreadBps", d["spreadBps"])), 0, 100),
    }


def _row_response(row: UserCoachSettings | None) -> dict[str, Any]:
    if row is None:
        return {
            "settings": dict(DEFAULT_COACH_SETTINGS),
            "auto_session_enabled": None,
        }
    try:
        parsed = json.loads(row.settings_json or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return {
        "settings": normalize_coach_settings(parsed if isinstance(parsed, dict) else {}),
        "auto_session_enabled": row.auto_session_enabled,
    }


def get_coach_settings(db: Session, user: User) -> dict[str, Any]:
    row = db.get(UserCoachSettings, user.id)
    return _row_response(row)


def put_coach_settings(
    db: Session,
    user: User,
    *,
    settings: dict[str, Any] | None = None,
    auto_session_enabled: bool | None = None,
    clear_auto_session: bool = False,
) -> dict[str, Any]:
    row = db.get(UserCoachSettings, user.id)
    current = _row_response(row)
    next_settings = normalize_coach_settings(
        {**current["settings"], **(settings or {})} if settings is not None else current["settings"]
    )
    if clear_auto_session:
        next_auto: bool | None = None
    elif auto_session_enabled is not None:
        next_auto = bool(auto_session_enabled)
    else:
        next_auto = current["auto_session_enabled"]

    if row is None:
        row = UserCoachSettings(
            user_id=user.id,
            settings_json=json.dumps(next_settings),
            auto_session_enabled=next_auto,
        )
        db.add(row)
    else:
        row.settings_json = json.dumps(next_settings)
        row.auto_session_enabled = next_auto
    db.commit()
    db.refresh(row)
    return _row_response(row)


def restore_coach_defaults(db: Session, user: User) -> dict[str, Any]:
    return put_coach_settings(
        db,
        user,
        settings=dict(DEFAULT_COACH_SETTINGS),
        clear_auto_session=True,
    )
