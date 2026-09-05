from __future__ import annotations

from dataclasses import dataclass

from .execution_metrics import MetricsConfig, compute_execution_metrics
from .execution_simulator import ExecutionResult, simulate_execution
from .execution_types import ExecutionDecision
from .hftbacktest_adapter import correct_and_validate_hftbacktest_feed, map_mbo_events_to_hftbacktest_feed
from .types import MBOEvent


@dataclass(slots=True, frozen=True)
class ParallelComparison:
    status: str
    baseline_metrics: dict[str, object]
    hftbacktest_metrics: dict[str, object] | None
    delta_filled_qty: int | None
    delta_avg_fill_px_ticks: float | None
    delta_participation_rate: float | None
    message: str | None = None


def run_parallel_comparison(
    *,
    events: list[MBOEvent],
    decisions: list[ExecutionDecision],
    instrument_id: int | None = None,
    queue_model: str = "level_depletion",
    validate_every: int = 0,
    metrics_config: MetricsConfig | None = None,
) -> ParallelComparison:
    cfg = MetricsConfig() if metrics_config is None else metrics_config
    baseline = simulate_execution(
        events,
        instrument_id=instrument_id,
        decisions=decisions,
        queue_model=queue_model,  # type: ignore[arg-type]
        validate_every=validate_every,
    )
    baseline_metrics = compute_execution_metrics(baseline, cfg)

    hft_result, status, message = _try_run_hftbacktest(
        events=events,
        decisions=decisions,
        instrument_id=instrument_id,
    )
    if hft_result is None:
        return ParallelComparison(
            status=status,
            baseline_metrics=baseline_metrics,
            hftbacktest_metrics=None,
            delta_filled_qty=None,
            delta_avg_fill_px_ticks=None,
            delta_participation_rate=None,
            message=message,
        )

    hft_metrics = compute_execution_metrics(hft_result, cfg)
    return ParallelComparison(
        status=status,
        baseline_metrics=baseline_metrics,
        hftbacktest_metrics=hft_metrics,
        delta_filled_qty=_to_int(hft_metrics.get("filled_qty")) - _to_int(baseline_metrics.get("filled_qty")),
        delta_avg_fill_px_ticks=_to_float(hft_metrics.get("avg_fill_px_ticks"))
        - _to_float(baseline_metrics.get("avg_fill_px_ticks")),
        delta_participation_rate=_to_float(hft_metrics.get("participation_rate"))
        - _to_float(baseline_metrics.get("participation_rate")),
        message=message,
    )


def _try_run_hftbacktest(
    *,
    events: list[MBOEvent],
    decisions: list[ExecutionDecision],
    instrument_id: int | None,
) -> tuple[ExecutionResult | None, str, str | None]:
    try:
        import hftbacktest
    except Exception as exc:  # noqa: BLE001
        return None, "hftbacktest_unavailable", f"{exc.__class__.__name__}: {exc}"
    _ = (decisions, instrument_id)
    try:
        mapped = map_mbo_events_to_hftbacktest_feed(events, hft_module=hftbacktest)
        corrected = correct_and_validate_hftbacktest_feed(mapped.data, hft_module=hftbacktest)
    except Exception as exc:  # noqa: BLE001
        return None, "hftbacktest_mapping_failed", f"{exc.__class__.__name__}: {exc}"
    message = (
        f"mapped_rows={corrected.shape[0]} "
        f"dropped_events={mapped.dropped_events} "
        f"l3_flags={int(mapped.used_l3_event_flags)}"
    )
    return None, "hftbacktest_feed_mapped", message


def _to_int(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def _to_float(value: object) -> float:
    if value is None:
        return 0.0
    return float(value)

