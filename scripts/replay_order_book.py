from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.pipeline import build_order_book_from_dbn


def main() -> None:
    parser = argparse.ArgumentParser(description="Build order-book snapshots from Databento DBN MBO")
    parser.add_argument("--mbo-path", required=True)
    parser.add_argument("--definition-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--instrument-id", type=int, default=None)
    parser.add_argument("--snapshot-every", type=int, default=10000)
    parser.add_argument("--validate-every", type=int, default=100000)
    parser.add_argument("--max-events", type=int, default=0)
    args = parser.parse_args()

    summary = build_order_book_from_dbn(
        mbo_path=args.mbo_path,
        definition_path=args.definition_path,
        output_dir=args.output_dir,
        instrument_id=args.instrument_id,
        snapshot_every=args.snapshot_every,
        validate_every=args.validate_every,
        max_events=args.max_events,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

