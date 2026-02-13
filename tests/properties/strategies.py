"""Hypothesis strategies for generating Copilot domain objects.

These strategies generate valid instances of signal models, health states,
and worker signals for property-based testing.
"""

from hypothesis import strategies as st

from copilot.models import (
    AmplifierSignals,
    CacheAmplifiers,
    ConnectionPoolAmplifiers,
    DeployAmplifiers,
    FrontendSignals,
    GrpcAmplifiers,
    HealthState,
    HistorySignals,
    HostAmplifiers,
    MatchingSignals,
    PersistenceAmplifiers,
    PersistenceSignals,
    PollerSignals,
    PrimarySignals,
    QueueAmplifiers,
    RuntimeAmplifiers,
    ShardAmplifiers,
    StateTransitionSignals,
    ThrottlingAmplifiers,
    WorkerAmplifiers,
    WorkerSignals,
    WorkflowCompletionSignals,
)

# =============================================================================
# HEALTH STATE
# =============================================================================

health_states = st.sampled_from(list(HealthState))

# =============================================================================
# PRIMARY SIGNAL STRATEGIES
# =============================================================================


@st.composite
def state_transition_signals(draw):
    return StateTransitionSignals(
        throughput_per_sec=draw(st.floats(min_value=0, max_value=1000, allow_nan=False)),
        latency_p95_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
        latency_p99_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
    )


@st.composite
def workflow_completion_signals(draw):
    return WorkflowCompletionSignals(
        completion_rate=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        success_per_sec=draw(st.floats(min_value=0, max_value=1000, allow_nan=False)),
        failed_per_sec=draw(st.floats(min_value=0, max_value=1000, allow_nan=False)),
    )


@st.composite
def history_signals(draw):
    return HistorySignals(
        backlog_age_sec=draw(st.floats(min_value=0, max_value=600, allow_nan=False)),
        task_processing_rate_per_sec=draw(st.floats(min_value=0, max_value=1000, allow_nan=False)),
        shard_churn_rate_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
    )


@st.composite
def frontend_signals(draw):
    return FrontendSignals(
        error_rate_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        latency_p95_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
        latency_p99_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
    )


@st.composite
def matching_signals(draw):
    return MatchingSignals(
        workflow_backlog_age_sec=draw(st.floats(min_value=0, max_value=600, allow_nan=False)),
        activity_backlog_age_sec=draw(st.floats(min_value=0, max_value=600, allow_nan=False)),
    )


@st.composite
def poller_signals(draw):
    return PollerSignals(
        poll_success_rate=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        poll_timeout_rate=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
        long_poll_latency_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
    )


@st.composite
def persistence_signals(draw):
    return PersistenceSignals(
        latency_p95_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
        latency_p99_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
        error_rate_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        retry_rate_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
    )


@st.composite
def primary_signals(draw):
    return PrimarySignals(
        state_transitions=draw(state_transition_signals()),
        workflow_completion=draw(workflow_completion_signals()),
        history=draw(history_signals()),
        frontend=draw(frontend_signals()),
        matching=draw(matching_signals()),
        poller=draw(poller_signals()),
        persistence=draw(persistence_signals()),
    )


# =============================================================================
# AMPLIFIER SIGNAL STRATEGIES
# =============================================================================


@st.composite
def amplifier_signals(draw):
    return AmplifierSignals(
        persistence=PersistenceAmplifiers(
            occ_conflicts_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            cas_failures_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            serialization_failures_per_sec=draw(
                st.floats(min_value=0, max_value=100, allow_nan=False)
            ),
        ),
        connection_pool=ConnectionPoolAmplifiers(
            utilization_pct=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            wait_count=draw(st.integers(min_value=0, max_value=1000)),
            wait_duration_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
            churn_rate_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            opens_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            closes_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        ),
        queue=QueueAmplifiers(
            task_backlog_depth=draw(st.integers(min_value=0, max_value=100000)),
            retry_time_spent_sec=draw(st.floats(min_value=0, max_value=1000, allow_nan=False)),
        ),
        worker=WorkerAmplifiers(
            poller_concurrency=draw(st.integers(min_value=0, max_value=100)),
            task_slots_available=draw(st.integers(min_value=0, max_value=1000)),
            task_slots_used=draw(st.integers(min_value=0, max_value=1000)),
        ),
        cache=CacheAmplifiers(
            hit_rate=draw(st.floats(min_value=0, max_value=1, allow_nan=False)),
            evictions_per_sec=draw(st.floats(min_value=0, max_value=1000, allow_nan=False)),
            size_bytes=draw(st.integers(min_value=0, max_value=10**9)),
        ),
        shard=ShardAmplifiers(
            hot_shard_ratio=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            max_shard_load_pct=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        ),
        grpc=GrpcAmplifiers(
            in_flight_requests=draw(st.integers(min_value=0, max_value=10000)),
            server_queue_depth=draw(st.integers(min_value=0, max_value=10000)),
        ),
        runtime=RuntimeAmplifiers(
            goroutines=draw(st.integers(min_value=0, max_value=100000)),
            blocked_goroutines=draw(st.integers(min_value=0, max_value=10000)),
        ),
        host=HostAmplifiers(
            cpu_throttle_pct=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            memory_rss_bytes=draw(st.integers(min_value=0, max_value=10**10)),
            gc_pause_ms=draw(st.floats(min_value=0, max_value=10000, allow_nan=False)),
        ),
        throttling=ThrottlingAmplifiers(
            rate_limit_events_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            admission_rejects_per_sec=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        ),
        deploy=DeployAmplifiers(
            task_restarts=draw(st.integers(min_value=0, max_value=100)),
            membership_changes_per_min=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
            leader_changes_per_min=draw(st.floats(min_value=0, max_value=100, allow_nan=False)),
        ),
    )


# =============================================================================
# WORKER SIGNAL STRATEGIES
# =============================================================================


@st.composite
def worker_signals(draw):
    return WorkerSignals(
        wft_schedule_to_start_p95_ms=draw(st.floats(min_value=0, max_value=5000, allow_nan=False)),
        wft_schedule_to_start_p99_ms=draw(st.floats(min_value=0, max_value=5000, allow_nan=False)),
        activity_schedule_to_start_p95_ms=draw(
            st.floats(min_value=0, max_value=5000, allow_nan=False)
        ),
        activity_schedule_to_start_p99_ms=draw(
            st.floats(min_value=0, max_value=5000, allow_nan=False)
        ),
        workflow_slots_available=draw(st.integers(min_value=0, max_value=500)),
        workflow_slots_used=draw(st.integers(min_value=0, max_value=500)),
        activity_slots_available=draw(st.integers(min_value=0, max_value=500)),
        activity_slots_used=draw(st.integers(min_value=0, max_value=500)),
        workflow_pollers=draw(st.integers(min_value=0, max_value=100)),
        activity_pollers=draw(st.integers(min_value=0, max_value=100)),
    )
