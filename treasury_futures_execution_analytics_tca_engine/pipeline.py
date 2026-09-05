from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .columnar import write_snapshots_columnar
from .databento_loader import (
    infer_primary_instrument_id,
    iter_normalized_mbo_events,
    load_instrument_defs,
)
from .order_book import OrderBook
from .replay import replay_events
from .types import MBOEvent


def replay_to_columnar(
    events: Iterable[MBOEvent],
    *,
    instrument_id: int,
    output_dir: str | Path,
    snapshot_every: int = 10_000,
    validate_every: int = 100_000,
) -> dict[str, object]:
    book = OrderBook(instrument_id=instrument_id)
    snapshots = replay_events(
        events=events,
        book=book,
        snapshot_every=snapshot_every,
        validate_every=validate_every,
    )
    book.validate()
    top = book.best_bid_ask()
    stats = write_snapshots_columnar(snapshots, output_dir)
    summary: dict[str, object] = {
        "instrument_id": instrument_id,
        "snapshots": len(snapshots),
        "final_ts_ns": top.ts_ns,
        "final_best_bid_px": top.bid_price_ticks,
        "final_best_bid_sz": top.bid_size,
        "final_best_ask_px": top.ask_price_ticks,
        "final_best_ask_sz": top.ask_size,
        "final_num_orders": len(book.orders_by_id),
        **stats,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_order_book_from_dbn(
    *,
    mbo_path: str | Path,
    definition_path: str | Path,
    output_dir: str | Path,
    instrument_id: int | None = None,
    snapshot_every: int = 10_000,
    validate_every: int = 100_000,
    max_events: int = 0,
) -> dict[str, object]:
    if instrument_id is None:
        instrument_id = infer_primary_instrument_id(mbo_path)
    defs = load_instrument_defs(definition_path)
    inst_def = defs.get(instrument_id)
    if inst_def is None:
        raise ValueError(f"instrument_id {instrument_id} not found in definition file")
    events = iter_normalized_mbo_events(
        mbo_path,
        instrument_id=instrument_id,
        tick_size=inst_def.tick_size,
        max_events=max_events,
    )
    summary = replay_to_columnar(
        events,
        instrument_id=instrument_id,
        output_dir=output_dir,
        snapshot_every=snapshot_every,
        validate_every=validate_every,
    )
    summary["symbol"] = inst_def.symbol
    summary["tick_size"] = inst_def.tick_size
    summary["lot_size"] = inst_def.lot_size
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    (Path(output_dir) / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

