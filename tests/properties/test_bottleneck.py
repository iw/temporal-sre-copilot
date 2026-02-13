"""Property tests for Bottleneck Classification and Worker Scaling Rules.

Property 14: Bottleneck Classification Correctness
- Server-limited vs worker-limited classification
- NEVER_SCALE_DOWN_AT_ZERO rule
- Deterministic classification

Validates: Requirements 14.2, 14.5
"""

from hypothesis import given, settings

from copilot.models import BottleneckClassification, PrimarySignals, WorkerSignals
from copilot.models.state_machine import (
    WorkerScalingContext,
    classify_bottleneck,
    evaluate_worker_scaling_rules,
)

from .strategies import primary_signals, worker_signals

# =============================================================================
# BOTTLENECK CLASSIFICATION
# =============================================================================


@given(primary=primary_signals(), worker=worker_signals())
@settings(max_examples=500)
def test_classification_is_valid(primary: PrimarySignals, worker: WorkerSignals):
    """Property: Classification always returns a valid enum value."""
    result = classify_bottleneck(primary, worker)
    assert result in BottleneckClassification


@given(primary=primary_signals(), worker=worker_signals())
@settings(max_examples=300)
def test_classification_is_deterministic(primary: PrimarySignals, worker: WorkerSignals):
    """Property: Same inputs always produce same classification."""
    result1 = classify_bottleneck(primary, worker)
    result2 = classify_bottleneck(primary, worker)
    assert result1 == result2


@given(primary=primary_signals())
@settings(max_examples=200)
def test_healthy_workers_not_worker_limited(primary: PrimarySignals):
    """Property: When workers have plenty of capacity, classification is never WORKER_LIMITED."""
    healthy_worker = WorkerSignals(
        wft_schedule_to_start_p95_ms=5,
        wft_schedule_to_start_p99_ms=10,
        activity_schedule_to_start_p95_ms=10,
        activity_schedule_to_start_p99_ms=20,
        workflow_slots_available=200,
        workflow_slots_used=10,
        activity_slots_available=200,
        activity_slots_used=10,
        workflow_pollers=16,
        activity_pollers=16,
    )
    result = classify_bottleneck(primary, healthy_worker)
    assert result != BottleneckClassification.WORKER_LIMITED


