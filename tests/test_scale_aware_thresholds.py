"""Unit tests for scale-aware thresholds.

Tests the motivating scenario, threshold profiles, hysteresis,
overrides, adapters, refinement, and bottleneck classifier.
"""

import pytest

from copilot.models import (
    FrontendSignals,
    HealthState,
    HistorySignals,
    MatchingSignals,
    PersistenceSignals,
    PollerSignals,
    PrimarySignals,
    ScaleBand,
    StateTransitionSignals,
    ThresholdOverrides,
    WorkflowCompletionSignals,
    classify_bottleneck,
    classify_scale_band,
    evaluate_health_state,
    get_threshold_profile,
    refine_thresholds,
)
from copilot.models.config import THRESHOLD_PROFILES

# =============================================================================
# HELPERS
# =============================================================================


def _make_healthy_signals(
    throughput: float = 42.5, persistence_p99: float = 15.0
) -> PrimarySignals:
    """Build healthy primary signals with configurable throughput and persistence latency."""
    return PrimarySignals(
        state_transitions=StateTransitionSignals(
            throughput_per_sec=throughput, latency_p95_ms=15.0, latency_p99_ms=25.0
        ),
        workflow_completion=WorkflowCompletionSignals(
            completion_rate=0.98, success_per_sec=throughput * 0.95, failed_per_sec=0.5
        ),
        history=HistorySignals(
            backlog_age_sec=2.0,
            task_processing_rate_per_sec=throughput * 2,
            shard_churn_rate_per_sec=0.0,
        ),
        frontend=FrontendSignals(error_rate_per_sec=0.0, latency_p95_ms=50.0, latency_p99_ms=120.0),
        matching=MatchingSignals(workflow_backlog_age_sec=0.5, activity_backlog_age_sec=1.0),
        poller=PollerSignals(
            poll_success_rate=0.95, poll_timeout_rate=0.05, long_poll_latency_ms=200.0
        ),
        persistence=PersistenceSignals(
            latency_p95_ms=persistence_p99 * 0.8,
            latency_p99_ms=persistence_p99,
            error_rate_per_sec=0.0,
            retry_rate_per_sec=0.0,
        ),
    )


# =============================================================================
# MOTIVATING SCENARIO
# =============================================================================


class TestMotivatingScenario:
    """The scenario that drove scale-aware thresholds:
    2 wf/s dev cluster with 367ms persistence p99 was incorrectly STRESSED.
    """

    def test_dev_cluster_with_high_persistence_latency_is_happy(self):
        """2 wf/s with 367ms persistence p99 should be HAPPY under starter band."""
        signals = _make_healthy_signals(throughput=4.0, persistence_p99=367.0)
        state, _, band = evaluate_health_state(
            signals,
            HealthState.HAPPY,
            consecutive_critical_count=0,
            current_scale_band=ScaleBand.STARTER,
        )
        assert state == HealthState.HAPPY
        assert band == ScaleBand.STARTER

    def test_same_scenario_was_stressed_under_old_defaults(self):
        """Under HIGH_THROUGHPUT (old defaults), 367ms p99 triggers STRESSED."""
        signals = _make_healthy_signals(throughput=4.0, persistence_p99=367.0)
        state, _, _ = evaluate_health_state(
            signals,
            HealthState.HAPPY,
            consecutive_critical_count=0,
            current_scale_band=ScaleBand.HIGH_THROUGHPUT,
        )
        assert state == HealthState.STRESSED


# =============================================================================
# THRESHOLD PROFILES
# =============================================================================


class TestThresholdProfiles:
    def test_starter_profile_relaxed_persistence(self):
        profile = THRESHOLD_PROFILES[ScaleBand.STARTER]
        assert profile.stressed.persistence_latency_p99_max_ms == 500.0

    def test_starter_profile_low_throughput_floor(self):
        profile = THRESHOLD_PROFILES[ScaleBand.STARTER]
        assert profile.critical.state_transitions_min_per_sec == 0.5
        assert profile.healthy.state_transitions_healthy_per_sec == 0.5

    def test_high_throughput_matches_production_defaults(self):
        """HIGH_THROUGHPUT profile uses the original production defaults."""
        profile = THRESHOLD_PROFILES[ScaleBand.HIGH_THROUGHPUT]
        assert profile.stressed.persistence_latency_p99_max_ms == 100.0
        assert profile.critical.state_transitions_min_per_sec == 5.0
        assert profile.healthy.state_transitions_healthy_per_sec == 10.0

    def test_mid_scale_intermediate_values(self):
        profile = THRESHOLD_PROFILES[ScaleBand.MID_SCALE]
        assert profile.stressed.persistence_latency_p99_max_ms == 200.0
        assert profile.critical.state_transitions_min_per_sec == 3.0


