"""Property-based tests for scale-aware thresholds.

Tests invariants that must hold across all scale bands, deployment contexts,
and threshold profiles.
"""

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter
from pydantic_core import to_json

from copilot.models import (
    HealthState,
    ScaleBand,
    classify_scale_band,
    evaluate_health_state,
    get_threshold_profile,
    refine_thresholds,
)
from copilot_core.deployment import DeploymentContext, DeploymentProfile

from .strategies import (
    deployment_context,
    deployment_profile,
    primary_signals,
    scale_bands,
)

# =============================================================================
# Property 1: Transition invariant — HAPPY never goes directly to CRITICAL
# =============================================================================


@given(signals=primary_signals(), band=scale_bands)
@settings(max_examples=200)
def test_no_happy_to_critical_transition(signals, band):
    """HAPPY → CRITICAL is forbidden across all scale bands."""
    new_state, _, _ = evaluate_health_state(
        signals,
        HealthState.HAPPY,
        consecutive_critical_count=0,
        current_scale_band=band,
    )
    assert new_state != HealthState.CRITICAL


# =============================================================================
# Property 2: Threshold ordering invariant
# =============================================================================


@given(band=scale_bands)
def test_threshold_ordering_invariant(band):
    """critical.state_transitions_min <= healthy.state_transitions_healthy for all bands."""
    profile = get_threshold_profile(band)
    assert (
        profile.critical.state_transitions_min_per_sec
        <= profile.healthy.state_transitions_healthy_per_sec
    )


# =============================================================================
# Property 3: Idle cluster is HAPPY
# =============================================================================


@given(band=scale_bands)
def test_idle_cluster_is_happy(band):
    """An idle cluster (zero throughput, zero errors) evaluates as HAPPY."""
    from copilot.models import (
        FrontendSignals,
        HistorySignals,
        MatchingSignals,
        PersistenceSignals,
        PollerSignals,
        PrimarySignals,
        StateTransitionSignals,
        WorkflowCompletionSignals,
    )

    idle = PrimarySignals(
        state_transitions=StateTransitionSignals(
            throughput_per_sec=0.0, latency_p95_ms=0.0, latency_p99_ms=0.0
        ),
        workflow_completion=WorkflowCompletionSignals(
            completion_rate=1.0, success_per_sec=0.0, failed_per_sec=0.0
        ),
        history=HistorySignals(
            backlog_age_sec=0.0, task_processing_rate_per_sec=0.0, shard_churn_rate_per_sec=0.0
        ),
        frontend=FrontendSignals(error_rate_per_sec=0.0, latency_p95_ms=0.0, latency_p99_ms=0.0),
        matching=MatchingSignals(workflow_backlog_age_sec=0.0, activity_backlog_age_sec=0.0),
        poller=PollerSignals(
            poll_success_rate=1.0, poll_timeout_rate=0.0, long_poll_latency_ms=0.0
        ),
        persistence=PersistenceSignals(
            latency_p95_ms=0.0, latency_p99_ms=0.0, error_rate_per_sec=0.0, retry_rate_per_sec=0.0
        ),
    )
    state, _, _ = evaluate_health_state(
        idle, HealthState.HAPPY, consecutive_critical_count=0, current_scale_band=band
    )
    assert state == HealthState.HAPPY


# =============================================================================
# Property 4: Dead zone elimination — low throughput with clean signals = HAPPY
# =============================================================================


