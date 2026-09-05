# Parquet to kdb+ ingestion

Import normalized `mbo_event` and `instrument_def` Parquet files into a
partitioned HDB. Install the `data` extra and obtain a working q runtime and
license separately. Run these PowerShell commands from the repository root;
replace the example q installation paths as needed.

## Diagnose the runtime

```powershell
python scripts/diagnose_kdb_runtime.py --q-exe C:/q/w64/q.exe --license-file C:/q/kc.lic
```

Both `q_startup_ok` and `test_expression_ok` must be true.

## Load and validate one session

```powershell
python scripts/load_parquet_to_kdb.py --parquet-input-dir outputs/normalized_parquet/20260224 --hdb-root kdb/hdb_demo --q-exe C:/q/w64/q.exe --q-home C:/q --duplicate-strategy skip --stage-dir kdb/stage
python scripts/validate_kdb_load.py --parquet-input-dir outputs/normalized_parquet/20260224 --hdb-root kdb/hdb_demo --q-exe C:/q/w64/q.exe --q-home C:/q
```

Expect `status=loaded` for both tables and `"status": "ok"` from validation.
Repeat the load command to check idempotency: previously imported files should
report `status=skipped`. Keep the ingestion manifest alongside the HDB.

## Load multiple sessions

```powershell
Get-ChildItem outputs/normalized_parquet -Directory | ForEach-Object {
    python scripts/load_parquet_to_kdb.py --parquet-input-dir $_.FullName --hdb-root kdb/hdb_research --q-exe C:/q/w64/q.exe --q-home C:/q --duplicate-strategy skip --stage-dir kdb/stage
}
python scripts/validate_kdb_load.py --parquet-input-dir outputs/normalized_parquet --hdb-root kdb/hdb_research --q-exe C:/q/w64/q.exe --q-home C:/q
```

HDB partitions, staging CSVs, and ingestion manifests stay local and are excluded
from the GitHub package. The q scripts in `q/` are required source files.

## Troubleshooting

- `couldn't connect to license daemon`: check the q license, daemon, and firewall.
- Only `skipped` results: the manifest may already record these files. Use a new
  HDB root for an independent reload; do not delete a production manifest.
- `multi_date_csv_not_supported`: split the input by date before loading.
- Validation failure: check row counts and confirm the input and HDB refer to
  the same batch. A failed check is not evidence of a successful import.

