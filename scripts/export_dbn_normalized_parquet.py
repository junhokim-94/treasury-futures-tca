from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.databento_loader import infer_primary_instrument_id, load_instrument_defs

_NULL_PRICE = 9_223_372_036_854_775_807

_ACTION_MAP: dict[str, str] = {
    "A": "ADD",
    "C": "CANCEL",
    "M": "MODIFY",
    "D": "DELETE",
    "R": "RESET",
    "T": "TRADE",
    "F": "FILL",
}

_SIDE_MAP: dict[str, str] = {"B": "B", "A": "A"}


@dataclass(slots=True, frozen=True)
class _InstMeta:
    instrument_id: int
    raw_symbol: str
    tick_size: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Export one-day normalized parquet from Databento DBN")
    parser.add_argument("--mbo-path", required=True)
    parser.add_argument("--definition-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--instrument-id", type=int, default=None)
    parser.add_argument("--max-events", type=int, default=0)
    args = parser.parse_args()

    mbo_path = Path(args.mbo_path)
    definition_path = Path(args.definition_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session_date_yyyymmdd = _infer_session_date_from_filename(mbo_path)
    session_date = _yyyymmdd_to_iso(session_date_yyyymmdd)

    defs = load_instrument_defs(definition_path)

    instrument_id = args.instrument_id
    if instrument_id is None:
        instrument_id = infer_primary_instrument_id(mbo_path, max_records=300_000)

    inst = defs.get(instrument_id)
    if inst is None:
        raise ValueError(f"instrument_id {instrument_id} not found in definition")

    meta = _InstMeta(
        instrument_id=inst.instrument_id,
        raw_symbol=inst.symbol,
        tick_size=inst.tick_size,
    )

    mbo_df = _build_mbo_parquet(
        mbo_path=mbo_path,
        meta=meta,
        session_date=session_date,
        max_events=args.max_events,
    )

    if mbo_df.empty:
        raise RuntimeError("no mbo rows produced")

    def_df = _build_instrument_def_parquet(
        defs=defs,
        date_text=session_date,
    )

    mbo_out = output_dir / f"mbo_event_{session_date_yyyymmdd}.parquet"
    def_out = output_dir / f"instrument_def_{session_date_yyyymmdd}.parquet"

    mbo_df.to_parquet(mbo_out, index=False)
    def_df.to_parquet(def_out, index=False)

    print(f"mbo_event_rows={len(mbo_df)} path={mbo_out}")
    print(f"instrument_def_rows={len(def_df)} path={def_out}")
    print("date_counts:")
    print(mbo_df["date"].value_counts().sort_index())
    print("event_date_counts:")
    print(mbo_df["event_date"].value_counts().sort_index())


def _build_mbo_parquet(
    *,
    mbo_path: Path,
    meta: _InstMeta,
    session_date: str,
    max_events: int,
) -> pd.DataFrame:
    import databento as db  # type: ignore[import-not-found]

    rows: list[dict[str, object]] = []
    emitted = 0

    for rec in db.DBNStore.from_file(mbo_path):
        if not hasattr(rec, "action"):
            continue

        if int(rec.instrument_id) != meta.instrument_id:
            continue

        action = _ACTION_MAP.get(str(rec.action))
        if action is None:
            continue

        ts_event_ns = int(rec.ts_event)
        ts_recv_ns = int(getattr(rec, "ts_recv", rec.ts_event))
        flags = int(getattr(rec, "flags", 0))
        sequence = int(getattr(rec, "sequence", 0))

        order_id = int(rec.order_id)
        side = _SIDE_MAP.get(str(rec.side), "")

        price_ticks: int | None = None
        price_raw = int(rec.price)

        if price_raw != _NULL_PRICE and meta.tick_size > 0 and price_raw % meta.tick_size == 0:
            price_ticks = price_raw // meta.tick_size

        size_raw = int(rec.size)
        size: int | None = size_raw if size_raw > 0 else None

        if action == "RESET":
            order_id = 0
            side = ""
            price_ticks = None
            size = None

        if action in ("ADD", "MODIFY") and (
            order_id <= 0 or side == "" or price_ticks is None or size is None
        ):
            continue

        if action in ("CANCEL", "FILL") and (order_id <= 0 or size is None):
            continue

        if action == "TRADE" and (order_id < 0 or size is None):
            continue

        if action == "DELETE" and order_id <= 0:
            continue

        event_date = datetime.fromtimestamp(
            ts_event_ns / 1_000_000_000,
            tz=timezone.utc,
        ).date().isoformat()

        rows.append(
            {
                # HDB partition/session date.
                "date": session_date,

                # Original calendar date from ts_event_ns.
                "event_date": event_date,

                "ts_event_ns": ts_event_ns,
                "ts_recv_ns": ts_recv_ns,
                "instrument_id": meta.instrument_id,
                "raw_symbol": meta.raw_symbol,
                "action": action,
                "side": side,
                "order_id": order_id,
                "price_ticks": price_ticks,
                "size": size,
                "flags": flags,
                "sequence": sequence,
            }
        )

        emitted += 1
        if max_events > 0 and emitted >= max_events and flags & (1 << 7):
            break

    return pd.DataFrame(rows)


def _build_instrument_def_parquet(*, defs: dict[int, object], date_text: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for instrument_id in sorted(defs):
        inst = defs[instrument_id]

        rows.append(
            {
                "date": date_text,
                "instrument_id": int(getattr(inst, "instrument_id")),
                "raw_symbol": str(getattr(inst, "symbol")),
                "min_price_increment": float(getattr(inst, "tick_size")),
                "price_scale": 1_000_000_000,
                "multiplier": 1.0,
                "asset_class": "",
                "exchange": "",
                "expiry": "",
            }
        )

    return pd.DataFrame(rows)


def _infer_session_date_from_filename(path: Path) -> str:
    matched = re.search(r"(20\d{6})", path.name)
    if matched is None:
        raise ValueError(f"could not infer session date from file name: {path.name}")
    return matched.group(1)


def _yyyymmdd_to_iso(value: str) -> str:
    if len(value) != 8:
        raise ValueError(f"invalid yyyymmdd value: {value}")
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


if __name__ == "__main__":
    main()

