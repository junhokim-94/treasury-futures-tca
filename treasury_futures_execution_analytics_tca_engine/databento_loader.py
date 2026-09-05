from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from pathlib import Path
import sys

from .types import Action, InstrumentDef, MBOEvent, MBO_F_LAST, Side

_NULL_PRICE = 9_223_372_036_854_775_807
_ACTION_MAP: dict[str, Action] = {
    "A": "ADD",
    "C": "CANCEL",
    "M": "MODIFY",
    "D": "DELETE",
    "R": "RESET",
    "T": "TRADE",
    "F": "FILL",
}
_SIDE_MAP: dict[str, Side] = {"B": "B", "A": "A"}


def normalize_mbo_values(
    *,
    ts_ns: int,
    action_code: str,
    side_code: str,
    order_id: int,
    price_raw: int,
    size: int,
    tick_size: int,
    ts_recv_ns: int | None = None,
    flags: int = MBO_F_LAST,
    sequence: int = 0,
) -> MBOEvent | None:
    action = _ACTION_MAP.get(action_code)
    if action is None:
        return None
    if action == "RESET":
        return MBOEvent(
            ts_ns=ts_ns,
            action="RESET",
            ts_recv_ns=ts_recv_ns,
            flags=flags,
            sequence=sequence,
        )
    side = _SIDE_MAP.get(side_code)
    if action == "DELETE":
        if order_id <= 0:
            return None
        return MBOEvent(
            ts_ns=ts_ns,
            action="DELETE",
            order_id=order_id,
            ts_recv_ns=ts_recv_ns,
            flags=flags,
            sequence=sequence,
        )
    price_ticks: int | None = None
    if price_raw != _NULL_PRICE:
        if tick_size <= 0 or price_raw % tick_size != 0:
            raise ValueError(f"invalid tick conversion price={price_raw} tick={tick_size}")
        price_ticks = price_raw // tick_size
    if action in ("ADD", "MODIFY"):
        if order_id <= 0 or side is None:
            return None
        if price_ticks is None or size <= 0:
            return None
        return MBOEvent(
            ts_ns=ts_ns,
            action=action,
            order_id=order_id,
            side=side,
            price_ticks=price_ticks,
            size=size,
            ts_recv_ns=ts_recv_ns,
            flags=flags,
            sequence=sequence,
        )
    if action == "TRADE":
        if order_id < 0 or size <= 0:
            return None
        return MBOEvent(
            ts_ns=ts_ns,
            action=action,
            order_id=order_id,
            side=side,
            price_ticks=price_ticks,
            size=size,
            ts_recv_ns=ts_recv_ns,
            flags=flags,
            sequence=sequence,
        )
    if action == "FILL":
        if order_id <= 0 or size <= 0:
            return None
        return MBOEvent(
            ts_ns=ts_ns,
            action=action,
            order_id=order_id,
            side=side,
            price_ticks=price_ticks,
            size=size,
            ts_recv_ns=ts_recv_ns,
            flags=flags,
            sequence=sequence,
        )
    if action == "CANCEL":
        if order_id <= 0 or size <= 0:
            return None
        return MBOEvent(
            ts_ns=ts_ns,
            action=action,
            order_id=order_id,
            side=side,
            price_ticks=price_ticks,
            size=size,
            ts_recv_ns=ts_recv_ns,
            flags=flags,
            sequence=sequence,
        )
    return None


def load_instrument_defs(definition_path: str | Path) -> dict[int, InstrumentDef]:
    db = _require_databento()
    defs: dict[int, InstrumentDef] = {}
    for rec in _iter_dbn_records(Path(definition_path), db):
        if not hasattr(rec, "min_price_increment"):
            continue
        tick_size = int(rec.min_price_increment)
        if tick_size <= 0:
            continue
        instrument_id = int(rec.instrument_id)
        defs[instrument_id] = InstrumentDef(
            instrument_id=instrument_id,
            symbol=str(rec.raw_symbol).strip(),
            tick_size=tick_size,
            lot_size=max(1, int(rec.min_trade_vol)),
            ts_ns=int(rec.ts_event),
        )
    return defs


def infer_primary_instrument_id(mbo_path: str | Path, max_records: int = 0) -> int:
    db = _require_databento()
    counts: Counter[int] = Counter()
    for index, rec in enumerate(_iter_dbn_records(Path(mbo_path), db), start=1):
        if not hasattr(rec, "action"):
            continue
        if str(rec.action) != "R":
            counts[int(rec.instrument_id)] += 1
        if max_records > 0 and index >= max_records:
            break
    if not counts:
        raise ValueError("no instrument found in mbo file")
    return counts.most_common(1)[0][0]


def iter_normalized_mbo_events(
    mbo_path: str | Path,
    *,
    instrument_id: int,
    tick_size: int,
    max_events: int = 0,
) -> Iterator[MBOEvent]:
    db = _require_databento()
    emitted = 0
    for rec in _iter_dbn_records(Path(mbo_path), db):
        if not hasattr(rec, "action"):
            continue
        if int(rec.instrument_id) != instrument_id:
            continue
        event = normalize_mbo_values(
            ts_ns=int(rec.ts_event),
            ts_recv_ns=int(getattr(rec, "ts_recv", rec.ts_event)),
            action_code=str(rec.action),
            side_code=str(rec.side),
            order_id=int(rec.order_id),
            price_raw=int(rec.price),
            size=int(rec.size),
            tick_size=tick_size,
            flags=int(getattr(rec, "flags", 0)),
            sequence=int(getattr(rec, "sequence", 0)),
        )
        if event is None:
            continue
        yield event
        emitted += 1
        if max_events > 0 and emitted >= max_events and event.is_event_end:
            break


def _iter_dbn_records(path: Path, db) -> Iterator[object]:
    store = db.DBNStore.from_file(path)
    yield from store


def _require_databento():
    _sanitize_import_path()
    try:
        import databento as db  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "databento is required for DBN loading. "
            "Install with: uv run --with databento ... "
            "If running from conda, set PYTHONNOUSERSITE=1."
        ) from exc
    return db


def _sanitize_import_path() -> None:
    return

