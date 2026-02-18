"""Health State Machine - Deterministic health evaluation.

Key Principle: "Rules decide, AI explains"
This module contains the deterministic rules that evaluate health state.
NO LLM is involved in state transitions.

Health State Gates:
- CRITICAL: Forward progress collapsed (signals 1/3/4/5) or backlog age critical
- STRESSED: Progress continues but latency + backlog trending wrong (signals 2/4/8/11)
- HAPPY: Otherwise

Signal Reference:
1. State transition throughput
2. State transition latency (p95/p99)
3. Workflow completion rate
4. History backlog age
5. History task processing rate
6. History shard churn rate
7. Frontend error rate
8. Frontend latency (p95/p99)
9. Matching backlog age
10. Poller health
11. Persistence latency (p95/p99)
12. Persistence error/retry rate

INVARIANT: Happy → Critical transition MUST go through Stressed.

Anti-flap Design:
- Critical requires sustained conditions (consecutive_critical_threshold)
- Recovery from Critical requires signals to clear a hysteresis band
- Completion rate gate only fires when there's meaningful demand
- Healthy thresholds are workload-relative, not absolute
"""

from .config import CriticalThresholds, HealthyThresholds, StressedThresholds
from .signals import (
    BottleneckClassification,
    HealthState,
    PrimarySignals,
    WorkerSignals,
)

# How many consecutive evaluations must show Critical before we transition.
# At 30s observation intervals, 3 consecutive = 90 seconds of sustained failure.
CONSECUTIVE_CRITICAL_THRESHOLD = 3


def evaluate_health_state(
    primary: PrimarySignals,
    current_state: HealthState,
    critical: CriticalThresholds | None = None,
    stressed: StressedThresholds | None = None,
    healthy: HealthyThresholds | None = None,
    *,
    consecutive_critical_count: int = 0,
) -> tuple[HealthState, int]:
    """Evaluate health state from signals using deterministic rules.

    This function is the core of the Health State Machine.
    It uses ONLY deterministic rules - NO LLM involvement.

    Args:
        primary: Forward progress indicators (12 signals)
        current_state: Current health state (for transition validation)
        critical: Thresholds for CRITICAL state
        stressed: Thresholds for STRESSED state
        healthy: Thresholds for HAPPY state
        consecutive_critical_count: How many consecutive evaluations have
            triggered critical gates. Caller must track and pass this in.

    Returns:
        Tuple of (new health state, updated consecutive critical count).
        The caller must persist the count for the next evaluation.
    """
    if critical is None:
        critical = CriticalThresholds()
    if stressed is None:
        stressed = StressedThresholds()
    if healthy is None:
        healthy = HealthyThresholds()

    # Idle cluster detection: zero throughput with zero errors/backlog
    # means no work is being submitted — not that something is broken.
    if _is_idle(primary):
        return HealthState.HAPPY, 0

    # Check CRITICAL gates first (any one triggers)
    if _is_critical(primary, critical):
        new_count = consecutive_critical_count + 1

        if new_count >= CONSECUTIVE_CRITICAL_THRESHOLD:
            # Sustained critical — transition (with invariant applied)
            return _apply_transition_invariant(current_state, HealthState.CRITICAL), new_count

        # Not yet sustained — report STRESSED as early warning, carry the count
        return _apply_transition_invariant(current_state, HealthState.STRESSED), new_count

    # Critical gates not triggered — reset the counter
    new_count = 0

    # Recovery hysteresis: when currently CRITICAL, require signals to be
    # clearly better than the stressed threshold before recovering.
    # This prevents flapping at the Critical/Stressed boundary.
    if current_state == HealthState.CRITICAL and _is_near_critical(primary, critical):
        return HealthState.STRESSED, new_count

    # Check STRESSED gates (trending wrong)
    if _is_stressed(primary, stressed):
        return HealthState.STRESSED, new_count

    # Check HAPPY gates (all must pass)
    if _is_healthy(primary, healthy):
        return HealthState.HAPPY, new_count

    # Default to STRESSED if between thresholds
    return HealthState.STRESSED, new_count


