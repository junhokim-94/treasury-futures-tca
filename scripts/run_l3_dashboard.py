from __future__ import annotations

import argparse
import asyncio
from bisect import bisect_left
from collections import deque
import contextlib
from dataclasses import dataclass, field
import sys
from pathlib import Path
from typing import Any, Deque

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from treasury_futures_execution_analytics_tca_engine.databento_loader import (
    infer_primary_instrument_id,
    iter_normalized_mbo_events,
    load_instrument_defs,
)
from treasury_futures_execution_analytics_tca_engine.execution_simulator import ExecutionSimulator
from treasury_futures_execution_analytics_tca_engine.execution_types import ExecutionDecision
from treasury_futures_execution_analytics_tca_engine.streaming import QueueSubscription, build_l3_update, parse_queue_levels

app = FastAPI(title="L3 Replay Dashboard")
_DASHBOARD_HTML = ROOT / "dashboard" / "index.html"

_REVERSION_HORIZON_NS = 1_000_000_000
_VPIN_BUCKET_QTY = 200
_VPIN_WINDOW_BUCKETS = 50


@dataclass(slots=True)
class _RealtimeTCAState:
    decision_ts_ns: int | None = None
    decision_mid_px_x2: int | None = None
    parent_side: str | None = None
    submitted_qty: int = 0
    market_trade_qty: int = 0
    market_trade_notional_ticks: int = 0
    twap_mid_sum_x2: int = 0
    twap_mid_count: int = 0
    vpin_bucket_qty: int = 0
    vpin_bucket_buy_qty: int = 0
    vpin_bucket_sell_qty: int = 0
    vpin_imbalances: Deque[float] = field(default_factory=deque)
    vpin_imbalance_sum: float = 0.0


@app.get("/")
def dashboard_index() -> FileResponse:
    return FileResponse(_DASHBOARD_HTML)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/replay")
