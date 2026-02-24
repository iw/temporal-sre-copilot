"""Configuration models for the SRE Copilot.

Thresholds and configuration for the Health State Machine.
These are the deterministic rules that decide health state.

Health State Gates:
- CRITICAL: Forward progress collapsed (signals 1/3/4/5) or backlog age critical
- STRESSED: Progress continues but latency + backlog trending wrong (signals 2/4/8/11)
- HAPPY: Otherwise
"""

from enum import StrEnum

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class CriticalThresholds(BaseModel):
    """Thresholds that trigger CRITICAL state.

    CRITICAL if forward progress collapses:
    - Signal 1: State transition throughput drops
    - Signal 3: Workflow completion rate drops (demand-gated)
    - Signal 4: History backlog age exceeds critical
    - Signal 5: History processing rate drops
    """

    # Signal 1: State transition throughput
    state_transitions_min_per_sec: float = Field(
        default=5.0,
        description=(
            "Below this, forward progress has collapsed. "
            "Set conservatively low to avoid false Critical during ramp-up/down."
        ),
    )

    # Signal 3: Workflow completion rate
    workflow_completion_rate_min: float = Field(
        default=0.3,
        description=(
            "Below this, workflows are failing at alarming rate. "
            "Only evaluated when demand exceeds completion_rate_demand_floor_per_sec."
        ),
    )

    # Signal 3 demand gate: completion rate is only meaningful when
    # there's enough terminal throughput to form a reliable ratio.
    completion_rate_demand_floor_per_sec: float = Field(
        default=5.0,
        description=(
            "Minimum terminal workflow throughput (success + failed) before "
            "completion_rate is evaluated. Prevents false Critical during "
            "ramp-up when completions naturally lag behind starts."
        ),
    )

    # Signal 4: History backlog age
    history_backlog_age_max_sec: float = Field(
        default=300.0,
        description=(
            "Above this, execution engine is critically behind. "
            "Set to 5 minutes — a 2-minute threshold was too eager "
            "during load test ramp-up and DSQL latency spikes."
        ),
    )

    # Signal 5: History processing rate
    history_processing_rate_min_per_sec: float = Field(
        default=5.0,
        description=(
            "Below this with steady demand, capacity exhausted. "
            "Set conservatively low to avoid false Critical during ramp transitions."
        ),
    )

    # Signal 12: Persistence error rate
    persistence_error_rate_max_per_sec: float = Field(
        default=50.0,
        description=(
            "Above this, persistence is failing not just slow. "
            "Set high because OCC retries during contention can easily "
            "spike above 10/sec transiently without impacting progress."
        ),
    )


class StressedThresholds(BaseModel):
    """Thresholds that trigger STRESSED state.

    STRESSED if progress continues but trending wrong:
    - Signal 2: State transition latency rising
    - Signal 4: History backlog age rising (but not critical)
    - Signal 8: Frontend latency rising
    - Signal 11: Persistence latency rising
    """

    # Signal 2: State transition latency
    state_transition_latency_p99_max_ms: float = Field(
        default=500.0,
        description="Above this, early warning of contention",
    )

    # Signal 4: History backlog age (stress threshold, lower than critical)
    history_backlog_age_stress_sec: float = Field(
        default=30.0,
        description="Above this, execution engine falling behind",
    )

    # Signal 8: Frontend latency
    frontend_latency_p99_max_ms: float = Field(
        default=1000.0,
        description="Above this, API surface is degrading",
    )

    # Signal 11: Persistence latency
    persistence_latency_p99_max_ms: float = Field(
        default=100.0,
        description="Above this, primary dependency is slow",
    )

    # Signal 6: Shard churn rate
    shard_churn_rate_max_per_sec: float = Field(
        default=5.0,
        description="Above this, membership instability",
    )

    # Signal 10: Poller timeout rate
    poller_timeout_rate_max: float = Field(
        default=0.1,
        description="Above this, matching pressure or misconfiguration",
    )