def _is_idle(primary: PrimarySignals) -> bool:
    """Detect an idle cluster — no work submitted, not broken.

    An idle cluster has:
    - Zero or near-zero throughput (no work to do)
    - Zero errors (nothing is failing)
    - Zero backlog (nothing is waiting)
    - Zero workflow failures

    This distinguishes "quiet" from "broken." A broken cluster
    typically has errors, backlog buildup, or non-zero failure rates.
    """
    has_no_throughput = (
        primary.state_transitions.throughput_per_sec < 1.0
        and primary.history.task_processing_rate_per_sec < 1.0
    )
    has_no_errors = (
        primary.frontend.error_rate_per_sec < 0.1
        and primary.persistence.error_rate_per_sec < 0.1
        and primary.workflow_completion.failed_per_sec < 0.1
    )
    has_no_backlog = (
        primary.history.backlog_age_sec < 1.0
        and primary.matching.workflow_backlog_age_sec < 1.0
        and primary.matching.activity_backlog_age_sec < 1.0
    )

    return has_no_throughput and has_no_errors and has_no_backlog


def _is_critical(
    primary: PrimarySignals,
    thresholds: CriticalThresholds,
) -> bool:
    """Check if any CRITICAL gate is triggered.

    CRITICAL if forward progress collapses:
    - Signal 1: State transition throughput drops below minimum
    - Signal 3: Workflow completion rate drops below minimum (demand-gated)
    - Signal 4: History backlog age exceeds critical threshold
    - Signal 5: History processing rate drops below minimum
    - Signal 12: Persistence error rate exceeds maximum
    """
    # Signal 1: State transition throughput collapsed
    if primary.state_transitions.throughput_per_sec < thresholds.state_transitions_min_per_sec:
        return True

    # Signal 3: Workflow completion rate collapsed — but only when there's
    # meaningful demand. During ramp-up, completions lag behind starts by
    # design. We require at least some completions+failures flowing before
    # treating a low ratio as a real problem.
    total_terminal = (
        primary.workflow_completion.success_per_sec + primary.workflow_completion.failed_per_sec
    )
    if (
        total_terminal >= thresholds.completion_rate_demand_floor_per_sec
        and primary.workflow_completion.completion_rate < thresholds.workflow_completion_rate_min
    ):
        return True

    # Signal 4: History backlog age critical
    if primary.history.backlog_age_sec > thresholds.history_backlog_age_max_sec:
        return True

    # Signal 5: History processing rate collapsed
    if (
        primary.history.task_processing_rate_per_sec
        < thresholds.history_processing_rate_min_per_sec
    ):
        return True

    # Signal 12: Persistence failing (not just slow)
    return primary.persistence.error_rate_per_sec > thresholds.persistence_error_rate_max_per_sec


def _is_near_critical(
    primary: PrimarySignals,
    thresholds: CriticalThresholds,
) -> bool:
    """Check if signals are near critical thresholds (hysteresis band).

    When recovering from CRITICAL, we require signals to clear a margin
    above/below the critical thresholds before downgrading to STRESSED.
    This prevents flapping at the boundary.

    The margin is 50% of the distance between the threshold and a
    "clearly safe" value.
    """
    # Throughput: must be at least 50% above the critical floor
    if (
        primary.state_transitions.throughput_per_sec
        < thresholds.state_transitions_min_per_sec * 1.5
    ):
        return True

    # Backlog age: must be at least 25% below the critical ceiling
    if primary.history.backlog_age_sec > thresholds.history_backlog_age_max_sec * 0.75:
        return True

    # Processing rate: must be at least 50% above the critical floor
    return (
        primary.history.task_processing_rate_per_sec
        < thresholds.history_processing_rate_min_per_sec * 1.5
    )


