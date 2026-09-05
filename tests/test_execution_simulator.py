from treasury_futures_execution_analytics_tca_engine.execution_metrics import compute_execution_metrics
from treasury_futures_execution_analytics_tca_engine.execution_simulator import simulate_execution
from treasury_futures_execution_analytics_tca_engine.execution_types import ExecutionDecision
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def _base_events() -> list[MBOEvent]:
    return [
        MBOEvent(ts_ns=1, action="ADD", order_id=100, side="B", price_ticks=100, size=5),
        MBOEvent(ts_ns=2, action="ADD", order_id=200, side="A", price_ticks=101, size=5),
        MBOEvent(ts_ns=3, action="CANCEL", order_id=100, size=3),
        MBOEvent(ts_ns=4, action="TRADE", order_id=0, side="A", price_ticks=100, size=4),
        MBOEvent(ts_ns=5, action="FILL", order_id=100, side="B", price_ticks=100, size=2),
        MBOEvent(ts_ns=6, action="CANCEL", order_id=100, size=2),
    ]


def test_simulator_level_depletion_fills_after_queue_advance() -> None:
    events = _base_events()
    decisions = [
        ExecutionDecision(
            ts_ns=2,
            action="NEW",
            client_order_id=1,
            side="B",
            price_ticks=100,
            size=3,
        )
    ]
    result = simulate_execution(events, decisions=decisions, queue_model="level_depletion")
    assert len(result.fills) == 1
    assert result.fills[0].client_order_id == 1
    assert result.fills[0].size == 2
    assert result.fills[0].price_ticks == 100
    assert result.market_trade_volume == 4


def test_simulator_trade_only_is_more_conservative() -> None:
    events = _base_events()
    decisions = [
        ExecutionDecision(
            ts_ns=2,
            action="NEW",
            client_order_id=1,
            side="B",
            price_ticks=100,
            size=3,
        )
    ]
    result = simulate_execution(events, decisions=decisions, queue_model="trade_only")
    assert len(result.fills) == 0


def test_execution_metrics_basic_fields_present() -> None:
    events = _base_events()
    decisions = [
        ExecutionDecision(
            ts_ns=2,
            action="NEW",
            client_order_id=1,
            side="B",
            price_ticks=100,
            size=3,
        )
    ]
    result = simulate_execution(events, decisions=decisions, queue_model="level_depletion")
    metrics = compute_execution_metrics(result)
    assert metrics["fills"] == 1
    assert metrics["filled_qty"] == 2
    assert "markout" in metrics
    assert "message_to_fill_ratio" in metrics

