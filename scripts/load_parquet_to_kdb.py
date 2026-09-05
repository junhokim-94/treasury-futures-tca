from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.io.kdb_loader import LoadConfig, load_parquet_directory, summarize_results


def main() -> None:
    parser = argparse.ArgumentParser(description="Load normalized parquet datasets into date-partitioned kdb+ HDB")
    parser.add_argument("--parquet-input-dir", required=True)
    parser.add_argument("--hdb-root", default="kdb/hdb")
    parser.add_argument("--q-exe", default=r"C:\q\w64\q.exe")
    parser.add_argument("--q-home", default=r"C:\q")
    parser.add_argument("--duplicate-strategy", choices=["skip", "fail"], default="skip")
    parser.add_argument("--stage-dir", default="kdb/stage")
    parser.add_argument("--keep-stage-csv", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=300)
    args = parser.parse_args()

    config = LoadConfig(
        parquet_input_dir=Path(args.parquet_input_dir).resolve(),
        hdb_root=Path(args.hdb_root).resolve(),
        q_exe=Path(args.q_exe).resolve(),
        q_home=Path(args.q_home).resolve(),
        repo_root=ROOT,
        duplicate_strategy=args.duplicate_strategy,
        stage_dir=Path(args.stage_dir).resolve(),
        keep_stage_csv=args.keep_stage_csv,
        timeout_sec=args.timeout_sec,
    )
    results = load_parquet_directory(config)
    summary = summarize_results(results)
    payload = {
        "summary": summary,
        "results": [
            {
                "table_name": row.table_name,
                "source_file": row.source_file,
                "row_count": row.row_count,
                "min_date": row.min_date,
                "max_date": row.max_date,
                "status": row.status,
                "q_stdout": row.q_stdout,
            }
            for row in results
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

