"""Property-based tests for Behaviour Profiles.

Properties 13-18 from the design document.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from behaviour_profiles.comparison import compare_profiles
from behaviour_profiles.models import (
    BehaviourProfile,
    ConfigSnapshot,
    DSQLPluginSnapshot,
    DynamicConfigEntry,
    EnvVarEntry,
    TelemetrySummary,
    WorkerOptionsSnapshot,
)
from copilot_core.models import MetricAggregate, ServiceMetrics

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def metric_aggregates(draw: st.DrawFn) -> MetricAggregate:
    """Generate a MetricAggregate with valid statistical ordering."""
    min_val = draw(st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False))
    p50 = draw(
        st.floats(min_value=min_val, max_value=min_val + 100, allow_nan=False, allow_infinity=False)
    )
    mean = draw(
        st.floats(min_value=p50, max_value=p50 + 100, allow_nan=False, allow_infinity=False)
    )
    p95 = draw(
        st.floats(min_value=mean, max_value=mean + 100, allow_nan=False, allow_infinity=False)
    )
    p99 = draw(st.floats(min_value=p95, max_value=p95 + 100, allow_nan=False, allow_infinity=False))
    max_val = draw(
        st.floats(min_value=p99, max_value=p99 + 100, allow_nan=False, allow_infinity=False)
    )
    return MetricAggregate(min=min_val, max=max_val, mean=mean, p50=p50, p95=p95, p99=p99)


@st.composite
def service_metrics(draw: st.DrawFn) -> ServiceMetrics:
    return ServiceMetrics(
        history=draw(metric_aggregates()),
        matching=draw(metric_aggregates()),
        frontend=draw(metric_aggregates()),
        worker=draw(metric_aggregates()),
    )


@st.composite
def telemetry_summaries(draw: st.DrawFn) -> TelemetrySummary:
    from behaviour_profiles.models import (
        DSQLPoolMetrics,
        ErrorMetrics,
        LatencyMetrics,
        MatchingMetrics,
        ResourceMetrics,
        ThroughputMetrics,
    )

    return TelemetrySummary(
        throughput=ThroughputMetrics(
            workflows_started_per_sec=draw(metric_aggregates()),
            workflows_completed_per_sec=draw(metric_aggregates()),
            state_transitions_per_sec=draw(metric_aggregates()),
        ),
        latency=LatencyMetrics(
            workflow_schedule_to_start_p95=draw(metric_aggregates()),
            workflow_schedule_to_start_p99=draw(metric_aggregates()),
            activity_schedule_to_start_p95=draw(metric_aggregates()),
            activity_schedule_to_start_p99=draw(metric_aggregates()),
            persistence_latency_p95=draw(metric_aggregates()),
            persistence_latency_p99=draw(metric_aggregates()),
        ),
        matching=MatchingMetrics(
            sync_match_rate=draw(metric_aggregates()),
            async_match_rate=draw(metric_aggregates()),
            task_dispatch_latency=draw(metric_aggregates()),
            backlog_count=draw(metric_aggregates()),
            backlog_age=draw(metric_aggregates()),
        ),
        dsql_pool=DSQLPoolMetrics(
            pool_open_count=draw(metric_aggregates()),
            pool_in_use_count=draw(metric_aggregates()),
            pool_idle_count=draw(metric_aggregates()),
            reservoir_size=draw(metric_aggregates()),
            reservoir_empty_events=draw(metric_aggregates()),
            open_failures=draw(metric_aggregates()),
            reconnect_count=draw(metric_aggregates()),
        ),
        errors=ErrorMetrics(
            occ_conflicts_per_sec=draw(metric_aggregates()),
            exhausted_retries_per_sec=draw(metric_aggregates()),
            dsql_auth_failures=draw(metric_aggregates()),
        ),
        resources=ResourceMetrics(
            cpu_utilization=draw(service_metrics()),
            memory_utilization=draw(service_metrics()),
            worker_task_slot_utilization=draw(metric_aggregates()),
        ),
    )


def _make_dsql_snapshot() -> DSQLPluginSnapshot:
    return DSQLPluginSnapshot(
        reservoir_enabled=True,
        reservoir_target_ready=50,
        reservoir_base_lifetime_min=11.0,
        reservoir_lifetime_jitter_min=2.0,
        reservoir_guard_window_sec=45.0,
        max_conns=50,
        max_idle_conns=50,
        max_conn_lifetime_min=55.0,
        distributed_rate_limiter_enabled=False,
        token_bucket_enabled=False,
        slot_block_enabled=False,
    )


@st.composite
def behaviour_profiles(draw: st.DrawFn) -> BehaviourProfile:
    """Generate a valid BehaviourProfile with realistic data."""
    telemetry = draw(telemetry_summaries())
    profile_id = draw(st.uuids().map(str))
    name = draw(st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N"))))

    return BehaviourProfile(
        id=profile_id,
        name=name,
        cluster_id="cluster-001",
        time_window_start="2026-01-15T10:00:00Z",
        time_window_end="2026-01-15T11:00:00Z",
        config_snapshot=ConfigSnapshot(
            dynamic_config=[
                DynamicConfigEntry(key="history.persistenceMaxQPS", value=1000),
            ],
            server_env_vars=[
                EnvVarEntry(name="TEMPORAL_SQL_MAX_CONNS", value="50"),
            ],
            worker_options=WorkerOptionsSnapshot(max_concurrent_activities=200),
            dsql_plugin_config=_make_dsql_snapshot(),
        ),
        telemetry=telemetry,
        created_at="2026-01-15T11:05:00Z",
    )


# =========================================================================
# Property 13: Behaviour_Profile completeness
# Feature: enhance-config-ux, Property 13: Behaviour_Profile completeness
# Validates: Requirements 9.2, 9.3, 9.4
# =========================================================================


@settings(max_examples=20)
@given(profile=behaviour_profiles())
def test_behaviour_profile_completeness(profile: BehaviourProfile):
    """Every BehaviourProfile has non-null identity, config snapshot, and telemetry."""
    assert profile.name
    assert profile.cluster_id
    assert profile.time_window_start
    assert profile.time_window_end
    assert profile.config_snapshot is not None
    assert profile.telemetry is not None


# =========================================================================
# Property 14: Telemetry_Summary completeness
# Feature: enhance-config-ux, Property 14: Telemetry_Summary completeness
# Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7
# =========================================================================


@settings(max_examples=20)
@given(telemetry=telemetry_summaries())
def test_telemetry_summary_completeness(telemetry: TelemetrySummary):
    """All six metric categories present, each MetricAggregate has all six fields."""
    assert telemetry.throughput is not None
    assert telemetry.latency is not None
    assert telemetry.matching is not None
    assert telemetry.dsql_pool is not None
    assert telemetry.errors is not None
    assert telemetry.resources is not None

    # Spot-check a MetricAggregate has all fields
    agg = telemetry.throughput.workflows_started_per_sec
    assert hasattr(agg, "min")
    assert hasattr(agg, "max")
    assert hasattr(agg, "mean")
    assert hasattr(agg, "p50")
    assert hasattr(agg, "p95")
    assert hasattr(agg, "p99")


# =========================================================================
# Property 15: Profile listing correctness
# Feature: enhance-config-ux, Property 15: Profile listing correctness
# Validates: Requirements 11.1, 11.3
# =========================================================================


def test_profile_metadata_excludes_telemetry():
    """ProfileMetadata does not contain full telemetry data."""
    from behaviour_profiles.models import ProfileMetadata

    fields = set(ProfileMetadata.model_fields.keys())
    assert "telemetry" not in fields
    assert "config_snapshot" not in fields


# =========================================================================
# Property 16: Profile retrieval identity
# Feature: enhance-config-ux, Property 16: Profile retrieval identity
# Validates: Requirements 11.2
# =========================================================================


@settings(max_examples=10)
@given(profile=behaviour_profiles())
def test_profile_serialization_identity(profile: BehaviourProfile):
    """Serializing and deserializing a profile produces an equivalent profile."""
    json_str = profile.model_dump_json()
    restored = BehaviourProfile.model_validate_json(json_str)
    assert restored == profile


# =========================================================================
# Property 17: Comparison completeness and ordering
# Feature: enhance-config-ux, Property 17: Comparison completeness and ordering
# Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5
# =========================================================================


@settings(max_examples=10)
@given(
    profile_a=behaviour_profiles(),
    profile_b=behaviour_profiles(),
)
def test_comparison_completeness_and_ordering(
    profile_a: BehaviourProfile,
    profile_b: BehaviourProfile,
):
    """Comparison includes config, telemetry, and version diffs; telemetry sorted by severity."""
    comparison = compare_profiles(profile_a, profile_b)

    assert comparison.profile_a_id == profile_a.id
    assert comparison.profile_b_id == profile_b.id

    # Telemetry diffs should be present (both profiles have telemetry)
    assert isinstance(comparison.telemetry_diffs, list)
    assert isinstance(comparison.config_diffs, list)
    assert isinstance(comparison.version_diffs, list)

    # Verify severity ordering: critical < warning < info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    for i in range(len(comparison.telemetry_diffs) - 1):
        curr = comparison.telemetry_diffs[i]
        nxt = comparison.telemetry_diffs[i + 1]
        assert severity_order[curr.severity] <= severity_order[nxt.severity]


# =========================================================================
# Property 18: Behaviour_Profile serialization round-trip
# Feature: enhance-config-ux, Property 18: Behaviour_Profile serialization round-trip
# Validates: Requirements 13.1, 13.2, 13.3
# =========================================================================


@settings(max_examples=20)
@given(profile=behaviour_profiles())
def test_behaviour_profile_round_trip(profile: BehaviourProfile):
    """Serializing to JSON then deserializing produces an equivalent BehaviourProfile."""
    json_str = profile.model_dump_json()
    restored = BehaviourProfile.model_validate_json(json_str)
    assert restored == profile


# =========================================================================
# Property 19: Drift detection
# Feature: enhance-config-ux, Property 19: Drift detection
# Validates: Requirements 15.2
# =========================================================================


@st.composite
def _baseline_and_drifted_telemetry(draw: st.DrawFn) -> tuple[BehaviourProfile, TelemetrySummary]:
    """Generate a baseline profile and a current telemetry with at least one drifted metric.

    We take a baseline profile and then create a current telemetry where at least
    one metric's mean is shifted beyond the drift threshold.
    """
    from behaviour_profiles.models import (
        ThroughputMetrics,
    )

    baseline = draw(behaviour_profiles())

    # Create current telemetry by copying baseline but shifting one metric significantly
    # We'll shift state_transitions_per_sec down by > 30% (throughput threshold)
    base_st = baseline.telemetry.throughput.state_transitions_per_sec
    # Ensure the baseline has a meaningful value to drift from
    shifted_mean = max(0.0, base_st.mean * 0.5)  # 50% drop — well beyond 30% threshold

    shifted_agg = MetricAggregate(
        min=shifted_mean * 0.8,
        max=shifted_mean * 1.2,
        mean=shifted_mean,
        p50=shifted_mean,
        p95=shifted_mean * 1.1,
        p99=shifted_mean * 1.15,
    )

    current = TelemetrySummary(
        throughput=ThroughputMetrics(
            workflows_started_per_sec=baseline.telemetry.throughput.workflows_started_per_sec,
            workflows_completed_per_sec=baseline.telemetry.throughput.workflows_completed_per_sec,
            state_transitions_per_sec=shifted_agg,
        ),
        latency=baseline.telemetry.latency,
        matching=baseline.telemetry.matching,
        dsql_pool=baseline.telemetry.dsql_pool,
        errors=baseline.telemetry.errors,
        resources=baseline.telemetry.resources,
    )

    return baseline, current


@settings(max_examples=20, deadline=None)
@given(data=_baseline_and_drifted_telemetry())
def test_drift_detection(data: tuple[BehaviourProfile, TelemetrySummary]):
    """When at least one metric deviates beyond threshold, drift is flagged.

    **Validates: Requirements 15.2**
    """
    from copilot.workflows.drift import detect_drift

    baseline, current_telemetry = data

    assessment = detect_drift(current_telemetry, baseline)

    assert assessment.baseline_profile_id == baseline.id
    assert assessment.baseline_profile_name == baseline.name
    assert isinstance(assessment.drifted_metrics, list)
    assert assessment.summary  # non-empty summary

    # If baseline had meaningful throughput, the 50% drop should be detected
    if baseline.telemetry.throughput.state_transitions_per_sec.mean > 10.0:
        assert assessment.is_drifted
        metric_names = [d.metric for d in assessment.drifted_metrics]
        assert "state_transitions_per_sec" in metric_names


# =========================================================================
# Property 20: Drift correlation
# Feature: enhance-config-ux, Property 20: Drift correlation
# Validates: Requirements 15.3
# =========================================================================


def test_drift_correlation_with_config_changes():
    """When config changes correlate with telemetry regressions, correlation is flagged.

    **Validates: Requirements 15.3**
    """
    from behaviour_profiles.models import ConfigDiff, ProfileComparison, TelemetryDiff

    comparison = ProfileComparison(
        profile_a_id="profile-a",
        profile_b_id="profile-b",
        config_diffs=[
            ConfigDiff(
                key="dynamic_config.history.persistenceMaxQPS",
                old_value=1000,
                new_value=500,
            ),
        ],
        telemetry_diffs=[
            TelemetryDiff(
                metric="state_transitions_per_sec",
                old_value=MetricAggregate(min=100, max=200, mean=150, p50=140, p95=180, p99=190),
                new_value=MetricAggregate(min=50, max=100, mean=75, p50=70, p95=90, p99=95),
                change_pct=-50.0,
                direction="regressed",
                severity="critical",
            ),
            TelemetryDiff(
                metric="persistence_latency_p95",
                old_value=MetricAggregate(min=5, max=20, mean=10, p50=9, p95=18, p99=19),
                new_value=MetricAggregate(min=10, max=50, mean=30, p50=25, p95=45, p99=48),
                change_pct=200.0,
                direction="regressed",
                severity="critical",
            ),
        ],
        version_diffs=[],
    )

    from copilot.workflows.drift import correlate_drift

    result = correlate_drift(comparison)

    assert result.has_correlations
    assert len(result.correlations) > 0
    assert result.summary  # non-empty

    # The persistenceMaxQPS change should correlate with state_transitions and persistence_latency
    corr_keys = [c.config_key for c in result.correlations]
    assert "dynamic_config.history.persistenceMaxQPS" in corr_keys

    for corr in result.correlations:
        if corr.config_key == "dynamic_config.history.persistenceMaxQPS":
            assert any(
                m in corr.correlated_metrics
                for m in ["state_transitions_per_sec", "persistence_latency_p95"]
            )
            assert corr.explanation  # non-empty explanation


def test_drift_correlation_no_regressions():
    """When no telemetry regressions exist, no correlations are found.

    **Validates: Requirements 15.3**
    """
    from behaviour_profiles.models import ConfigDiff, ProfileComparison, TelemetryDiff

    comparison = ProfileComparison(
        profile_a_id="profile-a",
        profile_b_id="profile-b",
        config_diffs=[
            ConfigDiff(
                key="dynamic_config.history.persistenceMaxQPS",
                old_value=500,
                new_value=1000,
            ),
        ],
        telemetry_diffs=[
            TelemetryDiff(
                metric="state_transitions_per_sec",
                old_value=MetricAggregate(min=100, max=200, mean=150, p50=140, p95=180, p99=190),
                new_value=MetricAggregate(min=150, max=250, mean=200, p50=190, p95=230, p99=240),
                change_pct=33.3,
                direction="improved",
                severity="info",
            ),
        ],
        version_diffs=[],
    )

    from copilot.workflows.drift import correlate_drift

    result = correlate_drift(comparison)
    assert not result.has_correlations
    assert len(result.correlations) == 0


# =========================================================================
# Property 21: Preset conformance assessment
# Feature: enhance-config-ux, Property 21: Preset conformance assessment
# Validates: Requirements 16.1, 16.2, 16.3, 16.4
# =========================================================================


def test_preset_conformance_conforming():
    """Profile within preset bounds is labelled 'conforming' with all metrics passing.

    **Validates: Requirements 16.1, 16.2, 16.3, 16.4**
    """
    from copilot.workflows.conformance import assess_conformance
    from copilot_core.models import TelemetryBound
    from dsql_config.models import ScalePreset, ThroughputRange

    # Create a preset with known bounds
    preset = ScalePreset(
        name="test-preset",
        description="Test preset",
        throughput_range=ThroughputRange(min_st_per_sec=0, max_st_per_sec=100, description="test"),
        slo_defaults=[],
        topology_defaults=[],
        safety_derivations=[],
        tuning_derivations=[],
        expected_bounds=[
            TelemetryBound(metric="state_transitions_per_sec", lower=10, upper=100),
            TelemetryBound(metric="workflow_schedule_to_start_p99", lower=0, upper=500),
        ],
    )

    # Create a profile with telemetry within bounds
    from behaviour_profiles.models import (
        ConfigSnapshot,
        DSQLPoolMetrics,
        DynamicConfigEntry,
        EnvVarEntry,
        ErrorMetrics,
        LatencyMetrics,
        MatchingMetrics,
        ResourceMetrics,
        ThroughputMetrics,
        WorkerOptionsSnapshot,
    )

    agg_in_range = MetricAggregate(min=20, max=80, mean=50, p50=45, p95=70, p99=75)
    agg_latency = MetricAggregate(min=10, max=200, mean=100, p50=90, p95=180, p99=190)
    agg_zero = MetricAggregate(min=0, max=1, mean=0.5, p50=0.4, p95=0.8, p99=0.9)

    profile = BehaviourProfile(
        id="test-profile-1",
        name="conforming-profile",
        cluster_id="cluster-001",
        time_window_start="2026-01-15T10:00:00Z",
        time_window_end="2026-01-15T11:00:00Z",
        config_snapshot=ConfigSnapshot(
            dynamic_config=[DynamicConfigEntry(key="test", value=1)],
            server_env_vars=[EnvVarEntry(name="TEST", value="1")],
            worker_options=WorkerOptionsSnapshot(),
            dsql_plugin_config=_make_dsql_snapshot(),
        ),
        telemetry=TelemetrySummary(
            throughput=ThroughputMetrics(
                workflows_started_per_sec=agg_in_range,
                workflows_completed_per_sec=agg_in_range,
                state_transitions_per_sec=agg_in_range,
            ),
            latency=LatencyMetrics(
                workflow_schedule_to_start_p95=agg_latency,
                workflow_schedule_to_start_p99=agg_latency,
                activity_schedule_to_start_p95=agg_latency,
                activity_schedule_to_start_p99=agg_latency,
                persistence_latency_p95=agg_latency,
                persistence_latency_p99=agg_latency,
            ),
            matching=MatchingMetrics(
                sync_match_rate=agg_zero,
                async_match_rate=agg_zero,
                task_dispatch_latency=agg_zero,
                backlog_count=agg_zero,
                backlog_age=agg_zero,
            ),
            dsql_pool=DSQLPoolMetrics(
                pool_open_count=agg_zero,
                pool_in_use_count=agg_zero,
                pool_idle_count=agg_zero,
                reservoir_size=agg_zero,
                reservoir_empty_events=agg_zero,
                open_failures=agg_zero,
                reconnect_count=agg_zero,
            ),
            errors=ErrorMetrics(
                occ_conflicts_per_sec=agg_zero,
                exhausted_retries_per_sec=agg_zero,
                dsql_auth_failures=agg_zero,
            ),
            resources=ResourceMetrics(
                cpu_utilization=ServiceMetrics(
                    history=agg_zero, matching=agg_zero, frontend=agg_zero, worker=agg_zero
                ),
                memory_utilization=ServiceMetrics(
                    history=agg_zero, matching=agg_zero, frontend=agg_zero, worker=agg_zero
                ),
                worker_task_slot_utilization=agg_zero,
            ),
        ),
        created_at="2026-01-15T11:05:00Z",
    )

    result = assess_conformance(profile, preset)

    assert result.label == "conforming"
    assert result.preset_name == "test-preset"
    assert result.profile_id == "test-profile-1"
    assert all(r.result == "pass" for r in result.metric_results)
    assert len(result.metric_results) == 2
    assert result.summary  # non-empty


def test_preset_conformance_drifted():
    """Profile outside preset bounds is labelled 'drifted' with failing metrics.

    **Validates: Requirements 16.1, 16.2, 16.3, 16.4**
    """
    from copilot.workflows.conformance import assess_conformance
    from copilot_core.models import TelemetryBound
    from dsql_config.models import ScalePreset, ThroughputRange

    preset = ScalePreset(
        name="test-preset",
        description="Test preset",
        throughput_range=ThroughputRange(min_st_per_sec=50, max_st_per_sec=500, description="test"),
        slo_defaults=[],
        topology_defaults=[],
        safety_derivations=[],
        tuning_derivations=[],
        expected_bounds=[
            TelemetryBound(metric="state_transitions_per_sec", lower=50, upper=500),
        ],
    )

    # Profile with state_transitions mean=10 — below the lower bound of 50
    from behaviour_profiles.models import (
        ConfigSnapshot,
        DSQLPoolMetrics,
        DynamicConfigEntry,
        EnvVarEntry,
        ErrorMetrics,
        LatencyMetrics,
        MatchingMetrics,
        ResourceMetrics,
        ThroughputMetrics,
        WorkerOptionsSnapshot,
    )

    low_agg = MetricAggregate(min=5, max=15, mean=10, p50=9, p95=13, p99=14)
    agg_zero = MetricAggregate(min=0, max=1, mean=0.5, p50=0.4, p95=0.8, p99=0.9)

    profile = BehaviourProfile(
        id="test-profile-2",
        name="drifted-profile",
        cluster_id="cluster-001",
        time_window_start="2026-01-15T10:00:00Z",
        time_window_end="2026-01-15T11:00:00Z",
        config_snapshot=ConfigSnapshot(
            dynamic_config=[DynamicConfigEntry(key="test", value=1)],
            server_env_vars=[EnvVarEntry(name="TEST", value="1")],
            worker_options=WorkerOptionsSnapshot(),
            dsql_plugin_config=_make_dsql_snapshot(),
        ),
        telemetry=TelemetrySummary(
            throughput=ThroughputMetrics(
                workflows_started_per_sec=agg_zero,
                workflows_completed_per_sec=agg_zero,
                state_transitions_per_sec=low_agg,
            ),
            latency=LatencyMetrics(
                workflow_schedule_to_start_p95=agg_zero,
                workflow_schedule_to_start_p99=agg_zero,
                activity_schedule_to_start_p95=agg_zero,
                activity_schedule_to_start_p99=agg_zero,
                persistence_latency_p95=agg_zero,
                persistence_latency_p99=agg_zero,
            ),
            matching=MatchingMetrics(
                sync_match_rate=agg_zero,
                async_match_rate=agg_zero,
                task_dispatch_latency=agg_zero,
                backlog_count=agg_zero,
                backlog_age=agg_zero,
            ),
            dsql_pool=DSQLPoolMetrics(
                pool_open_count=agg_zero,
                pool_in_use_count=agg_zero,
                pool_idle_count=agg_zero,
                reservoir_size=agg_zero,
                reservoir_empty_events=agg_zero,
                open_failures=agg_zero,
                reconnect_count=agg_zero,
            ),
            errors=ErrorMetrics(
                occ_conflicts_per_sec=agg_zero,
                exhausted_retries_per_sec=agg_zero,
                dsql_auth_failures=agg_zero,
            ),
            resources=ResourceMetrics(
                cpu_utilization=ServiceMetrics(
                    history=agg_zero, matching=agg_zero, frontend=agg_zero, worker=agg_zero
                ),
                memory_utilization=ServiceMetrics(
                    history=agg_zero, matching=agg_zero, frontend=agg_zero, worker=agg_zero
                ),
                worker_task_slot_utilization=agg_zero,
            ),
        ),
        created_at="2026-01-15T11:05:00Z",
    )

    result = assess_conformance(profile, preset)

    assert result.label == "drifted"
    assert any(r.result == "fail" for r in result.metric_results)

    # The state_transitions_per_sec metric should fail
    st_result = next(r for r in result.metric_results if r.metric == "state_transitions_per_sec")
    assert st_result.result == "fail"
    assert st_result.observed_value == 10.0
    assert result.summary  # non-empty
