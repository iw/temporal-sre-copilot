"""AMP (Amazon Managed Prometheus) signal fetching activity.

Fetches the 12 primary signals and 14 amplifier signals from AMP.
These signals drive the Health State Machine.

Also fetches worker-side signals from SDK metrics for bottleneck classification.

Date/Time: Uses `whenever` library (UTC-first, Rust-backed).
"""

import httpx
from temporalio import activity
from whenever import Instant

from copilot.models import (
    AmplifierSignals,
    CacheAmplifiers,
    ConnectionPoolAmplifiers,
    DeployAmplifiers,
    FetchSignalsInput,
    FetchWorkerSignalsInput,
    FrontendSignals,
    GrpcAmplifiers,
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
    Signals,
    StateTransitionSignals,
    ThrottlingAmplifiers,
    WorkerAmplifiers,
    WorkerCacheAmplifiers,
    WorkerHealthSignals,
    WorkerPollAmplifiers,
    WorkerSignals,
    WorkflowCompletionSignals,
)

# PromQL queries for primary signals (12)
PRIMARY_QUERIES = {
    # Signal 1-2: State transitions
    "state_transitions_throughput": "sum(rate(state_transition_count_count[1m]))",
    "state_transitions_latency_p95": (
        "histogram_quantile(0.95, sum by (le) (rate(state_transition_count_bucket[5m]))) * 1000"
    ),
    "state_transitions_latency_p99": (
        "histogram_quantile(0.99, sum by (le) (rate(state_transition_count_bucket[5m]))) * 1000"
    ),
    # Signal 3: Workflow completion
    "workflow_success_rate": "sum(rate(workflow_success_total[1m]))",
    "workflow_failed_rate": (
        "sum(rate(workflow_failed_total[1m]) + "
        "rate(workflow_timeout_total[1m]) + "
        "rate(workflow_terminate_total[1m]))"
    ),
}

# More primary signal queries
PRIMARY_QUERIES.update(
    {
        # Signal 4-6: History service
        "history_backlog_age": (
            "histogram_quantile(0.95, sum by (le) "
            '(rate(task_latency_queue_bucket{service_name="history"}[5m])))'
        ),
        "history_processing_rate": 'sum(rate(task_requests_total{service_name="history"}[1m]))',
        "history_shard_churn": (
            "sum(rate(sharditem_created_count_total[5m])) + "
            "sum(rate(sharditem_removed_count_total[5m]))"
        ),
        # Signal 7-8: Frontend service
        "frontend_error_rate": (
            'sum(rate(service_error_with_type_total{service_name="frontend"}[1m]))'
        ),
        "frontend_latency_p95": (
            "histogram_quantile(0.95, sum by (le) "
            '(rate(service_latency_bucket{service_name="frontend"}[5m]))) * 1000'
        ),
        "frontend_latency_p99": (
            "histogram_quantile(0.99, sum by (le) "
            '(rate(service_latency_bucket{service_name="frontend"}[5m]))) * 1000'
        ),
        # Signal 9: Matching service
        "matching_workflow_backlog": (
            "histogram_quantile(0.95, sum by (le) "
            "(rate(task_latency_queue_bucket"
            '{service_name="matching", task_type="WorkflowTask"}[5m])))'
        ),
        "matching_activity_backlog": (
            "histogram_quantile(0.95, sum by (le) "
            "(rate(task_latency_queue_bucket"
            '{service_name="matching", task_type="ActivityTask"}[5m])))'
        ),
        # Signal 10: Poller health
        "poller_success_rate": (
            "sum(rate(poll_success_total[1m])) / "
            "(sum(rate(poll_success_total[1m])) + sum(rate(poll_timeout_total[1m])) + 0.001)"
        ),
        "poller_timeout_rate": (
            "sum(rate(poll_timeout_total[1m])) / "
            "(sum(rate(poll_success_total[1m])) + sum(rate(poll_timeout_total[1m])) + 0.001)"
        ),
        "poller_latency": (
            "histogram_quantile(0.95, sum by (le) (rate(poll_latency_bucket[5m]))) * 1000"
        ),
        # Signal 11-12: Persistence
        "persistence_latency_p95": (
            "histogram_quantile(0.95, sum by (le) "
            '(rate(persistence_latency_bucket{service_name="history"}[5m]))) * 1000'
        ),
        "persistence_latency_p99": (
            "histogram_quantile(0.99, sum by (le) "
            '(rate(persistence_latency_bucket{service_name="history"}[5m]))) * 1000'
        ),
        "persistence_error_rate": 'sum(rate(persistence_errors_total{service_name="history"}[1m]))',
        "persistence_retry_rate": "sum(rate(dsql_tx_retry_total[1m]))",
    }
)


