"""Behaviour Profile data models — profile, config snapshot, telemetry, comparison."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from copilot_core.models import MetricAggregate, ServiceMetrics  # noqa: TC001
from copilot_core.types import ParameterClassification  # noqa: TC001
from copilot_core.versions import VersionType  # noqa: TC001
from dsql_config.models import ConfigProfile  # noqa: TC001

# ---------------------------------------------------------------------------
# Config snapshot components (Task 11.1)
# ---------------------------------------------------------------------------


class DynamicConfigEntry(BaseModel):
    key: str
    value: int | float | str | bool | list[str]


class EnvVarEntry(BaseModel):
    name: str
    value: str
    redacted: bool = False


class WorkerOptionsSnapshot(BaseModel):
    max_concurrent_activities: int | None = None
    max_concurrent_workflow_tasks: int | None = None
    max_concurrent_local_activities: int | None = None
    workflow_task_pollers: int | None = None
    activity_task_pollers: int | None = None
    sticky_schedule_to_start_timeout_sec: float | None = None
    disable_eager_activities: bool | None = None


class DSQLPluginSnapshot(BaseModel):
    reservoir_enabled: bool
    reservoir_target_ready: int
    reservoir_base_lifetime_min: float
    reservoir_lifetime_jitter_min: float
    reservoir_guard_window_sec: float
    max_conns: int
    max_idle_conns: int
    max_conn_lifetime_min: float
    distributed_rate_limiter_enabled: bool
    token_bucket_enabled: bool
    token_bucket_rate: int | None = None
    token_bucket_capacity: int | None = None
    slot_block_enabled: bool
    slot_block_size: int | None = None
    slot_block_count: int | None = None


class ConfigSnapshot(BaseModel):
    dynamic_config: list[DynamicConfigEntry]
    server_env_vars: list[EnvVarEntry]
    worker_options: WorkerOptionsSnapshot
    dsql_plugin_config: DSQLPluginSnapshot
    config_profile: ConfigProfile | None = None


# ---------------------------------------------------------------------------
# Telemetry summary models (Task 11.2)
# ---------------------------------------------------------------------------


class ThroughputMetrics(BaseModel):
    workflows_started_per_sec: MetricAggregate
    workflows_completed_per_sec: MetricAggregate
    state_transitions_per_sec: MetricAggregate


class LatencyMetrics(BaseModel):
    workflow_schedule_to_start_p95: MetricAggregate
    workflow_schedule_to_start_p99: MetricAggregate
    activity_schedule_to_start_p95: MetricAggregate
    activity_schedule_to_start_p99: MetricAggregate
    persistence_latency_p95: MetricAggregate
    persistence_latency_p99: MetricAggregate


class MatchingMetrics(BaseModel):
    sync_match_rate: MetricAggregate
    async_match_rate: MetricAggregate
    task_dispatch_latency: MetricAggregate
    backlog_count: MetricAggregate
    backlog_age: MetricAggregate


class DSQLPoolMetrics(BaseModel):
    pool_open_count: MetricAggregate
    pool_in_use_count: MetricAggregate
    pool_idle_count: MetricAggregate
    reservoir_size: MetricAggregate
    reservoir_empty_events: MetricAggregate
    open_failures: MetricAggregate
    reconnect_count: MetricAggregate


class ErrorMetrics(BaseModel):
    occ_conflicts_per_sec: MetricAggregate
    exhausted_retries_per_sec: MetricAggregate
    dsql_auth_failures: MetricAggregate


class ResourceMetrics(BaseModel):
    cpu_utilization: ServiceMetrics
    memory_utilization: ServiceMetrics
    worker_task_slot_utilization: MetricAggregate


class TelemetrySummary(BaseModel):
    throughput: ThroughputMetrics
    latency: LatencyMetrics
    matching: MatchingMetrics
    dsql_pool: DSQLPoolMetrics
    errors: ErrorMetrics
    resources: ResourceMetrics


# ---------------------------------------------------------------------------
# Behaviour Profile (Task 11.1)
# ---------------------------------------------------------------------------


class BehaviourProfile(BaseModel):
    id: str
    name: str
    label: str | None = None

    cluster_id: str
    namespace: str | None = None
    task_queue: str | None = None
    time_window_start: str
    time_window_end: str

    temporal_server_version: VersionType | None = None
    dsql_plugin_version: VersionType | None = None
    worker_code_sha: str | None = None

    config_snapshot: ConfigSnapshot | None = None
    telemetry: TelemetrySummary

    created_at: str
    is_baseline: bool = False


# ---------------------------------------------------------------------------
# API request/response models (Task 11.1)
# ---------------------------------------------------------------------------


class ProfileMetadata(BaseModel):
    id: str
    name: str
    label: str | None
    cluster_id: str
    namespace: str | None
    time_window_start: str
    time_window_end: str
    is_baseline: bool
    created_at: str


class CreateProfileRequest(BaseModel):
    name: str
    cluster_id: str
    time_window_start: str
    time_window_end: str
    namespace: str | None = None
    task_queue: str | None = None
    label: str | None = None


class CompareRequest(BaseModel):
    profile_a_id: str
    profile_b_id: str


# ---------------------------------------------------------------------------
# Profile comparison models (Task 11.3)
# ---------------------------------------------------------------------------


class ConfigDiff(BaseModel):
    key: str
    old_value: int | float | str | bool
    new_value: int | float | str | bool
    classification: ParameterClassification | None = None


class TelemetryDiff(BaseModel):
    metric: str
    old_value: MetricAggregate
    new_value: MetricAggregate
    change_pct: float
    direction: Literal["improved", "regressed", "unchanged"]
    severity: Literal["info", "warning", "critical"]


class VersionDiff(BaseModel):
    component: str
    old_version: VersionType | None
    new_version: VersionType | None


class ProfileComparison(BaseModel):
    profile_a_id: str
    profile_b_id: str
    config_diffs: list[ConfigDiff]
    telemetry_diffs: list[TelemetryDiff]
    version_diffs: list[VersionDiff]
