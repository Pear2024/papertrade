"""MetaAlpha Quantum Engine — optional ENTRY meta-label filter (Phase 1).

Default OFF via META_ALPHA_ENABLED. Heavy deps (numpy/pandas/sklearn) are only
imported on the enabled inference path.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "FEATURE_COLS",
    "decide_take_trade",
]


def __getattr__(name: str) -> Any:
    if name == "FEATURE_COLS":
        from app.services.meta_alpha.features import FEATURE_COLS

        return FEATURE_COLS
    if name == "decide_take_trade":
        from app.services.meta_alpha.live_gate import decide_take_trade

        return decide_take_trade
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
