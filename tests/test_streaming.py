from treasury_futures_execution_analytics_tca_engine.order_book import OrderBook
from treasury_futures_execution_analytics_tca_engine.streaming import build_l3_update, parse_queue_levels
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def test_parse_queue_levels() -> None:
    subs = parse_queue_levels("B:100, A:101 ,badtoken", max_orders=5)
    assert len(subs) == 2
    assert subs[0].side == "B"
    assert subs[0].price_ticks == 100
    assert subs[0].max_orders == 5
    assert subs[1].side == "A"
    assert subs[1].price_ticks == 101


def test_build_l3_update_contains_queue_view() -> None:
    book = OrderBook(instrument_id=1)
    ev1 = MBOEvent(ts_ns=1, action="ADD", order_id=11, side="B", price_ticks=100, size=3)
    ev2 = MBOEvent(ts_ns=2, action="ADD", order_id=12, side="B", price_ticks=100, size=4)
    book.apply_event(ev1)
    book.apply_event(ev2)

    payload = build_l3_update(
        seq=2,
        event=ev2,
        book=book,
        top_n=2,
        around_ticks=2,
        queue_subscriptions=parse_queue_levels("B:100"),
    )
    assert payload["type"] == "update"
    assert payload["seq"] == 2
    assert payload["ts_ns"] == 2
    assert payload["book"]["best_bid_px"] == 100  # type: ignore[index]
    assert payload["book"]["best_bid_sz"] == 7  # type: ignore[index]
    assert payload["book"]["bid_around"] == [(100, 7)]  # type: ignore[index]
    assert payload["queues"]["B:100"] == [(11, 3), (12, 4)]  # type: ignore[index]

