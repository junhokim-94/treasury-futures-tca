from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .types import MBOEvent, Side


@dataclass(slots=True, frozen=True)
class HftbConstants:
    exch_event: int
    local_event: int
    buy_event: int
    sell_event: int
    depth_event: int
    trade_event: int
    depth_clear_event: int
    add_order_event: int | None
    modify_order_event: int | None
    cancel_order_event: int | None
    fill_event: int | None


@dataclass(slots=True, frozen=True)
class HftbMappedFeed:
    data: np.ndarray
    used_l3_event_flags: bool
    dropped_events: int


_FALLBACK_EVENT_DTYPE = np.dtype(
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


def map_mbo_events_to_hftbacktest_feed(
    events: list[MBOEvent],
    *,
    price_tick_size: float = 1.0,
    local_ts_offset_ns: int = 0,
    use_l3_events: bool = True,
    hft_module: Any | None = None,
) -> HftbMappedFeed:
    if price_tick_size <= 0:
        raise ValueError("price_tick_size must be > 0")
    constants = _load_constants(hft_module)
    event_dtype = _load_event_dtype(hft_module)

    rows = np.zeros(len(events), dtype=event_dtype)
    order_state: dict[int, tuple[Side, int, int]] = {}
    written = 0
    dropped = 0
    use_l3 = use_l3_events and all(
        event_type is not None
        for event_type in (
            constants.add_order_event,
            constants.modify_order_event,
            constants.cancel_order_event,
            constants.fill_event,
        )
    )

    for event in events:
        action = event.action
        side = event.side
        price_ticks = event.price_ticks
        size = event.size
        order_id = event.order_id
        local_ts = (event.ts_recv_ns if event.ts_recv_ns is not None else event.ts_ns) + local_ts_offset_ns

        if action == "RESET":
            order_state.clear()
            ev_flags = constants.exch_event | constants.local_event | constants.depth_clear_event
            _write_row(
                rows,
                written,
                ev=ev_flags,
                exch_ts=event.ts_ns,
                local_ts=local_ts,
                px=0.0,
                qty=0.0,
                order_id=0,
                ival=event.flags,
            )
            written += 1
            continue

        prior = order_state.get(order_id)
        prior_side: Side | None = prior[0] if prior is not None else None
        prior_price_ticks = prior[1] if prior is not None else None
        prior_size = prior[2] if prior is not None else None

        if action in ("TRADE", "FILL"):
            event_side = side if side is not None else prior_side
            event_price_ticks = price_ticks if price_ticks is not None else prior_price_ticks
            if event_price_ticks is None or size is None or size <= 0:
                dropped += 1
                continue
            if action == "FILL":
                if not use_l3 or constants.fill_event is None:
                    dropped += 1
                    continue
                event_type = constants.fill_event
            else:
                event_type = constants.trade_event
            _write_row(
                rows,
                written,
                ev=_ev_flags(constants, event_side, event_type),
                exch_ts=event.ts_ns,
                local_ts=local_ts,
                px=event_price_ticks * price_tick_size,
                qty=float(size),
                order_id=max(0, order_id),
                ival=event.flags,
            )
            written += 1
            continue

        if order_id <= 0:
            dropped += 1
            continue

        if action == "ADD":
            if side is None or price_ticks is None or size is None or size <= 0:
                dropped += 1
                continue
            order_state[order_id] = (side, price_ticks, size)
            event_type = constants.add_order_event if use_l3 and constants.add_order_event is not None else constants.depth_event
            ev_flags = _ev_flags(constants, side, event_type)
            _write_row(
                rows,
                written,
                ev=ev_flags,
                exch_ts=event.ts_ns,
                local_ts=local_ts,
                px=price_ticks * price_tick_size,
                qty=float(size),
                order_id=order_id,
                ival=event.flags,
            )
            written += 1
            continue

        if action == "MODIFY":
            if prior is None:
                # Databento can emit MODIFY for unseen order. Treat as ADD if complete fields exist.
                if side is None or price_ticks is None or size is None or size <= 0:
                    dropped += 1
                    continue
                order_state[order_id] = (side, price_ticks, size)
                event_type = (
                    constants.add_order_event if use_l3 and constants.add_order_event is not None else constants.depth_event
                )
                ev_flags = _ev_flags(constants, side, event_type)
                _write_row(
                    rows,
                    written,
                    ev=ev_flags,
                    exch_ts=event.ts_ns,
                    local_ts=local_ts,
                    px=price_ticks * price_tick_size,
                    qty=float(size),
                    order_id=order_id,
                    ival=event.flags,
                )
                written += 1
                continue

            new_side = prior_side if side is None else side
            new_price_ticks = prior_price_ticks if price_ticks is None else price_ticks
            new_size = prior_size if size is None else size
            if new_side is None or new_price_ticks is None or new_size is None or new_size <= 0:
                # Reduce to cancel/delete.
                del order_state[order_id]
                event_type = (
                    constants.cancel_order_event
                    if use_l3 and constants.cancel_order_event is not None
                    else constants.depth_event
                )
                ev_flags = _ev_flags(constants, prior_side, event_type)
                _write_row(
                    rows,
                    written,
                    ev=ev_flags,
                    exch_ts=event.ts_ns,
                    local_ts=local_ts,
                    px=(prior_price_ticks or 0) * price_tick_size,
                    qty=float(prior_size or 0),
                    order_id=order_id,
                    ival=event.flags,
                )
                written += 1
                continue

            order_state[order_id] = (new_side, new_price_ticks, new_size)
            event_type = (
                constants.modify_order_event
                if use_l3 and constants.modify_order_event is not None
                else constants.depth_event
            )
            ev_flags = _ev_flags(constants, new_side, event_type)
            _write_row(
                rows,
                written,
                ev=ev_flags,
                exch_ts=event.ts_ns,
                local_ts=local_ts,
                px=new_price_ticks * price_tick_size,
                qty=float(new_size),
                order_id=order_id,
                ival=event.flags,
            )
            written += 1
            continue

        if action in ("CANCEL", "DELETE"):
            if prior is None:
                dropped += 1
                continue
            book_side, book_price_ticks, book_size = prior
            reduce_size = book_size if action == "DELETE" else (size if size is not None and size > 0 else 0)
            if reduce_size <= 0:
                dropped += 1
                continue
            executed = reduce_size if reduce_size < book_size else book_size
            remaining = book_size - executed
            if remaining > 0:
                order_state[order_id] = (book_side, book_price_ticks, remaining)
            else:
                del order_state[order_id]

            event_type = (
                constants.cancel_order_event
                if use_l3 and constants.cancel_order_event is not None
                else constants.depth_event
            )
            ev_flags = _ev_flags(constants, book_side, event_type)
            _write_row(
                rows,
                written,
                ev=ev_flags,
                exch_ts=event.ts_ns,
                local_ts=local_ts,
                px=book_price_ticks * price_tick_size,
                qty=float(executed),
                order_id=order_id,
                ival=event.flags,
            )
            written += 1
            continue

        dropped += 1

    return HftbMappedFeed(data=rows[:written], used_l3_event_flags=use_l3, dropped_events=dropped)


def write_hftbacktest_npz(mapped: HftbMappedFeed, output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, data=mapped.data)
    return out


def correct_and_validate_hftbacktest_feed(data: np.ndarray, *, hft_module: Any | None = None) -> np.ndarray:
    try:
        from hftbacktest.data import correct_event_order, validate_event_order  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("hftbacktest.data.correct_event_order/validate_event_order not available") from exc
    corrected = correct_event_order(
        data,
        np.argsort(data["exch_ts"], kind="mergesort"),
        np.argsort(data["local_ts"], kind="mergesort"),
    )
    validate_event_order(corrected)
    return corrected


def _write_row(
    rows: np.ndarray,
    idx: int,
    *,
    ev: int,
    exch_ts: int,
    local_ts: int,
    px: float,
    qty: float,
    order_id: int,
    ival: int = 0,
) -> None:
    rows["ev"][idx] = int(ev)
    rows["exch_ts"][idx] = int(exch_ts)
    rows["local_ts"][idx] = int(local_ts)
    rows["px"][idx] = float(px)
    rows["qty"][idx] = float(qty)
    rows["order_id"][idx] = int(order_id)
    rows["ival"][idx] = int(ival)


def _ev_flags(constants: HftbConstants, side: Side | None, event_type: int) -> int:
    side_flag = 0
    if side == "B":
        side_flag = constants.buy_event
    elif side == "A":
        side_flag = constants.sell_event
    return constants.exch_event | constants.local_event | side_flag | event_type


def _load_event_dtype(hft_module: Any | None) -> np.dtype:
    if hft_module is not None and hasattr(hft_module, "event_dtype"):
        return np.dtype(hft_module.event_dtype)
    return _FALLBACK_EVENT_DTYPE


def _load_constants(hft_module: Any | None) -> HftbConstants:
    if hft_module is not None:
        return HftbConstants(
            exch_event=int(getattr(hft_module, "EXCH_EVENT")),
            local_event=int(getattr(hft_module, "LOCAL_EVENT")),
            buy_event=int(getattr(hft_module, "BUY_EVENT")),
            sell_event=int(getattr(hft_module, "SELL_EVENT")),
            depth_event=int(getattr(hft_module, "DEPTH_EVENT")),
            trade_event=int(getattr(hft_module, "TRADE_EVENT")),
            depth_clear_event=int(getattr(hft_module, "DEPTH_CLEAR_EVENT")),
            add_order_event=_opt_int_attr(hft_module, "ADD_ORDER_EVENT"),
            modify_order_event=_opt_int_attr(hft_module, "MODIFY_ORDER_EVENT"),
            cancel_order_event=_opt_int_attr(hft_module, "CANCEL_ORDER_EVENT"),
            fill_event=_opt_int_attr(hft_module, "FILL_EVENT"),
        )
    return HftbConstants(
        exch_event=2_147_483_648,
        local_event=1_073_741_824,
        buy_event=536_870_912,
        sell_event=268_435_456,
        depth_event=1,
        trade_event=2,
        depth_clear_event=3,
        add_order_event=None,
        modify_order_event=None,
        cancel_order_event=None,
        fill_event=None,
    )


def _opt_int_attr(obj: Any, name: str) -> int | None:
    value = getattr(obj, name, None)
    if value is None:
        return None
    return int(value)