def _is_stressed(
    primary: PrimarySignals,
    thresholds: StressedThresholds,
) -> bool:
    """Check if any STRESSED gate is triggered.

    STRESSED if progress continues but trending wrong:
    - Signal 2: State transition latency rising
    - Signal 4: History backlog age rising (but not critical)
    - Signal 8: Frontend latency rising
    - Signal 11: Persistence latency rising
    - Signal 6: Shard churn rate high
    - Signal 10: Poller timeout rate high
    """
    # Signal 2: State transition latency rising
    if primary.state_transitions.latency_p99_ms > thresholds.state_transition_latency_p99_max_ms:
        return True

    # Signal 4: History backlog age rising
    if primary.history.backlog_age_sec > thresholds.history_backlog_age_stress_sec:
        return True

    # Signal 8: Frontend latency rising
    if primary.frontend.latency_p99_ms > thresholds.frontend_latency_p99_max_ms:
        return True

    # Signal 11: Persistence latency rising
    if primary.persistence.latency_p99_ms > thresholds.persistence_latency_p99_max_ms:
        return True

    # Signal 6: Shard churn high
    if primary.history.shard_churn_rate_per_sec > thresholds.shard_churn_rate_max_per_sec:
        return True

    # Signal 10: Poller timeout rate high
    return primary.poller.poll_timeout_rate > thresholds.poller_timeout_rate_max


def _is_healthy(
    primary: PrimarySignals,
    thresholds: HealthyThresholds,
) -> bool:
    """Check if all HAPPY gates pass.

    HAPPY requires ALL of:
    - Signal 1: State transition throughput above healthy threshold
    - Signal 4: History backlog age below healthy threshold
    - Signal 3: Workflow completion rate above healthy threshold
    """
    return (
        primary.state_transitions.throughput_per_sec >= thresholds.state_transitions_healthy_per_sec
        and primary.history.backlog_age_sec <= thresholds.history_backlog_age_healthy_sec
        and primary.workflow_completion.completion_rate
        >= thresholds.workflow_completion_rate_healthy
    )


def _apply_transition_invariant(
    current_state: HealthState,
    raw_state: HealthState,
) -> HealthState:
    """Apply the transition invariant: Happy → Critical must go through Stressed.

    This prevents over-eager critical alerts. If the system was Happy and
    conditions suddenly become Critical, we first transition to Stressed
    to give the system time to recover.
    """
    if current_state == HealthState.HAPPY and raw_state == HealthState.CRITICAL:
        return HealthState.STRESSED
    return raw_state


# =============================================================================
# WORKER HEALTH MODEL - Bottleneck Classification
# Source: Temporal Workers presentation (Tihomir Surdilovic, 2024)
# =============================================================================

# Worker thresholds (from presentation)
WORKER_WFT_SCHEDULE_TO_START_HEALTHY_MS = 50.0  # < 50ms is healthy
WORKER_WFT_SCHEDULE_TO_START_STRESSED_MS = 200.0  # > 200ms is critical
WORKER_SLOTS_STRESSED_PCT = 0.1  # < 10% available = stressed


def classify_bottleneck(
    primary: PrimarySignals,
    worker: WorkerSignals,
) -> BottleneckClassification:
    """Classify whether bottleneck is server-side or worker-side.

    This is DETERMINISTIC - no LLM involved.

    The classification guides remediation:
    - SERVER_LIMITED: Scale server capacity, tune persistence
    - WORKER_LIMITED: Scale workers, increase executor slots
    - MIXED: Both need attention
    - HEALTHY: Neither constrained
    """
    server_stressed = _is_server_stressed(primary)
    worker_stressed = _is_worker_stressed(worker)

    if server_stressed and worker_stressed:
        return BottleneckClassification.MIXED
    elif server_stressed:
        return BottleneckClassification.SERVER_LIMITED
    elif worker_stressed:
        return BottleneckClassification.WORKER_LIMITED
    else:
        return BottleneckClassification.HEALTHY


def _is_server_stressed(primary: PrimarySignals) -> bool:
    """Check if server is the bottleneck."""
    return primary.history.backlog_age_sec > 30.0 or primary.persistence.latency_p95_ms > 100.0


def _is_worker_stressed(worker: WorkerSignals) -> bool:
    """Check if workers are the bottleneck."""
    if worker.workflow_slots_available == 0:
        return True
    if worker.activity_slots_available == 0:
        return True
    return worker.wft_schedule_to_start_p95_ms > WORKER_WFT_SCHEDULE_TO_START_HEALTHY_MS


# =============================================================================
# WORKER SCALING RULES - Deterministic, NEVER violated
# =============================================================================