@given(worker=worker_signals())
@settings(max_examples=200)
def test_healthy_server_not_server_limited(worker: WorkerSignals):
    """Property: When server has low backlog and fast persistence, never SERVER_LIMITED."""
    healthy_primary = PrimarySignals(
        state_transitions={"throughput_per_sec": 200, "latency_p95_ms": 10, "latency_p99_ms": 20},
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
    result = classify_bottleneck(healthy_primary, worker)
    assert result != BottleneckClassification.SERVER_LIMITED


def test_exhausted_slots_is_worker_limited():
    """Property: When workflow slots are exhausted and server is healthy, WORKER_LIMITED."""
    healthy_primary = PrimarySignals(
        state_transitions={"throughput_per_sec": 200, "latency_p95_ms": 10, "latency_p99_ms": 20},
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
    exhausted_worker = WorkerSignals(
        wft_schedule_to_start_p95_ms=5,
        wft_schedule_to_start_p99_ms=10,
        activity_schedule_to_start_p95_ms=10,
        activity_schedule_to_start_p99_ms=20,
        workflow_slots_available=0,  # Exhausted
        workflow_slots_used=200,
        activity_slots_available=100,
        activity_slots_used=100,
        workflow_pollers=16,
        activity_pollers=16,
    )
    result = classify_bottleneck(healthy_primary, exhausted_worker)
    assert result == BottleneckClassification.WORKER_LIMITED


def test_both_stressed_is_mixed():
    """Property: When both server and workers are stressed, classification is MIXED."""
    stressed_primary = PrimarySignals(
        state_transitions={"throughput_per_sec": 200, "latency_p95_ms": 10, "latency_p99_ms": 20},
        workflow_completion={"completion_rate": 0.99, "success_per_sec": 100, "failed_per_sec": 0},
        history={
            "backlog_age_sec": 60,
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
    exhausted_worker = WorkerSignals(
        wft_schedule_to_start_p95_ms=5,
        wft_schedule_to_start_p99_ms=10,
        activity_schedule_to_start_p95_ms=10,
        activity_schedule_to_start_p99_ms=20,
        workflow_slots_available=0,
        workflow_slots_used=200,
        activity_slots_available=100,
        activity_slots_used=100,
        workflow_pollers=16,
        activity_pollers=16,
    )
    result = classify_bottleneck(stressed_primary, exhausted_worker)
    assert result == BottleneckClassification.MIXED


def test_both_healthy_is_healthy():
    """Property: When both server and workers are healthy, classification is HEALTHY."""
    healthy_primary = PrimarySignals(
        state_transitions={"throughput_per_sec": 200, "latency_p95_ms": 10, "latency_p99_ms": 20},
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
    healthy_worker = WorkerSignals(
        wft_schedule_to_start_p95_ms=5,
        wft_schedule_to_start_p99_ms=10,
        activity_schedule_to_start_p95_ms=10,
        activity_schedule_to_start_p99_ms=20,
        workflow_slots_available=200,
        workflow_slots_used=10,
        activity_slots_available=200,
        activity_slots_used=10,
        workflow_pollers=16,
        activity_pollers=16,
    )
    result = classify_bottleneck(healthy_primary, healthy_worker)
    assert result == BottleneckClassification.HEALTHY


# =============================================================================
# WORKER SCALING RULES
# =============================================================================


@given(worker=worker_signals())
@settings(max_examples=300)
def test_never_scale_down_at_zero_slots(worker: WorkerSignals):
    """Property: NEVER_SCALE_DOWN_AT_ZERO fires when slots are exhausted.

    When workflow_slots_available == 0 or activity_slots_available == 0,
    the rule MUST fire regardless of other signals.
    """
    if worker.workflow_slots_available == 0 or worker.activity_slots_available == 0:
        warnings = evaluate_worker_scaling_rules(worker)
        rule_names = [w.rule for w in warnings]
        assert "NEVER_SCALE_DOWN_AT_ZERO" in rule_names, (
            f"NEVER_SCALE_DOWN_AT_ZERO should fire when slots exhausted. "
            f"workflow_slots={worker.workflow_slots_available}, "
            f"activity_slots={worker.activity_slots_available}"
        )


@given(worker=worker_signals())
@settings(max_examples=300)
def test_scale_down_blocked_at_zero_slots(worker: WorkerSignals):
    """Property: Scale-down is BLOCKED when slots are exhausted.

    Proposing scale_down with exhausted slots must produce a critical warning.
    """
    if worker.workflow_slots_available == 0 or worker.activity_slots_available == 0:
        warnings = evaluate_worker_scaling_rules(worker, proposed_action="scale_down")
        critical_warnings = [w for w in warnings if w.severity == "critical"]
        assert len(critical_warnings) >= 2, (
            "Scale-down at zero slots should produce at least 2 critical warnings "
            "(the rule + the block)"
        )


def test_poller_executor_mismatch():
    """Property: Warning fires when pollers exceed executor slots."""
    mismatched = WorkerSignals(
        wft_schedule_to_start_p95_ms=5,
        wft_schedule_to_start_p99_ms=10,
        activity_schedule_to_start_p95_ms=10,
        activity_schedule_to_start_p99_ms=20,
        workflow_slots_available=5,
        workflow_slots_used=5,
        activity_slots_available=5,
        activity_slots_used=5,
        workflow_pollers=50,  # Way more pollers than slots
        activity_pollers=50,
    )
    warnings = evaluate_worker_scaling_rules(mismatched)
    rule_names = [w.rule for w in warnings]
    assert "POLLER_EXECUTOR_MISMATCH" in rule_names


def test_sticky_queue_warning_on_scale_up():
    """Property: Sticky queue warning fires when scaling up with long-running workflows."""
    worker = WorkerSignals(
        wft_schedule_to_start_p95_ms=5,
        wft_schedule_to_start_p99_ms=10,
        activity_schedule_to_start_p95_ms=10,
        activity_schedule_to_start_p99_ms=20,
        workflow_slots_available=100,
        workflow_slots_used=100,
        activity_slots_available=100,
        activity_slots_used=100,
        workflow_pollers=16,
        activity_pollers=16,
    )
    context = WorkerScalingContext(has_long_running_workflows=True)
    warnings = evaluate_worker_scaling_rules(worker, proposed_action="scale_up", context=context)
    rule_names = [w.rule for w in warnings]
    assert "STICKY_QUEUE_WARNING" in rule_names


def test_no_warnings_when_healthy():
    """Property: No warnings when workers are healthy and no scaling proposed."""
    healthy = WorkerSignals(
        wft_schedule_to_start_p95_ms=5,
        wft_schedule_to_start_p99_ms=10,
        activity_schedule_to_start_p95_ms=10,
        activity_schedule_to_start_p99_ms=20,
        workflow_slots_available=200,
        workflow_slots_used=10,
        activity_slots_available=200,
        activity_slots_used=10,
        workflow_pollers=16,
        activity_pollers=16,
    )
    warnings = evaluate_worker_scaling_rules(healthy)
    assert len(warnings) == 0, f"Healthy workers should produce no warnings, got: {warnings}"
