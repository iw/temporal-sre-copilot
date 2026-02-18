"""Unit tests for scale presets and workload modifiers.

Validates: Requirements 2.5, 2.6, 2.7, 3.2, 3.3, 3.4, 3.5
"""

from dsql_config.modifiers import MODIFIERS, get_modifier
from dsql_config.presets import HIGH_THROUGHPUT, MID_SCALE, PRESETS, STARTER


def _get_default(preset, key):
    for d in preset.slo_defaults + preset.topology_defaults:
        if d.key == key:
            return d.value
    return None


def _get_safety(preset, key):
    for d in preset.safety_derivations:
        if d.key == key:
            return d.expression
    return None


class TestStarterPreset:
    def test_reservoir_disabled(self):
        assert _get_safety(STARTER, "dsql.reservoir_enabled") == "False"

    def test_pool_size(self):
        assert _get_safety(STARTER, "persistence.maxConns") == "10"

    def test_no_distributed_rate_limiting(self):
        assert _get_safety(STARTER, "dsql.distributed_rate_limiter_enabled") == "False"

    def test_low_replicas(self):
        assert _get_default(STARTER, "history.replicas") == 2


class TestMidScalePreset:
    def test_reservoir_enabled(self):
        assert _get_safety(MID_SCALE, "dsql.reservoir_enabled") == "True"

    def test_pool_size(self):
        assert _get_safety(MID_SCALE, "persistence.maxConns") == "50"

    def test_higher_replicas(self):
        assert _get_default(MID_SCALE, "history.replicas") == 6


class TestHighThroughputPreset:
    def test_reservoir_enabled(self):
        assert _get_safety(HIGH_THROUGHPUT, "dsql.reservoir_enabled") == "True"

    def test_distributed_rate_limiting(self):
        assert _get_safety(HIGH_THROUGHPUT, "dsql.distributed_rate_limiter_enabled") == "True"

    def test_high_replicas(self):
        assert _get_default(HIGH_THROUGHPUT, "history.replicas") == 8

    def test_high_shards(self):
        assert _get_default(HIGH_THROUGHPUT, "history.shards") == 4096


class TestModifiers:
    def test_simple_crud_enables_eager(self):
        m = get_modifier("simple-crud")
        assert m is not None
        assert m.adjustments["system.enableActivityEagerExecution"] is True

    def test_batch_processor_high_activity_concurrency(self):
        m = get_modifier("batch-processor")
        assert m is not None
        assert m.adjustments["sdk.max_concurrent_activities"] == 500

    def test_long_running_sticky_timeout(self):
        m = get_modifier("long-running")
        assert m is not None
        assert m.adjustments["sdk.sticky_schedule_to_start_timeout"] == "10s"

    def test_orchestrator_balanced_partitions(self):
        m = get_modifier("orchestrator")
        assert m is not None
        assert m.adjustments["matching.numTaskqueueReadPartitions"] == 8

    def test_all_presets_registered(self):
        assert set(PRESETS.keys()) == {"starter", "mid-scale", "high-throughput"}

    def test_all_modifiers_registered(self):
        assert set(MODIFIERS.keys()) == {
            "simple-crud",
            "orchestrator",
            "batch-processor",
            "long-running",
        }
