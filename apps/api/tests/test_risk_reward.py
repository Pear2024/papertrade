from decimal import Decimal

from app.services.risk_reward import calculate_net_risk_reward


def test_calculates_gross_and_net_rr_after_round_trip_costs() -> None:
    result = calculate_net_risk_reward(
        entry=Decimal("100"),
        stop_loss=Decimal("98"),
        take_profit=Decimal("105"),
        fee_percent=Decimal("0.80"),
        slippage_bps_per_side=Decimal("3"),
        spread_bps=Decimal("2"),
    )

    assert result.gross_rr == Decimal("2.5")
    # 1.60% fees + 0.06% slippage + 0.02% spread.
    assert result.round_trip_cost_pct == Decimal("0.0168")
    assert result.net_rr.quantize(Decimal("0.01")) == Decimal("0.90")


def test_rejectable_plan_falls_below_two_net_rr() -> None:
    result = calculate_net_risk_reward(
        entry=Decimal("100"),
        stop_loss=Decimal("98"),
        take_profit=Decimal("103"),
        fee_percent=Decimal("0.80"),
        slippage_bps_per_side=Decimal("3"),
        spread_bps=Decimal("2"),
    )

    assert result.gross_rr == Decimal("1.5")
    assert result.net_rr < Decimal("2.0")


def test_flat_fee_uses_actual_notional_instead_of_percent_fee() -> None:
    result = calculate_net_risk_reward(
        entry=Decimal("100"),
        stop_loss=Decimal("98"),
        take_profit=Decimal("105"),
        fee_percent=Decimal("0.80"),
        fee_usd_per_fill=Decimal("9"),
        notional_usd=Decimal("100000"),
        slippage_bps_per_side=Decimal("3"),
        spread_bps=Decimal("2"),
    )

    assert result.net_rr > Decimal("2.0")


def test_seven_point_five_percent_base_target_clears_two_net_rr_with_fee_padding() -> None:
    # Coach adds 1.60% fee cover to the configured 7.5% target, quoting 9.1%.
    result = calculate_net_risk_reward(
        entry=Decimal("100"),
        stop_loss=Decimal("98"),
        take_profit=Decimal("109.1"),
        fee_percent=Decimal("0.80"),
        slippage_bps_per_side=Decimal("3"),
        spread_bps=Decimal("2"),
    )

    assert result.round_trip_cost_pct == Decimal("0.0168")
    assert result.net_rr.quantize(Decimal("0.01")) == Decimal("2.02")
