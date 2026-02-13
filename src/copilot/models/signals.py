"""Signal models for the Health State Machine.

Signal Taxonomy:
- Primary (12): Decide health state (forward progress indicators)
- Amplifiers (14): Explain why (resource pressure, contention)
- Narrative: Logs that explain transitions

Health State Gates:
- CRITICAL: Forward progress collapsed (signals 1/3/4/5) or backlog age critical
- STRESSED: Progress continues but latency + backlog trending wrong (signals 2/4/8/11)
- HAPPY: Otherwise

Date/Time: All timestamps use `whenever` library (UTC-first, Rust-backed).
"""

from enum import StrEnum

from pydantic import BaseModel, Field
from whenever import Instant


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return Instant.now().format_iso()


class HealthState(StrEnum):
    """Canonical health states derived from forward progress.

    The Health State Machine derives state from one question:
    "Is the cluster making forward progress on workflows?"

    State transitions:
        Happy → Stressed → Critical
          ↑         ↓         ↓
          └─────────┴─────────┘

    INVARIANT: Happy → Critical transition MUST go through Stressed.
    """

    HAPPY = "happy"  # Forward progress healthy, no concerning amplifiers
    STRESSED = "stressed"  # Progress continues but amplifiers indicate pressure
    CRITICAL = "critical"  # Forward progress is impaired or stopped


# =============================================================================
# PRIMARY SIGNALS (12) - Decide Health State
# =============================================================================


class StateTransitionSignals(BaseModel):
    """Signals 1-2: State transition throughput and latency."""

    throughput_per_sec: float = Field(
        ge=0,
        description="Real forward progress. If drops while RPS flat, systemic trouble.",
    )
    latency_p95_ms: float = Field(
        ge=0, description="Early warning of contention. Often rises before breaks."
    )
    latency_p99_ms: float = Field(ge=0, description="Tail latency for state transitions")


class WorkflowCompletionSignals(BaseModel):
    """Signal 3: Workflow completion rate."""

    completion_rate: float = Field(
        ge=0,
        le=1,
        description="User-visible 'is work finishing?'. Success + terminal outcomes.",
    )
    success_per_sec: float = Field(ge=0, description="Successful workflow completions/sec")
    failed_per_sec: float = Field(ge=0, description="Failed workflow completions/sec")


class HistorySignals(BaseModel):
    """Signals 4-6: History service health."""

    backlog_age_sec: float = Field(
        ge=0,
        description=(
            "Strongest predictor of cascading failures. Is execution engine falling behind?"
        ),
    )
    task_processing_rate_per_sec: float = Field(
        ge=0,
        description="Capacity vs demand. Falling rate with steady demand is red flag.",
    )
    shard_churn_rate_per_sec: float = Field(
        ge=0,
        description="Membership instability, resource pressure, deploy thrash. High churn is bad.",
    )


class FrontendSignals(BaseModel):
    """Signals 7-8: Frontend service health."""

    error_rate_per_sec: float = Field(
        ge=0, description="When clients are actually impacted. Often lags behind stress."
    )
    latency_p95_ms: float = Field(ge=0, description="Whether API surface is degrading.")
    latency_p99_ms: float = Field(ge=0, description="Tail latency for frontend requests")


class MatchingSignals(BaseModel):
    """Signal 9: Matching service health."""

    workflow_backlog_age_sec: float = Field(
        ge=0,
        description="Work is waiting. Separates 'server fine but workers slow' vs server issues.",
    )
    activity_backlog_age_sec: float = Field(ge=0, description="Activity task queue backlog age")


class PollerSignals(BaseModel):
    """Signal 10: Poller health."""

    poll_success_rate: float = Field(
        ge=0, le=1, description="Starvation and matching pressure indicator."
    )
    poll_timeout_rate: float = Field(
        ge=0, le=1, description="Catches misconfiguration ('no poller')."
    )
    long_poll_latency_ms: float = Field(ge=0, description="Long-poll latency")


