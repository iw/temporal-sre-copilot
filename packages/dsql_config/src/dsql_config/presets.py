"""Scale presets for Temporal DSQL deployments.

Each preset defines SLO defaults, topology defaults, and derivation rules
for safety and tuning parameters. Presets are the primary input to the
Config Compiler — an adopter picks a preset and optionally overrides
specific topology parameters.
"""

from copilot_core.models import TelemetryBound
from dsql_config.models import (
    DerivationRule,
    PresetDefault,
    ScalePreset,
    ThroughputRange,
)

STARTER = ScalePreset(
    name="starter",
    description="Low-throughput deployment for development, testing, or light production workloads",
    throughput_range=ThroughputRange(
        min_st_per_sec=0,
        max_st_per_sec=50,
        description="Under 50 state transitions per second",
    ),
    slo_defaults=[
        PresetDefault(key="target_state_transitions_per_sec", value=25),
        PresetDefault(key="target_workflow_completion_rate", value=25),
        PresetDefault(key="max_schedule_to_start_latency_ms", value=500),
        PresetDefault(key="max_e2e_workflow_latency_ms", value=1000),
    ],
    topology_defaults=[
        PresetDefault(key="history.shards", value=512),
        PresetDefault(key="history.replicas", value=2),
        PresetDefault(key="matching.replicas", value=2),
        PresetDefault(key="frontend.replicas", value=2),
        PresetDefault(key="worker.replicas", value=1),
        PresetDefault(key="matching.numTaskqueueReadPartitions", value=4),
        PresetDefault(key="matching.numTaskqueueWritePartitions", value=4),
        PresetDefault(key="sdk.worker_count", value=2),
    ],
    safety_derivations=[
        DerivationRule(
            key="persistence.maxConns",
            expression="10",
            depends_on=[],
        ),
        DerivationRule(
            key="persistence.maxIdleConns",
            expression="persistence.maxConns",
            depends_on=["persistence.maxConns"],
        ),
        DerivationRule(
            key="dsql.max_conn_lifetime",
            expression="'55m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_timeout",
            expression="'30s'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_enabled",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_target_ready",
            expression="10",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_base_lifetime",
            expression="'11m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_lifetime_jitter",
            expression="'2m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_guard_window",
            expression="'45s'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_inflight_limit",
            expression="4",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_rate_limit",
            expression="10",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_burst_limit",
            expression="50",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.distributed_rate_limiter_enabled",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.distributed_rate_limiter_table",
            expression="''",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_enabled",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_rate",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_capacity",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_enabled",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_size",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_count",
            expression="100",
            depends_on=[],
        ),
    ],
    tuning_derivations=[
        DerivationRule(
            key="history.persistenceMaxQPS",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.persistenceMaxQPS",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="frontend.persistenceMaxQPS",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.maxTaskBatchSize",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.getTasksBatchSize",
            expression="500",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.longPollExpirationInterval",
            expression="'60s'",
            depends_on=[],
        ),
        DerivationRule(
            key="history.timerProcessorMaxPollRPS",
            expression="10",
            depends_on=[],
        ),
        DerivationRule(
            key="history.timerProcessorUpdateAckInterval",
            expression="'30s'",
            depends_on=[],
        ),
        DerivationRule(
            key="system.enableActivityEagerExecution",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_activities",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_workflow_tasks",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_local_activities",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.workflow_task_pollers",
            expression="8",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.activity_task_pollers",
            expression="4",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.sticky_schedule_to_start_timeout",
            expression="'5s'",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.disable_eager_activities",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="persistence.transactionSizeLimit",
            expression="4000000",
            depends_on=[],
        ),
        DerivationRule(
            key="history.maxBufferedQueryCount",
            expression="1000",
            depends_on=[],
        ),
    ],
    expected_bounds=[
        TelemetryBound(metric="state_transitions_per_sec", lower=0, upper=50),
        TelemetryBound(metric="workflow_schedule_to_start_p99", lower=0, upper=500),
    ],
)


