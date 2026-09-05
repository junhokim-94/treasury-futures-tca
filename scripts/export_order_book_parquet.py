from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.databento_loader import (
    infer_primary_instrument_id,
    iter_normalized_mbo_events,
    load_instrument_defs,
)
from treasury_futures_execution_analytics_tca_engine.order_book import OrderBook
from treasury_futures_execution_analytics_tca_engine.replay import replay_events

_NONE_I64 = -(1 << 63)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Databento MBO DBN and export order-book snapshots to Parquet")
    parser.add_argument("--mbo-path", required=True)
    parser.add_argument("--definition-path", required=True)
    parser.add_argument("--output-parquet", required=True)
    parser.add_argument("--instrument-id", type=int, default=None)
    parser.add_argument("--snapshot-every", type=int, default=50_000)
    parser.add_argument("--validate-every", type=int, default=200_000)
    parser.add_argument("--max-events", type=int, default=0)
    args = parser.parse_args()

    if args.instrument_id is None:
        instrument_id = infer_primary_instrument_id(args.mbo_path)
    else:
        instrument_id = args.instrument_id

    defs = load_instrument_defs(args.definition_path)
    inst_def = defs.get(instrument_id)
    if inst_def is None:
        raise ValueError(f"instrument_id {instrument_id} not found in definition file")

    events = iter_normalized_mbo_events(
        args.mbo_path,
        instrument_id=instrument_id,
        tick_size=inst_def.tick_size,
        max_events=args.max_events,
    )
    book = OrderBook(instrument_id=instrument_id)
    snapshots = replay_events(
        events=events,
        book=book,
        snapshot_every=args.snapshot_every,
        validate_every=args.validate_every,
    )
    book.validate()
    if not snapshots or snapshots[-1]["ts_ns"] != book.best_bid_ask().ts_ns:
        snapshots.append(book.snapshot_top_n())

    rows = [_flatten_snapshot(snapshot) for snapshot in snapshots]
    df = _to_dataframe(rows)

    output_parquet = Path(args.output_parquet)
    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_parquet, index=False)

    top = book.best_bid_ask()
    summary = {
        "instrument_id": instrument_id,
        "symbol": inst_def.symbol,
        "tick_size": inst_def.tick_size,
        "lot_size": inst_def.lot_size,
        "snapshots": len(snapshots),
        "final_ts_ns": top.ts_ns,
        "final_best_bid_px": top.bid_price_ticks,
        "final_best_bid_sz": top.bid_size,
        "final_best_ask_px": top.ask_price_ticks,
        "final_best_ask_sz": top.ask_size,
        "final_num_orders": len(book.orders_by_id),
        "none_sentinel_i64": _NONE_I64,
    }
    summary_path = output_parquet.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _flatten_snapshot(snapshot: dict[str, object]) -> dict[str, int]:
    row: dict[str, int] = {
        "ts_ns": int(snapshot["ts_ns"]),
        "instrument_id": _i64(snapshot["instrument_id"]),
        "best_bid_px": _i64(snapshot["best_bid_px"]),
        "best_bid_sz": int(snapshot["best_bid_sz"]),
        "best_ask_px": _i64(snapshot["best_ask_px"]),
        "best_ask_sz": int(snapshot["best_ask_sz"]),
        "num_orders": int(snapshot["num_orders"]),
        "total_bid_depth": int(snapshot["total_bid_depth"]),
        "total_ask_depth": int(snapshot["total_ask_depth"]),
    }
    _append_top_levels(row, "bid", snapshot["bid_levels"])  # type: ignore[arg-type]
    _append_top_levels(row, "ask", snapshot["ask_levels"])  # type: ignore[arg-type]
    return row


def _append_top_levels(row: dict[str, int], side: str, levels: list[tuple[int, int]]) -> None:
    for idx in range(10):
        px_key = f"{side}_px_{idx + 1}"
        sz_key = f"{side}_sz_{idx + 1}"
        if idx < len(levels):
            px, sz = levels[idx]
            row[px_key] = int(px)
            row[sz_key] = int(sz)
        else:
            row[px_key] = _NONE_I64
            row[sz_key] = 0


def _i64(value: object) -> int:
    if value is None:
        return _NONE_I64
    return int(value)


def _to_dataframe(rows: list[dict[str, int]]):
    try:
        import pandas as pd  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pandas+pyarrow are required for parquet export") from exc
    df = pd.DataFrame(rows)
    for col in df.columns:
        df[col] = df[col].astype("int64")
    return df


if __name__ == "__main__":
    main()