async def replay_ws(ws: WebSocket) -> None:
    await ws.accept()
    try:
        start_msg = await ws.receive_json()
        if start_msg.get("cmd") != "start":
            await ws.send_json({"type": "error", "message": "first message must be {'cmd':'start', ...}"})
            await ws.close(code=1003)
            return

        config = start_msg
        await ws.send_json({"type": "status", "stage": "initializing"})
        mbo_path = str(config["mbo_path"])
        definition_path = str(config["definition_path"])
        instrument_id = _optional_int(config.get("instrument_id"))
        if instrument_id is None:
            instrument_id = infer_primary_instrument_id(mbo_path, max_records=300_000)
        max_events = _non_negative_int(config.get("max_events", 0))
        emit_every = max(1, _non_negative_int(config.get("emit_every", 1)))
        validate_every = _non_negative_int(config.get("validate_every", 0))
        top_n = max(1, _non_negative_int(config.get("top_n", 10)))
        around_ticks = _non_negative_int(config.get("around_ticks", 0))
        delay_ms = _non_negative_int(config.get("delay_ms", 0))
        max_queue_orders = max(1, _non_negative_int(config.get("max_queue_orders", 30)))
        queue_subscriptions = parse_queue_levels(str(config.get("queue_levels", "")), max_orders=max_queue_orders)

        defs = load_instrument_defs(definition_path)
        inst_def = defs.get(instrument_id)
        if inst_def is None:
            await ws.send_json(
                {"type": "error", "message": f"instrument_id {instrument_id} not found in definition file"}
            )
            await ws.close(code=1003)
            return

        events = iter_normalized_mbo_events(
            mbo_path,
            instrument_id=instrument_id,
            tick_size=inst_def.tick_size,
            max_events=max_events,
        )
        sim = ExecutionSimulator(instrument_id=instrument_id, validate_every=validate_every)
        book = sim.book

        await ws.send_json(
            {
                "type": "started",
                "instrument_id": instrument_id,
                "symbol": inst_def.symbol,
                "tick_size": inst_def.tick_size,
                "lot_size": inst_def.lot_size,
                "emit_every": emit_every,
                "validate_every": validate_every,
                "top_n": top_n,
                "around_ticks": around_ticks,
            }
        )

        controls: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        reader_task = asyncio.create_task(_read_controls(ws, controls))
        paused = False
        seq = 0
        consumed = 0
        current_ts_ns = 0
        next_client_order_id = 1
        tca_state = _RealtimeTCAState()

        try:
            for event in events:
                consumed += 1
                queue_subscriptions, delay_ms, paused, around_ticks, next_client_order_id = await _drain_controls(
                    controls=controls,
                    ws=ws,
                    queue_subscriptions=queue_subscriptions,
                    delay_ms=delay_ms,
                    paused=paused,
                    around_ticks=around_ticks,
                    max_queue_orders=max_queue_orders,
                    sim=sim,
                    ts_ns=current_ts_ns,
                    next_client_order_id=next_client_order_id,
                    tca_state=tca_state,
                )
                while paused:
                    cmd = await controls.get()
                    queue_subscriptions, delay_ms, paused, around_ticks, next_client_order_id = await _apply_control(
                        cmd=cmd,
                        ws=ws,
                        queue_subscriptions=queue_subscriptions,
                        delay_ms=delay_ms,
                        paused=paused,
                        around_ticks=around_ticks,
                        max_queue_orders=max_queue_orders,
                        sim=sim,
                        ts_ns=current_ts_ns,
                        next_client_order_id=next_client_order_id,
                        tca_state=tca_state,
                    )

                sim.apply_event(event)
                _update_tca_market_state(state=tca_state, event=event, sim=sim)
                current_ts_ns = event.ts_ns
                seq += 1
                await asyncio.sleep(0)
                if seq != 1 and seq % emit_every != 0:
                    continue

                update = build_l3_update(
                    seq=seq,
                    event=event,
                    book=book,
                    top_n=top_n,
                    around_ticks=around_ticks,
                    queue_subscriptions=queue_subscriptions,
                )
                update["execution"] = _build_execution_snapshot(sim, tca_state)
                await ws.send_json(update)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)
        finally:
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader_task

        top = book.best_bid_ask()
        await ws.send_json(
            {
                "type": "eof",
                "events": consumed,
                "seq": seq,
                "final_ts_ns": top.ts_ns,
                "final_best_bid_px": top.bid_price_ticks,
                "final_best_bid_sz": top.bid_size,
                "final_best_ask_px": top.ask_price_ticks,
                "final_best_ask_sz": top.ask_size,
                "final_num_orders": len(book.orders_by_id),
            }
        )
    except WebSocketDisconnect:
        return


async def _read_controls(ws: WebSocket, controls: asyncio.Queue[dict[str, Any]]) -> None:
    while True:
        msg = await ws.receive_json()
        if isinstance(msg, dict):
            await controls.put(msg)


async def _drain_controls(
    *,
    controls: asyncio.Queue[dict[str, Any]],
    ws: WebSocket,
    queue_subscriptions: list[QueueSubscription],
    delay_ms: int,
    paused: bool,
    around_ticks: int,
    max_queue_orders: int,
    sim: ExecutionSimulator,
    ts_ns: int,
    next_client_order_id: int,
    tca_state: _RealtimeTCAState,
) -> tuple[list[QueueSubscription], int, bool, int, int]:
    while True:
        try:
            cmd = controls.get_nowait()
        except asyncio.QueueEmpty:
            return queue_subscriptions, delay_ms, paused, around_ticks, next_client_order_id
        queue_subscriptions, delay_ms, paused, around_ticks, next_client_order_id = await _apply_control(
            cmd=cmd,
            ws=ws,
            queue_subscriptions=queue_subscriptions,
            delay_ms=delay_ms,
            paused=paused,
            around_ticks=around_ticks,
            max_queue_orders=max_queue_orders,
            sim=sim,
            ts_ns=ts_ns,
            next_client_order_id=next_client_order_id,
            tca_state=tca_state,
        )


