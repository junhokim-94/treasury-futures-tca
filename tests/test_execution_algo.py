from treasury_futures_execution_analytics_tca_engine.engine_compare import run_parallel_comparison
from treasury_futures_execution_analytics_tca_engine.execution_algo import PovLiteConfig, build_pov_lite_executor
from treasury_futures_execution_analytics_tca_engine.execution_simulator import simulate_execution
from treasury_futures_execution_analytics_tca_engine.execution_types import ExecutionDecision
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def test_pov_lite_executor_generates_and_fills_child_orders() -> None:
    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=200),
        MBOEvent(ts_ns=2, action="ADD", order_id=2, side="A", price_ticks=101, size=200),
    ]
    ts = 3
    for _ in range(20):
        events.append(MBOEvent(ts_ns=ts, action="TRADE", order_id=0, side="A", price_ticks=100, size=5))
        ts += 1

    algo = build_pov_lite_executor(
        PovLiteConfig(
            side="B",
            target_qty=8,
            participation_bps=1000,
            min_clip=1,
            max_clip=2,
            price_offset_ticks=1,
            cooldown_events=1,
        ),
        first_client_order_id=10_000,
    )
    result = simulate_execution(events, decision_fn=algo.on_event, queue_model="level_depletion")
    filled_qty = sum(fill.size for fill in result.fills)
    assert filled_qty > 0
    assert filled_qty <= 8
    assert len(result.decisions) > 0
    assert all(fill.side == "B" for fill in result.fills)


def test_parallel_comparison_returns_baseline_even_without_hftbacktest() -> None:
    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=10),
        MBOEvent(ts_ns=2, action="ADD", order_id=2, side="A", price_ticks=101, size=10),
        MBOEvent(ts_ns=3, action="TRADE", order_id=0, side="A", price_ticks=100, size=2),
    ]
    decisions = [ExecutionDecision(ts_ns=3, action="NEW", client_order_id=1, side="B", price_ticks=101, size=1)]
    out = run_parallel_comparison(events=events, decisions=decisions)
    assert "filled_qty" in out.baseline_metrics
    assert out.status in {
        "hftbacktest_unavailable",
        "hftbacktest_feed_mapped",
        "hftbacktest_mapping_failed",
    }

