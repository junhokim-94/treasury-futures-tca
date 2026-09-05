from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from .execution_simulator import ExecutionResult


@dataclass(slots=True, frozen=True)
class MetricsConfig:
    markout_horizons_ns: tuple[int, ...] = (
        10_000_000,
        100_000_000,
        1_000_000_000,
        10_000_000_000,
    )
    decision_mid_px_x2: int | None = None
    target_qty: int | None = None


def compute_execution_metrics(result: ExecutionResult, config: MetricsConfig | None = None) -> dict[str, object]:
    cfg = MetricsConfig() if config is None else config
    fills = result.fills
    fill_qty = sum(fill.size for fill in fills)
    notional_ticks = sum(fill.size * fill.price_ticks for fill in fills)
    avg_fill_px = (notional_ticks / fill_qty) if fill_qty > 0 else None

    submitted_qty = 0
    live_order_count = 0
    for order in result.orders:
        submitted_qty += order.initial_size
        if order.status in ("LIVE", "CANCELED", "FILLED", "EXPIRED"):
            live_order_count += 1
    filled_order_count = len({fill.client_order_id for fill in fills})

    market_trade_volume = result.market_trade_volume
    participation_rate = (fill_qty / market_trade_volume) if market_trade_volume > 0 else None
    fill_probability = (filled_order_count / live_order_count) if live_order_count > 0 else None
    message_to_fill = (len(result.decisions) / fill_qty) if fill_qty > 0 else None

    total_cost_x2 = 0
    total_cost_qty = 0
    markout_by_h: dict[str, dict[str, float | int | None]] = {}
    for horizon in cfg.markout_horizons_ns:
        markout_x2_sum = 0
        realized_spread_x2_sum = 0
        adverse_x2_sum = 0
        qty_sum = 0
        for fill in fills:
            side_sign = 1 if fill.side == "B" else -1
            mid_h = _mid_at_or_after(result.mid_ts_ns, result.mid_px_x2, fill.ts_ns + horizon)
            if mid_h is None:
                continue
            qty_sum += fill.size
            # Signed markout from fill price to future mid.
            markout_x2_sum += side_sign * fill.size * (mid_h - 2 * fill.price_ticks)
            # Realized spread proxy.
            realized_spread_x2_sum += side_sign * fill.size * (2 * fill.price_ticks - mid_h)
            # Adverse selection vs arrival mid.
            if fill.arrival_mid_px_x2 is not None:
                adverse_x2_sum += side_sign * fill.size * (mid_h - fill.arrival_mid_px_x2)

        key = str(horizon)
        if qty_sum == 0:
            markout_by_h[key] = {
                "markout_ticks": None,
                "realized_spread_ticks": None,
                "adverse_selection_ticks": None,
                "qty": 0,
            }
            continue
        markout_by_h[key] = {
            "markout_ticks": markout_x2_sum / (2 * qty_sum),
            "realized_spread_ticks": realized_spread_x2_sum / (2 * qty_sum),
            "adverse_selection_ticks": adverse_x2_sum / (2 * qty_sum),
            "qty": qty_sum,
        }

    for fill in fills:
        if fill.arrival_mid_px_x2 is None:
            continue
        side_sign = 1 if fill.side == "B" else -1
        total_cost_x2 += side_sign * fill.size * (2 * fill.price_ticks - fill.arrival_mid_px_x2)
        total_cost_qty += fill.size

    arrival_slippage_ticks = (total_cost_x2 / (2 * total_cost_qty)) if total_cost_qty > 0 else None

    # Perold-style IS proxy for filled quantity; opportunity cost needs target_qty + end benchmark.
    implementation_shortfall_ticks = None
    if cfg.decision_mid_px_x2 is not None and fill_qty > 0:
        side_sign = _infer_parent_side_sign(fills)
        if side_sign is not None:
            implementation_shortfall_ticks = (
                side_sign * (2 * notional_ticks - cfg.decision_mid_px_x2 * fill_qty) / (2 * fill_qty)
            )

    return {
        "fills": len(fills),
        "filled_qty": fill_qty,
        "submitted_qty": submitted_qty,
        "avg_fill_px_ticks": avg_fill_px,
        "arrival_slippage_ticks": arrival_slippage_ticks,
        "implementation_shortfall_ticks": implementation_shortfall_ticks,
        "participation_rate": participation_rate,
        "fill_probability": fill_probability,
        "message_to_fill_ratio": message_to_fill,
        "markout": markout_by_h,
    }


def _mid_at_or_after(ts_ns: list[int], mid_x2: list[int], target_ts_ns: int) -> int | None:
    index = bisect_left(ts_ns, target_ts_ns)
    if index >= len(mid_x2):
        return None
    return mid_x2[index]


def _infer_parent_side_sign(fills) -> int | None:
    if not fills:
        return None
    first_side = fills[0].side
    for fill in fills:
        if fill.side != first_side:
            return None
    return 1 if first_side == "B" else -1