# PromQL queries for amplifier signals (14)
AMPLIFIER_QUERIES = {
    # Amplifier 1: Persistence contention
    "occ_conflicts": "sum(rate(dsql_tx_conflict_total[1m]))",
    "cas_failures": 'sum(rate(persistence_errors_total{error_type="ShardOwnershipLost"}[1m]))',
    "serialization_failures": "sum(rate(dsql_tx_serialization_failure_total[1m]))",
    # Amplifier 2-3: Connection pool
    "pool_utilization": ("100 * sum(dsql_pool_in_use) / (sum(dsql_pool_open) + 0.001)"),
    "pool_wait_count": "sum(dsql_pool_wait_count)",
    "pool_wait_duration": "sum(rate(dsql_pool_wait_duration_total[1m])) * 1000",
    "pool_churn_opens": "sum(rate(dsql_reservoir_refills_total[1m]))",
    "pool_churn_closes": "sum(rate(dsql_reservoir_discards_total[1m]))",
    # Amplifier 4-5: Queue depth and retry
    "task_backlog_depth": 'sum(task_schedule_to_start_latency_count{service_name="history"})',
    "retry_time_spent": "sum(rate(dsql_tx_retry_duration_total[1m]))",
    # Amplifier 6: Worker saturation
    "worker_poller_concurrency": "sum(temporal_num_pollers)",
    "worker_slots_available": "sum(temporal_worker_task_slots_available)",
    "worker_slots_used": "sum(temporal_worker_task_slots_used)",
    # Amplifier 7: Cache pressure
    "cache_hit_rate": (
        "sum(rate(history_cache_hit_total[1m])) / "
        "(sum(rate(history_cache_hit_total[1m])) + sum(rate(history_cache_miss_total[1m])) + 0.001)"
    ),
    "cache_evictions": "sum(rate(history_cache_eviction_total[1m]))",
    "cache_size": "sum(history_cache_size)",
    # Amplifier 8: Shard hot spotting
    "shard_max_load": "max(shard_controller_lock_requests_total)",
    # Amplifier 9: gRPC saturation
    "grpc_in_flight": "sum(grpc_server_started_total) - sum(grpc_server_handled_total)",
    # Amplifier 10: Runtime pressure
    "goroutines": "sum(go_goroutines)",
    # Amplifier 11: Host pressure
    "gc_pause_ms": "sum(rate(go_gc_duration_seconds_sum[1m])) * 1000",
    # Amplifier 12: Rate limiting
    "rate_limit_events": "sum(rate(dsql_rate_limit_wait_total[1m]))",
    # Amplifier 14: Deploy churn
    "membership_changes": "sum(rate(membership_changed_total[1m])) * 60",
}


# =============================================================================
# WORKER SIGNAL QUERIES - SDK metrics for bottleneck classification
# Source: Temporal Workers presentation (Tihomir Surdilovic, 2024)
# =============================================================================

WORKER_SIGNAL_QUERIES = {
    # W1-W2: Schedule-to-start latencies (< 50ms healthy for WFT)
    "wft_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(temporal_workflow_task_schedule_to_start_latency_seconds_bucket[5m]))) * 1000"
    ),
    "wft_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le) "
        "(rate(temporal_workflow_task_schedule_to_start_latency_seconds_bucket[5m]))) * 1000"
    ),
    "activity_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(temporal_activity_schedule_to_start_latency_seconds_bucket[5m]))) * 1000"
    ),
    "activity_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le) "
        "(rate(temporal_activity_schedule_to_start_latency_seconds_bucket[5m]))) * 1000"
    ),
    # W3-W4: Task slots (0 = worker stops polling)
    "workflow_slots_available": (
        'sum(temporal_worker_task_slots_available{worker_type="WorkflowWorker"})'
    ),
    "workflow_slots_used": ('sum(temporal_worker_task_slots_used{worker_type="WorkflowWorker"})'),
    "activity_slots_available": (
        'sum(temporal_worker_task_slots_available{worker_type="ActivityWorker"})'
    ),
    "activity_slots_used": ('sum(temporal_worker_task_slots_used{worker_type="ActivityWorker"})'),
    # W5-W6: Poller counts
    "workflow_pollers": 'sum(temporal_num_pollers{poller_type="workflow_task"})',
    "activity_pollers": 'sum(temporal_num_pollers{poller_type="activity_task"})',
}

