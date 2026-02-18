"""Profile comparison logic — config diffs, telemetry diffs, version diffs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copilot_core.models import MetricAggregate

from behaviour_profiles.models import (
    BehaviourProfile,
    ConfigDiff,
    ProfileComparison,
    TelemetryDiff,
    VersionDiff,
)


def compare_profiles(
    a: BehaviourProfile,
    b: BehaviourProfile,
    *,
    latency_threshold_pct: float = 20.0,
    error_threshold_pct: float = 50.0,
) -> ProfileComparison:
    """Produce a structured diff between two profiles.

    Diffs are ordered by severity (largest regressions first).
    """
    config_diffs = _compare_config(a, b)
    telemetry_diffs = _compare_telemetry(a, b, latency_threshold_pct, error_threshold_pct)
    version_diffs = _compare_versions(a, b)

    # Sort telemetry diffs: critical first, then warning, then info;
    # within each by abs change_pct desc
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    telemetry_diffs.sort(key=lambda d: (severity_order[d.severity], -abs(d.change_pct)))

    return ProfileComparison(
        profile_a_id=a.id,
        profile_b_id=b.id,
        config_diffs=config_diffs,
        telemetry_diffs=telemetry_diffs,
        version_diffs=version_diffs,
    )


def _compare_config(a: BehaviourProfile, b: BehaviourProfile) -> list[ConfigDiff]:
    """Compare dynamic config and env vars between two profiles."""
    diffs: list[ConfigDiff] = []

    # Dynamic config
    a_dc = {e.key: e.value for e in a.config_snapshot.dynamic_config}
    b_dc = {e.key: e.value for e in b.config_snapshot.dynamic_config}
    for key in sorted(a_dc.keys() | b_dc.keys()):
        old = a_dc.get(key)
        new = b_dc.get(key)
        if old != new and old is not None and new is not None:
            diffs.append(ConfigDiff(key=f"dynamic_config.{key}", old_value=old, new_value=new))

    # Server env vars (skip redacted)
    a_env = {e.name: e.value for e in a.config_snapshot.server_env_vars if not e.redacted}
    b_env = {e.name: e.value for e in b.config_snapshot.server_env_vars if not e.redacted}
    for key in sorted(a_env.keys() | b_env.keys()):
        old = a_env.get(key)
        new = b_env.get(key)
        if old != new and old is not None and new is not None:
            diffs.append(ConfigDiff(key=f"env.{key}", old_value=old, new_value=new))

    return diffs


def _compare_telemetry(
    a: BehaviourProfile,
    b: BehaviourProfile,
    latency_threshold_pct: float,
    error_threshold_pct: float,
) -> list[TelemetryDiff]:
    """Compare telemetry aggregates between two profiles."""
    diffs: list[TelemetryDiff] = []

    # Flatten telemetry into (name, MetricAggregate) pairs
    a_metrics = _flatten_telemetry(a)
    b_metrics = _flatten_telemetry(b)

    for name in sorted(a_metrics.keys() & b_metrics.keys()):
        old = a_metrics[name]
        new = b_metrics[name]
        change_pct = _pct_change(old.mean, new.mean)

        # Determine direction and severity based on metric type
        is_error = "error" in name or "conflict" in name or "failure" in name or "empty" in name
        # For throughput metrics, higher is generally better
        is_throughput = "per_sec" in name and not is_error

        if abs(change_pct) < 5.0:
            direction = "unchanged"
        elif is_throughput:
            direction = "improved" if change_pct > 0 else "regressed"
        else:
            # For latency/errors, lower is better
            direction = "improved" if change_pct < 0 else "regressed"

        threshold = error_threshold_pct if is_error else latency_threshold_pct
        if direction == "regressed" and abs(change_pct) > threshold * 2:
            severity = "critical"
        elif direction == "regressed" and abs(change_pct) > threshold:
            severity = "warning"
        else:
            severity = "info"

        diffs.append(
            TelemetryDiff(
                metric=name,
                old_value=old,
                new_value=new,
                change_pct=round(change_pct, 2),
                direction=direction,
                severity=severity,
            )
        )

    return diffs


def _compare_versions(a: BehaviourProfile, b: BehaviourProfile) -> list[VersionDiff]:
    """Compare version metadata between two profiles."""
    diffs: list[VersionDiff] = []

    if a.temporal_server_version != b.temporal_server_version:
        diffs.append(
            VersionDiff(
                component="temporal_server",
                old_version=a.temporal_server_version,
                new_version=b.temporal_server_version,
            )
        )
    if a.dsql_plugin_version != b.dsql_plugin_version:
        diffs.append(
            VersionDiff(
                component="dsql_plugin",
                old_version=a.dsql_plugin_version,
                new_version=b.dsql_plugin_version,
            )
        )
    if a.worker_code_sha != b.worker_code_sha:
        # VersionDiff expects VersionType | None, but SHA is str — use None for non-version fields
        diffs.append(
            VersionDiff(
                component="worker_code_sha",
                old_version=None,
                new_version=None,
            )
        )

    return diffs


def _flatten_telemetry(profile: BehaviourProfile) -> dict[str, MetricAggregate]:
    """Flatten nested telemetry into a flat dict of metric name → aggregate."""
    t = profile.telemetry
    flat: dict[str, MetricAggregate] = {}

    # Throughput
    flat["workflows_started_per_sec"] = t.throughput.workflows_started_per_sec
    flat["workflows_completed_per_sec"] = t.throughput.workflows_completed_per_sec
    flat["state_transitions_per_sec"] = t.throughput.state_transitions_per_sec

    # Latency
    flat["workflow_schedule_to_start_p95"] = t.latency.workflow_schedule_to_start_p95
    flat["workflow_schedule_to_start_p99"] = t.latency.workflow_schedule_to_start_p99
    flat["activity_schedule_to_start_p95"] = t.latency.activity_schedule_to_start_p95
    flat["activity_schedule_to_start_p99"] = t.latency.activity_schedule_to_start_p99
    flat["persistence_latency_p95"] = t.latency.persistence_latency_p95
    flat["persistence_latency_p99"] = t.latency.persistence_latency_p99

    # Matching
    flat["sync_match_rate"] = t.matching.sync_match_rate
    flat["async_match_rate"] = t.matching.async_match_rate
    flat["task_dispatch_latency"] = t.matching.task_dispatch_latency
    flat["backlog_count"] = t.matching.backlog_count
    flat["backlog_age"] = t.matching.backlog_age

    # DSQL pool
    flat["pool_open_count"] = t.dsql_pool.pool_open_count
    flat["pool_in_use_count"] = t.dsql_pool.pool_in_use_count
    flat["pool_idle_count"] = t.dsql_pool.pool_idle_count
    flat["reservoir_size"] = t.dsql_pool.reservoir_size
    flat["reservoir_empty_events"] = t.dsql_pool.reservoir_empty_events
    flat["open_failures"] = t.dsql_pool.open_failures
    flat["reconnect_count"] = t.dsql_pool.reconnect_count

    # Errors
    flat["occ_conflicts_per_sec"] = t.errors.occ_conflicts_per_sec
    flat["exhausted_retries_per_sec"] = t.errors.exhausted_retries_per_sec
    flat["dsql_auth_failures"] = t.errors.dsql_auth_failures

    # Resources — worker task slot only (per-service handled separately)
    flat["worker_task_slot_utilization"] = t.resources.worker_task_slot_utilization

    return flat


def _pct_change(old: float, new: float) -> float:
    """Percentage change from old to new. Returns 0 if old is 0."""
    if old == 0:
        return 0.0 if new == 0 else 100.0
    return ((new - old) / abs(old)) * 100