class PersistenceSignals(BaseModel):
    """Signals 11-12: Persistence health."""

    latency_p95_ms: float = Field(
        ge=0,
        description="Primary systemic dependency. If slow, everything amplifies.",
    )
    latency_p99_ms: float = Field(ge=0, description="Tail latency for persistence ops")
    error_rate_per_sec: float = Field(
        ge=0,
        description="'Slow but working' vs 'failing'. Essential for health state transitions.",
    )
    retry_rate_per_sec: float = Field(ge=0, description="Persistence retry rate")


class PrimarySignals(BaseModel):
    """All 12 primary signals that decide health state.

    These are the ONLY inputs to state transitions. They answer:
    "Is the cluster making forward progress on workflows?"

    Health State Gates:
    - CRITICAL: signals 1/3/4/5 collapse or backlog age critical
    - STRESSED: signals 2/4/8/11 trending wrong
    - HAPPY: otherwise
    """

    state_transitions: StateTransitionSignals
    workflow_completion: WorkflowCompletionSignals
    history: HistorySignals
    frontend: FrontendSignals
    matching: MatchingSignals
    poller: PollerSignals
    persistence: PersistenceSignals


# =============================================================================
# AMPLIFIER SIGNALS (14) - Explain Why
# =============================================================================


class PersistenceAmplifiers(BaseModel):
    """Amplifier 1: Persistence contention."""

    occ_conflicts_per_sec: float = Field(
        ge=0,
        description="Turns load into retry storms. You'll feel it everywhere.",
    )
    cas_failures_per_sec: float = Field(ge=0, description="CAS/compare-and-swap failures")
    serialization_failures_per_sec: float = Field(
        ge=0, description="Serialization failures (SQLSTATE 40001)"
    )


class ConnectionPoolAmplifiers(BaseModel):
    """Amplifiers 2-3: Connection pool health."""

    utilization_pct: float = Field(
        ge=0,
        le=100,
        description="Creates artificial throttling + latency. Hidden 'why did everything spike?'",
    )
    wait_count: int = Field(ge=0, description="Requests waiting for connection")
    wait_duration_ms: float = Field(ge=0, description="Time spent waiting for connection")
    churn_rate_per_sec: float = Field(
        ge=0,
        description="Kills performance, triggers auth/token failures with short-lived creds.",
    )
    opens_per_sec: float = Field(ge=0, description="Connection opens per second")
    closes_per_sec: float = Field(ge=0, description="Connection closes per second")


class QueueAmplifiers(BaseModel):
    """Amplifiers 4-5: Queue depth and retry pressure."""

    task_backlog_depth: int = Field(
        ge=0,
        description="Age tells 'lateness'; depth tells 'how much work to drain'.",
    )
    retry_time_spent_sec: float = Field(
        ge=0,
        description="How much time burned just trying again. Great 'amplification meter'.",
    )


class WorkerAmplifiers(BaseModel):
    """Amplifier 6: Worker-side saturation."""

    poller_concurrency: int = Field(
        ge=0, description="Even for server dashboards, tells if backlog is worker capacity issue."
    )
    task_slots_available: int = Field(ge=0, description="Available task slots")
    task_slots_used: int = Field(ge=0, description="Used task slots")


class CacheAmplifiers(BaseModel):
    """Amplifier 7: History cache pressure."""

    hit_rate: float = Field(
        ge=0,
        le=1,
        description="Cache thrash increases DB reads and latency. Common silent multiplier.",
    )
    evictions_per_sec: float = Field(ge=0, description="Cache evictions per second")
    size_bytes: int = Field(ge=0, description="Current cache size")


class ShardAmplifiers(BaseModel):
    """Amplifier 8: Shard-level hot spotting."""

    hot_shard_ratio: float = Field(
        ge=0,
        description="One hot shard can dominate tail latency for whole cluster.",
    )
    max_shard_load_pct: float = Field(ge=0, le=100, description="Load on most loaded shard")