async def _apply_control(
    *,
    cmd: dict[str, Any],
    ws: WebSocket,
    queue_subscriptions: list[QueueSubscription],
    delay_ms: int,
    paused: bool,
    around_ticks: int,
    max_queue_orders: int,
    sim: ExecutionSimulator,
    ts_ns: int,
    next_client_order_id: int,
    tca_state: _RealtimeTCAState,
) -> tuple[list[QueueSubscription], int, bool, int, int]:
    name = str(cmd.get("cmd", "")).lower()
    next_id, exec_ack = _apply_execution_command(
        cmd=cmd,
        sim=sim,
        ts_ns=ts_ns,
        next_client_order_id=next_client_order_id,
        tca_state=tca_state,
    )
    if exec_ack is not None:
        exec_ack["execution"] = _build_execution_snapshot(sim, tca_state)
        await ws.send_json(exec_ack)
        next_client_order_id = next_id
        return queue_subscriptions, delay_ms, paused, around_ticks, next_client_order_id
    if name == "pause":
        return queue_subscriptions, delay_ms, True, around_ticks, next_client_order_id
    if name == "resume":
        return queue_subscriptions, delay_ms, False, around_ticks, next_client_order_id
    if name == "set_delay_ms":
        new_delay = _non_negative_int(cmd.get("delay_ms", delay_ms))
        return queue_subscriptions, new_delay, paused, around_ticks, next_client_order_id
    if name == "set_around_ticks":
        new_around = _non_negative_int(cmd.get("around_ticks", around_ticks))
        return queue_subscriptions, delay_ms, paused, new_around, next_client_order_id
    if name == "set_queue_levels":
        raw = str(cmd.get("queue_levels", ""))
        subs = parse_queue_levels(raw, max_orders=max_queue_orders)
        return subs, delay_ms, paused, around_ticks, next_client_order_id
    return queue_subscriptions, delay_ms, paused, around_ticks, next_client_order_id


