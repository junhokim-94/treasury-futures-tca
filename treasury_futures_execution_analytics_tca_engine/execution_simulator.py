from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .execution_types import ExecutionDecision, ExecutionFill, ExecutionOrder
from .order_book import OrderBook
from .types import MBOEvent, Side

QueueModel = Literal["trade_only", "level_depletion"]
DecisionFn = Callable[[MBOEvent, OrderBook], list[ExecutionDecision]]


@dataclass(slots=True)
class _LiveOrder:
    client_order_id: int
    side: Side
    price_ticks: int
    initial_size: int
    remaining_size: int
    queue_ahead_size: int
    submit_ts_ns: int
    last_update_ts_ns: int
    arrival_mid_px_x2: int | None
    status: str = "LIVE"


@dataclass(slots=True, frozen=True)
class ExecutionResult:
    fills: list[ExecutionFill]
    orders: list[ExecutionOrder]
    decisions: list[ExecutionDecision]
    mid_ts_ns: list[int]
    mid_px_x2: list[int]
    market_trade_volume: int


class ExecutionSimulator:
    __slots__ = (
        "book",
        "queue_model",
        "validate_every",
        "_live_orders",
        "_fills",
        "_decisions",
        "_mid_ts_ns",
        "_mid_px_x2",
        "_market_trade_volume",
        "_event_count",
    )

    def __init__(
        self,
        *,
        instrument_id: int | None = None,
        queue_model: QueueModel = "level_depletion",
        validate_every: int = 0,
    ) -> None:
        self.book = OrderBook(instrument_id=instrument_id)
        self.queue_model = queue_model
        self.validate_every = validate_every
        self._live_orders: dict[int, _LiveOrder] = {}
        self._fills: list[ExecutionFill] = []
        self._decisions: list[ExecutionDecision] = []
        self._mid_ts_ns: list[int] = []
        self._mid_px_x2: list[int] = []
        self._market_trade_volume = 0
        self._event_count = 0

    def apply_event(self, event: MBOEvent) -> None:
        prior = self.book.orders_by_id.get(event.order_id)
        prior_side: Side | None = None
        prior_price: int | None = None
        prior_size = 0
        if prior is not None:
            prior_side = prior.side
            prior_price = prior.price_ticks
            prior_size = prior.size

        self.book.apply_event(event)
        self._event_count += 1
        if self.validate_every > 0 and self._event_count % self.validate_every == 0:
            self.book.validate()

        if event.action == "TRADE":
            if event.size is not None and event.size > 0:
                self._market_trade_volume += event.size
            self._apply_market_trade(event)

        reduced_at_level = self._reduced_at_old_level(
            event=event,
            prior_side=prior_side,
            prior_price=prior_price,
            prior_size=prior_size,
        )
        if reduced_at_level > 0 and prior_side is not None and prior_price is not None:
            self._advance_queue(
                side=prior_side,
                price_ticks=prior_price,
                reduced_at_level=reduced_at_level,
                ts_ns=event.ts_ns,
            )

        self._record_mid(event.ts_ns)

    def apply_decision(self, decision: ExecutionDecision) -> None:
        self._decisions.append(decision)
        action = decision.action
        if action == "NEW":
            self._submit_new(decision)
            return
        if action == "CANCEL":
            self._cancel(decision.client_order_id, decision.ts_ns, "CANCELED")
            return
        if action == "REPLACE":
            self._replace(decision)
            return
        raise ValueError(f"unsupported decision action: {action}")

    def finalize(self) -> ExecutionResult:
        orders = [
            ExecutionOrder(
                client_order_id=order.client_order_id,
                side=order.side,
                price_ticks=order.price_ticks,
                initial_size=order.initial_size,
                remaining_size=order.remaining_size,
                queue_ahead_size=order.queue_ahead_size,
                submit_ts_ns=order.submit_ts_ns,
                last_update_ts_ns=order.last_update_ts_ns,
                status=order.status,  # type: ignore[arg-type]
            )
            for order in sorted(self._live_orders.values(), key=lambda x: x.client_order_id)
        ]
        return ExecutionResult(
            fills=list(self._fills),
            orders=orders,
            decisions=list(self._decisions),
            mid_ts_ns=list(self._mid_ts_ns),
            mid_px_x2=list(self._mid_px_x2),
            market_trade_volume=self._market_trade_volume,
        )

    def _submit_new(self, decision: ExecutionDecision) -> None:
        if decision.side is None or decision.price_ticks is None or decision.size is None or decision.size <= 0:
            raise ValueError("NEW requires side, price_ticks, and positive size")
        if decision.client_order_id in self._live_orders:
            self._cancel(decision.client_order_id, decision.ts_ns, "CANCELED")
        arrival_mid = self._current_mid_x2()
        queue_ahead_size = self.book.level_size(decision.side, decision.price_ticks)
        order = _LiveOrder(
            client_order_id=decision.client_order_id,
            side=decision.side,
            price_ticks=decision.price_ticks,
            initial_size=decision.size,
            remaining_size=decision.size,
            queue_ahead_size=queue_ahead_size,
            submit_ts_ns=decision.ts_ns,
            last_update_ts_ns=decision.ts_ns,
            arrival_mid_px_x2=arrival_mid,
        )
        self._live_orders[decision.client_order_id] = order

        # Immediate marketable quantity is treated as taker fill.
        top = self.book.best_bid_ask()
        if order.side == "B" and top.ask_price_ticks is not None and order.price_ticks >= top.ask_price_ticks:
            self._fill_order(order, top.ask_price_ticks, min(order.remaining_size, top.ask_size), decision.ts_ns)
        elif order.side == "A" and top.bid_price_ticks is not None and order.price_ticks <= top.bid_price_ticks:
            self._fill_order(order, top.bid_price_ticks, min(order.remaining_size, top.bid_size), decision.ts_ns)

    def _replace(self, decision: ExecutionDecision) -> None:
        self._cancel(decision.client_order_id, decision.ts_ns, "CANCELED")
        if decision.side is None or decision.price_ticks is None or decision.size is None:
            return
        self._submit_new(
            ExecutionDecision(
                ts_ns=decision.ts_ns,
                action="NEW",
                client_order_id=decision.client_order_id,
                side=decision.side,
                price_ticks=decision.price_ticks,
                size=decision.size,
            )
        )

    def _cancel(self, client_order_id: int, ts_ns: int, status: str) -> None:
        order = self._live_orders.get(client_order_id)
        if order is None:
            return
        order.last_update_ts_ns = ts_ns
        order.status = status
        if order.remaining_size <= 0:
            order.status = "FILLED"
        # Keep canceled/filled orders in final result for post-trade analysis.
        self._live_orders[client_order_id] = order

    def _reduced_at_old_level(
        self,
        *,
        event: MBOEvent,
        prior_side: Side | None,
        prior_price: int | None,
        prior_size: int,
    ) -> int:
        if prior_side is None or prior_price is None or prior_size <= 0:
            return 0
        post = self.book.orders_by_id.get(event.order_id)
        post_size_at_old = 0
        if post is not None and post.side == prior_side and post.price_ticks == prior_price:
            post_size_at_old = post.size
        reduced = prior_size - post_size_at_old
        if reduced <= 0:
            return 0
        return reduced

    def _advance_queue(
        self,
        *,
        side: Side,
        price_ticks: int,
        reduced_at_level: int,
        ts_ns: int,
    ) -> None:
        if self.queue_model != "level_depletion":
            return
        for order in self._live_orders.values():
            if order.status != "LIVE":
                continue
            if order.side != side or order.price_ticks != price_ticks:
                continue
            order.queue_ahead_size = max(0, order.queue_ahead_size - reduced_at_level)
            order.last_update_ts_ns = ts_ns

    def _apply_market_trade(self, event: MBOEvent) -> None:
        price_ticks = event.price_ticks
        trade_size = event.size
        if price_ticks is None or trade_size is None or trade_size <= 0:
            return
        resting_side = self._resting_side(event.side, price_ticks)
        if resting_side is None:
            return
        for order in self._live_orders.values():
            if order.status != "LIVE":
                continue
            if order.side != resting_side or order.price_ticks != price_ticks:
                continue
            ahead_before = order.queue_ahead_size
            if self.queue_model == "trade_only":
                order.queue_ahead_size = max(0, ahead_before - trade_size)
            fillable = trade_size - ahead_before
            if fillable > 0:
                self._fill_order(order, price_ticks, fillable, event.ts_ns)
            order.last_update_ts_ns = event.ts_ns

    def _resting_side(self, aggressor_side: Side | None, price_ticks: int) -> Side | None:
        if aggressor_side == "A":
            return "B"
        if aggressor_side == "B":
            return "A"
        has_bid = self.book.level_size("B", price_ticks) > 0
        has_ask = self.book.level_size("A", price_ticks) > 0
        if has_bid != has_ask:
            return "B" if has_bid else "A"
        return None

    def _fill_order(self, order: _LiveOrder, price_ticks: int, size: int, ts_ns: int) -> None:
        if size <= 0 or order.remaining_size <= 0:
            return
        fill_size = size if size < order.remaining_size else order.remaining_size
        if fill_size <= 0:
            return
        order.remaining_size -= fill_size
        if order.remaining_size == 0:
            order.status = "FILLED"
        self._fills.append(
            ExecutionFill(
                ts_ns=ts_ns,
                client_order_id=order.client_order_id,
                side=order.side,
                price_ticks=price_ticks,
                size=fill_size,
                arrival_mid_px_x2=order.arrival_mid_px_x2,
            )
        )

    def _current_mid_x2(self) -> int | None:
        top = self.book.best_bid_ask()
        if top.bid_price_ticks is None or top.ask_price_ticks is None:
            return None
        return top.bid_price_ticks + top.ask_price_ticks

    def _record_mid(self, ts_ns: int) -> None:
        mid_x2 = self._current_mid_x2()
        if mid_x2 is None:
            return
        self._mid_ts_ns.append(ts_ns)
        self._mid_px_x2.append(mid_x2)


def simulate_execution(
    events: list[MBOEvent],
    *,
    instrument_id: int | None = None,
    decisions: list[ExecutionDecision] | None = None,
    decision_fn: DecisionFn | None = None,
    queue_model: QueueModel = "level_depletion",
    validate_every: int = 0,
) -> ExecutionResult:
    sim = ExecutionSimulator(
        instrument_id=instrument_id,
        queue_model=queue_model,
        validate_every=validate_every,
    )
    pending = sorted(decisions or [], key=lambda x: x.ts_ns)
    pending_index = 0
    pending_count = len(pending)

    for event in events:
        sim.apply_event(event)
        while pending_index < pending_count and pending[pending_index].ts_ns <= event.ts_ns:
            sim.apply_decision(pending[pending_index])
            pending_index += 1
        if decision_fn is not None:
            for decision in decision_fn(event, sim.book):
                sim.apply_decision(decision)

    while pending_index < pending_count:
        sim.apply_decision(pending[pending_index])
        pending_index += 1

    return sim.finalize()