class GrpcAmplifiers(BaseModel):
    """Amplifier 9: gRPC saturation."""

    in_flight_requests: int = Field(
        ge=0,
        description="Tail latency can be network/serialization, not DB.",
    )
    server_queue_depth: int = Field(ge=0, description="Server-side queueing depth")


class RuntimeAmplifiers(BaseModel):
    """Amplifier 10: Thread/goroutine pool pressure."""

    goroutines: int = Field(
        ge=0,
        description="Reveals internal starvation before external symptoms.",
    )
    blocked_goroutines: int = Field(ge=0, description="Blocked goroutines")


class HostAmplifiers(BaseModel):
    """Amplifier 11: Host resource pressure."""

    cpu_throttle_pct: float = Field(ge=0, le=100, description="CPU throttling percentage")
    memory_rss_bytes: int = Field(ge=0, description="Resident set size")
    gc_pause_ms: float = Field(
        ge=0,
        description="GC/heap growth in History is a classic. Shape matters.",
    )


class ThrottlingAmplifiers(BaseModel):
    """Amplifier 12: Rate limiting / throttling events."""

    rate_limit_events_per_sec: float = Field(
        ge=0,
        description=(
            "Creates 'progress continues but slower' patterns that look like random latency."
        ),
    )
    admission_rejects_per_sec: float = Field(ge=0, description="Admission control rejections")


class DeployAmplifiers(BaseModel):
    """Amplifier 14: Deploy / scaling churn markers."""

    task_restarts: int = Field(
        ge=0,
        description="Change itself is an amplifier. Correlate with every spike.",
    )
    membership_changes_per_min: float = Field(ge=0, description="Membership changes per minute")
    leader_changes_per_min: float = Field(ge=0, description="Leader changes per minute")


class AmplifierSignals(BaseModel):
    """All 14 amplifier signals that explain why state changed.

    Amplifiers do NOT decide state—they provide context for explanation.
    They guide the LLM's "why" and "what to do" narrative.

    Amplifier → Remediation Mapping:
    - Persistence contention → tune retries/backoff, increase History capacity
    - Connection pool saturation → pool sizing, reduce churn, check token refresh
    - Matching backlog age → scale workers, fix pollers
    """

    persistence: PersistenceAmplifiers
    connection_pool: ConnectionPoolAmplifiers
    queue: QueueAmplifiers
    worker: WorkerAmplifiers
    cache: CacheAmplifiers
    shard: ShardAmplifiers
    grpc: GrpcAmplifiers
    runtime: RuntimeAmplifiers
    host: HostAmplifiers
    throttling: ThrottlingAmplifiers
    deploy: DeployAmplifiers


# =============================================================================
# NARRATIVE SIGNALS - Logs Explain Transitions
# =============================================================================


class LogPattern(BaseModel):
    """Narrative signal from logs (Amplifier 13).

    A small set of repeated log messages often explains 80% of incidents.

    Key patterns:
    - "deadline exceeded" → timeout pressure
    - "context canceled" → cancellation cascade
    - "shard ownership" → membership instability
    - "membership" → ringpop churn
    - "no poller" → worker misconfiguration
    - "reservoir discard" → connection pool pressure
    - "SQLSTATE 40001" → OCC serialization failure
    """

    count: int = Field(ge=0, description="Number of occurrences in the window")
    pattern: str = Field(description="The error pattern detected")
    service: str = Field(description="Service that emitted the log")
    sample_message: str | None = Field(
        default=None, description="Example log message matching the pattern"
    )


# =============================================================================
# COMBINED SIGNALS
# =============================================================================


class Signals(BaseModel):
    """Complete signal collection with taxonomy.

    Combines all signal types for health evaluation:
    - primary: Decide state (12 signals for forward progress)
    - amplifiers: Explain why (14 signals for resource pressure)
    - timestamp: When signals were collected (ISO 8601 UTC string)
    """

    primary: PrimarySignals
    amplifiers: AmplifierSignals
    timestamp: str = Field(
        default_factory=_now_iso, description="When signals were collected (ISO 8601 UTC)"
    )


