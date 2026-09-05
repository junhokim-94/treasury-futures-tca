from __future__ import annotations

from dataclasses import dataclass

from .execution_types import ExecutionDecision
from .order_book import OrderBook
from .types import MBOEvent, Side


@dataclass(slots=True, frozen=True)
class PovLiteConfig:
    side: Side
    target_qty: int
    participation_bps: int = 500
    min_clip: int = 1
    max_clip: int = 5
    price_offset_ticks: int = 1
    cooldown_events: int = 20


class PovLiteExecutor:
    __slots__ = (
        "config",
        "next_client_order_id",
        "submitted_qty",
        "market_trade_qty",
        "_event_index",
        "_next_allowed_event",
    )

    def __init__(self, config: PovLiteConfig, *, first_client_order_id: int = 1) -> None:
        if config.target_qty <= 0:
            raise ValueError("target_qty must be > 0")
        if config.participation_bps <= 0 or config.participation_bps > 10_000:
            raise ValueError("participation_bps must be in (0, 10000]")
        if config.min_clip <= 0 or config.max_clip < config.min_clip:
            raise ValueError("clip bounds are invalid")
        if config.cooldown_events < 0:
            raise ValueError("cooldown_events must be >= 0")
        self.config = config
        self.next_client_order_id = first_client_order_id
        self.submitted_qty = 0
        self.market_trade_qty = 0
        self._event_index = 0
        self._next_allowed_event = 0

    def on_event(self, event: MBOEvent, book: OrderBook) -> list[ExecutionDecision]:
        self._event_index += 1
        if self.submitted_qty >= self.config.target_qty:
            return []
        if self._event_index < self._next_allowed_event:
            return []
        if event.action != "TRADE" or event.size is None or event.size <= 0:
            return []

        self.market_trade_qty += event.size
        desired_submitted = (self.market_trade_qty * self.config.participation_bps) // 10_000
        if desired_submitted <= self.submitted_qty:
            return []

        remaining = self.config.target_qty - self.submitted_qty
        shortfall = desired_submitted - self.submitted_qty
        clip = shortfall
        if clip < self.config.min_clip:
            clip = self.config.min_clip
        if clip > self.config.max_clip:
            clip = self.config.max_clip
        if clip > remaining:
            clip = remaining
        if clip <= 0:
            return []

        top = book.best_bid_ask()
        if self.config.side == "B":
            if top.ask_price_ticks is None:
                return []
            price_ticks = top.ask_price_ticks + self.config.price_offset_ticks
        else:
            if top.bid_price_ticks is None:
                return []
            price_ticks = top.bid_price_ticks - self.config.price_offset_ticks

        order_id = self.next_client_order_id
        self.next_client_order_id += 1
        self.submitted_qty += clip
        self._next_allowed_event = self._event_index + self.config.cooldown_events
        return [
            ExecutionDecision(
                ts_ns=event.ts_ns,
                action="NEW",
                client_order_id=order_id,
                side=self.config.side,
                price_ticks=price_ticks,
                size=clip,
            )
        ]


def build_pov_lite_executor(config: PovLiteConfig, *, first_client_order_id: int = 1) -> PovLiteExecutor:
    return PovLiteExecutor(config=config, first_client_order_id=first_client_order_id)


