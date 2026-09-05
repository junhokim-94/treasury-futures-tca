from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["B", "A"]
Action = Literal["ADD", "CANCEL", "MODIFY", "TRADE", "FILL", "DELETE", "RESET"]
MBO_F_LAST = 1 << 7


@dataclass(slots=True, frozen=True)
class InstrumentDef:
    instrument_id: int
    symbol: str
    tick_size: int
    lot_size: int = 1
    ts_ns: int = 0


@dataclass(slots=True, frozen=True)
class MBOEvent:
    ts_ns: int
    action: Action
    order_id: int = 0
    side: Side | None = None
    price_ticks: int | None = None
    size: int | None = None
    ts_recv_ns: int | None = None
    flags: int = MBO_F_LAST
    sequence: int = 0

    @property
    def is_event_end(self) -> bool:
        return bool(self.flags & MBO_F_LAST)


@dataclass(slots=True, frozen=True)
class BookTop:
    ts_ns: int
    bid_price_ticks: int | None
    bid_size: int
    ask_price_ticks: int | None
    ask_size: int


@dataclass(slots=True, frozen=True)
class QuoteIntent:
    ts_ns: int
    bid_price_ticks: int | None
    bid_size: int
    ask_price_ticks: int | None
    ask_size: int


@dataclass(slots=True, frozen=True)
class FillEvent:
    ts_ns: int
    order_id: int
    side: Side
    price_ticks: int
    size: int

