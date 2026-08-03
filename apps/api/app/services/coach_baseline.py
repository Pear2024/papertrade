"""Baseline promotion policy — never silently overwrite locked rules.

Current: A4 (EMA9 close + separation > 50). Archives: A_v1, A2, A3.
"""

from __future__ import annotations

ACTIVE_BASELINE = "A4"
ACTIVE_BASELINE_NAME = "DayTradeCryptoCoach"
ACTIVE_BASELINE_ID = "A4_ema9_close_sep50"
ARCHIVED_BASELINE = "A3"
ARCHIVED_MODULE = "coach_brain_archive_a3"

CANDIDATE_EXPERIMENT = "B"
CANDIDATE_NAME = "DayTradeCryptoCoach-Experiment-B"

PROMOTE_REQUIRES_ENV = "CONFIRM_PROMOTE_BASELINE"


def promotion_status(*, paper_b_better_markets: int, markets_tested: int) -> dict:
    return {
        "active_baseline": ACTIVE_BASELINE,
        "active_baseline_id": ACTIVE_BASELINE_ID,
        "archived_baseline": ARCHIVED_BASELINE,
        "candidate": CANDIDATE_EXPERIMENT,
        "markets_tested": markets_tested,
        "b_better_markets": paper_b_better_markets,
        "evidence_clear_for_human_review": False,
        "auto_promote": False,
        "action": (
            "A4 hypothesis live: trend + close vs EMA9 + |EMA gap|>0.10% of price. "
            "Keep paper auto on; review win rate after 200–500 trades."
        ),
    }