class HealthyThresholds(BaseModel):
    """Thresholds for HAPPY state (all must be met).

    These are deliberately set low to avoid the "perpetually STRESSED" trap.
    A cluster running at 20 WPS with 90% completion is healthy — the old
    thresholds (50 st/sec, 95% completion) would have kept it in STRESSED
    permanently, making it one transient spike away from Critical.
    """

    # Signal 1: State transition throughput
    state_transitions_healthy_per_sec: float = Field(
        default=10.0,
        description=(
            "Above this, forward progress is healthy. "
            "Set to match the critical floor — if you're above critical, "
            "and other gates pass, you're healthy."
        ),
    )

    # Signal 4: History backlog age
    history_backlog_age_healthy_sec: float = Field(
        default=30.0,
        description=(
            "Below this, execution engine is keeping up. "
            "Relaxed from 10s — some backlog is normal under load."
        ),
    )

    # Signal 3: Workflow completion rate
    workflow_completion_rate_healthy: float = Field(
        default=0.85,
        description=(
            "Above this, workflows completing normally. "
            "Relaxed from 0.95 — a 90% completion rate with retries "
            "is healthy for many workloads."
        ),
    )


class AmplifierThresholds(BaseModel):
    """Thresholds for amplifier signals (explain why, guide remediation)."""

    # Amplifier 1: Persistence contention
    occ_conflicts_pressure_per_sec: float = Field(
        default=30.0,
        description="Above this, retry storms likely",
    )

    # Amplifier 2: Connection pool saturation
    pool_utilization_pressure_pct: float = Field(
        default=80.0,
        description="Above this, artificial throttling",
    )
    pool_wait_duration_pressure_ms: float = Field(
        default=100.0,
        description="Above this, connection starvation",
    )

    # Amplifier 3: Connection churn
    connection_churn_pressure_per_sec: float = Field(
        default=10.0,
        description="Above this, auth/token issues likely",
    )

    # Amplifier 7: Cache pressure
    cache_hit_rate_min: float = Field(
        default=0.8,
        description="Below this, cache thrash increasing DB load",
    )

    # Amplifier 11: Host pressure
    cpu_throttle_pressure_pct: float = Field(
        default=10.0,
        description="Above this, CPU throttling impacting performance",
    )
    gc_pause_pressure_ms: float = Field(
        default=100.0,
        description="Above this, GC pauses impacting latency",
    )


class NarrativePatterns(BaseModel):
    """Error patterns for narrative signals (logs).

    Amplifier 13: A small set of repeated log messages often explains 80% of incidents.
    """

    patterns: dict[str, tuple[str, str]] = Field(
        default={
            # Pattern → (service, description)
            "deadline exceeded": ("all", "Timeout pressure"),
            "context canceled": ("all", "Cancellation cascade"),
            "shard ownership": ("history", "Membership instability"),
            "member joined": ("all", "Ringpop membership change"),
            "member left": ("all", "Ringpop membership change"),
            "no poller": ("matching", "Worker misconfiguration"),
            "reservoir discard": ("history", "Connection pool pressure"),
            "SQLSTATE 40001": ("all", "OCC serialization failure"),
            "rate limit exceeded": ("all", "DSQL connection rate limit"),
            "shard acquired": ("history", "Shard ownership change"),
            "shard released": ("history", "Shard ownership change"),
        },
        description="Log patterns to detect as narrative signals",
    )


