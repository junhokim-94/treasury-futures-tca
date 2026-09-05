from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from treasury_futures_execution_analytics_tca_engine.io.kdb_runtime import diagnose_kdb_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose local kdb+ runtime for subprocess execution")
    parser.add_argument("--q-exe", default=r"C:\q\w64\q.exe")
    parser.add_argument("--license-file", default=r"C:\q\kc.lic")
    parser.add_argument("--cwd", default=str(ROOT))
    args = parser.parse_args()

    diag = diagnose_kdb_runtime(
        q_exe=Path(args.q_exe),
        license_file=Path(args.license_file),
        cwd=Path(args.cwd),
    )
    payload = {
        "q_executable_found": diag.q_executable_found,
        "license_file_found": diag.license_file_found,
        "q_startup_ok": diag.q_startup_ok,
        "test_expression_ok": diag.test_expression_ok,
        "startup_returncode": None if diag.startup is None else diag.startup.returncode,
        "startup_stdout": None if diag.startup is None else diag.startup.stdout,
        "startup_stderr": None if diag.startup is None else diag.startup.stderr,
        "expression_returncode": None if diag.expression is None else diag.expression.returncode,
        "expression_stdout": None if diag.expression is None else diag.expression.stdout,
        "expression_stderr": None if diag.expression is None else diag.expression.stderr,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if not (diag.q_executable_found and diag.license_file_found and diag.q_startup_ok and diag.test_expression_ok):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

