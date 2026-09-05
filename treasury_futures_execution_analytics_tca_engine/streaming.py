from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .order_book import OrderBook
from .types import MBOEvent, Side


@dataclass(slots=True, frozen=True)
class QueueSubscription:
    side: Side
    price_ticks: int
    max_orders: int = 30


def parse_queue_levels(raw: str, max_orders: int = 30) -> list[QueueSubscription]:
    text = raw.strip()
    if not text:
        return []
    out: list[QueueSubscription] = []
    for token in text.split(","):
        part = token.strip()
        if not part:
            continue
        if ":" not in part:
            continue
        side_txt, price_txt = part.split(":", 1)
        price_txt = price_txt.strip()
        if not price_txt:
            continue
        side_upper = side_txt.strip().upper()
        if side_upper not in ("B", "A"):
            continue
        side: Side = "B" if side_upper == "B" else "A"
        out.append(QueueSubscription(side=side, price_ticks=int(price_txt), max_orders=max_orders))
    return out


def build_l3_update(
    *,
    seq: int,
    event: MBOEvent,
    book: OrderBook,
    top_n: int,
    around_ticks: int = 0,
    queue_subscriptions: Iterable[QueueSubscription] = (),
) -> dict[str, object]:
    top = book.best_bid_ask()
    around_bid: list[tuple[int, int]] = []
    around_ask: list[tuple[int, int]] = []
    if around_ticks > 0:
        around_bid = _levels_around(book, side="B", around_ticks=around_ticks)
        around_ask = _levels_around(book, side="A", around_ticks=around_ticks)
    payload: dict[str, object] = {
        "type": "update",
        "seq": seq,
        "ts_ns": event.ts_ns,
        "ts_ns_str": str(event.ts_ns),
        "event": {
            "action": event.action,
            "order_id": event.order_id,
            "side": event.side,
            "price_ticks": event.price_ticks,
            "size": event.size,
        },
        "book": {
            "instrument_id": book.instrument_id,
            "best_bid_px": top.bid_price_ticks,
            "best_bid_sz": top.bid_size,
            "best_ask_px": top.ask_price_ticks,
            "best_ask_sz": top.ask_size,
            "bid_levels": book.top_n("B", top_n),
            "ask_levels": book.top_n("A", top_n),
            "bid_around": around_bid,
            "ask_around": around_ask,
            "num_orders": len(book.orders_by_id),
            "total_bid_depth": sum(book.bid_levels.values()),
            "total_ask_depth": sum(book.ask_levels.values()),
        },
    }
    queues: dict[str, list[tuple[int, int]]] = {}
    for sub in queue_subscriptions:
        key = f"{sub.side}:{sub.price_ticks}"
        queues[key] = book.queue_at_level(sub.side, sub.price_ticks, max_orders=sub.max_orders)
    if queues:
        payload["queues"] = queues
    return payload


def _levels_around(book: OrderBook, side: Side, around_ticks: int) -> list[tuple[int, int]]:
    levels = book.bid_levels if side == "B" else book.ask_levels
    if not levels:
        return []
    best_px = max(levels) if side == "B" else min(levels)
    if side == "B":
        lower = best_px - around_ticks
        out = [(px, sz) for px, sz in levels.items() if px >= lower and px <= best_px]
        out.sort(key=lambda x: x[0], reverse=True)
        return out
    upper = best_px + around_ticks
    out = [(px, sz) for px, sz in levels.items() if px >= best_px and px <= upper]
    out.sort(key=lambda x: x[0])
    return out

