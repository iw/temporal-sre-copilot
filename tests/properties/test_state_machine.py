"""Property tests for the Health State Machine.

Validates: Requirements 12.2, 12.3
"""

from hypothesis import given, settings

from copilot.models import HealthState, PrimarySignals
from copilot.models.config import CriticalThresholds, HealthyThresholds, StressedThresholds
from copilot.models.state_machine import (
    CONSECUTIVE_CRITICAL_THRESHOLD,
    _is_idle,
    evaluate_health_state,
)

from .strategies import health_states, primary_signals


def _healthy_signals():
    return PrimarySignals(
        state_transitions={"throughput_per_sec": 200, "latency_p95_ms": 10, "latency_p99_ms": 20},
        workflow_completion={
            "completion_rate": 0.99,
            "success_per_sec": 100,
            "failed_per_sec": 0.1,
        },
        history={
            "backlog_age_sec": 1,
            "task_processing_rate_per_sec": 200,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 50, "latency_p99_ms": 80},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 0.99, "poll_timeout_rate": 0.01, "long_poll_latency_ms": 10},
        persistence={
            "latency_p95_ms": 10,
            "latency_p99_ms": 20,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )


def _critical_throughput_signals():
    """Throughput collapsed but everything else fine."""
    return PrimarySignals(
        state_transitions={"throughput_per_sec": 1, "latency_p95_ms": 10, "latency_p99_ms": 20},
        workflow_completion={"completion_rate": 0.99, "success_per_sec": 100, "failed_per_sec": 0},
        history={
            "backlog_age_sec": 1,
            "task_processing_rate_per_sec": 200,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 50, "latency_p99_ms": 80},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 0.99, "poll_timeout_rate": 0.01, "long_poll_latency_ms": 10},
        persistence={
            "latency_p95_ms": 10,
            "latency_p99_ms": 20,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )


def _idle_signals():
    return PrimarySignals(
        state_transitions={"throughput_per_sec": 0, "latency_p95_ms": 0, "latency_p99_ms": 0},
        workflow_completion={"completion_rate": 1.0, "success_per_sec": 0, "failed_per_sec": 0},
        history={
            "backlog_age_sec": 0,
            "task_processing_rate_per_sec": 0,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 0, "latency_p99_ms": 0},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 1.0, "poll_timeout_rate": 0, "long_poll_latency_ms": 0},
        persistence={
            "latency_p95_ms": 0,
            "latency_p99_ms": 0,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )


# === INVARIANT: Happy -> Critical must go through Stressed ===


@given(signals=primary_signals())
@settings(max_examples=500)
def test_no_direct_happy_to_critical(signals: PrimarySignals):
    """Starting from HAPPY, never returns CRITICAL directly."""
    result, _ = evaluate_health_state(signals, HealthState.HAPPY)
    assert result != HealthState.CRITICAL


@given(signals=primary_signals())
@settings(max_examples=500)
def test_no_direct_happy_to_critical_even_with_sustained(signals: PrimarySignals):
    """Even with max consecutive critical count, HAPPY never goes to CRITICAL."""
    result, _ = evaluate_health_state(
        signals,
        HealthState.HAPPY,
        consecutive_critical_count=CONSECUTIVE_CRITICAL_THRESHOLD + 10,
    )
    assert result != HealthState.CRITICAL


@given(signals=primary_signals())
@settings(max_examples=500)
def test_stressed_can_reach_critical(signals: PrimarySignals):
    """From STRESSED with sustained critical, all three states are reachable."""
    result, _ = evaluate_health_state(
        signals,
        HealthState.STRESSED,
        consecutive_critical_count=CONSECUTIVE_CRITICAL_THRESHOLD,
    )
    assert result in (HealthState.HAPPY, HealthState.STRESSED, HealthState.CRITICAL)


@given(signals=primary_signals())
@settings(max_examples=500)
def test_critical_can_recover(signals: PrimarySignals):
    """From CRITICAL, all three states are reachable."""
    result, _ = evaluate_health_state(signals, HealthState.CRITICAL)
    assert result in (HealthState.HAPPY, HealthState.STRESSED, HealthState.CRITICAL)


# === INVARIANT: Deterministic ===


