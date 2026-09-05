from __future__ import annotations

import json
from array import array
from collections.abc import Iterable, Mapping
from pathlib import Path

_NONE_I64 = -(1 << 63)


def write_snapshots_columnar(
    snapshots: Iterable[Mapping[str, object]],
    output_dir: str | Path,
) -> dict[str, int]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ts_ns = array("q")
    instrument_id = array("q")
    best_bid_px = array("q")
    best_bid_sz = array("q")
    best_ask_px = array("q")
    best_ask_sz = array("q")
    num_orders = array("q")
    total_bid_depth = array("q")
    total_ask_depth = array("q")

    bid_levels_px = array("q")
    bid_levels_sz = array("q")
    bid_offsets = array("q", [0])
    ask_levels_px = array("q")
    ask_levels_sz = array("q")
    ask_offsets = array("q", [0])

    rows = 0
    for snapshot in snapshots:
        rows += 1
        ts_ns.append(int(snapshot["ts_ns"]))
        instrument_id.append(_to_i64(snapshot["instrument_id"]))
        best_bid_px.append(_to_i64(snapshot["best_bid_px"]))
        best_bid_sz.append(int(snapshot["best_bid_sz"]))
        best_ask_px.append(_to_i64(snapshot["best_ask_px"]))
        best_ask_sz.append(int(snapshot["best_ask_sz"]))
        num_orders.append(int(snapshot["num_orders"]))
        total_bid_depth.append(int(snapshot["total_bid_depth"]))
        total_ask_depth.append(int(snapshot["total_ask_depth"]))

        for px, sz in snapshot["bid_levels"]:  # type: ignore[index]
            bid_levels_px.append(int(px))
            bid_levels_sz.append(int(sz))
        bid_offsets.append(len(bid_levels_px))

        for px, sz in snapshot["ask_levels"]:  # type: ignore[index]
            ask_levels_px.append(int(px))
            ask_levels_sz.append(int(sz))
        ask_offsets.append(len(ask_levels_px))

    _write_i64(out / "ts_ns.i64", ts_ns)
    _write_i64(out / "instrument_id.i64", instrument_id)
    _write_i64(out / "best_bid_px.i64", best_bid_px)
    _write_i64(out / "best_bid_sz.i64", best_bid_sz)
    _write_i64(out / "best_ask_px.i64", best_ask_px)
    _write_i64(out / "best_ask_sz.i64", best_ask_sz)
    _write_i64(out / "num_orders.i64", num_orders)
    _write_i64(out / "total_bid_depth.i64", total_bid_depth)
    _write_i64(out / "total_ask_depth.i64", total_ask_depth)
    _write_i64(out / "bid_levels_px.i64", bid_levels_px)
    _write_i64(out / "bid_levels_sz.i64", bid_levels_sz)
    _write_i64(out / "bid_offsets.i64", bid_offsets)
    _write_i64(out / "ask_levels_px.i64", ask_levels_px)
    _write_i64(out / "ask_levels_sz.i64", ask_levels_sz)
    _write_i64(out / "ask_offsets.i64", ask_offsets)

    stats = {
        "rows": rows,
        "bid_level_rows": len(bid_levels_px),
        "ask_level_rows": len(ask_levels_px),
        "none_sentinel_i64": _NONE_I64,
    }
    (out / "metadata.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def _to_i64(value: object) -> int:
    if value is None:
        return _NONE_I64
    return int(value)


def _write_i64(path: Path, values: array) -> None:
    with path.open("wb") as file:
        values.tofile(file)