def _apply_execution_command(
    *,
    cmd: dict[str, Any],
    sim: ExecutionSimulator,
    ts_ns: int,
    next_client_order_id: int,
    tca_state: _RealtimeTCAState,
) -> tuple[int, dict[str, object] | None]:
    name = str(cmd.get("cmd", "")).lower()
    if name not in {"submit_order", "cancel_order", "replace_order"}:
        return next_client_order_id, None
    try:
        top_before = sim.book.best_bid_ask()
        fills_before = len(sim._fills)  # noqa: SLF001
        if name == "cancel_order":
            client_order_id = int(cmd.get("client_order_id"))
            sim.apply_decision(
                ExecutionDecision(
                    ts_ns=ts_ns,
                    action="CANCEL",
                    client_order_id=client_order_id,
                )
            )
            return next_client_order_id, {
                "type": "exec_ack",
                "cmd": "cancel_order",
                "client_order_id": client_order_id,
                "best_bid_px": top_before.bid_price_ticks,
                "best_ask_px": top_before.ask_price_ticks,
                "fills_added": 0,
            }

        side = str(cmd.get("side", "")).upper()
        if side not in {"B", "A"}:
            raise ValueError("side must be B or A")
        price_ticks = int(cmd.get("price_ticks"))
        size = int(cmd.get("size"))
        if size <= 0:
            raise ValueError("size must be > 0")
        client_order_id = _optional_int(cmd.get("client_order_id"))
        if client_order_id is None:
            client_order_id = next_client_order_id
            next_client_order_id += 1
        elif client_order_id >= next_client_order_id:
            next_client_order_id = client_order_id + 1
        action = "NEW" if name == "submit_order" else "REPLACE"
        if tca_state.parent_side is None:
            tca_state.parent_side = side
            tca_state.decision_ts_ns = ts_ns
            if top_before.bid_price_ticks is not None and top_before.ask_price_ticks is not None:
                tca_state.decision_mid_px_x2 = top_before.bid_price_ticks + top_before.ask_price_ticks
        if name == "submit_order" and tca_state.parent_side == side and size > 0:
            tca_state.submitted_qty += size
        sim.apply_decision(
            ExecutionDecision(
                ts_ns=ts_ns,
                action=action,  # type: ignore[arg-type]
                client_order_id=client_order_id,
                side=side,  # type: ignore[arg-type]
                price_ticks=price_ticks,
                size=size,
            )
        )
        fills_after = len(sim._fills)  # noqa: SLF001
        fills_added = fills_after - fills_before
        immediate_filled_size = 0
        if fills_added > 0:
            for fill in sim._fills[fills_before:fills_after]:  # noqa: SLF001
                immediate_filled_size += fill.size

        top_after = sim.book.best_bid_ask()
        marketable = False
        if side == "B" and top_before.ask_price_ticks is not None:
            marketable = price_ticks >= top_before.ask_price_ticks
        if side == "A" and top_before.bid_price_ticks is not None:
            marketable = price_ticks <= top_before.bid_price_ticks

        return next_client_order_id, {
            "type": "exec_ack",
            "cmd": name,
            "client_order_id": client_order_id,
            "side": side,
            "price_ticks": price_ticks,
            "size": size,
            "best_bid_px": top_before.bid_price_ticks,
            "best_ask_px": top_before.ask_price_ticks,
            "best_bid_px_after": top_after.bid_price_ticks,
            "best_ask_px_after": top_after.ask_price_ticks,
            "marketable_at_submit": marketable,
            "fills_added": fills_added,
            "immediate_filled_size": immediate_filled_size,
        }
    except Exception as exc:  # noqa: BLE001
        return next_client_order_id, {
            "type": "error",
            "message": f"execution command failed: {exc}",
        }


def _build_execution_snapshot(sim: ExecutionSimulator, tca_state: _RealtimeTCAState) -> dict[str, object]:
    book = sim.book
    top = book.best_bid_ask()
    mid_x2 = None
    if top.bid_price_ticks is not None and top.ask_price_ticks is not None:
        mid_x2 = top.bid_price_ticks + top.ask_price_ticks

    position = 0
    cash_ticks = 0
    recent_fills: list[dict[str, object]] = []
    fills = sim._fills  # noqa: SLF001
    for fill in fills:
        if fill.side == "B":
            position += fill.size
            cash_ticks -= fill.price_ticks * fill.size
        else:
            position -= fill.size
            cash_ticks += fill.price_ticks * fill.size
    for fill in reversed(fills):
        if len(recent_fills) >= 20:
            break
        recent_fills.append(
            {
                "ts_ns": fill.ts_ns,
                "client_order_id": fill.client_order_id,
                "side": fill.side,
                "price_ticks": fill.price_ticks,
                "size": fill.size,
            }
        )

    mtm_pnl_x2 = None
    if mid_x2 is not None:
        mtm_pnl_x2 = cash_ticks * 2 + position * mid_x2

    live_orders = [
        {
            "client_order_id": order.client_order_id,
            "side": order.side,
            "price_ticks": order.price_ticks,
            "initial_size": order.initial_size,
            "remaining_size": order.remaining_size,
            "queue_ahead_size": order.queue_ahead_size,
            "status": order.status,
        }
        for order in sorted(sim._live_orders.values(), key=lambda x: x.client_order_id)  # noqa: SLF001
        if order.status == "LIVE" and order.remaining_size > 0
    ]
    tca = _build_tca_metrics(
        sim=sim,
        state=tca_state,
        current_mid_x2=mid_x2,
        live_orders=live_orders,
    )
    return {
        "position": position,
        "cash_ticks": cash_ticks,
        "mid_px_x2": mid_x2,
        "mtm_pnl_x2": mtm_pnl_x2,
        "live_orders": live_orders,
        "recent_fills": recent_fills,
        "tca": tca,
    }


