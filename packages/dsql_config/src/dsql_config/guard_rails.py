"""Guard rail engine — validates configuration constraints before deployment.

Guard rails catch unsafe or contradictory configurations. Errors halt compilation;
warnings are included in the result but don't block artifact generation.
"""

from __future__ import annotations

from dsql_config.models import ConfigProfile, GuardRailResult


class GuardRailEngine:
    """Evaluates all guard rails against a resolved ConfigProfile."""

    def evaluate(self, profile: ConfigProfile) -> list[GuardRailResult]:
        results: list[GuardRailResult] = []
        for check in (
            self._check_max_idle_equals_max_conns,
            self._check_cluster_connection_limit,
            self._check_matching_partition_warning,
            self._check_sticky_warning,
            self._check_thundering_herd,
            self._check_reservoir_target_positive,
            self._check_distributed_rate_limiter_table,
        ):
            result = check(profile)
            if result:
                results.append(result)
        return results

    @staticmethod
    def _check_max_idle_equals_max_conns(profile: ConfigProfile) -> GuardRailResult | None:
        """Req 5.5: MaxIdleConns MUST equal MaxConns."""
        max_conns = profile.get_param("persistence.maxConns")
        max_idle = profile.get_param("persistence.maxIdleConns")
        if max_conns and max_idle and max_conns.value != max_idle.value:
            return GuardRailResult(
                rule_name="max_idle_equals_max_conns",
                severity="error",
                message=(
                    f"persistence.maxIdleConns ({max_idle.value}) must equal "
                    f"persistence.maxConns ({max_conns.value}). Pool decay causes "
                    f"rate limit pressure under load because Go's database/sql closes "
                    f"idle connections beyond MaxIdleConns."
                ),
                parameter_keys=["persistence.maxConns", "persistence.maxIdleConns"],
            )
        return None

    @staticmethod
    def _check_cluster_connection_limit(profile: ConfigProfile) -> GuardRailResult | None:
        """Req 5.1: Total reservoir_target across replicas must not exceed 10,000."""
        reservoir_target = profile.get_param("dsql.reservoir_target_ready")
        reservoir_enabled = profile.get_param("dsql.reservoir_enabled")

        if not reservoir_enabled or not reservoir_enabled.value:
            # Use maxConns when reservoir is disabled
            max_conns = profile.get_param("persistence.maxConns")
            pool_per_instance = int(max_conns.value) if max_conns else 50
        else:
            pool_per_instance = int(reservoir_target.value) if reservoir_target else 50

        # Sum replicas across all services
        total_replicas = 0
        for key in (
            "history.replicas",
            "matching.replicas",
            "frontend.replicas",
            "worker.replicas",
        ):
            p = profile.get_param(key)
            if p:
                total_replicas += int(p.value)

        total_connections = pool_per_instance * total_replicas
        if total_connections > 10_000:
            return GuardRailResult(
                rule_name="cluster_connection_limit",
                severity="error",
                message=(
                    f"Total estimated connections ({total_connections} = "
                    f"{pool_per_instance} per instance × {total_replicas} replicas) "
                    f"exceeds DSQL's 10,000 connection cluster limit."
                ),
                parameter_keys=["dsql.reservoir_target_ready", "persistence.maxConns"],
            )
        return None

    @staticmethod
    def _check_matching_partition_warning(profile: ConfigProfile) -> GuardRailResult | None:
        """Req 5.2: Warn if matching partitions exceed what throughput can utilize."""
        partitions = profile.get_param("matching.numTaskqueueReadPartitions")
        target_st = profile.get_param("target_state_transitions_per_sec")

        if partitions and target_st:
            # Heuristic: each partition can handle ~50 st/s efficiently
            useful_partitions = max(1, int(target_st.value) // 50)
            if int(partitions.value) > useful_partitions * 2:
                return GuardRailResult(
                    rule_name="matching_partition_oversized",
                    severity="warning",
                    message=(
                        f"matching.numTaskqueueReadPartitions ({partitions.value}) is high "
                        f"for target throughput ({target_st.value} st/s). Consider "
                        f"{useful_partitions} partitions to reduce overhead."
                    ),
                    parameter_keys=[
                        "matching.numTaskqueueReadPartitions",
                        "target_state_transitions_per_sec",
                    ],
                )
        return None

    @staticmethod
    def _check_sticky_warning(profile: ConfigProfile) -> GuardRailResult | None:
        """Req 5.3: Warn if sticky enabled but typical workflow runtime is very short."""
        sticky_timeout = profile.get_param("sdk.sticky_schedule_to_start_timeout")
        e2e_latency = profile.get_param("max_e2e_workflow_latency_ms")

        if (
            sticky_timeout
            and e2e_latency
            and int(e2e_latency.value) < 2000
            and str(sticky_timeout.value) != "0s"
        ):
            return GuardRailResult(
                rule_name="sticky_minimal_benefit",
                severity="warning",
                message=(
                    f"Sticky execution is enabled (timeout={sticky_timeout.value}) but "
                    f"max_e2e_workflow_latency_ms ({e2e_latency.value}ms) suggests "
                    f"workflows complete in under 2 seconds. Sticky caching provides "
                    f"minimal benefit for short-lived workflows."
                ),
                parameter_keys=[
                    "sdk.sticky_schedule_to_start_timeout",
                    "max_e2e_workflow_latency_ms",
                ],
            )
        return None

    @staticmethod
    def _check_thundering_herd(profile: ConfigProfile) -> GuardRailResult | None:
        """Req 5.4: Ensure jittered rotation when lifetime could cause thundering herd."""
        jitter = profile.get_param("dsql.reservoir_lifetime_jitter")
        reservoir_enabled = profile.get_param("dsql.reservoir_enabled")

        if (
            reservoir_enabled
            and reservoir_enabled.value
            and jitter
            and str(jitter.value) in ("0s", "0m", "0")
        ):
            return GuardRailResult(
                rule_name="thundering_herd_risk",
                severity="error",
                message=(
                    "dsql.reservoir_lifetime_jitter is zero while reservoir is enabled. "
                    "Without jitter, all connections expire simultaneously causing a "
                    "burst that can exceed DSQL's 100 conn/sec rate limit. "
                    "Set jitter to at least '1m'."
                ),
                parameter_keys=[
                    "dsql.reservoir_lifetime_jitter",
                    "dsql.reservoir_enabled",
                ],
            )
        return None

    @staticmethod
    def _check_reservoir_target_positive(profile: ConfigProfile) -> GuardRailResult | None:
        """Req 5.6: Reservoir target must be positive when reservoir is enabled."""
        reservoir_enabled = profile.get_param("dsql.reservoir_enabled")
        reservoir_target = profile.get_param("dsql.reservoir_target_ready")

        if (
            reservoir_enabled
            and reservoir_enabled.value
            and reservoir_target
            and int(reservoir_target.value) <= 0
        ):
            return GuardRailResult(
                rule_name="reservoir_target_zero",
                severity="error",
                message=(
                    "dsql.reservoir_target_ready is 0 but reservoir is enabled. "
                    "Reservoir target must be positive when reservoir is enabled."
                ),
                parameter_keys=[
                    "dsql.reservoir_target_ready",
                    "dsql.reservoir_enabled",
                ],
            )
        return None

    @staticmethod
    def _check_distributed_rate_limiter_table(profile: ConfigProfile) -> GuardRailResult | None:
        """Req 5.7: DynamoDB table name required when distributed rate limiting is enabled."""
        enabled = profile.get_param("dsql.distributed_rate_limiter_enabled")
        table = profile.get_param("dsql.distributed_rate_limiter_table")

        if enabled and enabled.value and (not table or not str(table.value).strip()):
            return GuardRailResult(
                rule_name="distributed_rate_limiter_table_missing",
                severity="error",
                message=(
                    "dsql.distributed_rate_limiter_enabled is true but "
                    "dsql.distributed_rate_limiter_table is not configured. "
                    "A DynamoDB table name is required for distributed "
                    "rate limiting."
                ),
                parameter_keys=[
                    "dsql.distributed_rate_limiter_enabled",
                    "dsql.distributed_rate_limiter_table",
                ],
            )
        return None
