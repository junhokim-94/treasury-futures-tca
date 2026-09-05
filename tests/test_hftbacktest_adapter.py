import numpy as np

from treasury_futures_execution_analytics_tca_engine.hftbacktest_adapter import map_mbo_events_to_hftbacktest_feed
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def test_map_mbo_events_to_hftbacktest_feed_basic() -> None:
    events = [
        MBOEvent(ts_ns=1, action="ADD", order_id=10, side="B", price_ticks=100, size=10),
        MBOEvent(ts_ns=2, action="ADD", order_id=20, side="A", price_ticks=101, size=8),
        MBOEvent(ts_ns=3, action="CANCEL", order_id=10, size=3),
        MBOEvent(ts_ns=4, action="TRADE", order_id=0, side="A", price_ticks=100, size=4),
        MBOEvent(ts_ns=5, action="FILL", order_id=10, side="B", price_ticks=100, size=4),
        MBOEvent(ts_ns=6, action="MODIFY", order_id=20, side="A", price_ticks=102, size=5),
        MBOEvent(ts_ns=7, action="DELETE", order_id=20),
        MBOEvent(ts_ns=8, action="RESET"),
    ]
    out = map_mbo_events_to_hftbacktest_feed(events)

    assert out.data.shape[0] == 7
    assert out.dropped_events == 1
    assert out.used_l3_event_flags is False
    assert tuple(out.data.dtype.names or ()) == ("ev", "exch_ts", "local_ts", "px", "qty", "order_id", "ival", "fval")
    assert float(out.data["px"][0]) == 100.0
    assert float(out.data["qty"][0]) == 10.0
    assert float(out.data["qty"][2]) == 3.0
    assert float(out.data["qty"][3]) == 4.0
    assert int(out.data["order_id"][3]) == 0
    assert float(out.data["px"][4]) == 102.0
    assert float(out.data["qty"][5]) == 5.0
    assert int(out.data["order_id"][6]) == 0
    assert float(out.data["px"][6]) == 0.0
    assert float(out.data["qty"][6]) == 0.0


def test_map_mbo_events_to_hftbacktest_feed_uses_l3_flags_when_available() -> None:
    class _FakeHft:
        EXCH_EVENT = 1 << 31
        LOCAL_EVENT = 1 << 30
        BUY_EVENT = 1 << 29
        SELL_EVENT = 1 << 28
        DEPTH_EVENT = 1
        TRADE_EVENT = 2
        DEPTH_CLEAR_EVENT = 3
        ADD_ORDER_EVENT = 10
        MODIFY_ORDER_EVENT = 11
        CANCEL_ORDER_EVENT = 12
        FILL_EVENT = 13
        event_dtype = np.dtype(
            [
                ("ev", "<u8"),
                ("exch_ts", "<i8"),
                ("local_ts", "<i8"),
                ("px", "<f8"),
                ("qty", "<f8"),
                ("order_id", "<u8"),
                ("ival", "<i8"),
                ("fval", "<f8"),
            ],
            align=True,
        )

    events = [
        MBOEvent(
            ts_ns=1,
            action="ADD",
            order_id=100,
            side="B",
            price_ticks=200,
            size=7,
            ts_recv_ns=11,
            flags=5,
        ),
        MBOEvent(ts_ns=2, action="TRADE", order_id=0, side="A", price_ticks=200, size=2),
        MBOEvent(ts_ns=3, action="FILL", order_id=100, side="B", price_ticks=200, size=2),
        MBOEvent(ts_ns=4, action="CANCEL", order_id=100, size=7),
    ]
    out = map_mbo_events_to_hftbacktest_feed(events, hft_module=_FakeHft)

    assert out.used_l3_event_flags is True
    assert int(out.data["ev"][0]) & 0xFF == _FakeHft.ADD_ORDER_EVENT
    assert int(out.data["ev"][1]) & 0xFF == _FakeHft.TRADE_EVENT
    assert int(out.data["ev"][2]) & 0xFF == _FakeHft.FILL_EVENT
    assert int(out.data["ev"][3]) & 0xFF == _FakeHft.CANCEL_ORDER_EVENT
    assert float(out.data["qty"][3]) == 7.0
    assert int(out.data["local_ts"][0]) == 11
    assert int(out.data["ival"][0]) == 5