# =============================================================================
# HYSTERESIS
# =============================================================================


class TestHysteresis:
    def test_no_flap_at_50_boundary(self):
        """Oscillating 45-55 st/sec doesn't flap between STARTER and MID_SCALE."""
        band = ScaleBand.STARTER
        # At 56, should transition to MID_SCALE (above 50 * 1.1 = ~55)
        band = classify_scale_band(56.0, band)
        assert band == ScaleBand.MID_SCALE

        # At 48, should stay MID_SCALE (above 50 * 0.9 = 45)
        band = classify_scale_band(48.0, band)
        assert band == ScaleBand.MID_SCALE

        # At 44, should drop back to STARTER (below 45)
        band = classify_scale_band(44.0, band)
        assert band == ScaleBand.STARTER

    def test_no_flap_at_500_boundary(self):
        """Oscillating 450-550 st/sec doesn't flap between MID_SCALE and HIGH_THROUGHPUT."""
        band = ScaleBand.MID_SCALE
        # At 551, should transition (above 500 * 1.1 = ~550)
        band = classify_scale_band(551.0, band)
        assert band == ScaleBand.HIGH_THROUGHPUT

        # At 480, should stay HIGH_THROUGHPUT (above 500 * 0.9 = 450)
        band = classify_scale_band(480.0, band)
        assert band == ScaleBand.HIGH_THROUGHPUT

        # At 449, should drop back
        band = classify_scale_band(449.0, band)
        assert band == ScaleBand.MID_SCALE


# =============================================================================
# OVERRIDES
# =============================================================================


class TestOverrides:
    def test_valid_override_applied(self):
        profile = get_threshold_profile(
            ScaleBand.STARTER,
            overrides=ThresholdOverrides(persistence_latency_p99_max_ms=300.0),
        )
        assert profile.stressed.persistence_latency_p99_max_ms == 300.0

    def test_invalid_override_raises_value_error(self):
        """Override that violates ordering invariant raises ValueError."""
        with pytest.raises(ValueError, match="must be"):
            get_threshold_profile(
                ScaleBand.STARTER,
                overrides=ThresholdOverrides(
                    state_transitions_min_per_sec=10.0,
                    state_transitions_healthy_per_sec=5.0,
                ),
            )


# =============================================================================
# ADAPTERS
# =============================================================================


class TestAdapters:
    def test_compose_adapter_fixed_replicas(self):
        from dsql_config.adapters.compose import ComposeDeploymentAdapter
        from dsql_config.models import ConfigProfile

        adapter = ComposeDeploymentAdapter()
        profile = ConfigProfile(
            preset_name="starter",
            slo_params=[],
            topology_params=[],
            safety_params=[],
            tuning_params=[],
            temporal_server_version="1.26.0",
            dsql_plugin_version="0.1.0",
            compiled_at="2026-02-20T10:00:00Z",
            compiler_version="0.1.0",
        )
        result = adapter.render_deployment(
            profile=profile,
            annotations={
                "compose_project_name": "temporal-dev",
                "dsql_endpoint": "test.dsql.eu-west-1.on.aws",
            },
        )
        assert result.scaling_topology.history.min_replicas == 1
        assert result.scaling_topology.history.max_replicas == 1
        from copilot_core.deployment import AutoscalerType

        assert result.scaling_topology.autoscaler_type == AutoscalerType.FIXED

    def test_ecs_adapter_populates_resource_identity(self):
        from dsql_config.adapters.ecs import ECSDeploymentAdapter
        from dsql_config.models import ConfigProfile

        adapter = ECSDeploymentAdapter()
        profile = ConfigProfile(
            preset_name="mid-scale",
            slo_params=[],
            topology_params=[],
            safety_params=[],
            tuning_params=[],
            temporal_server_version="1.26.0",
            dsql_plugin_version="0.1.0",
            compiled_at="2026-02-20T10:00:00Z",
            compiler_version="0.1.0",
        )
        result = adapter.render_deployment(
            profile=profile,
            annotations={
                "ecs_cluster_arn": "arn:aws:ecs:eu-west-1:123:cluster/temporal",
                "dsql_endpoint": "test.dsql.eu-west-1.on.aws",
                "amp_workspace_id": "ws-abc",
            },
        )
        assert result.resource_identity.platform_type == "ecs"
        assert result.resource_identity.dsql_endpoint == "test.dsql.eu-west-1.on.aws"


# =============================================================================
# REFINEMENT
# =============================================================================


