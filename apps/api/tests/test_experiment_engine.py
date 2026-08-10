from app.research.experiment_engine.runner import Candle, Costs, Strategy, completed_h1_map, simulate


def candle(time: int, open_: float = 100, high: float = 101, low: float = 99, close: float = 100) -> Candle:
    return Candle(time, open_, high, low, close, 100)


def test_htf_mapping_only_uses_completed_hour() -> None:
    hourly = [candle(0), candle(3600)]
    fifteen = [candle(2700), candle(3600), candle(6300), candle(7200)]
    # The bar opening at 3600 is unavailable until its close at 7200.
    assert completed_h1_map(fifteen, hourly) == [0, 0, 1, 1]


def test_simulation_uses_stop_first_for_same_bar_collision() -> None:
    bars = [candle(i * 900) for i in range(205)]
    # Signal at 200; following entry bar touches both ATR stop and target.
    bars[201] = candle(201 * 900, 100, 110, 90, 100)
    signals, reasons = [False] * len(bars), [""] * len(bars)
    signals[200], reasons[200] = True, "test trigger"
    # ATR on flat 100-price history is zero, so create enough range before signal.
    bars[199] = candle(199 * 900, 100, 101, 99, 100)
    trades = simulate(Strategy("T", "1.0.0", "test", "test"), bars, signals, reasons, 1.5, Costs(fee_rate=0), 10_000, 0.005, 48)
    assert len(trades) == 1
    assert trades[0].exit_reason == "stop"
