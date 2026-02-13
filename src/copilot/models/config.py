"""Configuration models for the SRE Copilot.

Thresholds and configuration for the Health State Machine.
These are the deterministic rules that decide health state.

Health State Gates:
- CRITICAL: Forward progress collapsed (signals 1/3/4/5) or backlog age critical
- STRESSED: Progress continues but latency + backlog trending wrong (signals 2/4/8/11)
- HAPPY: Otherwise
"""

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class CriticalThresholds(BaseModel):
    """Thresholds that trigger CRITICAL state.

    CRITICAL if forward progress collapses:
    - Signal 1: State transition throughput drops
    - Signal 3: Workflow completion rate drops
    - Signal 4: History backlog age exceeds critical
    - Signal 5: History processing rate drops
    """

    # Signal 1: State transition throughput
    state_transitions_min_per_sec: float = Field(
        default=10.0,
        description="Below this, forward progress has collapsed",
    )

    # Signal 3: Workflow completion rate
    workflow_completion_rate_min: float = Field(
        default=0.5,
        description="Below this, workflows are failing at alarming rate",
    )

    # Signal 4: History backlog age
    history_backlog_age_max_sec: float = Field(
        default=120.0,
        description="Above this, execution engine is critically behind",
    )

    # Signal 5: History processing rate
    history_processing_rate_min_per_sec: float = Field(
        default=10.0,
        description="Below this with steady demand, capacity exhausted",
    )

    # Signal 12: Persistence error rate
    persistence_error_rate_max_per_sec: float = Field(
        default=10.0,
        description="Above this, persistence is failing not just slow",
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
    """Thresholds for HAPPY state (all must be met)."""

    # Signal 1: State transition throughput
    state_transitions_healthy_per_sec: float = Field(
        default=50.0,
        description="Above this, forward progress is healthy",
    )

    # Signal 4: History backlog age
    history_backlog_age_healthy_sec: float = Field(
        default=10.0,
        description="Below this, execution engine is keeping up",
    )

    # Signal 3: Workflow completion rate
    workflow_completion_rate_healthy: float = Field(
        default=0.95,
        description="Above this, workflows completing normally",
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

    model_config = {"env_prefix": "COPILOT_"}
