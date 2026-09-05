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

from treasury_futures_execution_analytics_tca_engine.engine_compare import run_parallel_comparison
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run internal execution simulator and compare against HFTBacktest")
    parser.add_argument("--mbo-parquet", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--orders", default="")
    parser.add_argument("--queue-model", choices=["trade_only", "level_depletion"], default="level_depletion")
    parser.add_argument("--validate-every", type=int, default=0)
    parser.add_argument("--instrument-id", type=int, default=None)
    args = parser.parse_args()

    events = load_events_from_parquet(Path(args.mbo_parquet), instrument_id=args.instrument_id)
    decisions = parse_decisions(args.orders)
    out = run_parallel_comparison(
        events=events,
        decisions=decisions,
        instrument_id=args.instrument_id,
        queue_model=args.queue_model,
        validate_every=args.validate_every,
    )
    payload = asdict(out)
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


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


def parse_decisions(raw: str):
    from treasury_futures_execution_analytics_tca_engine.execution_types import ExecutionDecision

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