@given(signals=primary_signals(), current_state=health_states)
@settings(max_examples=300)
def test_deterministic(signals: PrimarySignals, current_state: HealthState):
    """Same inputs always produce same output."""
    r1 = evaluate_health_state(signals, current_state, consecutive_critical_count=0)
    r2 = evaluate_health_state(signals, current_state, consecutive_critical_count=0)
    assert r1 == r2


@given(signals=primary_signals(), current_state=health_states)
@settings(max_examples=500)
def test_output_is_valid_health_state(signals: PrimarySignals, current_state: HealthState):
    """Output is always a valid HealthState + non-negative count."""
    result, count = evaluate_health_state(signals, current_state)
    assert result in HealthState
    assert count >= 0


# === INVARIANT: Forward progress anchoring ===


@given(current_state=health_states)
@settings(max_examples=100)
def test_healthy_signals_produce_happy(current_state: HealthState):
    """Clearly healthy signals always produce HAPPY."""
    result, count = evaluate_health_state(_healthy_signals(), current_state)
    assert result == HealthState.HAPPY
    assert count == 0


@given(current_state=health_states)
@settings(max_examples=100)
def test_collapsed_throughput_not_happy(current_state: HealthState):
    """Collapsed throughput is never HAPPY."""
    collapsed = PrimarySignals(
        state_transitions={"throughput_per_sec": 0, "latency_p95_ms": 10, "latency_p99_ms": 20},
        workflow_completion={"completion_rate": 0.99, "success_per_sec": 100, "failed_per_sec": 0},
        history={
            "backlog_age_sec": 1,
            "task_processing_rate_per_sec": 200,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 50, "latency_p99_ms": 80},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 0.99, "poll_timeout_rate": 0.01, "long_poll_latency_ms": 10},
        persistence={
            "latency_p95_ms": 10,
            "latency_p99_ms": 20,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )
    result, _ = evaluate_health_state(collapsed, current_state)
    assert result != HealthState.HAPPY


@given(current_state=health_states)
@settings(max_examples=100)
def test_critical_backlog_not_happy(current_state: HealthState):
    """Critical backlog age (>300s) is never HAPPY."""
    signals = PrimarySignals(
        state_transitions={"throughput_per_sec": 200, "latency_p95_ms": 10, "latency_p99_ms": 20},
        workflow_completion={"completion_rate": 0.99, "success_per_sec": 100, "failed_per_sec": 0},
        history={
            "backlog_age_sec": 400,
            "task_processing_rate_per_sec": 200,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 50, "latency_p99_ms": 80},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 0.99, "poll_timeout_rate": 0.01, "long_poll_latency_ms": 10},
        persistence={
            "latency_p95_ms": 10,
            "latency_p99_ms": 20,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )
    result, _ = evaluate_health_state(signals, current_state)
    assert result != HealthState.HAPPY


# === INVARIANT: Threshold ordering ===


def test_threshold_ordering():
    """Critical thresholds are more extreme than stressed thresholds."""
    critical = CriticalThresholds()
    stressed = StressedThresholds()
    healthy = HealthyThresholds()

    assert healthy.history_backlog_age_healthy_sec <= stressed.history_backlog_age_stress_sec
    assert stressed.history_backlog_age_stress_sec < critical.history_backlog_age_max_sec
    assert critical.state_transitions_min_per_sec <= healthy.state_transitions_healthy_per_sec
    assert critical.workflow_completion_rate_min < healthy.workflow_completion_rate_healthy


# === INVARIANT: Idle cluster is HAPPY ===


@given(current_state=health_states)
@settings(max_examples=100)
def test_idle_cluster_is_happy(current_state: HealthState):
    """Idle cluster (zero everything) is HAPPY, not CRITICAL."""
    result, count = evaluate_health_state(_idle_signals(), current_state)
    assert result == HealthState.HAPPY
    assert count == 0


def test_idle_detection_requires_no_errors():
    """Zero throughput with errors is NOT idle."""
    signals = PrimarySignals(
        state_transitions={"throughput_per_sec": 0, "latency_p95_ms": 0, "latency_p99_ms": 0},
        workflow_completion={"completion_rate": 0.5, "success_per_sec": 0, "failed_per_sec": 5},
        history={
            "backlog_age_sec": 0,
            "task_processing_rate_per_sec": 0,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 0, "latency_p99_ms": 0},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 1.0, "poll_timeout_rate": 0, "long_poll_latency_ms": 0},
        persistence={
            "latency_p95_ms": 0,
            "latency_p99_ms": 0,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )
    assert not _is_idle(signals)


