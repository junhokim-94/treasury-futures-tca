# Repository organization

Public files contain English comments and documentation. Existing package
module names and imports are retained to preserve the public Python interface.

| Previous path | Current path |
| --- | --- |
| `scripts/run_dbn_order_book.py` | `scripts/replay_order_book.py` |
| `scripts/run_dbn_order_book_parquet.py` | `scripts/export_order_book_parquet.py` |
| `scripts/run_parallel_execution_compare.py` | `scripts/compare_execution_engines.py` |
| `treasury_futures_execution_analytics_tca_engine/read_dbn.py` | `scripts/inspect_dbn.py` |
| Root ingestion guide | `docs/kdb_ingestion.md` |
| Dashboard text instructions | `docs/dashboard.md` |

The DBN inspection utility now accepts a file argument and has no import-time
file access. Dashboard example paths are relative to the repository root.

Personal Word documents are preserved under `local_notes/` with descriptive
English filenames and a `.ko.docx` suffix identifying their original language.
These archival originals are excluded from the public package. Public run
instructions are maintained in Markdown. Data directories, the existing
environment, and caches remain local to preserve existing data workflows.

`.gitignore` allows only public root entries. `scripts/package_github.py` also
uses explicit file types and directories, so ZIP packaging does not depend on
Git being initialized. It does not create or modify a remote repository.

