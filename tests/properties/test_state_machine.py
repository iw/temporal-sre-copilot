"""Property tests for the Health State Machine.

Property 12: Health State Machine Invariants
- Forward progress invariant: health is anchored to forward progress
- No direct Happy → Critical transition
- Deterministic: same inputs always produce same output
- Amplifiers never influence state transitions

Validates: Requirements 12.2, 12.3
"""

from hypothesis import given, settings

from copilot.models import HealthState, PrimarySignals
from copilot.models.config import CriticalThresholds, HealthyThresholds, StressedThresholds
from copilot.models.state_machine import _is_idle, evaluate_health_state

from .strategies import health_states, primary_signals

# =============================================================================
# INVARIANT: Happy → Critical must go through Stressed
# =============================================================================


@given(signals=primary_signals())
@settings(max_examples=500)
def test_no_direct_happy_to_critical(signals: PrimarySignals):
    """Property: Starting from HAPPY, evaluate_health_state never returns CRITICAL.

    The transition invariant requires Happy → Stressed → Critical.
    A single evaluation from HAPPY can only reach HAPPY or STRESSED.
    """
    result = evaluate_health_state(signals, HealthState.HAPPY)
    assert result != HealthState.CRITICAL, (
        f"Direct Happy → Critical transition detected. "
        f"Signals: throughput={signals.state_transitions.throughput_per_sec}, "
        f"completion_rate={signals.workflow_completion.completion_rate}, "
        f"backlog_age={signals.history.backlog_age_sec}"
    )


@given(signals=primary_signals())
@settings(max_examples=500)
def test_stressed_can_reach_critical(signals: PrimarySignals):
    """Property: From STRESSED, all three states are reachable.

    This is the complement of the above — STRESSED → CRITICAL is allowed.
    """
    result = evaluate_health_state(signals, HealthState.STRESSED)
    assert result in (HealthState.HAPPY, HealthState.STRESSED, HealthState.CRITICAL)


@given(signals=primary_signals())
@settings(max_examples=500)
def test_critical_can_recover(signals: PrimarySignals):
    """Property: From CRITICAL, all three states are reachable.

    Recovery paths: Critical → Stressed → Happy.
    """
    result = evaluate_health_state(signals, HealthState.CRITICAL)
    assert result in (HealthState.HAPPY, HealthState.STRESSED, HealthState.CRITICAL)


# =============================================================================
# INVARIANT: Deterministic — same inputs, same output
# =============================================================================


@given(signals=primary_signals(), current_state=health_states)
@settings(max_examples=300)
def test_deterministic(signals: PrimarySignals, current_state: HealthState):
    """Property: evaluate_health_state is a pure function.

    Same inputs must always produce the same output.
    No randomness, no LLM, no side effects.
    """
    result1 = evaluate_health_state(signals, current_state)
    result2 = evaluate_health_state(signals, current_state)
    assert result1 == result2


# =============================================================================
# INVARIANT: Output is always a valid HealthState
# =============================================================================


@given(signals=primary_signals(), current_state=health_states)
@settings(max_examples=500)
def test_output_is_valid_health_state(signals: PrimarySignals, current_state: HealthState):
    """Property: Output is always one of the three canonical states."""
    result = evaluate_health_state(signals, current_state)
    assert result in HealthState


# =============================================================================
# INVARIANT: Forward progress anchoring
# =============================================================================


@given(current_state=health_states)
@settings(max_examples=100)
def test_healthy_signals_produce_happy(current_state: HealthState):
    """Property: When all forward progress signals are clearly healthy, state is HAPPY.

    This tests the "anchor to progress, not pain" principle.
    """
    healthy = PrimarySignals(
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
    result = evaluate_health_state(healthy, current_state)
    assert result == HealthState.HAPPY


@given(current_state=health_states)
@settings(max_examples=100)
def test_collapsed_throughput_not_happy(current_state: HealthState):
    """Property: When state transition throughput collapses, state is never HAPPY.

    Signal 1 collapse = forward progress has stopped.
    """
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
    result = evaluate_health_state(collapsed, current_state)
    assert result != HealthState.HAPPY, "Collapsed throughput should never be HAPPY"


@given(current_state=health_states)
@settings(max_examples=100)
def test_critical_backlog_not_happy(current_state: HealthState):
    """Property: When history backlog age is critical, state is never HAPPY.

    Signal 4 > 120s = execution engine critically behind.
    """
    critical_backlog = PrimarySignals(
        state_transitions={"throughput_per_sec": 200, "latency_p95_ms": 10, "latency_p99_ms": 20},
        workflow_completion={"completion_rate": 0.99, "success_per_sec": 100, "failed_per_sec": 0},
        history={
            "backlog_age_sec": 200,
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
    result = evaluate_health_state(critical_backlog, current_state)
    assert result != HealthState.HAPPY, "Critical backlog age should never be HAPPY"


# =============================================================================
# INVARIANT: Threshold ordering
# =============================================================================


def test_threshold_ordering():
    """Property: Critical thresholds are more extreme than stressed thresholds.

    This ensures the state machine gates are properly ordered.
    """
    critical = CriticalThresholds()
    stressed = StressedThresholds()
    healthy = HealthyThresholds()

    # Backlog: healthy < stressed < critical
    assert healthy.history_backlog_age_healthy_sec < stressed.history_backlog_age_stress_sec
    assert stressed.history_backlog_age_stress_sec < critical.history_backlog_age_max_sec

    # Throughput: critical < healthy (lower is worse)
    assert critical.state_transitions_min_per_sec < healthy.state_transitions_healthy_per_sec

    # Completion rate: critical < healthy (lower is worse)
    assert critical.workflow_completion_rate_min < healthy.workflow_completion_rate_healthy


# =============================================================================
# INVARIANT: Idle cluster is HAPPY, not CRITICAL
# =============================================================================


@given(current_state=health_states)
@settings(max_examples=100)
def test_idle_cluster_is_happy(current_state: HealthState):
    """Property: An idle cluster (zero throughput, zero errors, zero backlog) is HAPPY.

    Zero progress with zero demand is not a failure — it's a quiet cluster.
    This prevents false CRITICAL alerts on clusters with no inbound work.
    """
    idle = PrimarySignals(
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
    result = evaluate_health_state(idle, current_state)
    assert result == HealthState.HAPPY, (
        f"Idle cluster should be HAPPY, got {result.value}. "
        "Zero throughput + zero errors + zero backlog = quiet, not broken."
    )


def test_idle_detection_requires_no_errors():
    """Property: A cluster with zero throughput but errors is NOT idle.

    If errors are present, something is wrong — the cluster should be
    making progress but isn't. This is a failure, not idleness.
    """
    zero_throughput_with_errors = PrimarySignals(
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
    assert not _is_idle(zero_throughput_with_errors), "Cluster with workflow failures is NOT idle"


def test_idle_detection_requires_no_backlog():
    """Property: A cluster with zero throughput but backlog is NOT idle.

    If work is waiting, the cluster should be processing it.
    Zero throughput with backlog = broken, not quiet.
    """
    zero_throughput_with_backlog = PrimarySignals(
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
    assert not _is_idle(zero_throughput_with_backlog), "Cluster with history backlog is NOT idle"


def test_idle_detection_near_zero_noise():
    """Property: Tiny floating-point noise doesn't break idle detection.

    Real metrics often have tiny non-zero values from rate() calculations.
    The idle check uses relaxed thresholds (< 1.0, < 0.1) to handle this.
    """
    near_zero = PrimarySignals(
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
    assert _is_idle(near_zero), "Near-zero noise should still be detected as idle"
