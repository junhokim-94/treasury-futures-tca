import json

from treasury_futures_execution_analytics_tca_engine.columnar import write_snapshots_columnar
from treasury_futures_execution_analytics_tca_engine.pipeline import replay_to_columnar
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent
from treasury_futures_execution_analytics_tca_engine.databento_loader import normalize_mbo_values


def test_normalize_mbo_values_maps_actions_and_ticks() -> None:
    add = normalize_mbo_values(
        ts_ns=1,
        action_code="A",
        side_code="B",
        order_id=10,
        price_raw=15_625_000,
        size=3,
        tick_size=15_625_000,
    )
    assert add is not None
    assert add.action == "ADD"
    assert add.price_ticks == 1
    assert add.side == "B"
    assert add.size == 3

    fill = normalize_mbo_values(
        ts_ns=2,
        action_code="F",
        side_code="A",
        order_id=10,
        price_raw=15_625_000,
        size=1,
        tick_size=15_625_000,
        ts_recv_ns=12,
        flags=0,
        sequence=99,
    )
    assert fill is not None
    assert fill.action == "FILL"
    assert fill.order_id == 10
    assert fill.side == "A"
    assert fill.price_ticks == 1
    assert fill.ts_recv_ns == 12
    assert fill.flags == 0
    assert fill.sequence == 99
    assert fill.is_event_end is False

    trade_unknown_side = normalize_mbo_values(
        ts_ns=21,
        action_code="T",
        side_code="N",
        order_id=0,
        price_raw=15_625_000,
        size=2,
        tick_size=15_625_000,
    )
    assert trade_unknown_side is not None
    assert trade_unknown_side.action == "TRADE"
    assert trade_unknown_side.order_id == 0
    assert trade_unknown_side.side is None

    cancel_unknown_side = normalize_mbo_values(
        ts_ns=22,
        action_code="C",
        side_code="N",
        order_id=11,
        price_raw=15_625_000,
        size=1,
        tick_size=15_625_000,
    )
    assert cancel_unknown_side is not None
    assert cancel_unknown_side.action == "CANCEL"
    assert cancel_unknown_side.side is None

    reset = normalize_mbo_values(
        ts_ns=3,
        action_code="R",
        side_code="N",
        order_id=0,
        price_raw=0,
        size=0,
        tick_size=15_625_000,
    )
    assert reset is not None
    assert reset.action == "RESET"


def test_write_snapshots_columnar_writes_expected_files(tmp_path) -> None:
    snapshots = [
        {
            "ts_ns": 1,
            "instrument_id": 100,
            "best_bid_px": 10,
            "best_bid_sz": 2,
            "best_ask_px": 11,
            "best_ask_sz": 3,
            "bid_levels": [(10, 2)],
            "ask_levels": [(11, 3)],
            "num_orders": 2,
            "total_bid_depth": 2,
            "total_ask_depth": 3,
        },
        {
            "ts_ns": 2,
            "instrument_id": 100,
            "best_bid_px": 10,
            "best_bid_sz": 1,
            "best_ask_px": 11,
            "best_ask_sz": 4,
            "bid_levels": [(10, 1)],
            "ask_levels": [(11, 4), (12, 1)],
            "num_orders": 3,
            "total_bid_depth": 1,
            "total_ask_depth": 5,
        },
    ]
    stats = write_snapshots_columnar(snapshots, tmp_path)
    assert stats["rows"] == 2
    assert stats["bid_level_rows"] == 2
    assert stats["ask_level_rows"] == 3
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["rows"] == 2
    assert (tmp_path / "ts_ns.i64").exists()
    assert (tmp_path / "bid_offsets.i64").exists()
    assert (tmp_path / "ask_offsets.i64").exists()


def test_replay_to_columnar_builds_outputs(tmp_path) -> None:
    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=5),
        MBOEvent(ts_ns=2, action="ADD", order_id=2, side="A", price_ticks=101, size=5),
        MBOEvent(ts_ns=3, action="CANCEL", order_id=1, size=2),
        MBOEvent(ts_ns=4, action="CANCEL", order_id=2, size=1),
    ]
    summary = replay_to_columnar(
        events,
        instrument_id=999,
        output_dir=tmp_path,
        snapshot_every=2,
        validate_every=1,
    )
    assert summary["instrument_id"] == 999
    assert summary["snapshots"] == 2
    assert summary["final_best_bid_px"] == 100
    assert summary["final_best_bid_sz"] == 3
    assert summary["final_best_ask_px"] == 101
    assert summary["final_best_ask_sz"] == 4
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "best_bid_px.i64").exists()

