from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.execution_metrics import MetricsConfig, compute_execution_metrics
from treasury_futures_execution_analytics_tca_engine.execution_algo import PovLiteConfig, build_pov_lite_executor
from treasury_futures_execution_analytics_tca_engine.execution_simulator import simulate_execution
from treasury_futures_execution_analytics_tca_engine.execution_types import ExecutionDecision
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run queue-aware execution simulation on normalized MBO parquet")
    parser.add_argument("--mbo-parquet", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--orders", default="")
    parser.add_argument("--queue-model", choices=["trade_only", "level_depletion"], default="level_depletion")
    parser.add_argument("--validate-every", type=int, default=0)
    parser.add_argument("--instrument-id", type=int, default=None)
    parser.add_argument("--markout-horizons-ns", default="10000000,100000000,1000000000,10000000000")
    parser.add_argument("--algo", choices=["none", "pov_lite"], default="none")
    parser.add_argument("--algo-side", choices=["B", "A"], default="B")
    parser.add_argument("--algo-target-qty", type=int, default=0)
    parser.add_argument("--algo-participation-bps", type=int, default=500)
    parser.add_argument("--algo-min-clip", type=int, default=1)
    parser.add_argument("--algo-max-clip", type=int, default=5)
    parser.add_argument("--algo-price-offset-ticks", type=int, default=1)
    parser.add_argument("--algo-cooldown-events", type=int, default=20)
    args = parser.parse_args()

    mbo_path = Path(args.mbo_parquet)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    events = load_events_from_parquet(mbo_path, instrument_id=args.instrument_id)
    decisions = parse_decisions(args.orders)
    decision_fn = None
    algo_summary: dict[str, object] | None = None
    if args.algo == "pov_lite":
        if args.algo_target_qty <= 0:
            raise ValueError("--algo-target-qty must be > 0 when --algo pov_lite")
        cfg = PovLiteConfig(
            side=args.algo_side,  # type: ignore[arg-type]
            target_qty=args.algo_target_qty,
            participation_bps=args.algo_participation_bps,
            min_clip=args.algo_min_clip,
            max_clip=args.algo_max_clip,
            price_offset_ticks=args.algo_price_offset_ticks,
            cooldown_events=args.algo_cooldown_events,
        )
        algo = build_pov_lite_executor(cfg, first_client_order_id=1_000_000)
        decision_fn = algo.on_event
        algo_summary = {
            "name": "pov_lite",
            "side": cfg.side,
            "target_qty": cfg.target_qty,
            "participation_bps": cfg.participation_bps,
            "min_clip": cfg.min_clip,
            "max_clip": cfg.max_clip,
            "price_offset_ticks": cfg.price_offset_ticks,
            "cooldown_events": cfg.cooldown_events,
        }
    result = simulate_execution(
        events,
        instrument_id=args.instrument_id,
        decisions=decisions,
        decision_fn=decision_fn,
        queue_model=args.queue_model,
        validate_every=args.validate_every,
    )
    cfg = MetricsConfig(markout_horizons_ns=parse_horizons(args.markout_horizons_ns))
    metrics = compute_execution_metrics(result, cfg)

    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if algo_summary is not None:
        (output_dir / "algo.json").write_text(json.dumps(algo_summary, indent=2), encoding="utf-8")
    pd.DataFrame([asdict(fill) for fill in result.fills]).to_parquet(output_dir / "fills.parquet", index=False)
    pd.DataFrame([asdict(order) for order in result.orders]).to_parquet(output_dir / "orders.parquet", index=False)

    print(json.dumps(metrics, indent=2))


def load_events_from_parquet(path: Path, *, instrument_id: int | None) -> list[MBOEvent]:
    df = pd.read_parquet(path)
    if instrument_id is not None:
        df = df[df["instrument_id"] == instrument_id]
    df = df.sort_values(["ts_event_ns", "sequence"], kind="mergesort")
    events: list[MBOEvent] = []
    for row in df.itertuples(index=False):
        action = str(row.action)
        side = _parse_side(row.side)
        price_ticks = _parse_opt_int(row.price_ticks)
        size = _parse_opt_int(row.size)
        order_id = int(row.order_id)
        if action == "RESET":
            order_id = 0
            side = None
            price_ticks = None
            size = None
        events.append(
            MBOEvent(
                ts_ns=int(row.ts_event_ns),
                action=action,  # type: ignore[arg-type]
                order_id=order_id,
                side=side,
                price_ticks=price_ticks,
                size=size,
                ts_recv_ns=int(row.ts_recv_ns),
                flags=int(row.flags),
                sequence=int(row.sequence),
            )
        )
    return events


def parse_decisions(raw: str) -> list[ExecutionDecision]:
    text = raw.strip()
    if not text:
        return []
    out: list[ExecutionDecision] = []
    for token in text.split(";"):
        part = token.strip()
        if not part:
            continue
        fields = [x.strip() for x in part.split(",")]
        if len(fields) < 3:
            continue
        ts_ns = int(fields[0])
        action = fields[1].upper()
        client_order_id = int(fields[2])
        side = _parse_side(fields[3]) if len(fields) > 3 else None
        price_ticks = int(fields[4]) if len(fields) > 4 and fields[4] != "" else None
        size = int(fields[5]) if len(fields) > 5 and fields[5] != "" else None
        out.append(
            ExecutionDecision(
                ts_ns=ts_ns,
                action=action,  # type: ignore[arg-type]
                client_order_id=client_order_id,
                side=side,
                price_ticks=price_ticks,
                size=size,
            )
        )
    out.sort(key=lambda x: x.ts_ns)
    return out


def parse_horizons(raw: str) -> tuple[int, ...]:
    out = []
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        out.append(int(text))
    return tuple(out)


def _parse_opt_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if text == "":
        return None
    return int(value)


def _parse_side(value: object) -> str | None:
    text = str(value).strip().upper()
    if text == "B":
        return "B"
    if text == "A":
        return "A"
    return None


if __name__ == "__main__":
    main()