def _update_tca_market_state(*, state: _RealtimeTCAState, event, sim: ExecutionSimulator) -> None:
    top = sim.book.best_bid_ask()
    if top.bid_price_ticks is not None and top.ask_price_ticks is not None:
        mid_x2 = top.bid_price_ticks + top.ask_price_ticks
        state.twap_mid_sum_x2 += mid_x2
        state.twap_mid_count += 1
        if state.parent_side is not None and state.decision_mid_px_x2 is None:
            state.decision_mid_px_x2 = mid_x2
            if state.decision_ts_ns is None:
                state.decision_ts_ns = event.ts_ns

    if event.action == "TRADE" and event.price_ticks is not None and event.size is not None and event.size > 0:
        state.market_trade_qty += event.size
        state.market_trade_notional_ticks += event.price_ticks * event.size
        _update_vpin(state=state, side=event.side, size=event.size)


def _build_tca_metrics(
    *,
    sim: ExecutionSimulator,
    state: _RealtimeTCAState,
    current_mid_x2: int | None,
    live_orders: list[dict[str, object]],
) -> dict[str, object]:
    parent_side = state.parent_side
    side_sign = 1 if parent_side == "B" else -1 if parent_side == "A" else None
    fills = sim._fills  # noqa: SLF001
    fill_qty = 0
    fill_notional = 0
    arrival_mid_x2_sum = 0
    arrival_mid_qty = 0
    effective_spread_x2_sum = 0
    first_fill_arrival_mid_x2: int | None = None
    reversion_x2_sum = 0
    reversion_qty = 0
    mid_ts = sim._mid_ts_ns  # noqa: SLF001
    mid_x2 = sim._mid_px_x2  # noqa: SLF001

    for fill in fills:
        if parent_side is not None and fill.side != parent_side:
            continue
        fill_qty += fill.size
        fill_notional += fill.price_ticks * fill.size
        if fill.arrival_mid_px_x2 is not None:
            arrival_mid_x2_sum += fill.arrival_mid_px_x2 * fill.size
            arrival_mid_qty += fill.size
            diff_x2 = abs(2 * fill.price_ticks - fill.arrival_mid_px_x2)
            effective_spread_x2_sum += 2 * diff_x2 * fill.size
            if first_fill_arrival_mid_x2 is None:
                first_fill_arrival_mid_x2 = fill.arrival_mid_px_x2
        if side_sign is not None:
            future_mid_x2 = _mid_at_or_after(mid_ts, mid_x2, fill.ts_ns + _REVERSION_HORIZON_NS)
            if future_mid_x2 is not None:
                reversion_x2_sum += side_sign * fill.size * (future_mid_x2 - 2 * fill.price_ticks)
                reversion_qty += fill.size

    avg_fill_px = (fill_notional / fill_qty) if fill_qty > 0 else None
    market_vwap = (
        state.market_trade_notional_ticks / state.market_trade_qty
        if state.market_trade_qty > 0
        else None
    )
    twap_mid = (state.twap_mid_sum_x2 / (2 * state.twap_mid_count)) if state.twap_mid_count > 0 else None
    arrival_mid = (arrival_mid_x2_sum / (2 * arrival_mid_qty)) if arrival_mid_qty > 0 else None

    implementation_shortfall = None
    vwap_slippage = None
    twap_slippage = None
    market_impact = None
    delay_cost = None
    opportunity_cost = None
    participation_rate = None
    if side_sign is not None and fill_qty > 0:
        if state.decision_mid_px_x2 is not None:
            implementation_shortfall = (
                side_sign * (2 * fill_notional - state.decision_mid_px_x2 * fill_qty) / (2 * fill_qty)
            )
        if market_vwap is not None:
            vwap_slippage = side_sign * (avg_fill_px - market_vwap)
        if twap_mid is not None:
            twap_slippage = side_sign * (avg_fill_px - twap_mid)
        if arrival_mid is not None and state.decision_mid_px_x2 is not None:
            market_impact = side_sign * (2 * arrival_mid - state.decision_mid_px_x2) / 2
        if first_fill_arrival_mid_x2 is not None and state.decision_mid_px_x2 is not None:
            delay_cost = side_sign * (first_fill_arrival_mid_x2 - state.decision_mid_px_x2) / 2
    if state.market_trade_qty > 0 and fill_qty > 0:
        participation_rate = fill_qty / state.market_trade_qty

    effective_spread = (effective_spread_x2_sum / (2 * arrival_mid_qty)) if arrival_mid_qty > 0 else None
    price_reversion_1s = (reversion_x2_sum / (2 * reversion_qty)) if reversion_qty > 0 else None

    working_qty = 0
    if parent_side is not None:
        for order in live_orders:
            if order["side"] == parent_side:
                working_qty += int(order["remaining_size"])
    if side_sign is not None and current_mid_x2 is not None and state.decision_mid_px_x2 is not None and working_qty > 0:
        opportunity_cost = side_sign * (current_mid_x2 - state.decision_mid_px_x2) * working_qty / 2
    vpin = None
    if state.vpin_imbalances:
        vpin = state.vpin_imbalance_sum / len(state.vpin_imbalances)

    return {
        "parent_side": parent_side,
        "submitted_qty": state.submitted_qty,
        "filled_qty": fill_qty,
        "implementation_shortfall_ticks": implementation_shortfall,
        "vwap_slippage_ticks": vwap_slippage,
        "twap_slippage_ticks": twap_slippage,
        "market_impact_ticks": market_impact,
        "delay_cost_ticks": delay_cost,
        "price_reversion_1s_ticks": price_reversion_1s,
        "effective_spread_ticks": effective_spread,
        "opportunity_cost_tick_qty": opportunity_cost,
        "participation_rate": participation_rate,
        "vpin": vpin,
        "market_vwap_ticks": market_vwap,
        "market_twap_mid_ticks": twap_mid,
    }


