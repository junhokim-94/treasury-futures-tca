# Result provenance

`order_book_summary.json` is an unchanged copy of the saved
`outputs/corrected_mbo_v2/20260224/order_book_snapshots.summary.json`.
It describes ZNH6, instrument 42004475, from the 2026-02-24 session.
The raw price increment uses Databento's fixed-point representation; displayed
book prices in the figure are integer ticks, not dollar prices.

`execution_metrics.json` is an unchanged copy of the separate saved
`outputs/execution_research_20260224/metrics.json`. It reports five submitted
lots and zero fills. The original command and full run configuration were not
preserved here, so these metrics must not be treated as a controlled comparison
with the corrected book replay. No missing metric is replaced by zero.

The figure is generated directly from these JSON files. It shows a final book
snapshot and execution counts, not a fabricated PnL curve. Raw DBN, Parquet,
and order-level records are excluded from the upload package.

