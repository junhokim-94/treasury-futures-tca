from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.io.kdb_loader import discover_parquet_files
from treasury_futures_execution_analytics_tca_engine.io.kdb_runtime import build_q_subprocess_env, diagnose_kdb_runtime, run_q_script

_MBO_ACTIONS = {"ADD", "CANCEL", "MODIFY", "TRADE", "FILL", "DELETE", "RESET"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate parquet->kdb+ load results")
    parser.add_argument("--parquet-input-dir", required=True)
    parser.add_argument("--hdb-root", default="kdb/hdb")
    parser.add_argument("--q-exe", default=r"C:\q\w64\q.exe")
    parser.add_argument("--q-home", default=r"C:\q")
    args = parser.parse_args()

    parquet_dir = Path(args.parquet_input_dir).resolve()
    hdb_root = Path(args.hdb_root).resolve()
    q_exe = Path(args.q_exe).resolve()
    q_home = Path(args.q_home).resolve()

    diag = diagnose_kdb_runtime(q_exe=q_exe, license_file=q_home / "kc.lic", cwd=ROOT)
    if not (diag.q_startup_ok and diag.test_expression_ok):
        raise RuntimeError("kdb runtime diagnostics failed before validation")

    expected = _expected_from_parquet(parquet_dir)
    q_payload = _fetch_kdb_validation_payload(
        hdb_root=hdb_root,
        q_exe=q_exe,
        q_home=q_home,
    )

    _validate_payload(expected=expected, actual=q_payload, hdb_root=hdb_root)
    output = {"expected": expected, "actual": q_payload, "status": "ok"}
    print(json.dumps(output, indent=2, ensure_ascii=False))


def _expected_from_parquet(parquet_dir: Path) -> dict[str, object]:
    expected: dict[str, dict[str, object]] = {
        "mbo_event": {"rows": 0, "partitions": set()},
        "instrument_def": {"rows": 0, "partitions": set()},
    }
    for table_name, path in discover_parquet_files(parquet_dir):
        df = pd.read_parquet(path, columns=["date"])
        expected[table_name]["rows"] = int(expected[table_name]["rows"]) + int(len(df))
        dates = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d").dropna().tolist()
        part_set = expected[table_name]["partitions"]
        assert isinstance(part_set, set)
        part_set.update(d for d in dates if d != "")
    return {
        table: {
            "rows": int(values["rows"]),
            "partitions": sorted(values["partitions"]),  # type: ignore[arg-type]
        }
        for table, values in expected.items()
    }


def _fetch_kdb_validation_payload(*, hdb_root: Path, q_exe: Path, q_home: Path) -> dict[str, object]:
    env = build_q_subprocess_env(q_home=q_home)
    script = ROOT / "q" / "validate_hdb.q"
    try:
        hdb_arg = hdb_root.relative_to(ROOT).as_posix()
    except ValueError:
        hdb_arg = hdb_root.as_posix()
    with NamedTemporaryFile(mode="w", suffix=".json", prefix="kdb_validate_", dir=str(ROOT), delete=False) as file:
        json_path = Path(file.name)
    try:
        result = run_q_script(
            q_exe=q_exe,
            q_script=script,
            args=[hdb_arg, json_path.as_posix()],
            cwd=ROOT,
            env=env,
            timeout_sec=180,
        )
        if result.returncode != 0:
            raise RuntimeError(f"validate_hdb.q failed\nstdout={result.stdout}\nstderr={result.stderr}")
        text = json_path.read_text(encoding="utf-8").strip()
        if not text:
            raise RuntimeError("validate_hdb.q returned empty output")
        return json.loads(text)
    finally:
        json_path.unlink(missing_ok=True)


def _validate_payload(*, expected: dict[str, object], actual: dict[str, object], hdb_root: Path) -> None:
    for table in ("mbo_event", "instrument_def"):
        actual_table = actual[table]
        if not actual_table["exists"]:
            raise AssertionError(f"{table}: not found in HDB")
        if actual_table["missing_cols"]:
            raise AssertionError(f"{table}: missing columns: {actual_table['missing_cols']}")

        expected_rows = int(expected[table]["rows"])
        actual_rows = int(actual_table["rows"])
        if actual_rows != expected_rows:
            raise AssertionError(f"{table}: row count mismatch expected={expected_rows} actual={actual_rows}")

        expected_parts = set(expected[table]["partitions"])
        actual_parts = set(_table_partitions_from_hdb(hdb_root=hdb_root, table_name=table))
        if actual_parts != expected_parts:
            raise AssertionError(f"{table}: partition mismatch expected={sorted(expected_parts)} actual={sorted(actual_parts)}")

    mbo = actual["mbo_event"]
    if "invalid_action_count" in mbo:
        if int(mbo["invalid_action_count"]) != 0:
            raise AssertionError("mbo_event: invalid actions present")
    else:
        invalid_actions = set(mbo["invalid_actions"])
        if invalid_actions:
            bad = sorted(invalid_actions - _MBO_ACTIONS)
            if bad:
                raise AssertionError(f"mbo_event: invalid actions present: {bad}")
    if int(mbo["invalid_side_count"]) != 0:
        raise AssertionError("mbo_event: invalid side values present")

    inst = actual["instrument_def"]
    if int(inst["null_instrument_id_count"]) != 0:
        raise AssertionError("instrument_def: null instrument_id values present")
    if int(inst["empty_raw_symbol_count"]) != 0:
        raise AssertionError("instrument_def: empty raw_symbol values present")


def _table_partitions_from_hdb(*, hdb_root: Path, table_name: str) -> list[str]:
    out: list[str] = []
    if not hdb_root.exists():
        return out
    for path in sorted(hdb_root.iterdir()):
        if not path.is_dir():
            continue
        try:
            day = dt.datetime.strptime(path.name, "%Y.%m.%d").date()
        except ValueError:
            continue
        if (path / table_name).is_dir():
            out.append(day.isoformat())
    return out


if __name__ == "__main__":
    main()