def _update_vpin(*, state: _RealtimeTCAState, side: str | None, size: int) -> None:
    if side not in {"B", "A"} or size <= 0:
        return
    remaining = size
    while remaining > 0:
        space = _VPIN_BUCKET_QTY - state.vpin_bucket_qty
        take = remaining if remaining < space else space
        if side == "B":
            state.vpin_bucket_buy_qty += take
        else:
            state.vpin_bucket_sell_qty += take
        state.vpin_bucket_qty += take
        remaining -= take
        if state.vpin_bucket_qty < _VPIN_BUCKET_QTY:
            break
        imbalance = abs(state.vpin_bucket_buy_qty - state.vpin_bucket_sell_qty) / _VPIN_BUCKET_QTY
        state.vpin_imbalances.append(imbalance)
        state.vpin_imbalance_sum += imbalance
        if len(state.vpin_imbalances) > _VPIN_WINDOW_BUCKETS:
            state.vpin_imbalance_sum -= state.vpin_imbalances.popleft()
        state.vpin_bucket_qty = 0
        state.vpin_bucket_buy_qty = 0
        state.vpin_bucket_sell_qty = 0


def _mid_at_or_after(ts_ns: list[int], mid_x2: list[int], target_ts_ns: int) -> int | None:
    index = bisect_left(ts_ns, target_ts_ns)
    if index >= len(mid_x2):
        return None
    return mid_x2[index]


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _non_negative_int(value: Any) -> int:
    number = int(value)
    return number if number > 0 else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run minimal FastAPI + WebSocket L3 replay dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


if __name__ == "__main__":
    import uvicorn

    args = _parse_args()
    uvicorn.run(app, host=args.host, port=args.port)