@given(
    throughput=st.floats(min_value=1.0, max_value=10.0, allow_nan=False),
)
def test_dead_zone_eliminated_under_starter(throughput):
    """1-10 st/sec with zero errors and good completion rate = HAPPY under starter."""
    from copilot.models import (
        FrontendSignals,
        HistorySignals,
        MatchingSignals,
        PersistenceSignals,
        PollerSignals,
        PrimarySignals,
        StateTransitionSignals,
        WorkflowCompletionSignals,
    )

    signals = PrimarySignals(
        state_transitions=StateTransitionSignals(
            throughput_per_sec=throughput, latency_p95_ms=50.0, latency_p99_ms=100.0
        ),
        workflow_completion=WorkflowCompletionSignals(
            completion_rate=0.95, success_per_sec=throughput * 0.95, failed_per_sec=0.0
        ),
        history=HistorySignals(
            backlog_age_sec=1.0,
            task_processing_rate_per_sec=throughput * 2,
            shard_churn_rate_per_sec=0.0,
        ),
        frontend=FrontendSignals(error_rate_per_sec=0.0, latency_p95_ms=50.0, latency_p99_ms=100.0),
        matching=MatchingSignals(workflow_backlog_age_sec=0.0, activity_backlog_age_sec=0.0),
        poller=PollerSignals(
            poll_success_rate=0.95, poll_timeout_rate=0.05, long_poll_latency_ms=100.0
        ),
        persistence=PersistenceSignals(
            latency_p95_ms=50.0,
            latency_p99_ms=100.0,
            error_rate_per_sec=0.0,
            retry_rate_per_sec=0.0,
        ),
    )
    state, _, _ = evaluate_health_state(
        signals,
        HealthState.HAPPY,
        consecutive_critical_count=0,
        current_scale_band=ScaleBand.STARTER,
    )
    assert state == HealthState.HAPPY


# =============================================================================
# Property 5: Scale band classification is pure
# =============================================================================


@given(
    throughput=st.floats(min_value=0, max_value=2000, allow_nan=False),
    band=scale_bands,
)
def test_scale_band_classification_is_pure(throughput, band):
    """Same inputs always produce the same output."""
    result1 = classify_scale_band(throughput, band)
    result2 = classify_scale_band(throughput, band)
    assert result1 == result2


# =============================================================================
# Property 6: DeploymentProfile serialization round-trip
# =============================================================================


@given(profile=deployment_profile())
@settings(max_examples=50)
def test_deployment_profile_serialization_round_trip(profile):
    """DeploymentProfile survives JSON round-trip."""
    json_bytes = to_json(profile)
    restored = TypeAdapter(DeploymentProfile).validate_json(json_bytes)
    assert restored.preset_name == profile.preset_name
    assert restored.throughput_range_min == profile.throughput_range_min


# =============================================================================
# Property 7: DeploymentContext serialization round-trip
# =============================================================================


@given(ctx=deployment_context())
@settings(max_examples=50)
def test_deployment_context_serialization_round_trip(ctx):
    """DeploymentContext survives JSON round-trip."""
    json_bytes = to_json(ctx)
    restored = TypeAdapter(DeploymentContext).validate_json(json_bytes)
    assert restored.history.running == ctx.history.running
    assert restored.timestamp == ctx.timestamp


# =============================================================================
# Property 8: Threshold refinement preserves invariants
# =============================================================================


@given(band=scale_bands, ctx=deployment_context())
@settings(max_examples=100)
def test_refinement_preserves_invariants(band, ctx):
    """Refined thresholds still satisfy ordering invariant."""
    profile = get_threshold_profile(band)
    refined = refine_thresholds(profile, ctx)
    # Ordering invariant must hold (equal allowed for STARTER)
    assert (
        refined.critical.state_transitions_min_per_sec
        <= refined.healthy.state_transitions_healthy_per_sec
    )


# =============================================================================
# Property 9: Backward compatibility — None deployment_context = same result
# =============================================================================


@given(signals=primary_signals(), band=scale_bands)
@settings(max_examples=100)
def test_none_deployment_context_backward_compat(signals, band):
    """deployment_context=None produces identical results to omitting the parameter."""
    state_with_none, count_with_none, band_with_none = evaluate_health_state(
        signals,
        HealthState.HAPPY,
        consecutive_critical_count=0,
        current_scale_band=band,
        deployment_context=None,
    )
    state_without, count_without, band_without = evaluate_health_state(
        signals,
        HealthState.HAPPY,
        consecutive_critical_count=0,
        current_scale_band=band,
    )
    assert state_with_none == state_without
    assert count_with_none == count_without
    assert band_with_none == band_without