class WorkerScalingWarning:
    """Warning about worker scaling decisions."""

    def __init__(self, rule: str, message: str, severity: str = "warning"):
        self.rule = rule
        self.message = message
        self.severity = severity

    def __repr__(self) -> str:
        return f"WorkerScalingWarning(rule={self.rule!r}, severity={self.severity!r})"


class WorkerScalingContext:
    """Additional context for worker scaling decisions."""

    def __init__(
        self,
        has_long_running_workflows: bool = False,
        sticky_cache_hit_rate: float = 1.0,
        worker_count: int = 1,
        proposed_scale_up_count: int = 0,
    ):
        self.has_long_running_workflows = has_long_running_workflows
        self.sticky_cache_hit_rate = sticky_cache_hit_rate
        self.worker_count = worker_count
        self.proposed_scale_up_count = proposed_scale_up_count


def evaluate_worker_scaling_rules(
    worker: WorkerSignals,
    proposed_action: str | None = None,
    context: WorkerScalingContext | None = None,
) -> list[WorkerScalingWarning]:
    """Evaluate worker scaling rules and return warnings.

    These rules are DETERMINISTIC and NEVER violated.
    """
    warnings: list[WorkerScalingWarning] = []

    # Rule 1: NEVER_SCALE_DOWN_AT_ZERO
    if worker.workflow_slots_available == 0 or worker.activity_slots_available == 0:
        warnings.append(
            WorkerScalingWarning(
                rule="NEVER_SCALE_DOWN_AT_ZERO",
                message=(
                    "Worker task slots exhausted."
                    " NEVER scale down workers in this state"
                    " - it worsens backlog."
                ),
                severity="critical",
            )
        )

        if proposed_action == "scale_down":
            warnings.append(
                WorkerScalingWarning(
                    rule="NEVER_SCALE_DOWN_AT_ZERO",
                    message=("BLOCKED: Cannot scale down workers when task_slots_available == 0."),
                    severity="critical",
                )
            )

    # Rule 2: STICKY_QUEUE_WARNING
    if context is not None and context.has_long_running_workflows and proposed_action == "scale_up":
        warnings.append(
            WorkerScalingWarning(
                rule="STICKY_QUEUE_WARNING",
                message=(
                    "Long-running workflows detected."
                    " New workers may not receive tasks for"
                    " workflows with updates due to sticky queues."
                    " Consider RESTART_TO_REDISTRIBUTE."
                ),
                severity="warning",
            )
        )

    # Rule 3: RESTART_TO_REDISTRIBUTE
    if context is not None:
        if context.sticky_cache_hit_rate < 0.5 and context.worker_count > 1:
            warnings.append(
                WorkerScalingWarning(
                    rule="RESTART_TO_REDISTRIBUTE",
                    message=(
                        f"Sticky cache hit rate is low"
                        f" ({context.sticky_cache_hit_rate:.0%})."
                        " Consider rolling restart of existing"
                        " workers to redistribute workflow state."
                    ),
                    severity="warning",
                )
            )

        if (
            context.has_long_running_workflows
            and context.proposed_scale_up_count > 0
            and context.proposed_scale_up_count >= context.worker_count
        ):
            n = context.proposed_scale_up_count
            warnings.append(
                WorkerScalingWarning(
                    rule="RESTART_TO_REDISTRIBUTE",
                    message=(
                        f"Scaling up by {n} workers with"
                        " long-running workflows. Consider"
                        " restarting a percentage of existing"
                        " workers to redistribute sticky work"
                        " to new workers."
                    ),
                    severity="warning",
                )
            )

    # Rule 4: POLLER_EXECUTOR_MISMATCH
    total_slots = (
        worker.workflow_slots_available
        + worker.workflow_slots_used
        + worker.activity_slots_available
        + worker.activity_slots_used
    )
    total_pollers = worker.workflow_pollers + worker.activity_pollers

    if total_pollers > total_slots and total_slots > 0:
        warnings.append(
            WorkerScalingWarning(
                rule="POLLER_EXECUTOR_MISMATCH",
                message=(
                    f"Pollers ({total_pollers}) exceed executor"
                    f" slots ({total_slots}). 'Makes no sense to"
                    " configure more pollers than executor slots.'"
                ),
                severity="warning",
            )
        )

    return warnings
