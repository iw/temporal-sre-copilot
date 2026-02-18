"""Parameter Registry — single source of truth for all Temporal DSQL configuration parameters."""

from copilot_core.types import (
    OutputTarget,
    ParameterClassification,
    ParameterConstraints,
    ParameterEntry,
    ParameterUnit,
    ParameterValueType,
)


class ParameterRegistry:
    """Registry of all known configuration parameters.

    Stores classification, constraints, and rationale for each parameter.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ParameterEntry] = {}

    def register(self, entry: ParameterEntry) -> None:
        if entry.key in self._entries:
            raise ValueError(f"Parameter '{entry.key}' is already registered")
        self._entries[entry.key] = entry

    def get(self, key: str) -> ParameterEntry | None:
        return self._entries.get(key)

    def list_by_classification(
        self, classification: ParameterClassification
    ) -> list[ParameterEntry]:
        return [e for e in self._entries.values() if e.classification == classification]

    def all_keys(self) -> list[str]:
        return list(self._entries.keys())

    def all_entries(self) -> list[ParameterEntry]:
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


def build_default_registry() -> ParameterRegistry:
    """Build the default registry populated with all known Temporal DSQL parameters."""
    registry = ParameterRegistry()

    # =========================================================================
    # SLO Parameters — adopter-chosen, reflect service-level objectives
    # =========================================================================

    registry.register(
        ParameterEntry(
            key="target_state_transitions_per_sec",
            classification=ParameterClassification.SLO,
            description=("Target state transitions per second the cluster should sustain"),
            rationale=(
                "Primary throughput SLO — drives history replica"
                " count, persistence QPS limits, and matching"
                " partition sizing"
            ),
            default_value=50,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=1, max_value=10000),
            output_targets=[],
        )
    )

    registry.register(
        ParameterEntry(
            key="target_workflow_completion_rate",
            classification=ParameterClassification.SLO,
            description="Target workflow completions per second",
            rationale=(
                "Secondary throughput SLO — validates that workflows complete, not just start"
            ),
            default_value=50,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=1, max_value=10000),
            output_targets=[],
        )
    )

    registry.register(
        ParameterEntry(
            key="max_schedule_to_start_latency_ms",
            classification=ParameterClassification.SLO,
            description=("Maximum acceptable schedule-to-start latency for workflow tasks"),
            rationale=("Latency SLO — drives matching partition count and poller configuration"),
            default_value=200,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.MILLISECONDS,
            constraints=ParameterConstraints(min_value=10, max_value=60000),
            output_targets=[],
        )
    )

    registry.register(
        ParameterEntry(
            key="max_e2e_workflow_latency_ms",
            classification=ParameterClassification.SLO,
            description=("Maximum acceptable end-to-end workflow latency for simple workflows"),
            rationale=(
                "End-to-end latency SLO — drives eager execution"
                " settings and activity dispatch strategy"
            ),
            default_value=500,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.MILLISECONDS,
            constraints=ParameterConstraints(min_value=50, max_value=300000),
            output_targets=[],
        )
    )

    # =========================================================================
    # Topology Parameters — adopter-optional, preset-provided defaults
    # =========================================================================

    registry.register(
        ParameterEntry(
            key="history.shards",
            classification=ParameterClassification.TOPOLOGY,
            description=("Number of history shards for the Temporal cluster"),
            rationale=(
                "Shard count determines parallelism for history"
                " processing; must be set at cluster creation"
                " and cannot be changed"
            ),
            default_value=512,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=16384),
            output_targets=[OutputTarget.ENV_VARS],
        )
    )

    registry.register(
        ParameterEntry(
            key="history.replicas",
            classification=ParameterClassification.TOPOLOGY,
            description="Number of history service replicas",
            rationale=("More replicas distribute shard ownership and increase throughput capacity"),
            default_value=4,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=100),
            output_targets=[OutputTarget.ENV_VARS],
        )
    )

    registry.register(
        ParameterEntry(
            key="matching.replicas",
            classification=ParameterClassification.TOPOLOGY,
            description="Number of matching service replicas",
            rationale=("Matching replicas handle task dispatch; scale with task queue throughput"),
            default_value=2,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=50),
            output_targets=[OutputTarget.ENV_VARS],
        )
    )

    registry.register(
        ParameterEntry(
            key="frontend.replicas",
            classification=ParameterClassification.TOPOLOGY,
            description="Number of frontend service replicas",
            rationale=("Frontend replicas handle API requests; scale with client connection count"),
            default_value=2,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=50),
            output_targets=[OutputTarget.ENV_VARS],
        )
    )

    registry.register(
        ParameterEntry(
            key="worker.replicas",
            classification=ParameterClassification.TOPOLOGY,
            description=("Number of Temporal internal worker replicas"),
            rationale=(
                "Internal workers handle system workflows"
                " (archival, replication); typically 2 is"
                " sufficient"
            ),
            default_value=2,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=10),
            output_targets=[OutputTarget.ENV_VARS],
        )
    )

    registry.register(
        ParameterEntry(
            key="matching.numTaskqueueReadPartitions",
            classification=ParameterClassification.TOPOLOGY,
            description=("Number of task queue read partitions for matching service"),
            rationale=(
                "More partitions increase task dispatch throughput but add overhead; scale with WPS"
            ),
            default_value=4,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=64),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="matching.numTaskqueueWritePartitions",
            classification=ParameterClassification.TOPOLOGY,
            description=("Number of task queue write partitions for matching service"),
            rationale=("Should match read partitions for balanced dispatch"),
            default_value=4,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=64),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.worker_count",
            classification=ParameterClassification.TOPOLOGY,
            description=("Number of SDK worker instances processing workflows and activities"),
            rationale=(
                "Worker count determines total polling capacity; scale with workflow throughput"
            ),
            default_value=4,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=200),
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    # =========================================================================
    # Safety Parameters — auto-derived, incorrect values cause failures
    # =========================================================================

    registry.register(
        ParameterEntry(
            key="persistence.maxConns",
            classification=ParameterClassification.SAFETY,
            description=("Maximum open database connections per service instance"),
            rationale=(
                "Pool size must be pre-warmed and stable;"
                " DSQL's 100 conn/sec rate limit means pool"
                " decay under load causes cascading failures"
            ),
            default_value=50,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.CONNECTIONS,
            constraints=ParameterConstraints(min_value=1, max_value=500),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="persistence.maxIdleConns",
            classification=ParameterClassification.SAFETY,
            description=("Maximum idle database connections per service instance"),
            rationale=(
                "MUST equal maxConns to prevent pool decay;"
                " Go's database/sql closes idle connections"
                " beyond this limit"
            ),
            default_value=50,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.CONNECTIONS,
            constraints=ParameterConstraints(min_value=1, max_value=500),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.max_conn_lifetime",
            classification=ParameterClassification.SAFETY,
            description=("Maximum lifetime of a database connection before replacement"),
            rationale=(
                "Must be under DSQL's 60-minute connection"
                " limit; 55m allows headroom for in-flight"
                " transactions"
            ),
            default_value="55m",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.MINUTES,
            output_targets=[OutputTarget.ENV_VARS],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.connection_timeout",
            classification=ParameterClassification.SAFETY,
            description=("Timeout for establishing a new database connection"),
            rationale=(
                "Prevents indefinite blocking on connection"
                " creation; must account for IAM token"
                " generation and TLS handshake"
            ),
            default_value="30s",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.SECONDS,
            output_targets=[OutputTarget.ENV_VARS],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.reservoir_enabled",
            classification=ParameterClassification.SAFETY,
            description=(
                "Enable connection reservoir for pre-creating connections off the request path"
            ),
            rationale=(
                "Reservoir avoids competing for DSQL's"
                " 100 conn/sec rate limit during request"
                " processing"
            ),
            default_value=True,
            value_type=ParameterValueType.BOOL,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.reservoir_target_ready",
            classification=ParameterClassification.SAFETY,
            description=("Target number of ready connections in the reservoir"),
            rationale=(
                "Should match maxConns so the reservoir always"
                " has connections available; prevents empty"
                " checkout events"
            ),
            default_value=50,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.CONNECTIONS,
            constraints=ParameterConstraints(min_value=1, max_value=500),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.reservoir_base_lifetime",
            classification=ParameterClassification.SAFETY,
            description=("Base lifetime for reservoir connections before proactive replacement"),
            rationale=(
                "11 minutes with 2m jitter gives 10-12m"
                " effective range, well under DSQL's 60m"
                " limit; short enough to rotate credentials"
                " regularly"
            ),
            default_value="11m",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.MINUTES,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.reservoir_lifetime_jitter",
            classification=ParameterClassification.SAFETY,
            description=(
                "Random jitter added to each connection's lifetime to prevent thundering herd"
            ),
            rationale=(
                "Without jitter, all connections expire"
                " simultaneously causing a burst of new"
                " connections that can exceed the rate limit"
            ),
            default_value="2m",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.MINUTES,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.reservoir_guard_window",
            classification=ParameterClassification.SAFETY,
            description=("Time before expiry when connections are considered too old to hand out"),
            rationale=(
                "Prevents handing out connections that might"
                " expire during a transaction; 45s covers the"
                " longest expected DSQL transaction"
            ),
            default_value="45s",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.SECONDS,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.reservoir_inflight_limit",
            classification=ParameterClassification.SAFETY,
            description=(
                "Maximum concurrent connection creation attempts in the reservoir refiller"
            ),
            rationale=(
                "Limits concurrent TCP/TLS handshakes to prevent pile-ups during burst refill"
            ),
            default_value=8,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=32),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.connection_rate_limit",
            classification=ParameterClassification.SAFETY,
            description=("Per-instance connection creation rate limit (connections per second)"),
            rationale=(
                "Partitions DSQL's cluster-wide 100 conn/sec"
                " budget across service instances to prevent"
                " rate limit errors"
            ),
            default_value=10,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=1, max_value=100),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.connection_burst_limit",
            classification=ParameterClassification.SAFETY,
            description=("Per-instance connection creation burst capacity"),
            rationale=(
                "Allows brief bursts during startup or"
                " connection replacement without exceeding"
                " sustained rate"
            ),
            default_value=100,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=1000),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.distributed_rate_limiter_enabled",
            classification=ParameterClassification.SAFETY,
            description=(
                "Enable DynamoDB-backed distributed rate limiting for multi-instance deployments"
            ),
            rationale=(
                "Coordinates connection rate across all"
                " instances to respect DSQL's cluster-wide"
                " 100 conn/sec limit"
            ),
            default_value=False,
            value_type=ParameterValueType.BOOL,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.distributed_rate_limiter_table",
            classification=ParameterClassification.SAFETY,
            description=("DynamoDB table name for distributed rate limiting"),
            rationale=(
                "Required when distributed rate limiting is"
                " enabled; table must exist with correct schema"
            ),
            default_value="",
            value_type=ParameterValueType.STR,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.token_bucket_enabled",
            classification=ParameterClassification.SAFETY,
            description=(
                "Use token bucket algorithm for distributed"
                " rate limiting (vs simple per-second counter)"
            ),
            rationale=(
                "Token bucket supports burst capacity matching"
                " DSQL's 1000-connection burst; recommended"
                " over simple counter"
            ),
            default_value=False,
            value_type=ParameterValueType.BOOL,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.token_bucket_rate",
            classification=ParameterClassification.SAFETY,
            description=("Token refill rate for distributed rate limiting (tokens per second)"),
            rationale=("Should match DSQL's sustained connection rate limit of 100 conn/sec"),
            default_value=100,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=1, max_value=1000),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.token_bucket_capacity",
            classification=ParameterClassification.SAFETY,
            description=("Maximum tokens in the distributed rate limiter bucket"),
            rationale=("Should match DSQL's burst capacity of 1000 connections"),
            default_value=1000,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=10000),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.slot_block_enabled",
            classification=ParameterClassification.SAFETY,
            description=("Enable DynamoDB-backed distributed connection leasing via slot blocks"),
            rationale=(
                "Coordinates global connection count against"
                " DSQL's 10,000 max connections limit"
                " across all services"
            ),
            default_value=False,
            value_type=ParameterValueType.BOOL,
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.slot_block_size",
            classification=ParameterClassification.SAFETY,
            description="Number of connection slots per block",
            rationale=(
                "100 slots per block with 100 blocks gives"
                " 10,000 total slots matching DSQL's"
                " connection limit"
            ),
            default_value=100,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=10, max_value=1000),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    registry.register(
        ParameterEntry(
            key="dsql.slot_block_count",
            classification=ParameterClassification.SAFETY,
            description=("Total number of slot blocks available for leasing"),
            rationale=(
                "100 blocks × 100 slots = 10,000 total connections matching DSQL's cluster limit"
            ),
            default_value=100,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=1000),
            output_targets=[OutputTarget.DSQL_PLUGIN],
        )
    )

    # =========================================================================
    # Tuning Parameters — never exposed, derived from SLO + Topology
    # =========================================================================

    registry.register(
        ParameterEntry(
            key="history.persistenceMaxQPS",
            classification=ParameterClassification.TUNING,
            description=("Maximum persistence operations per second for history service"),
            rationale=(
                "Derived from target state transitions; higher"
                " values allow more throughput but increase"
                " DSQL load"
            ),
            default_value=3000,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=100, max_value=20000),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="matching.persistenceMaxQPS",
            classification=ParameterClassification.TUNING,
            description=("Maximum persistence operations per second for matching service"),
            rationale=(
                "Derived from target throughput; matching persistence is lighter than history"
            ),
            default_value=3000,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=100, max_value=20000),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="frontend.persistenceMaxQPS",
            classification=ParameterClassification.TUNING,
            description=("Maximum persistence operations per second for frontend service"),
            rationale=("Frontend persistence is primarily for namespace and visibility operations"),
            default_value=3000,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=100, max_value=20000),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="matching.maxTaskBatchSize",
            classification=ParameterClassification.TUNING,
            description=("Maximum number of tasks returned in a single matching batch"),
            rationale=(
                "Larger batches reduce round-trips but"
                " increase per-request latency; tuned for"
                " DSQL transaction sizes"
            ),
            default_value=100,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=10, max_value=1000),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="matching.getTasksBatchSize",
            classification=ParameterClassification.TUNING,
            description=("Number of tasks fetched from persistence in a single query"),
            rationale=(
                "Controls persistence read amplification;"
                " larger values reduce queries but increase"
                " memory"
            ),
            default_value=1000,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=100, max_value=10000),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="matching.longPollExpirationInterval",
            classification=ParameterClassification.TUNING,
            description=("Duration before a long-poll request expires and is retried"),
            rationale=(
                "60s balances responsiveness with connection"
                " efficiency; shorter values increase polling"
                " overhead"
            ),
            default_value="60s",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.SECONDS,
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="history.timerProcessorMaxPollRPS",
            classification=ParameterClassification.TUNING,
            description=("Maximum rate for timer processor polling"),
            rationale=(
                "Controls timer processing throughput; higher"
                " values increase DSQL load from timer queries"
            ),
            default_value=20,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.PER_SEC,
            constraints=ParameterConstraints(min_value=1, max_value=200),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="history.timerProcessorUpdateAckInterval",
            classification=ParameterClassification.TUNING,
            description=("Interval between timer processor acknowledgment updates"),
            rationale=(
                "Controls how often timer progress is"
                " persisted; shorter intervals increase"
                " DSQL writes"
            ),
            default_value="30s",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.SECONDS,
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="system.enableActivityEagerExecution",
            classification=ParameterClassification.TUNING,
            description=(
                "Enable eager activity execution — activities"
                " dispatched back to the same worker inline"
            ),
            rationale=(
                "Reduces round-trips for simple activities;"
                " must be enabled server-side for SDK eager"
                " activities to work"
            ),
            default_value=True,
            value_type=ParameterValueType.BOOL,
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.max_concurrent_activities",
            classification=ParameterClassification.TUNING,
            description=("Maximum concurrent activity executions per worker"),
            rationale=("Derived from throughput target and worker count; prevents worker overload"),
            default_value=200,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=2000),
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.max_concurrent_workflow_tasks",
            classification=ParameterClassification.TUNING,
            description=("Maximum concurrent workflow task executions per worker"),
            rationale=(
                "Derived from throughput target; controls workflow task processing parallelism"
            ),
            default_value=200,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=2000),
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.max_concurrent_local_activities",
            classification=ParameterClassification.TUNING,
            description=("Maximum concurrent local activity executions per worker"),
            rationale=(
                "Local activities run in the workflow task"
                " thread; limit prevents workflow task"
                " starvation"
            ),
            default_value=200,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=2000),
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.workflow_task_pollers",
            classification=ParameterClassification.TUNING,
            description=("Number of concurrent workflow task pollers per worker"),
            rationale=(
                "More pollers increase workflow task throughput"
                " but consume more connections; scale with WPS"
            ),
            default_value=16,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=64),
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.activity_task_pollers",
            classification=ParameterClassification.TUNING,
            description=("Number of concurrent activity task pollers per worker"),
            rationale=(
                "Activity pollers fetch tasks from matching;"
                " fewer needed when eager activities"
                " are enabled"
            ),
            default_value=8,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=1, max_value=64),
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.sticky_schedule_to_start_timeout",
            classification=ParameterClassification.TUNING,
            description=(
                "Timeout for sticky workflow task"
                " schedule-to-start before falling back"
                " to non-sticky"
            ),
            rationale=(
                "Sticky execution caches workflow state on"
                " the worker; timeout controls fallback to"
                " any-worker dispatch"
            ),
            default_value="5s",
            value_type=ParameterValueType.DURATION,
            unit=ParameterUnit.SECONDS,
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    registry.register(
        ParameterEntry(
            key="sdk.disable_eager_activities",
            classification=ParameterClassification.TUNING,
            description=("Disable eager activity execution on the SDK worker"),
            rationale=(
                "When false (eager enabled), activities"
                " dispatch inline reducing latency; requires"
                " server-side enablement"
            ),
            default_value=False,
            value_type=ParameterValueType.BOOL,
            output_targets=[OutputTarget.WORKER_OPTIONS],
        )
    )

    registry.register(
        ParameterEntry(
            key="persistence.transactionSizeLimit",
            classification=ParameterClassification.TUNING,
            description=("Maximum transaction size in bytes for persistence operations"),
            rationale=(
                "DSQL has transaction size limits; 4MB accommodates large workflow histories"
            ),
            default_value=4000000,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.BYTES,
            constraints=ParameterConstraints(min_value=1000000, max_value=16000000),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    registry.register(
        ParameterEntry(
            key="history.maxBufferedQueryCount",
            classification=ParameterClassification.TUNING,
            description=("Maximum number of buffered queries per workflow execution"),
            rationale=(
                "Controls memory usage for query buffering; 1000 is sufficient for most workloads"
            ),
            default_value=1000,
            value_type=ParameterValueType.INT,
            unit=ParameterUnit.COUNT,
            constraints=ParameterConstraints(min_value=100, max_value=10000),
            output_targets=[OutputTarget.DYNAMIC_CONFIG],
        )
    )

    return registry
