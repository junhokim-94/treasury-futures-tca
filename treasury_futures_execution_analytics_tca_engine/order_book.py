from __future__ import annotations

from dataclasses import dataclass

from .types import BookTop, MBOEvent, Side


@dataclass(slots=True)
class _OrderState:
    side: Side
    price_ticks: int
    size: int


class OrderBook:
    __slots__ = (
        "instrument_id",
        "orders_by_id",
        "bid_levels",
        "ask_levels",
        "bid_queues",
        "ask_queues",
        "_last_ts_ns",
    )

    def __init__(self, instrument_id: int | None = None) -> None:
        self.instrument_id = instrument_id
        self.orders_by_id: dict[int, _OrderState] = {}
        self.bid_levels: dict[int, int] = {}
        self.ask_levels: dict[int, int] = {}
        self.bid_queues: dict[int, dict[int, int]] = {}
        self.ask_queues: dict[int, dict[int, int]] = {}
        self._last_ts_ns = 0

    def apply_event(self, event: MBOEvent) -> None:
        self._last_ts_ns = event.ts_ns
        action = event.action
        if action == "ADD":
            self._on_add(event)
            return
        if action == "CANCEL":
            self._on_reduce(event.order_id, event.size)
            return
        if action in ("TRADE", "FILL"):
            return
        if action == "MODIFY":
            self._on_modify(event)
            return
        if action == "DELETE":
            self._remove_order(event.order_id)
            return
        if action == "RESET":
            self.orders_by_id.clear()
            self.bid_levels.clear()
            self.ask_levels.clear()
            self.bid_queues.clear()
            self.ask_queues.clear()
            return
        raise ValueError(f"unsupported action: {action}")

    def best_bid_ask(self) -> BookTop:
        bid_price = max(self.bid_levels) if self.bid_levels else None
        ask_price = min(self.ask_levels) if self.ask_levels else None
        return BookTop(
            ts_ns=self._last_ts_ns,
            bid_price_ticks=bid_price,
            bid_size=self.bid_levels.get(bid_price, 0) if bid_price is not None else 0,
            ask_price_ticks=ask_price,
            ask_size=self.ask_levels.get(ask_price, 0) if ask_price is not None else 0,
        )

    def level_size(self, side: Side, price_ticks: int) -> int:
        return self._levels(side).get(price_ticks, 0)

    def top_n(self, side: Side, n: int) -> list[tuple[int, int]]:
        if n <= 0:
            return []
        levels = self._levels(side)
        prices = sorted(levels, reverse=(side == "B"))
        return [(price, levels[price]) for price in prices[:n]]

    def snapshot_top_n(self, n: int = 10) -> dict[str, object]:
        top = self.best_bid_ask()
        return {
            "ts_ns": self._last_ts_ns,
            "instrument_id": self.instrument_id,
            "best_bid_px": top.bid_price_ticks,
            "best_bid_sz": top.bid_size,
            "best_ask_px": top.ask_price_ticks,
            "best_ask_sz": top.ask_size,
            "bid_levels": self.top_n("B", n),
            "ask_levels": self.top_n("A", n),
            "num_orders": len(self.orders_by_id),
            "total_bid_depth": sum(self.bid_levels.values()),
            "total_ask_depth": sum(self.ask_levels.values()),
        }

    def validate(self) -> None:
        for order_id, order in self.orders_by_id.items():
            assert order.size > 0, f"non-positive live order size: {order_id}"
            queue = self._queues(order.side).get(order.price_ticks)
            assert queue is not None, f"missing queue for live order: {order_id}"
            queued_size = queue.get(order_id)
            assert queued_size is not None, f"live order missing from queue: {order_id}"
            assert queued_size == order.size, f"queue/live size mismatch for order: {order_id}"

        for side in ("B", "A"):
            typed_side = side  # keep local stable for message clarity
            levels = self._levels(typed_side)
            queues = self._queues(typed_side)

            for price, level_size in levels.items():
                assert level_size > 0, f"non-positive level size: side={typed_side} px={price}"
                queue = queues.get(price)
                assert queue is not None, f"missing queue for level: side={typed_side} px={price}"
                assert queue, f"empty queue stored: side={typed_side} px={price}"
                queue_sum = 0
                for queued_order_id, queued_size in queue.items():
                    assert queued_size > 0, (
                        f"non-positive queue size: side={typed_side} px={price} order={queued_order_id}"
                    )
                    queue_sum += queued_size
                assert queue_sum == level_size, (
                    f"level/queue mismatch: side={typed_side} px={price} level={level_size} queue={queue_sum}"
                )

            for price, queue in queues.items():
                assert queue, f"empty queue stored: side={typed_side} px={price}"
                queue_sum = 0
                for queued_order_id, queued_size in queue.items():
                    assert queued_size > 0, (
                        f"non-positive queue size: side={typed_side} px={price} order={queued_order_id}"
                    )
                    order = self.orders_by_id.get(queued_order_id)
                    assert order is not None, f"queued order missing live state: {queued_order_id}"
                    assert order.side == typed_side, f"queued order side mismatch: {queued_order_id}"
                    assert order.price_ticks == price, f"queued order price mismatch: {queued_order_id}"
                    assert order.size == queued_size, f"queued order size mismatch: {queued_order_id}"
                    queue_sum += queued_size
                level_size = levels.get(price)
                assert level_size is not None, f"queue exists without level: side={typed_side} px={price}"
                assert level_size == queue_sum, (
                    f"level/queue mismatch: side={typed_side} px={price} level={level_size} queue={queue_sum}"
                )

        if self.bid_levels and self.ask_levels:
            best_bid_px = max(self.bid_levels)
            best_ask_px = min(self.ask_levels)
            assert best_bid_px < best_ask_px, (
                f"crossed or locked book: best_bid={best_bid_px} best_ask={best_ask_px}"
            )

    def queue_ahead(self, order_id: int) -> int:
        order = self.orders_by_id.get(order_id)
        if order is None:
            return 0
        queue = self._queues(order.side).get(order.price_ticks)
        if queue is None:
            return 0
        ahead = 0
        for queued_order_id, queued_size in queue.items():
            if queued_order_id == order_id:
                return ahead
            ahead += queued_size
        return 0

    def queue_at_level(self, side: Side, price_ticks: int, max_orders: int = 0) -> list[tuple[int, int]]:
        queue = self._queues(side).get(price_ticks)
        if not queue:
            return []
        items = list(queue.items())
        if max_orders > 0:
            return items[:max_orders]
        return items

    def _on_add(self, event: MBOEvent) -> None:
        side = event.side
        price_ticks = event.price_ticks
        size = event.size
        if side is None or price_ticks is None or size is None or size <= 0:
            raise ValueError("ADD requires side, price_ticks, and positive size")
        if event.order_id in self.orders_by_id:
            self._remove_order(event.order_id)
        self.orders_by_id[event.order_id] = _OrderState(side=side, price_ticks=price_ticks, size=size)
        self._add_level_delta(side, price_ticks, size)
        self._queues(side).setdefault(price_ticks, {})[event.order_id] = size

    def _on_reduce(self, order_id: int, reduce_size: int | None) -> None:
        if reduce_size is None or reduce_size <= 0:
            return
        order = self.orders_by_id.get(order_id)
        if order is None:
            return
        reduced = reduce_size if reduce_size < order.size else order.size
        self._add_level_delta(order.side, order.price_ticks, -reduced)
        order.size -= reduced
        queue = self._queues(order.side).get(order.price_ticks)
        if queue is not None:
            if order.size > 0:
                queue[order_id] = order.size
            else:
                queue.pop(order_id, None)
                if not queue:
                    self._queues(order.side).pop(order.price_ticks, None)
        if order.size == 0:
            del self.orders_by_id[order_id]

    def _on_modify(self, event: MBOEvent) -> None:
        order = self.orders_by_id.get(event.order_id)
        if order is None:
            if event.side is None or event.price_ticks is None or event.size is None or event.size <= 0:
                return
            self._on_add(event)
            return
        new_side = order.side if event.side is None else event.side
        new_price = order.price_ticks if event.price_ticks is None else event.price_ticks
        new_size = order.size if event.size is None else event.size
        if new_size <= 0:
            self._remove_order(event.order_id)
            return
        if new_side == order.side and new_price == order.price_ticks:
            delta = new_size - order.size
            if delta != 0:
                self._add_level_delta(order.side, order.price_ticks, delta)
            order.size = new_size
            queue = self._queues(order.side).get(order.price_ticks)
            if queue is not None:
                queue[event.order_id] = new_size
            return
        old_queue = self._queues(order.side).get(order.price_ticks)
        if old_queue is not None:
            old_queue.pop(event.order_id, None)
            if not old_queue:
                self._queues(order.side).pop(order.price_ticks, None)
        self._add_level_delta(order.side, order.price_ticks, -order.size)
        self._add_level_delta(new_side, new_price, new_size)
        self._queues(new_side).setdefault(new_price, {})[event.order_id] = new_size
        order.side = new_side
        order.price_ticks = new_price
        order.size = new_size

    def _remove_order(self, order_id: int) -> None:
        order = self.orders_by_id.pop(order_id, None)
        if order is None:
            return
        self._add_level_delta(order.side, order.price_ticks, -order.size)
        queue = self._queues(order.side).get(order.price_ticks)
        if queue is not None:
            queue.pop(order_id, None)
            if not queue:
                self._queues(order.side).pop(order.price_ticks, None)

    def _add_level_delta(self, side: Side, price_ticks: int, delta: int) -> None:
        if delta == 0:
            return
        levels = self._levels(side)
        new_size = levels.get(price_ticks, 0) + delta
        if new_size <= 0:
            levels.pop(price_ticks, None)
            return
        levels[price_ticks] = new_size

    def _levels(self, side: Side) -> dict[int, int]:
        if side == "B":
            return self.bid_levels
        if side == "A":
            return self.ask_levels
        raise ValueError(f"unsupported side: {side}")

    def _queues(self, side: Side) -> dict[int, dict[int, int]]:
        if side == "B":
            return self.bid_queues
        if side == "A":
            return self.ask_queues
        raise ValueError(f"unsupported side: {side}")