MID_SCALE = ScalePreset(
    name="mid-scale",
    description=(
        "Moderate-throughput deployment for production workloads with balanced resource allocation"
    ),
    throughput_range=ThroughputRange(
        min_st_per_sec=50,
        max_st_per_sec=500,
        description="50 to 500 state transitions per second",
    ),
    slo_defaults=[
        PresetDefault(key="target_state_transitions_per_sec", value=150),
        PresetDefault(key="target_workflow_completion_rate", value=150),
        PresetDefault(key="max_schedule_to_start_latency_ms", value=200),
        PresetDefault(key="max_e2e_workflow_latency_ms", value=500),
    ],
    topology_defaults=[
        PresetDefault(key="history.shards", value=512),
        PresetDefault(key="history.replicas", value=6),
        PresetDefault(key="matching.replicas", value=4),
        PresetDefault(key="frontend.replicas", value=3),
        PresetDefault(key="worker.replicas", value=2),
        PresetDefault(key="matching.numTaskqueueReadPartitions", value=8),
        PresetDefault(key="matching.numTaskqueueWritePartitions", value=8),
        PresetDefault(key="sdk.worker_count", value=8),
    ],
    safety_derivations=[
        DerivationRule(
            key="persistence.maxConns",
            expression="50",
            depends_on=[],
        ),
        DerivationRule(
            key="persistence.maxIdleConns",
            expression="persistence.maxConns",
            depends_on=["persistence.maxConns"],
        ),
        DerivationRule(
            key="dsql.max_conn_lifetime",
            expression="'55m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_timeout",
            expression="'30s'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_enabled",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_target_ready",
            expression="50",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_base_lifetime",
            expression="'11m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_lifetime_jitter",
            expression="'2m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_guard_window",
            expression="'45s'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_inflight_limit",
            expression="8",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_rate_limit",
            expression="10",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_burst_limit",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.distributed_rate_limiter_enabled",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.distributed_rate_limiter_table",
            expression="''",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_enabled",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_rate",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_capacity",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_enabled",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_size",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_count",
            expression="100",
            depends_on=[],
        ),
    ],
    tuning_derivations=[
        DerivationRule(
            key="history.persistenceMaxQPS",
            expression="6000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.persistenceMaxQPS",
            expression="6000",
            depends_on=[],
        ),
        DerivationRule(
            key="frontend.persistenceMaxQPS",
            expression="6000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.maxTaskBatchSize",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.getTasksBatchSize",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.longPollExpirationInterval",
            expression="'60s'",
            depends_on=[],
        ),
        DerivationRule(
            key="history.timerProcessorMaxPollRPS",
            expression="20",
            depends_on=[],
        ),
        DerivationRule(
            key="history.timerProcessorUpdateAckInterval",
            expression="'30s'",
            depends_on=[],
        ),
        DerivationRule(
            key="system.enableActivityEagerExecution",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_activities",
            expression="200",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_workflow_tasks",
            expression="200",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_local_activities",
            expression="200",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.workflow_task_pollers",
            expression="16",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.activity_task_pollers",
            expression="8",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.sticky_schedule_to_start_timeout",
            expression="'5s'",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.disable_eager_activities",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="persistence.transactionSizeLimit",
            expression="4000000",
            depends_on=[],
        ),
        DerivationRule(
            key="history.maxBufferedQueryCount",
            expression="1000",
            depends_on=[],
        ),
    ],
    expected_bounds=[
        TelemetryBound(metric="state_transitions_per_sec", lower=50, upper=500),
        TelemetryBound(metric="workflow_schedule_to_start_p99", lower=0, upper=200),
    ],
)


