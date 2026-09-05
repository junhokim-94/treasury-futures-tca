from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import Side

ExecutionAction = Literal["NEW", "CANCEL", "REPLACE"]
ExecutionOrderStatus = Literal["LIVE", "FILLED", "CANCELED", "EXPIRED"]


@dataclass(slots=True, frozen=True)
class ExecutionDecision:
    ts_ns: int
    action: ExecutionAction
    client_order_id: int
    side: Side | None = None
    price_ticks: int | None = None
    size: int | None = None


@dataclass(slots=True, frozen=True)
class ExecutionFill:
    ts_ns: int
    client_order_id: int
    side: Side
    price_ticks: int
    size: int
    arrival_mid_px_x2: int | None


@dataclass(slots=True, frozen=True)
class ExecutionOrder:
    client_order_id: int
    side: Side
    price_ticks: int
    initial_size: int
    remaining_size: int
    queue_ahead_size: int
    submit_ts_ns: int
    last_update_ts_ns: int
    status: ExecutionOrderStatus