class CopilotConfig(BaseSettings):
    """Main configuration for the SRE Copilot."""

    # AWS Configuration
    aws_region: str = Field(default="eu-west-1", description="AWS region")

    # DSQL Configuration
    dsql_endpoint: str = Field(description="Aurora DSQL cluster endpoint")
    dsql_database: str = Field(default="postgres", description="DSQL database name")

    # AMP Configuration
    amp_workspace_id: str = Field(description="Amazon Managed Prometheus workspace ID")
    amp_endpoint: str = Field(description="AMP query endpoint URL")

    # Loki Configuration
    loki_url: str = Field(description="Loki query endpoint URL")

    # Bedrock Configuration
    knowledge_base_id: str = Field(description="Bedrock Knowledge Base ID")
    data_source_id: str = Field(description="Bedrock KB Data Source ID")

    # Temporal Configuration
    temporal_host: str = Field(default="localhost:7233", description="Temporal server address")
    temporal_namespace: str = Field(
        default="copilot", description="Temporal namespace for Copilot workflows"
    )
    task_queue: str = Field(default="copilot-tasks", description="Temporal task queue name")

    # Observation Configuration
    observation_interval_sec: int = Field(
        default=30, description="Interval between signal observations"
    )
    sliding_window_size: int = Field(default=10, description="Number of signal snapshots to keep")
    assessment_interval_min: int = Field(
        default=5, description="Interval between scheduled assessments"
    )
    deduplication_window_min: int = Field(
        default=4, description="Window for assessment deduplication"
    )

    # Thresholds (nested)
    critical: CriticalThresholds = Field(default_factory=CriticalThresholds)
    stressed: StressedThresholds = Field(default_factory=StressedThresholds)
    healthy: HealthyThresholds = Field(default_factory=HealthyThresholds)
    amplifiers: AmplifierThresholds = Field(default_factory=AmplifierThresholds)
    narrative_patterns: NarrativePatterns = Field(default_factory=NarrativePatterns)

    # Scale-aware threshold overrides (optional)
    threshold_overrides: ThresholdOverrides | None = Field(
        default=None,
        description="Per-threshold overrides that take precedence over scale band defaults",
    )

    model_config = {"env_prefix": "COPILOT_"}


# =============================================================================
# SCALE-AWARE THRESHOLDS
# =============================================================================


class ScaleBand(StrEnum):
    """Scale band aligned with Config Compiler presets.

    Throughput ranges (state transitions per second):
    - STARTER: 0-50 st/sec (dev clusters, low-throughput workloads)
    - MID_SCALE: 50-500 st/sec (moderate production workloads)
    - HIGH_THROUGHPUT: 500+ st/sec (high-throughput production)
    """

    STARTER = "starter"
    MID_SCALE = "mid-scale"
    HIGH_THROUGHPUT = "high-throughput"


class ThresholdProfile(BaseModel):
    """Complete threshold set for a scale band."""

    scale_band: ScaleBand
    critical: CriticalThresholds
    stressed: StressedThresholds
    healthy: HealthyThresholds


class ThresholdOverrides(BaseModel):
    """Optional per-threshold overrides that take precedence over scale band defaults.

    Only non-None fields are applied. This allows operators to tune
    individual thresholds without replacing the entire profile.
    """

    # Critical overrides
    state_transitions_min_per_sec: float | None = None
    history_processing_rate_min_per_sec: float | None = None
    completion_rate_demand_floor_per_sec: float | None = None
    history_backlog_age_max_sec: float | None = None
    persistence_error_rate_max_per_sec: float | None = None

    # Stressed overrides
    state_transition_latency_p99_max_ms: float | None = None
    history_backlog_age_stress_sec: float | None = None
    frontend_latency_p99_max_ms: float | None = None
    persistence_latency_p99_max_ms: float | None = None
    poller_timeout_rate_max: float | None = None

    # Healthy overrides
    state_transitions_healthy_per_sec: float | None = None
    history_backlog_age_healthy_sec: float | None = None
    workflow_completion_rate_healthy: float | None = None