def test_idle_detection_requires_no_backlog():
    """Zero throughput with backlog is NOT idle."""
    signals = PrimarySignals(
        state_transitions={"throughput_per_sec": 0, "latency_p95_ms": 0, "latency_p99_ms": 0},
        workflow_completion={"completion_rate": 1.0, "success_per_sec": 0, "failed_per_sec": 0},
        history={
            "backlog_age_sec": 60,
            "task_processing_rate_per_sec": 0,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 0, "latency_p99_ms": 0},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 1.0, "poll_timeout_rate": 0, "long_poll_latency_ms": 0},
        persistence={
            "latency_p95_ms": 0,
            "latency_p99_ms": 0,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )
    assert not _is_idle(signals)


def test_idle_detection_near_zero_noise():
    """Tiny floating-point noise still detected as idle."""
    signals = PrimarySignals(
        state_transitions={"throughput_per_sec": 0.001, "latency_p95_ms": 0, "latency_p99_ms": 0},
        workflow_completion={"completion_rate": 1.0, "success_per_sec": 0, "failed_per_sec": 0.001},
        history={
            "backlog_age_sec": 0.01,
            "task_processing_rate_per_sec": 0.001,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0.001, "latency_p95_ms": 0, "latency_p99_ms": 0},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 1.0, "poll_timeout_rate": 0, "long_poll_latency_ms": 0},
        persistence={
            "latency_p95_ms": 0,
            "latency_p99_ms": 0,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )
    assert _is_idle(signals)


# === ANTI-FLAP: Critical requires sustained conditions ===


def test_single_critical_observation_stays_stressed():
    """A single critical observation from STRESSED stays STRESSED (debounce)."""
    result, count = evaluate_health_state(
        _critical_throughput_signals(),
        HealthState.STRESSED,
        consecutive_critical_count=0,
    )
    assert result == HealthState.STRESSED
    assert count == 1


def test_sustained_critical_triggers_critical():
    """After CONSECUTIVE_CRITICAL_THRESHOLD observations, CRITICAL is reached."""
    count = 0
    state = HealthState.STRESSED
    for _ in range(CONSECUTIVE_CRITICAL_THRESHOLD):
        state, count = evaluate_health_state(
            _critical_throughput_signals(),
            state,
            consecutive_critical_count=count,
        )
    assert state == HealthState.CRITICAL


def test_transient_spike_resets_counter():
    """A good observation between bad ones resets the critical counter."""
    state = HealthState.STRESSED
    state, count = evaluate_health_state(
        _critical_throughput_signals(),
        state,
        consecutive_critical_count=0,
    )
    state, count = evaluate_health_state(
        _critical_throughput_signals(),
        state,
        consecutive_critical_count=count,
    )
    assert count == 2

    # One good observation resets
    state, count = evaluate_health_state(
        _healthy_signals(),
        state,
        consecutive_critical_count=count,
    )
    assert count == 0


# === ANTI-FLAP: Completion rate demand-gating ===


def test_low_completion_rate_during_ramp_up_not_critical():
    """Low completion rate with low terminal throughput is not Critical."""
    ramp_up = PrimarySignals(
        state_transitions={"throughput_per_sec": 100, "latency_p95_ms": 50, "latency_p99_ms": 80},
        workflow_completion={"completion_rate": 0.2, "success_per_sec": 2, "failed_per_sec": 0.5},
        history={
            "backlog_age_sec": 5,
            "task_processing_rate_per_sec": 100,
            "shard_churn_rate_per_sec": 0,
        },
        frontend={"error_rate_per_sec": 0, "latency_p95_ms": 50, "latency_p99_ms": 80},
        matching={"workflow_backlog_age_sec": 0, "activity_backlog_age_sec": 0},
        poller={"poll_success_rate": 0.99, "poll_timeout_rate": 0.01, "long_poll_latency_ms": 10},
        persistence={
            "latency_p95_ms": 10,
            "latency_p99_ms": 20,
            "error_rate_per_sec": 0,
            "retry_rate_per_sec": 0,
        },
    )
    result, _ = evaluate_health_state(
        ramp_up,
        HealthState.STRESSED,
        consecutive_critical_count=CONSECUTIVE_CRITICAL_THRESHOLD,
    )
    assert result != HealthState.CRITICAL