# =============================================================================
# WORKER HEALTH MODEL - Separate from Server Health
# Source: Temporal Workers presentation (Tihomir Surdilovic, 2024)
# =============================================================================


class WorkerSignals(BaseModel):
    """Worker-side primary signals (forward progress indicators).

    These answer: "Can workers make forward progress?"
    Collected from SDK metrics emitted by worker processes.

    Critical thresholds:
    - WFT schedule-to-start > 50ms = worker pressure
    - task_slots_available == 0 = worker stops polling entirely
    """

    # Schedule-to-start latencies (< 50ms healthy for WFT)
    wft_schedule_to_start_p95_ms: float = Field(
        ge=0,
        description="Workflow task schedule-to-start latency. < 50ms is healthy.",
    )
    wft_schedule_to_start_p99_ms: float = Field(
        ge=0, description="Tail latency for workflow task schedule-to-start"
    )
    activity_schedule_to_start_p95_ms: float = Field(
        ge=0,
        description=(
            "Activity schedule-to-start latency. Workers not picking up activities fast enough."
        ),
    )
    activity_schedule_to_start_p99_ms: float = Field(
        ge=0, description="Tail latency for activity schedule-to-start"
    )

    # Task slots (0 = worker stops polling)
    workflow_slots_available: int = Field(
        ge=0,
        description="Available workflow task slots. 0 = worker stops polling.",
    )
    workflow_slots_used: int = Field(ge=0, description="Workflow task slots in use")
    activity_slots_available: int = Field(
        ge=0,
        description="Available activity task slots. 0 = worker stops polling.",
    )
    activity_slots_used: int = Field(ge=0, description="Activity task slots in use")

    # Poller counts
    workflow_pollers: int = Field(ge=0, description="Number of workflow task pollers")
    activity_pollers: int = Field(ge=0, description="Number of activity task pollers")


class WorkerCacheAmplifiers(BaseModel):
    """Worker sticky cache amplifiers.

    Sticky cache stores workflow state to avoid replaying history.
    Cache misses cause full history replay, increasing DB reads and latency.
    """

    sticky_cache_size: int = Field(
        ge=0, description="Current sticky cache size (number of cached workflows)"
    )
    sticky_cache_hit_rate: float = Field(
        ge=0,
        le=1,
        description="Cache hit rate. < 80% = investigate, < 50% = critical.",
    )
    sticky_cache_miss_rate_per_sec: float = Field(
        ge=0, description="Cache miss rate. High = excessive history replay."
    )


class WorkerPollAmplifiers(BaseModel):
    """Worker polling amplifiers.

    Long-poll latency and failures indicate network/service pressure.
    """

    long_poll_latency_p95_ms: float = Field(ge=0, description="Long-poll request latency")
    long_poll_failure_rate_per_sec: float = Field(ge=0, description="Long-poll request failures")
    poller_executor_mismatch: bool = Field(
        default=False,
        description=(
            "True if pollers > executor slots."
            " 'Makes no sense to configure more pollers than executor slots.'"
        ),
    )


class WorkerHealthSignals(BaseModel):
    """Complete worker health signal collection.

    Combines worker signals and amplifiers for bottleneck classification.
    """

    signals: WorkerSignals
    cache: WorkerCacheAmplifiers
    poll: WorkerPollAmplifiers
    timestamp: str = Field(
        default_factory=_now_iso, description="When signals were collected (ISO 8601 UTC)"
    )


class BottleneckClassification(StrEnum):
    """Bottleneck classification for remediation guidance.

    Classifies whether the bottleneck is server-side or worker-side.
    This is DETERMINISTIC - no LLM involved.
    """

    SERVER_LIMITED = "server_limited"  # Server can't keep up (high backlog, persistence latency)
    WORKER_LIMITED = (
        "worker_limited"  # Workers can't keep up (slots exhausted, high schedule-to-start)
    )
    MIXED = "mixed"  # Both server and workers under pressure
    HEALTHY = "healthy"  # Neither constrained