HIGH_THROUGHPUT = ScalePreset(
    name="high-throughput",
    description=(
        "High-throughput deployment with aggressive resource"
        " allocation and full DSQL plugin features"
    ),
    throughput_range=ThroughputRange(
        min_st_per_sec=500,
        max_st_per_sec=None,
        description="Over 500 state transitions per second",
    ),
    slo_defaults=[
        PresetDefault(key="target_state_transitions_per_sec", value=1000),
        PresetDefault(key="target_workflow_completion_rate", value=1000),
        PresetDefault(key="max_schedule_to_start_latency_ms", value=100),
        PresetDefault(key="max_e2e_workflow_latency_ms", value=300),
    ],
    topology_defaults=[
        PresetDefault(key="history.shards", value=4096),
        PresetDefault(key="history.replicas", value=8),
        PresetDefault(key="matching.replicas", value=6),
        PresetDefault(key="frontend.replicas", value=4),
        PresetDefault(key="worker.replicas", value=2),
        PresetDefault(key="matching.numTaskqueueReadPartitions", value=16),
        PresetDefault(key="matching.numTaskqueueWritePartitions", value=16),
        PresetDefault(key="sdk.worker_count", value=16),
    ],
    safety_derivations=[
        DerivationRule(
            key="persistence.maxConns",
            expression="50",
            depends_on=[],
        ),
        DerivationRule(
            key="persistence.maxIdleConns",
            expression="persistence.maxConns",
            depends_on=["persistence.maxConns"],
        ),
        DerivationRule(
            key="dsql.max_conn_lifetime",
            expression="'55m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_timeout",
            expression="'30s'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_enabled",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_target_ready",
            expression="50",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_base_lifetime",
            expression="'11m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_lifetime_jitter",
            expression="'2m'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_guard_window",
            expression="'45s'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.reservoir_inflight_limit",
            expression="8",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_rate_limit",
            expression="8",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.connection_burst_limit",
            expression="40",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.distributed_rate_limiter_enabled",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.distributed_rate_limiter_table",
            expression="'temporal-dsql-rate-limiter'",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_enabled",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_rate",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.token_bucket_capacity",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_enabled",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_size",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="dsql.slot_block_count",
            expression="100",
            depends_on=[],
        ),
    ],
    tuning_derivations=[
        DerivationRule(
            key="history.persistenceMaxQPS",
            expression="10000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.persistenceMaxQPS",
            expression="10000",
            depends_on=[],
        ),
        DerivationRule(
            key="frontend.persistenceMaxQPS",
            expression="10000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.maxTaskBatchSize",
            expression="100",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.getTasksBatchSize",
            expression="1000",
            depends_on=[],
        ),
        DerivationRule(
            key="matching.longPollExpirationInterval",
            expression="'60s'",
            depends_on=[],
        ),
        DerivationRule(
            key="history.timerProcessorMaxPollRPS",
            expression="40",
            depends_on=[],
        ),
        DerivationRule(
            key="history.timerProcessorUpdateAckInterval",
            expression="'15s'",
            depends_on=[],
        ),
        DerivationRule(
            key="system.enableActivityEagerExecution",
            expression="True",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_activities",
            expression="200",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_workflow_tasks",
            expression="200",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.max_concurrent_local_activities",
            expression="200",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.workflow_task_pollers",
            expression="32",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.activity_task_pollers",
            expression="8",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.sticky_schedule_to_start_timeout",
            expression="'5s'",
            depends_on=[],
        ),
        DerivationRule(
            key="sdk.disable_eager_activities",
            expression="False",
            depends_on=[],
        ),
        DerivationRule(
            key="persistence.transactionSizeLimit",
            expression="4000000",
            depends_on=[],
        ),
        DerivationRule(
            key="history.maxBufferedQueryCount",
            expression="1000",
            depends_on=[],
        ),
    ],
    expected_bounds=[
        TelemetryBound(metric="state_transitions_per_sec", lower=500, upper=10000),
        TelemetryBound(metric="workflow_schedule_to_start_p99", lower=0, upper=100),
    ],
)


# Preset registry for lookup by name
PRESETS: dict[str, ScalePreset] = {
    "starter": STARTER,
    "mid-scale": MID_SCALE,
    "high-throughput": HIGH_THROUGHPUT,
}


def get_preset(name: str) -> ScalePreset | None:
    """Look up a scale preset by name."""
    return PRESETS.get(name)


def list_preset_names() -> list[str]:
    """Return all available preset names."""
    return list(PRESETS.keys())