class TestRefinement:
    def test_more_replicas_tighter_thresholds(self):
        """More History replicas than default → tighter persistence latency threshold."""
        from copilot_core.deployment import DeploymentContext, ServiceReplicaState

        ctx = DeploymentContext(
            history=ServiceReplicaState(running=12, desired=12),
            matching=ServiceReplicaState(running=4, desired=4),
            frontend=ServiceReplicaState(running=3, desired=3),
            worker=ServiceReplicaState(running=2, desired=2),
            timestamp="2026-02-20T10:00:00Z",
        )
        profile = get_threshold_profile(ScaleBand.MID_SCALE)
        original_latency = profile.stressed.persistence_latency_p99_max_ms
        refined = refine_thresholds(profile, ctx)
        # More replicas → tighter (lower) latency threshold
        assert refined.stressed.persistence_latency_p99_max_ms <= original_latency

    def test_fewer_replicas_looser_thresholds(self):
        """Fewer History replicas than default → looser persistence latency threshold."""
        from copilot_core.deployment import DeploymentContext, ServiceReplicaState

        ctx = DeploymentContext(
            history=ServiceReplicaState(running=3, desired=3),
            matching=ServiceReplicaState(running=2, desired=2),
            frontend=ServiceReplicaState(running=1, desired=1),
            worker=ServiceReplicaState(running=1, desired=1),
            timestamp="2026-02-20T10:00:00Z",
        )
        profile = get_threshold_profile(ScaleBand.MID_SCALE)
        original_latency = profile.stressed.persistence_latency_p99_max_ms
        refined = refine_thresholds(profile, ctx)
        # Fewer replicas → looser (higher) latency threshold
        assert refined.stressed.persistence_latency_p99_max_ms >= original_latency

    def test_grace_period_during_active_scaling(self):
        """Refinement skips tightening when autoscaler is actively scaling."""
        from copilot_core.deployment import (
            AutoscalerState,
            DeploymentContext,
            ServiceReplicaState,
        )

        ctx = DeploymentContext(
            history=ServiceReplicaState(running=12, desired=12),
            matching=ServiceReplicaState(running=4, desired=4),
            frontend=ServiceReplicaState(running=3, desired=3),
            worker=ServiceReplicaState(running=2, desired=2),
            autoscaler=AutoscalerState(
                min_capacity=6, max_capacity=12, desired_capacity=12, actively_scaling=True
            ),
            timestamp="2026-02-20T10:00:00Z",
        )
        profile = get_threshold_profile(ScaleBand.MID_SCALE)
        refined = refine_thresholds(profile, ctx)
        # During active scaling, thresholds should not be tightened
        assert (
            refined.stressed.persistence_latency_p99_max_ms
            == profile.stressed.persistence_latency_p99_max_ms
        )


# =============================================================================
# CONSECUTIVE CRITICAL COUNT
# =============================================================================


class TestConsecutiveCriticalCount:
    def test_preserved_across_scale_band_change(self):
        """consecutive_critical_count is preserved when scale band changes
        and signals remain critical."""
        # Signals that are critical: very low throughput, high backlog
        signals = _make_healthy_signals(throughput=60.0)
        # Make it critical under MID_SCALE: throughput below critical floor (3.0)
        signals.state_transitions.throughput_per_sec = 60.0  # Triggers MID_SCALE band
        signals.history.backlog_age_sec = 400.0  # Above MID_SCALE critical (300s)
        state, count, band = evaluate_health_state(
            signals,
            HealthState.STRESSED,
            consecutive_critical_count=2,
            current_scale_band=ScaleBand.STARTER,
        )
        # Band should change to MID_SCALE
        assert band == ScaleBand.MID_SCALE
        # Count should be incremented (was 2, now 3)
        assert count == 3


# =============================================================================
# BOTTLENECK CLASSIFIER
# =============================================================================


class TestBottleneckClassifier:
    def test_starter_band_relaxed_thresholds(self):
        """Bottleneck classifier uses relaxed thresholds under starter band."""
        from copilot.models import BottleneckClassification, WorkerSignals

        # Persistence p95 at 150ms — stressed under HIGH_THROUGHPUT but not STARTER
        signals = _make_healthy_signals(throughput=5.0, persistence_p99=150.0)
        signals.persistence.latency_p95_ms = 150.0
        worker = WorkerSignals(
            wft_schedule_to_start_p95_ms=10.0,
            wft_schedule_to_start_p99_ms=20.0,
            activity_schedule_to_start_p95_ms=10.0,
            activity_schedule_to_start_p99_ms=20.0,
            workflow_slots_available=100,
            workflow_slots_used=10,
            activity_slots_available=100,
            activity_slots_used=10,
            workflow_pollers=8,
            activity_pollers=8,
        )
        result = classify_bottleneck(signals, worker, scale_band=ScaleBand.STARTER)
        assert result == BottleneckClassification.HEALTHY