# Pre-built profiles for each scale band.
# Starter accommodates DSQL baseline latency and low-throughput characteristics.
# High-throughput retains current production-calibrated defaults.
THRESHOLD_PROFILES: dict[ScaleBand, ThresholdProfile] = {
    ScaleBand.STARTER: ThresholdProfile(
        scale_band=ScaleBand.STARTER,
        critical=CriticalThresholds(
            state_transitions_min_per_sec=0.5,
            history_processing_rate_min_per_sec=0.5,
            completion_rate_demand_floor_per_sec=0.5,
            history_backlog_age_max_sec=600.0,
        ),
        stressed=StressedThresholds(
            state_transition_latency_p99_max_ms=2000.0,
            history_backlog_age_stress_sec=120.0,
            frontend_latency_p99_max_ms=5000.0,
            persistence_latency_p99_max_ms=500.0,
            poller_timeout_rate_max=0.5,
        ),
        healthy=HealthyThresholds(
            state_transitions_healthy_per_sec=0.5,
            history_backlog_age_healthy_sec=120.0,
        ),
    ),
    ScaleBand.MID_SCALE: ThresholdProfile(
        scale_band=ScaleBand.MID_SCALE,
        critical=CriticalThresholds(
            state_transitions_min_per_sec=3.0,
            history_processing_rate_min_per_sec=3.0,
            completion_rate_demand_floor_per_sec=3.0,
            history_backlog_age_max_sec=300.0,
        ),
        stressed=StressedThresholds(
            state_transition_latency_p99_max_ms=1000.0,
            history_backlog_age_stress_sec=60.0,
            frontend_latency_p99_max_ms=2000.0,
            persistence_latency_p99_max_ms=200.0,
            poller_timeout_rate_max=0.3,
        ),
        healthy=HealthyThresholds(
            state_transitions_healthy_per_sec=5.0,
            history_backlog_age_healthy_sec=60.0,
        ),
    ),
    ScaleBand.HIGH_THROUGHPUT: ThresholdProfile(
        scale_band=ScaleBand.HIGH_THROUGHPUT,
        critical=CriticalThresholds(),  # Production defaults
        stressed=StressedThresholds(),  # Production defaults
        healthy=HealthyThresholds(),  # Production defaults
    ),
}


def _apply_overrides(profile: ThresholdProfile, overrides: ThresholdOverrides) -> None:
    """Apply non-None override fields to a threshold profile (mutates in place)."""
    for field_name in (
        "state_transitions_min_per_sec",
        "history_processing_rate_min_per_sec",
        "completion_rate_demand_floor_per_sec",
        "history_backlog_age_max_sec",
        "persistence_error_rate_max_per_sec",
    ):
        val = getattr(overrides, field_name)
        if val is not None:
            setattr(profile.critical, field_name, val)

    for field_name in (
        "state_transition_latency_p99_max_ms",
        "history_backlog_age_stress_sec",
        "frontend_latency_p99_max_ms",
        "persistence_latency_p99_max_ms",
        "poller_timeout_rate_max",
    ):
        val = getattr(overrides, field_name)
        if val is not None:
            setattr(profile.stressed, field_name, val)

    for field_name in (
        "state_transitions_healthy_per_sec",
        "history_backlog_age_healthy_sec",
        "workflow_completion_rate_healthy",
    ):
        val = getattr(overrides, field_name)
        if val is not None:
            setattr(profile.healthy, field_name, val)


def _validate_threshold_ordering(profile: ThresholdProfile) -> None:
    """Validate that threshold ordering invariants hold.

    Raises ValueError if critical > healthy for throughput thresholds.
    Equal values are allowed (e.g., STARTER band where both are 0.5).
    """
    if (
        profile.critical.state_transitions_min_per_sec
        > profile.healthy.state_transitions_healthy_per_sec
    ):
        raise ValueError(
            f"critical.state_transitions_min_per_sec "
            f"({profile.critical.state_transitions_min_per_sec}) must be ≤ "
            f"healthy.state_transitions_healthy_per_sec "
            f"({profile.healthy.state_transitions_healthy_per_sec})"
        )


def get_threshold_profile(
    scale_band: ScaleBand,
    *,
    overrides: ThresholdOverrides | None = None,
) -> ThresholdProfile:
    """Get the threshold profile for a scale band, with optional overrides.

    Raises:
        ValueError: If overrides violate the ordering invariant.
    """
    profile = THRESHOLD_PROFILES[scale_band].model_copy(deep=True)
    if overrides:
        _apply_overrides(profile, overrides)
        _validate_threshold_ordering(profile)
    return profile