# Worker amplifier queries (cache and poll metrics)
WORKER_AMPLIFIER_QUERIES = {
    # WA1-WA3: Sticky cache metrics
    "sticky_cache_size": "sum(temporal_sticky_cache_size)",
    "sticky_cache_hit_total": "sum(rate(temporal_sticky_cache_hit_total[5m]))",
    "sticky_cache_miss_total": "sum(rate(temporal_sticky_cache_miss_total[5m]))",
    # WA4-WA5: Long poll metrics
    "long_poll_latency_p95": (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(temporal_long_request_latency_seconds_bucket[5m]))) * 1000"
    ),
    "long_poll_failures": "sum(rate(temporal_long_request_failure_total[5m]))",
}


async def _query_prometheus(
    client: httpx.AsyncClient,
    endpoint: str,
    query: str,
) -> float:
    """Execute a PromQL instant query and return the scalar result."""
    try:
        response = await client.get(
            f"{endpoint}/api/v1/query",
            params={"query": query},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        if data["status"] != "success":
            activity.logger.warning(f"Query failed: {query}, status: {data['status']}")
            return 0.0

        result = data.get("data", {}).get("result", [])
        if not result:
            return 0.0

        # Get the value from the first result
        value = result[0].get("value", [None, "0"])
        return float(value[1]) if value[1] != "NaN" else 0.0

    except Exception as e:
        activity.logger.warning(f"Query error: {query}, error: {e}")
        return 0.0


async def _fetch_all_queries(
    client: httpx.AsyncClient,
    endpoint: str,
    queries: dict[str, str],
) -> dict[str, float]:
    """Fetch all queries and return results as a dict."""
    results = {}
    for name, query in queries.items():
        results[name] = await _query_prometheus(client, endpoint, query)
    return results


def _build_primary_signals(results: dict[str, float]) -> PrimarySignals:
    """Build PrimarySignals from query results."""
    # Calculate workflow completion rate
    success = results.get("workflow_success_rate", 0)
    failed = results.get("workflow_failed_rate", 0)
    total = success + failed
    completion_rate = success / total if total > 0 else 1.0

    return PrimarySignals(
        state_transitions=StateTransitionSignals(
            throughput_per_sec=results.get("state_transitions_throughput", 0),
            latency_p95_ms=results.get("state_transitions_latency_p95", 0),
            latency_p99_ms=results.get("state_transitions_latency_p99", 0),
        ),
        workflow_completion=WorkflowCompletionSignals(
            completion_rate=min(1.0, max(0.0, completion_rate)),
            success_per_sec=success,
            failed_per_sec=failed,
        ),
        history=HistorySignals(
            backlog_age_sec=results.get("history_backlog_age", 0),
            task_processing_rate_per_sec=results.get("history_processing_rate", 0),
            shard_churn_rate_per_sec=results.get("history_shard_churn", 0),
        ),
        frontend=FrontendSignals(
            error_rate_per_sec=results.get("frontend_error_rate", 0),
            latency_p95_ms=results.get("frontend_latency_p95", 0),
            latency_p99_ms=results.get("frontend_latency_p99", 0),
        ),
        matching=MatchingSignals(
            workflow_backlog_age_sec=results.get("matching_workflow_backlog", 0),
            activity_backlog_age_sec=results.get("matching_activity_backlog", 0),
        ),
        poller=PollerSignals(
            poll_success_rate=min(1.0, max(0.0, results.get("poller_success_rate", 1.0))),
            poll_timeout_rate=min(1.0, max(0.0, results.get("poller_timeout_rate", 0))),
            long_poll_latency_ms=results.get("poller_latency", 0),
        ),
        persistence=PersistenceSignals(
            latency_p95_ms=results.get("persistence_latency_p95", 0),
            latency_p99_ms=results.get("persistence_latency_p99", 0),
            error_rate_per_sec=results.get("persistence_error_rate", 0),
            retry_rate_per_sec=results.get("persistence_retry_rate", 0),
        ),
    )


def _build_amplifier_signals(results: dict[str, float]) -> AmplifierSignals:
    """Build AmplifierSignals from query results."""
    return AmplifierSignals(
        persistence=PersistenceAmplifiers(
            occ_conflicts_per_sec=results.get("occ_conflicts", 0),
            cas_failures_per_sec=results.get("cas_failures", 0),
            serialization_failures_per_sec=results.get("serialization_failures", 0),
        ),
        connection_pool=ConnectionPoolAmplifiers(
            utilization_pct=min(100.0, max(0.0, results.get("pool_utilization", 0))),
            wait_count=int(results.get("pool_wait_count", 0)),
            wait_duration_ms=results.get("pool_wait_duration", 0),
            churn_rate_per_sec=results.get("pool_churn_opens", 0)
            + results.get("pool_churn_closes", 0),
            opens_per_sec=results.get("pool_churn_opens", 0),
            closes_per_sec=results.get("pool_churn_closes", 0),
        ),
        queue=QueueAmplifiers(
            task_backlog_depth=int(results.get("task_backlog_depth", 0)),
            retry_time_spent_sec=results.get("retry_time_spent", 0),
        ),
        worker=WorkerAmplifiers(
            poller_concurrency=int(results.get("worker_poller_concurrency", 0)),
            task_slots_available=int(results.get("worker_slots_available", 0)),
            task_slots_used=int(max(0, results.get("worker_slots_used", 0))),
        ),
        cache=CacheAmplifiers(
            hit_rate=min(1.0, max(0.0, results.get("cache_hit_rate", 1.0))),
            evictions_per_sec=results.get("cache_evictions", 0),
            size_bytes=int(results.get("cache_size", 0)),
        ),
        shard=ShardAmplifiers(
            hot_shard_ratio=0.0,  # Computed separately if needed
            max_shard_load_pct=min(100.0, results.get("shard_max_load", 0)),
        ),
        grpc=GrpcAmplifiers(
            in_flight_requests=int(max(0, results.get("grpc_in_flight", 0))),
            server_queue_depth=0,  # Not directly available
        ),
        runtime=RuntimeAmplifiers(
            goroutines=int(results.get("goroutines", 0)),
            blocked_goroutines=0,  # Not directly available
        ),
        host=HostAmplifiers(
            cpu_throttle_pct=0.0,  # From CloudWatch, not Prometheus
            memory_rss_bytes=0,  # From CloudWatch
            gc_pause_ms=results.get("gc_pause_ms", 0),
        ),
        throttling=ThrottlingAmplifiers(
            rate_limit_events_per_sec=results.get("rate_limit_events", 0),
            admission_rejects_per_sec=0.0,  # Not directly available
        ),
        deploy=DeployAmplifiers(
            task_restarts=0,  # From ECS, not Prometheus
            membership_changes_per_min=results.get("membership_changes", 0),
            leader_changes_per_min=0.0,  # Not directly available
        ),
    )


@activity.defn
async def fetch_signals_from_amp(input: FetchSignalsInput) -> Signals:
    """Fetch all signals from Amazon Managed Prometheus.

    This activity queries AMP for the 12 primary signals and 14 amplifier signals
    that drive the Health State Machine.

    Args:
        input: FetchSignalsInput with Prometheus endpoint

    Returns:
        Signals object containing primary and amplifier signals
    """
    activity.logger.info(f"Fetching signals from {input.prometheus_endpoint}")

    async with httpx.AsyncClient() as client:
        # Fetch primary signals
        endpoint = input.prometheus_endpoint
        primary_results = await _fetch_all_queries(client, endpoint, PRIMARY_QUERIES)
        primary = _build_primary_signals(primary_results)

        # Fetch amplifier signals
        amplifier_results = await _fetch_all_queries(client, endpoint, AMPLIFIER_QUERIES)
        amplifiers = _build_amplifier_signals(amplifier_results)

    activity.logger.info(
        f"Signals fetched: state_transitions={primary.state_transitions.throughput_per_sec:.1f}/s, "
        f"backlog_age={primary.history.backlog_age_sec:.1f}s"
    )

    return Signals(
        primary=primary,
        amplifiers=amplifiers,
        timestamp=Instant.now().format_iso(),
    )


def _build_worker_signals(results: dict[str, float]) -> WorkerSignals:
    """Build WorkerSignals from query results.

    Worker signals answer: "Can workers make forward progress?"
    Critical thresholds:
    - WFT schedule-to-start > 50ms = worker pressure
    - task_slots_available == 0 = worker stops polling entirely
    """
    return WorkerSignals(
        wft_schedule_to_start_p95_ms=results.get("wft_schedule_to_start_p95", 0),
        wft_schedule_to_start_p99_ms=results.get("wft_schedule_to_start_p99", 0),
        activity_schedule_to_start_p95_ms=results.get("activity_schedule_to_start_p95", 0),
        activity_schedule_to_start_p99_ms=results.get("activity_schedule_to_start_p99", 0),
        workflow_slots_available=int(results.get("workflow_slots_available", 0)),
        workflow_slots_used=int(results.get("workflow_slots_used", 0)),
        activity_slots_available=int(results.get("activity_slots_available", 0)),
        activity_slots_used=int(results.get("activity_slots_used", 0)),
        workflow_pollers=int(results.get("workflow_pollers", 0)),
        activity_pollers=int(results.get("activity_pollers", 0)),
    )


def _build_worker_cache_amplifiers(results: dict[str, float]) -> WorkerCacheAmplifiers:
    """Build WorkerCacheAmplifiers from query results.

    Sticky cache stores workflow state to avoid replaying history.
    Cache misses cause full history replay, increasing DB reads and latency.
    """
    hit_rate = results.get("sticky_cache_hit_total", 0)
    miss_rate = results.get("sticky_cache_miss_total", 0)
    total = hit_rate + miss_rate

    return WorkerCacheAmplifiers(
        sticky_cache_size=int(results.get("sticky_cache_size", 0)),
        sticky_cache_hit_rate=hit_rate / total if total > 0 else 1.0,
        sticky_cache_miss_rate_per_sec=miss_rate,
    )


def _build_worker_poll_amplifiers(
    results: dict[str, float],
    worker_signals: WorkerSignals,
) -> WorkerPollAmplifiers:
    """Build WorkerPollAmplifiers from query results.

    Long-poll latency and failures indicate network/service pressure.
    Poller/executor mismatch is a configuration anti-pattern.
    """
    # Calculate poller/executor mismatch
    total_slots = (
        worker_signals.workflow_slots_available
        + worker_signals.workflow_slots_used
        + worker_signals.activity_slots_available
        + worker_signals.activity_slots_used
    )
    total_pollers = worker_signals.workflow_pollers + worker_signals.activity_pollers
    mismatch = total_pollers > total_slots and total_slots > 0

    return WorkerPollAmplifiers(
        long_poll_latency_p95_ms=results.get("long_poll_latency_p95", 0),
        long_poll_failure_rate_per_sec=results.get("long_poll_failures", 0),
        poller_executor_mismatch=mismatch,
    )


@activity.defn
async def fetch_worker_signals_from_amp(input: FetchWorkerSignalsInput) -> WorkerHealthSignals:
    """Fetch worker-side signals from Amazon Managed Prometheus.

    This activity queries AMP for worker SDK metrics that enable
    bottleneck classification (server-limited vs worker-limited).

    Worker signals answer: "Can workers make forward progress?"

    Args:
        input: FetchWorkerSignalsInput with Prometheus endpoint

    Returns:
        WorkerHealthSignals object containing worker signals and amplifiers
    """
    activity.logger.info(f"Fetching worker signals from {input.prometheus_endpoint}")

    async with httpx.AsyncClient() as client:
        # Fetch worker signals
        endpoint = input.prometheus_endpoint
        signal_results = await _fetch_all_queries(client, endpoint, WORKER_SIGNAL_QUERIES)
        worker_signals = _build_worker_signals(signal_results)

        # Fetch worker amplifiers
        amplifier_results = await _fetch_all_queries(
            client, endpoint, WORKER_AMPLIFIER_QUERIES
        )
        cache_amplifiers = _build_worker_cache_amplifiers(amplifier_results)
        poll_amplifiers = _build_worker_poll_amplifiers(amplifier_results, worker_signals)

    activity.logger.info(
        "Worker signals fetched: "
        f"wft_schedule_to_start={worker_signals.wft_schedule_to_start_p95_ms:.1f}ms, "
        f"workflow_slots_available={worker_signals.workflow_slots_available}, "
        f"activity_slots_available={worker_signals.activity_slots_available}"
    )

    return WorkerHealthSignals(
        signals=worker_signals,
        cache=cache_amplifiers,
        poll=poll_amplifiers,
        timestamp=Instant.now().format_iso(),
    )
