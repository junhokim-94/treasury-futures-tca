from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.databento_loader import (
    infer_primary_instrument_id,
    iter_normalized_mbo_events,
    load_instrument_defs,
)
from treasury_futures_execution_analytics_tca_engine.types import MBOEvent


@dataclass(slots=True)
class _PartMeta:
    part: int
    rows: int
    csv_path: str
    kdb_path: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Databento DBN MBO into KDB+ part tables")
    parser.add_argument("--mbo-path", required=True)
    parser.add_argument("--definition-path", required=True)
    parser.add_argument("--kdb-root", required=True, help="KDB+ output root (e.g. C:\\q\\db)")
    parser.add_argument("--q-exe", default=r"C:\q\w64\q.exe")
    parser.add_argument("--instrument-id", type=int, default=None)
    parser.add_argument("--batch-rows", type=int, default=2_000_000)
    parser.add_argument("--max-events", type=int, default=0)
    parser.add_argument("--stage-dir", default="outputs/kdb_stage")
    parser.add_argument("--table-name", default="mbo")
    parser.add_argument("--keep-csv", action="store_true")
    parser.add_argument("--skip-q", action="store_true", help="write staged CSV parts only")
    args = parser.parse_args()

    mbo_path = Path(args.mbo_path)
    definition_path = Path(args.definition_path)
    q_exe = Path(args.q_exe)
    if not q_exe.exists():
        raise FileNotFoundError(f"q executable not found: {q_exe}")

    instrument_id = args.instrument_id
    if instrument_id is None:
        instrument_id = infer_primary_instrument_id(mbo_path, max_records=300_000)

    defs = load_instrument_defs(definition_path)
    inst_def = defs.get(instrument_id)
    if inst_def is None:
        raise ValueError(f"instrument_id {instrument_id} not found in definition file")

    trade_date = _infer_trade_date(mbo_path.name)
    base_dir = Path(args.kdb_root) / args.table_name / trade_date / f"i{instrument_id}"
    parts_dir = base_dir / "parts"
    stage_dir = Path(args.stage_dir) / trade_date / f"i{instrument_id}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    q_script = Path(__file__).resolve().with_name("kdb_import_mbo_part.q")
    events = iter_normalized_mbo_events(
        mbo_path,
        instrument_id=instrument_id,
        tick_size=inst_def.tick_size,
        max_events=args.max_events,
    )

    total_rows = 0
    part_no = 0
    part_rows = 0
    writer: csv.writer | None = None
    csv_file = None
    csv_path: Path | None = None
    parts: list[_PartMeta] = []

    try:
        for event in events:
            if writer is None:
                part_no += 1
                part_rows = 0
                csv_path = stage_dir / f"part_{part_no:06d}.csv"
                csv_file = csv_path.open("w", newline="", encoding="utf-8")
                writer = csv.writer(csv_file)
                writer.writerow(["ts_ns", "instrument_id", "action", "order_id", "side", "price_ticks", "size"])

            writer.writerow(_row_from_event(event, instrument_id))
            part_rows += 1
            total_rows += 1

            if part_rows >= args.batch_rows:
                assert csv_file is not None and csv_path is not None
                csv_file.close()
                writer = None
                if not args.skip_q:
                    _import_part_with_q(
                        q_exe=q_exe,
                        q_script=q_script,
                        csv_path=csv_path,
                        out_dir=parts_dir / f"part_{part_no:06d}",
                    )
                parts.append(
                    _PartMeta(
                        part=part_no,
                        rows=part_rows,
                        csv_path=str(csv_path.resolve()),
                        kdb_path=str((parts_dir / f"part_{part_no:06d}").resolve()),
                    )
                )
                if not args.keep_csv:
                    csv_path.unlink(missing_ok=True)

        if writer is not None and csv_file is not None and csv_path is not None:
            csv_file.close()
            if not args.skip_q:
                _import_part_with_q(
                    q_exe=q_exe,
                    q_script=q_script,
                    csv_path=csv_path,
                    out_dir=parts_dir / f"part_{part_no:06d}",
                )
            parts.append(
                _PartMeta(
                    part=part_no,
                    rows=part_rows,
                    csv_path=str(csv_path.resolve()),
                    kdb_path=str((parts_dir / f"part_{part_no:06d}").resolve()),
                )
            )
            if not args.keep_csv:
                csv_path.unlink(missing_ok=True)
    finally:
        if csv_file is not None and not csv_file.closed:
            csv_file.close()

    summary = {
        "mbo_path": str(mbo_path.resolve()),
        "definition_path": str(definition_path.resolve()),
        "kdb_root": str(Path(args.kdb_root).resolve()),
        "table_name": args.table_name,
        "trade_date": trade_date,
        "instrument_id": instrument_id,
        "symbol": inst_def.symbol,
        "tick_size": inst_def.tick_size,
        "lot_size": inst_def.lot_size,
        "batch_rows": args.batch_rows,
        "max_events": args.max_events,
        "skip_q": args.skip_q,
        "parts": [_part_to_dict(part) for part in parts],
        "total_parts": len(parts),
        "total_rows": total_rows,
    }
    summary_path = base_dir / "manifest.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _row_from_event(event: MBOEvent, instrument_id: int) -> list[str]:
    return [
        str(event.ts_ns),
        str(instrument_id),
        event.action,
        str(event.order_id),
        "" if event.side is None else event.side,
        "" if event.price_ticks is None else str(event.price_ticks),
        "" if event.size is None else str(event.size),
    ]


def _import_part_with_q(*, q_exe: Path, q_script: Path, csv_path: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(q_exe),
        "-q",
        str(q_script),
        _q_path(csv_path),
        _q_path(out_dir) + "/",
    ]
    env = os.environ.copy()
    q_home = str(q_exe.parent.parent)
    env.setdefault("QHOME", q_home)
    env.setdefault("QLIC", q_home)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            f"kdb import failed ({proc.returncode})\n"
            f"cmd={cmd}\n"
            f"stdout={proc.stdout}\n"
            f"stderr={proc.stderr}"
        )


def _q_path(path: Path) -> str:
    return path.resolve().as_posix()


def _infer_trade_date(name: str) -> str:
    matched = re.search(r"(20\d{6})", name)
    if matched is None:
        return "unknown_date"
    return matched.group(1)


def _part_to_dict(part: _PartMeta) -> dict[str, object]:
    return {
        "part": part.part,
        "rows": part.rows,
        "csv_path": part.csv_path,
        "kdb_path": part.kdb_path,
    }


if __name__ == "__main__":
    main()

