"""Drift detection — compare current telemetry against a Baseline_Profile.

Drift detection compares the current telemetry snapshot against the active
Baseline_Profile for a cluster/namespace. Deviations beyond configured
thresholds are flagged as drift in the health assessment.

Drift correlation identifies when config changes in a ProfileComparison
are correlated with telemetry regressions, and includes the correlation
in the assessment explanation.

This module is deterministic — no LLM involvement. It follows the same
"Rules Decide, AI Explains" principle as the Health State Machine.

Requirements: 15.1, 15.2, 15.3
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from behaviour_profiles.comparison import _flatten_telemetry, _pct_change

if TYPE_CHECKING:
    from behaviour_profiles.models import BehaviourProfile, ProfileComparison, TelemetrySummary
    from copilot_core.models import MetricAggregate


class DriftThresholds(BaseModel):
    """Configurable thresholds for drift detection."""

    latency_pct: float = Field(
        default=20.0,
        description="Percentage change in latency metrics to flag as drift",
    )
    error_pct: float = Field(
        default=50.0,
        description="Percentage change in error metrics to flag as drift",
    )
    throughput_pct: float = Field(
        default=30.0,
        description="Percentage change in throughput metrics to flag as drift",
    )


class DriftResult(BaseModel):
    """A single metric that has drifted from the baseline."""

    metric: str
    baseline_value: float
    current_value: float
    change_pct: float
    direction: Literal["improved", "regressed", "unchanged"]
    severity: Literal["info", "warning", "critical"]


class DriftAssessment(BaseModel):
    """Complete drift assessment comparing current telemetry to baseline."""

    baseline_profile_id: str
    baseline_profile_name: str
    drifted_metrics: list[DriftResult]
    is_drifted: bool = Field(description="True if any metric exceeds drift thresholds")
    summary: str = Field(description="Human-readable drift summary")


def _flatten_current_telemetry(telemetry: TelemetrySummary) -> dict[str, MetricAggregate]:
    """Flatten a TelemetrySummary into a flat dict of metric name → aggregate.

    Uses the same metric names as _flatten_telemetry from comparison.py
    so drift detection and profile comparison use consistent naming.
    """
    flat: dict[str, MetricAggregate] = {}

    flat["workflows_started_per_sec"] = telemetry.throughput.workflows_started_per_sec
    flat["workflows_completed_per_sec"] = telemetry.throughput.workflows_completed_per_sec
    flat["state_transitions_per_sec"] = telemetry.throughput.state_transitions_per_sec

    flat["workflow_schedule_to_start_p95"] = telemetry.latency.workflow_schedule_to_start_p95
    flat["workflow_schedule_to_start_p99"] = telemetry.latency.workflow_schedule_to_start_p99
    flat["activity_schedule_to_start_p95"] = telemetry.latency.activity_schedule_to_start_p95
    flat["activity_schedule_to_start_p99"] = telemetry.latency.activity_schedule_to_start_p99
    flat["persistence_latency_p95"] = telemetry.latency.persistence_latency_p95
    flat["persistence_latency_p99"] = telemetry.latency.persistence_latency_p99

    flat["sync_match_rate"] = telemetry.matching.sync_match_rate
    flat["async_match_rate"] = telemetry.matching.async_match_rate
    flat["task_dispatch_latency"] = telemetry.matching.task_dispatch_latency
    flat["backlog_count"] = telemetry.matching.backlog_count
    flat["backlog_age"] = telemetry.matching.backlog_age

    flat["pool_open_count"] = telemetry.dsql_pool.pool_open_count
    flat["pool_in_use_count"] = telemetry.dsql_pool.pool_in_use_count
    flat["pool_idle_count"] = telemetry.dsql_pool.pool_idle_count
    flat["reservoir_size"] = telemetry.dsql_pool.reservoir_size
    flat["reservoir_empty_events"] = telemetry.dsql_pool.reservoir_empty_events
    flat["open_failures"] = telemetry.dsql_pool.open_failures
    flat["reconnect_count"] = telemetry.dsql_pool.reconnect_count

    flat["occ_conflicts_per_sec"] = telemetry.errors.occ_conflicts_per_sec
    flat["exhausted_retries_per_sec"] = telemetry.errors.exhausted_retries_per_sec
    flat["dsql_auth_failures"] = telemetry.errors.dsql_auth_failures

    flat["worker_task_slot_utilization"] = telemetry.resources.worker_task_slot_utilization

    return flat


def detect_drift(
    current_telemetry: TelemetrySummary,
    baseline: BehaviourProfile,
    *,
    thresholds: DriftThresholds | None = None,
) -> DriftAssessment:
    """Compare current telemetry against a Baseline_Profile and flag drift.

    Args:
        current_telemetry: Current telemetry snapshot from AMP.
        baseline: The active Baseline_Profile for the cluster/namespace.
        thresholds: Configurable drift thresholds. Uses defaults if None.

    Returns:
        DriftAssessment with all drifted metrics and a summary.
    """
    if thresholds is None:
        thresholds = DriftThresholds()

    baseline_metrics = _flatten_telemetry(baseline)
    current_metrics = _flatten_current_telemetry(current_telemetry)

    drifted: list[DriftResult] = []

    for name in sorted(baseline_metrics.keys() & current_metrics.keys()):
        baseline_agg = baseline_metrics[name]
        current_agg = current_metrics[name]

        change_pct = _pct_change(baseline_agg.mean, current_agg.mean)

        is_error = "error" in name or "conflict" in name or "failure" in name or "empty" in name
        is_throughput = "per_sec" in name and not is_error

        # Determine direction
        if abs(change_pct) < 5.0:
            direction: Literal["improved", "regressed", "unchanged"] = "unchanged"
        elif is_throughput:
            direction = "improved" if change_pct > 0 else "regressed"
        else:
            direction = "improved" if change_pct < 0 else "regressed"

        # Determine threshold for this metric type
        if is_error:
            threshold = thresholds.error_pct
        elif is_throughput:
            threshold = thresholds.throughput_pct
        else:
            threshold = thresholds.latency_pct

        # Determine severity
        if direction == "regressed" and abs(change_pct) > threshold * 2:
            severity: Literal["info", "warning", "critical"] = "critical"
        elif direction == "regressed" and abs(change_pct) > threshold:
            severity = "warning"
        else:
            severity = "info"

        # Only include metrics that exceed the drift threshold
        if abs(change_pct) > threshold:
            drifted.append(
                DriftResult(
                    metric=name,
                    baseline_value=baseline_agg.mean,
                    current_value=current_agg.mean,
                    change_pct=round(change_pct, 2),
                    direction=direction,
                    severity=severity,
                )
            )

    # Sort by severity (critical first), then by abs change_pct desc
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    drifted.sort(key=lambda d: (severity_order[d.severity], -abs(d.change_pct)))

    is_drifted = any(d.severity in ("warning", "critical") for d in drifted)

    summary = _build_drift_summary(drifted, baseline, is_drifted)

    return DriftAssessment(
        baseline_profile_id=baseline.id,
        baseline_profile_name=baseline.name,
        drifted_metrics=drifted,
        is_drifted=is_drifted,
        summary=summary,
    )


def _build_drift_summary(
    drifted: list[DriftResult],
    baseline: BehaviourProfile,
    is_drifted: bool,
) -> str:
    """Build a human-readable drift summary."""
    if not is_drifted:
        return f"No significant drift detected from baseline '{baseline.name}'."

    critical_count = sum(1 for d in drifted if d.severity == "critical")
    warning_count = sum(1 for d in drifted if d.severity == "warning")

    parts = [f"Drift detected from baseline '{baseline.name}':"]
    if critical_count:
        parts.append(f"{critical_count} critical regression(s)")
    if warning_count:
        parts.append(f"{warning_count} warning(s)")

    # List the top 3 most severe drifts
    for result in drifted[:3]:
        parts.append(f"  {result.metric}: {result.change_pct:+.1f}% ({result.direction})")

    return " ".join(parts[:2]) + ". " + "\n".join(parts[2:]) if len(parts) > 2 else parts[0]


# ---------------------------------------------------------------------------
# Drift Correlation (Requirement 15.3)
# ---------------------------------------------------------------------------

# Known correlations between config parameters and telemetry metrics.
# When a config change is observed alongside a telemetry regression in a
# correlated metric, the correlation is flagged in the assessment.
CONFIG_TELEMETRY_CORRELATIONS: dict[str, list[str]] = {
    # Connection pool config → pool and latency metrics
    "persistence.maxConns": [
        "pool_open_count",
        "pool_in_use_count",
        "pool_idle_count",
        "persistence_latency_p95",
        "persistence_latency_p99",
    ],
    "persistence.maxIdleConns": [
        "pool_idle_count",
        "pool_open_count",
        "persistence_latency_p95",
    ],
    "persistence.maxConnLifetime": [
        "pool_open_count",
        "reconnect_count",
    ],
    # Reservoir config → reservoir and pool metrics
    "env.DSQL_RESERVOIR_ENABLED": [
        "reservoir_size",
        "reservoir_empty_events",
        "open_failures",
    ],
    "env.DSQL_RESERVOIR_TARGET_READY": [
        "reservoir_size",
        "reservoir_empty_events",
    ],
    # Rate limiting → error and throughput metrics
    "env.DSQL_CONNECTION_RATE_LIMIT": [
        "open_failures",
        "persistence_latency_p95",
        "state_transitions_per_sec",
    ],
    "env.DSQL_DISTRIBUTED_RATE_LIMITER_ENABLED": [
        "open_failures",
        "reconnect_count",
    ],
    # Matching partitions → matching metrics
    "dynamic_config.matching.numTaskqueueReadPartitions": [
        "sync_match_rate",
        "async_match_rate",
        "task_dispatch_latency",
        "backlog_count",
        "backlog_age",
    ],
    "dynamic_config.matching.numTaskqueueWritePartitions": [
        "sync_match_rate",
        "async_match_rate",
        "task_dispatch_latency",
    ],
    # Persistence QPS → throughput and latency
    "dynamic_config.history.persistenceMaxQPS": [
        "state_transitions_per_sec",
        "persistence_latency_p95",
        "persistence_latency_p99",
    ],
    # Worker options → throughput metrics
    "dynamic_config.history.transferActiveTaskQueueTimeout": [
        "state_transitions_per_sec",
        "backlog_age",
    ],
}


class DriftCorrelation(BaseModel):
    """A correlation between a config change and a telemetry regression."""

    config_key: str = Field(description="The config parameter that changed")
    config_old_value: int | float | str | bool
    config_new_value: int | float | str | bool
    correlated_metrics: list[str] = Field(
        description="Telemetry metrics that regressed and are known to correlate with this config"
    )
    explanation: str = Field(description="Human-readable explanation of the correlation")


class CorrelationAssessment(BaseModel):
    """Assessment of correlations between config changes and telemetry regressions."""

    correlations: list[DriftCorrelation]
    has_correlations: bool
    summary: str


def correlate_drift(comparison: ProfileComparison) -> CorrelationAssessment:
    """Identify config changes correlated with telemetry regressions.

    When a ProfileComparison shows config changes alongside telemetry
    regressions in known-correlated metrics, this function flags the
    correlation for inclusion in the assessment explanation.

    Args:
        comparison: A ProfileComparison between two BehaviourProfiles.

    Returns:
        CorrelationAssessment with identified correlations.
    """
    # Build set of regressed metric names
    regressed_metrics = {
        d.metric
        for d in comparison.telemetry_diffs
        if d.direction == "regressed" and d.severity in ("warning", "critical")
    }

    if not regressed_metrics or not comparison.config_diffs:
        return CorrelationAssessment(
            correlations=[],
            has_correlations=False,
            summary="No correlations found between config changes and telemetry regressions.",
        )

    correlations: list[DriftCorrelation] = []

    for config_diff in comparison.config_diffs:
        known_correlated = CONFIG_TELEMETRY_CORRELATIONS.get(config_diff.key, [])
        matched = [m for m in known_correlated if m in regressed_metrics]

        if matched:
            explanation = (
                f"Config '{config_diff.key}' changed from {config_diff.old_value} "
                f"to {config_diff.new_value}. "
                f"Correlated metric(s) regressed: {', '.join(matched)}."
            )
            correlations.append(
                DriftCorrelation(
                    config_key=config_diff.key,
                    config_old_value=config_diff.old_value,
                    config_new_value=config_diff.new_value,
                    correlated_metrics=matched,
                    explanation=explanation,
                )
            )

    has_correlations = len(correlations) > 0
    summary = (
        _build_correlation_summary(correlations)
        if has_correlations
        else ("Config changes detected but no known correlations with observed regressions.")
    )

    return CorrelationAssessment(
        correlations=correlations,
        has_correlations=has_correlations,
        summary=summary,
    )


def _build_correlation_summary(correlations: list[DriftCorrelation]) -> str:
    """Build a human-readable correlation summary."""
    parts = [f"{len(correlations)} config change(s) correlated with telemetry regressions:"]
    for corr in correlations:
        parts.append(
            f"  '{corr.config_key}' ({corr.config_old_value} → {corr.config_new_value}) "
            f"→ {', '.join(corr.correlated_metrics)}"
        )
    return "\n".join(parts)
