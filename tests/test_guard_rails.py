"""Unit tests for guard rail edge cases.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

from copilot_core.types import ParameterOverrides
from dsql_config.compiler import ConfigCompiler
from dsql_config.guard_rails import GuardRailEngine
from dsql_config.registry import build_default_registry


def _compile(preset, **overrides):
    registry = build_default_registry()
    compiler = ConfigCompiler(registry)
    result = compiler.compile(
        preset,
        overrides=ParameterOverrides(values=overrides) if overrides else None,
    )
    return result.profile


def _evaluate(profile):
    return GuardRailEngine().evaluate(profile)


def _has_rule(results, rule_name, severity=None):
    return any(
        r.rule_name == rule_name and (severity is None or r.severity == severity) for r in results
    )


class TestConnectionLimit:
    """Req 5.1: Total connections must not exceed 10,000."""

    def test_normal_config_passes(self):
        profile = _compile("starter")
        results = _evaluate(profile)
        assert not _has_rule(results, "cluster_connection_limit")

    def test_excessive_connections_triggers_error(self):
        # High-throughput uses reservoir; set target high to exceed cluster limit
        profile = _compile("high-throughput")
        for p in profile.safety_params:
            if p.key == "dsql.reservoir_target_ready":
                p.value = 600  # 600 × (8+6+4+2) = 12,000 > 10,000
        results = _evaluate(profile)
        assert _has_rule(results, "cluster_connection_limit", "error")


class TestMatchingPartitionWarning:
    """Req 5.2: Warn if partitions exceed useful count for throughput."""

    def test_oversized_partitions_warns(self):
        # Starter has 25 st/s target, 4 partitions is already high
        # Override to 64 partitions — way too many for 25 st/s
        profile = _compile("starter", **{"matching.numTaskqueueReadPartitions": 64})
        results = _evaluate(profile)
        assert _has_rule(results, "matching_partition_oversized", "warning")

    def test_appropriate_partitions_no_warning(self):
        # High-throughput has 500 st/s target, useful_partitions = 500//50 = 10
        # Default partitions (8) is within 10*2 = 20, so no warning
        profile = _compile("high-throughput")
        results = _evaluate(profile)
        assert not _has_rule(results, "matching_partition_oversized")


class TestStickyWarning:
    """Req 5.3: Warn if sticky enabled for very short workflows."""

    def test_short_workflow_sticky_warns(self):
        # Starter has max_e2e_workflow_latency_ms=1000 (< 2000)
        profile = _compile("starter")
        results = _evaluate(profile)
        assert _has_rule(results, "sticky_minimal_benefit", "warning")


class TestThunderingHerd:
    """Req 5.4: Error if jitter is zero with reservoir enabled."""

    def test_zero_jitter_with_reservoir_errors(self):
        profile = _compile("mid-scale")
        for p in profile.safety_params:
            if p.key == "dsql.reservoir_lifetime_jitter":
                p.value = "0s"
        results = _evaluate(profile)
        assert _has_rule(results, "thundering_herd_risk", "error")

    def test_nonzero_jitter_passes(self):
        profile = _compile("mid-scale")
        results = _evaluate(profile)
        assert not _has_rule(results, "thundering_herd_risk")


class TestMaxIdleEqualsMaxConns:
    """Req 5.5: MaxIdleConns MUST equal MaxConns."""

    def test_mismatch_errors(self):
        profile = _compile("starter")
        for p in profile.safety_params:
            if p.key == "persistence.maxIdleConns":
                p.value = 1  # Break invariant
        results = _evaluate(profile)
        assert _has_rule(results, "max_idle_equals_max_conns", "error")

    def test_match_passes(self):
        profile = _compile("starter")
        results = _evaluate(profile)
        assert not _has_rule(results, "max_idle_equals_max_conns")


class TestReservoirTarget:
    """Req 5.6: Reservoir target must be positive when enabled."""

    def test_zero_target_with_reservoir_errors(self):
        profile = _compile("mid-scale")
        for p in profile.safety_params:
            if p.key == "dsql.reservoir_target_ready":
                p.value = 0
        results = _evaluate(profile)
        assert _has_rule(results, "reservoir_target_zero", "error")


class TestDistributedRateLimiterTable:
    """Req 5.7: Table name required when distributed rate limiting enabled."""

    def test_missing_table_errors(self):
        profile = _compile("high-throughput")
        for p in profile.safety_params:
            if p.key == "dsql.distributed_rate_limiter_table":
                p.value = ""
        results = _evaluate(profile)
        assert _has_rule(results, "distributed_rate_limiter_table_missing", "error")

    def test_table_present_passes(self):
        profile = _compile("high-throughput")
        results = _evaluate(profile)
        assert not _has_rule(results, "distributed_rate_limiter_table_missing")
