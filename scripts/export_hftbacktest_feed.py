from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.hftbacktest_adapter import (
    HftbMappedFeed,
    correct_and_validate_hftbacktest_feed,
    map_mbo_events_to_hftbacktest_feed,
    write_hftbacktest_npz,
)
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


def main() -> None:
    parser = argparse.ArgumentParser(description="Export normalized MBO parquet to HFTBacktest npz feed")
    parser.add_argument("--mbo-parquet", required=True)
    parser.add_argument("--output-npz", required=True)
    parser.add_argument("--instrument-id", type=int, default=None)
    parser.add_argument("--price-tick-size", type=float, default=1.0)
    parser.add_argument("--local-ts-offset-ns", type=int, default=0)
    parser.add_argument("--disable-l3-events", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    events = load_events_from_parquet(Path(args.mbo_parquet), instrument_id=args.instrument_id)
    mapped = map_mbo_events_to_hftbacktest_feed(
        events,
        price_tick_size=args.price_tick_size,
        local_ts_offset_ns=args.local_ts_offset_ns,
        use_l3_events=not args.disable_l3_events,
    )
    data = mapped.data
    validated = False
    if args.validate:
        data = correct_and_validate_hftbacktest_feed(data)
        validated = True
    out_path = write_hftbacktest_npz(
        HftbMappedFeed(
            data=data,
            used_l3_event_flags=mapped.used_l3_event_flags,
            dropped_events=mapped.dropped_events,
        ),
        Path(args.output_npz),
    )

    summary = {
        "output_npz": str(out_path),
        "events_in": len(events),
        "rows_out": int(data.shape[0]),
        "dropped_events": mapped.dropped_events,
        "used_l3_event_flags": mapped.used_l3_event_flags,
        "validated": validated,
    }
    print(json.dumps(summary, indent=2))


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

