# Release validation

Validated on Windows with Python 3.14.2 during repository preparation.

- `python -m pytest -q -p no:cacheprovider`: 24 tests passed.
- All 12 data, replay, dashboard, and research CLI entry points: `--help` passed.
- Dashboard health handler returned `{"status": "ok"}`; its HTML path resolved.
- Local Markdown links resolved and preserved result JSON files matched their
  original saved artifacts byte for byte.
- `python scripts/render_project_results.py`: PNG generated and visually checked.
- Setuptools wheel build completed successfully.
- The generated GitHub ZIP was extracted into an isolated directory and all
  24 tests passed there, confirming the release does not depend on omitted files.

The existing passing-schema test fixture was updated to include `event_date`,
which is already required by the Python schema, exporter, and q schema. Core
execution and book logic were not changed by this repository cleanup.

Full DBN replay, live browser/WebSocket interaction, q ingestion, and execution
inside HFTBacktest were not run for this cleanup. Python 3.12 is declared as the
minimum version but was not the runtime used for this test run.

