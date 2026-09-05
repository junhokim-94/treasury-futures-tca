import pytest

from treasury_futures_execution_analytics_tca_engine.order_book import OrderBook
from treasury_futures_execution_analytics_tca_engine.replay import replay_events
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def test_order_book_l3_l2_updates() -> None:
    book = OrderBook(instrument_id=1)

    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=10),
        MBOEvent(ts_ns=2, action="ADD", order_id=2, side="A", price_ticks=101, size=7),
        MBOEvent(ts_ns=3, action="ADD", order_id=3, side="B", price_ticks=100, size=5),
        MBOEvent(ts_ns=4, action="CANCEL", order_id=1, size=3),
        MBOEvent(ts_ns=5, action="TRADE", order_id=0, side="A", price_ticks=100, size=5),
        MBOEvent(ts_ns=6, action="FILL", order_id=3, side="B", price_ticks=100, size=5),
        MBOEvent(ts_ns=7, action="CANCEL", order_id=3, size=5),
        MBOEvent(ts_ns=8, action="MODIFY", order_id=1, side="B", price_ticks=99, size=6),
        MBOEvent(ts_ns=9, action="MODIFY", order_id=2, side="A", price_ticks=102, size=10),
        MBOEvent(ts_ns=10, action="DELETE", order_id=2),
    ]
    for event in events:
        book.apply_event(event)

    top = book.best_bid_ask()
    assert top.ts_ns == 10
    assert top.bid_price_ticks == 99
    assert top.bid_size == 6
    assert top.ask_price_ticks is None
    assert top.ask_size == 0

    assert 3 not in book.orders_by_id
    assert book.orders_by_id[1].size == 6
    assert book.level_size("B", 100) == 0
    assert book.level_size("B", 99) == 6
    assert book.top_n("B", 2) == [(99, 6)]
    assert book.top_n("A", 2) == []
    assert book.queue_ahead(1) == 0


def test_partial_and_full_reduction_and_reset() -> None:
    book = OrderBook(instrument_id=1)
    book.apply_event(MBOEvent(ts_ns=1, action="ADD", order_id=10, side="A", price_ticks=105, size=4))
    book.apply_event(MBOEvent(ts_ns=2, action="TRADE", order_id=0, side="B", price_ticks=105, size=1))
    assert book.level_size("A", 105) == 4
    assert book.orders_by_id[10].size == 4

    book.apply_event(MBOEvent(ts_ns=3, action="FILL", order_id=10, side="A", price_ticks=105, size=1))
    assert book.level_size("A", 105) == 4
    assert book.orders_by_id[10].size == 4

    book.apply_event(MBOEvent(ts_ns=4, action="CANCEL", order_id=10, size=1))
    assert book.level_size("A", 105) == 3
    assert book.orders_by_id[10].size == 3

    book.apply_event(MBOEvent(ts_ns=5, action="CANCEL", order_id=10, size=10))
    assert book.level_size("A", 105) == 0
    assert 10 not in book.orders_by_id

    book.apply_event(MBOEvent(ts_ns=6, action="ADD", order_id=11, side="B", price_ticks=99, size=2))
    book.apply_event(MBOEvent(ts_ns=7, action="RESET"))
    top = book.best_bid_ask()
    assert top.ts_ns == 7
    assert top.bid_price_ticks is None and top.ask_price_ticks is None
    assert book.orders_by_id == {}


def test_queue_ahead_size_is_fifo_and_price_sensitive() -> None:
    book = OrderBook(instrument_id=1)
    book.apply_event(MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=5))
    book.apply_event(MBOEvent(ts_ns=2, action="ADD", order_id=2, side="B", price_ticks=100, size=3))
    book.apply_event(MBOEvent(ts_ns=3, action="ADD", order_id=3, side="B", price_ticks=100, size=2))

    assert book.queue_ahead(1) == 0
    assert book.queue_ahead(2) == 5
    assert book.queue_ahead(3) == 8

    book.apply_event(MBOEvent(ts_ns=4, action="CANCEL", order_id=1, size=2))
    book.apply_event(MBOEvent(ts_ns=5, action="MODIFY", order_id=2, side="B", price_ticks=100, size=4))
    assert book.queue_ahead(2) == 3
    assert book.queue_ahead(3) == 7

    book.apply_event(MBOEvent(ts_ns=6, action="MODIFY", order_id=2, side="B", price_ticks=99, size=4))
    assert book.queue_ahead(2) == 0
    assert book.queue_ahead(3) == 3

    book.apply_event(MBOEvent(ts_ns=7, action="DELETE", order_id=1))
    assert book.queue_ahead(3) == 0
    assert book.queue_at_level("B", 100) == [(3, 2)]


