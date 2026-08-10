"""Pure, execution-cost-aware risk/reward calculations for planned trades.

Costs are applied pessimistically at both entry and exit.  A full quoted spread
is split equally between the two sides of an execution, so each fill includes
half the spread plus configured adverse slippage and exchange fee.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RiskReward:
    gross_risk_pct: Decimal
    gross_reward_pct: Decimal
    round_trip_cost_pct: Decimal
    net_risk_pct: Decimal
    net_reward_pct: Decimal
    gross_rr: Decimal
    net_rr: Decimal


def calculate_net_risk_reward(
    *,
    entry: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal,
    fee_percent: Decimal = Decimal("0"),
    fee_usd_per_fill: Decimal = Decimal("0"),
    notional_usd: Decimal | None = None,
    slippage_bps_per_side: Decimal = Decimal("3"),
    spread_bps: Decimal = Decimal("2"),
) -> RiskReward:
    """Calculate gross and net R:R as price fractions, with no market data access.

    ``fee_percent`` is percentage points (0.80 means 0.80%). When an explicit
    flat paper-fee override is configured, ``fee_usd_per_fill / notional_usd``
    replaces it.
    Net reward deducts round-trip execution cost; net risk adds the same cost.
    This makes the outcome conservative for either a long or short plan.
    """
    if entry <= 0:
        raise ValueError("entry must be positive")
    if notional_usd is not None and notional_usd <= 0:
        raise ValueError("notional_usd must be positive when provided")

    gross_risk = abs(entry - stop_loss) / entry
    gross_reward = abs(take_profit - entry) / entry
    if gross_risk <= 0:
        raise ValueError("stop_loss must differ from entry")

    fee_per_side = (
        fee_usd_per_fill / notional_usd
        if fee_usd_per_fill > 0 and notional_usd is not None
        else fee_percent / Decimal("100")
    )
    impact_per_side = (
        fee_per_side
        + slippage_bps_per_side / Decimal("10000")
        + spread_bps / Decimal("20000")
    )
    round_trip_cost = impact_per_side * Decimal("2")
    net_risk = gross_risk + round_trip_cost
    net_reward = max(Decimal("0"), gross_reward - round_trip_cost)

    return RiskReward(
        gross_risk_pct=gross_risk,
        gross_reward_pct=gross_reward,
        round_trip_cost_pct=round_trip_cost,
        net_risk_pct=net_risk,
        net_reward_pct=net_reward,
        gross_rr=gross_reward / gross_risk,
        net_rr=net_reward / net_risk,
    )