def test_validate_passes_on_existing_happy_path() -> None:
    book = OrderBook(instrument_id=1)
    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=10),
        MBOEvent(ts_ns=2, action="ADD", order_id=2, side="B", price_ticks=99, size=5),
        MBOEvent(ts_ns=3, action="ADD", order_id=3, side="A", price_ticks=102, size=7),
        MBOEvent(ts_ns=4, action="CANCEL", order_id=1, size=2),
        MBOEvent(ts_ns=5, action="MODIFY", order_id=2, side="B", price_ticks=98, size=4),
        MBOEvent(ts_ns=6, action="FILL", order_id=3, side="A", price_ticks=102, size=3),
        MBOEvent(ts_ns=7, action="CANCEL", order_id=3, size=3),
    ]
    for event in events:
        book.apply_event(event)
    book.validate()


def test_validate_detects_level_queue_mismatch() -> None:
    book = OrderBook(instrument_id=1)
    book.apply_event(MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=5))
    book.bid_levels[100] += 1
    with pytest.raises(AssertionError):
        book.validate()


def test_validate_detects_missing_order_in_queue() -> None:
    book = OrderBook(instrument_id=1)
    book.apply_event(MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=5))
    book.apply_event(MBOEvent(ts_ns=2, action="ADD", order_id=2, side="B", price_ticks=100, size=3))
    book.bid_queues[100].pop(2)
    with pytest.raises(AssertionError):
        book.validate()


def test_snapshot_top_n_contains_expected_fields_and_values() -> None:
    book = OrderBook(instrument_id=777)
    book.apply_event(MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=5))
    book.apply_event(MBOEvent(ts_ns=2, action="ADD", order_id=2, side="B", price_ticks=99, size=3))
    book.apply_event(MBOEvent(ts_ns=3, action="ADD", order_id=3, side="A", price_ticks=102, size=4))
    book.apply_event(MBOEvent(ts_ns=4, action="ADD", order_id=4, side="A", price_ticks=103, size=6))

    snap = book.snapshot_top_n(n=1)
    assert set(snap) == {
        "ts_ns",
        "instrument_id",
        "best_bid_px",
        "best_bid_sz",
        "best_ask_px",
        "best_ask_sz",
        "bid_levels",
        "ask_levels",
        "num_orders",
        "total_bid_depth",
        "total_ask_depth",
    }
    assert snap["ts_ns"] == 4
    assert snap["instrument_id"] == 777
    assert snap["best_bid_px"] == 100
    assert snap["best_bid_sz"] == 5
    assert snap["best_ask_px"] == 102
    assert snap["best_ask_sz"] == 4
    assert snap["bid_levels"] == [(100, 5)]
    assert snap["ask_levels"] == [(102, 4)]
    assert snap["num_orders"] == 4
    assert snap["total_bid_depth"] == 8
    assert snap["total_ask_depth"] == 10


def test_replay_events_collects_snapshots_and_runs_validation() -> None:
    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=5),
        MBOEvent(ts_ns=2, action="ADD", order_id=2, side="A", price_ticks=102, size=7),
        MBOEvent(ts_ns=3, action="ADD", order_id=3, side="B", price_ticks=99, size=2),
        MBOEvent(ts_ns=4, action="CANCEL", order_id=1, size=2),
    ]
    book = OrderBook(instrument_id=5)
    snapshots = replay_events(events, book, snapshot_every=2, validate_every=1)

    assert len(snapshots) == 2
    first = snapshots[0]
    second = snapshots[1]

    assert first["ts_ns"] == 2
    assert first["best_bid_px"] == 100
    assert first["best_bid_sz"] == 5
    assert first["best_ask_px"] == 102
    assert first["best_ask_sz"] == 7
    assert first["num_orders"] == 2

    assert second["ts_ns"] == 4
    assert second["best_bid_px"] == 100
    assert second["best_bid_sz"] == 3
    assert second["best_ask_px"] == 102
    assert second["best_ask_sz"] == 7
    assert second["num_orders"] == 3


def test_replay_delays_snapshot_until_event_boundary() -> None:
    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=1, side="B", price_ticks=100, size=5, flags=0),
        MBOEvent(ts_ns=2, action="ADD", order_id=2, side="B", price_ticks=99, size=3, flags=0),
        MBOEvent(ts_ns=3, action="ADD", order_id=3, side="A", price_ticks=102, size=4, flags=1 << 7),
        MBOEvent(ts_ns=4, action="CANCEL", order_id=1, size=1, flags=1 << 7),
    ]
    snapshots = replay_events(events, OrderBook(instrument_id=1), snapshot_every=2, validate_every=2)

    assert [snapshot["ts_ns"] for snapshot in snapshots] == [3, 4]

