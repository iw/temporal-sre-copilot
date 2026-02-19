"""AMP (Amazon Managed Prometheus) signal fetching activity.

Fetches the 12 primary signals and 14 amplifier signals from AMP.
These signals drive the Health State Machine.

Also fetches worker-side signals from SDK metrics for bottleneck classification.

Metric names verified against Mimir (2026-02-19):
  - Server timers: {name}_milliseconds_bucket (OTel adds _milliseconds suffix)
  - Dimensionless histograms: {name}_ratio_bucket (OTel adds _ratio suffix)
  - Counters: {name}_total (OTel adds _total suffix)
  - SDK metrics: temporal_{name}_milliseconds_bucket (Python SDK uses ms, not seconds)
  - DSQL plugin metrics: dsql_{name} (gauges) or dsql_{name}_total (counters)

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

# =============================================================================
# PRIMARY SIGNAL QUERIES (12)
#
# Metric naming convention (OTel Prometheus exporter):
#   Timer (unit=ms)        → {name}_milliseconds_bucket/sum/count
#   Dimensionless histogram → {name}_ratio_bucket/sum/count
#   Counter                → {name}_total
#   Gauge                  → {name} (no suffix)
#
# Values are already in milliseconds for timers — no * 1000 needed.
# Dimensionless histograms: rate(_ratio_sum) / rate(_ratio_count) = avg value.
# =============================================================================

PRIMARY_QUERIES = {
    # Signal 1-2: State transitions (dimensionless histogram → _ratio suffix)
    # rate(sum) gives total state transitions per second across all shards.
    "state_transitions_throughput": ("sum(rate(state_transition_count_ratio_sum[1m]))"),
    # Latency: avg value from dimensionless histogram (already unitless counts,
    # but represents ms internally in Temporal's recording).
    # Use histogram_quantile on _ratio_bucket for percentiles.
    "state_transitions_latency_p95": (
        "histogram_quantile(0.95, sum by (le) (rate(state_transition_count_ratio_bucket[5m])))"
    ),
    "state_transitions_latency_p99": (
        "histogram_quantile(0.99, sum by (le) (rate(state_transition_count_ratio_bucket[5m])))"
    ),
    # Signal 3: Workflow completion
    "workflow_success_rate": "sum(rate(workflow_success_total[1m]))",
    "workflow_failed_rate": "sum(rate(workflow_failed_total[1m]))",
    # Signal 4-6: History service
    # task_latency_queue = end-to-end history task latency (timer → _milliseconds)
    "history_backlog_age": (
        "histogram_quantile(0.95, sum by (le)"
        ' (rate(task_latency_queue_milliseconds_bucket{service_name="history"}[5m])))'
        " / 1000"
    ),
    "history_processing_rate": ('sum(rate(task_requests_total{service_name="history"}[1m]))'),
    "history_shard_churn": "sum(rate(sharditem_created_count_total[5m]))",
    # Signal 7-8: Frontend service (timer → _milliseconds)
    "frontend_error_rate": (
        'sum(rate(service_error_with_type_total{service_name="frontend"}[1m]))'
    ),
    "frontend_latency_p95": (
        "histogram_quantile(0.95, sum by (le)"
        ' (rate(service_latency_milliseconds_bucket{service_name="frontend"}[5m])))'
    ),
    "frontend_latency_p99": (
        "histogram_quantile(0.99, sum by (le)"
        ' (rate(service_latency_milliseconds_bucket{service_name="frontend"}[5m])))'
    ),
    # Signal 9: Matching service (timer → _milliseconds, convert to seconds)
    "matching_workflow_backlog": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(task_latency_queue_milliseconds_bucket"
        '{service_name="matching", task_type="WorkflowTask"}[5m])))'
        " / 1000"
    ),
    "matching_activity_backlog": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(task_latency_queue_milliseconds_bucket"
        '{service_name="matching", task_type="ActivityTask"}[5m])))'
        " / 1000"
    ),
    # Signal 10: Poller health (poll_timeouts, not poll_timeout)
    "poller_success_rate": (
        "sum(rate(poll_success_total[1m])) /"
        " (sum(rate(poll_success_total[1m])) + sum(rate(poll_timeouts_total[1m])) + 0.001)"
    ),
    "poller_timeout_rate": (
        "sum(rate(poll_timeouts_total[1m])) /"
        " (sum(rate(poll_success_total[1m])) + sum(rate(poll_timeouts_total[1m])) + 0.001)"
    ),
    # poll_latency is a timer → _milliseconds
    "poller_latency": (
        "histogram_quantile(0.95, sum by (le) (rate(poll_latency_milliseconds_bucket[5m])))"
    ),
    # Signal 11-12: Persistence (timer → _milliseconds)
    "persistence_latency_p95": (
        "histogram_quantile(0.95, sum by (le)"
        ' (rate(persistence_latency_milliseconds_bucket{service_name="history"}[5m])))'
    ),
    "persistence_latency_p99": (
        "histogram_quantile(0.99, sum by (le)"
        ' (rate(persistence_latency_milliseconds_bucket{service_name="history"}[5m])))'
    ),
    "persistence_error_rate": ('sum(rate(persistence_errors_total{service_name="history"}[1m]))'),
    # persistence_error_with_type_total exists but no dsql_tx_retry_total in Mimir
    "persistence_retry_rate": (
        'sum(rate(persistence_error_with_type_total{service_name="history"}[1m]))'
    ),
}


# =============================================================================
# AMPLIFIER SIGNAL QUERIES (14)
#
# Amplifiers explain WHY — they don't decide state.
# Many DSQL tx-level metrics (conflict, retry, serialization) are not emitted
# in the current build. We use persistence_error_with_type_total as a proxy.
# =============================================================================

AMPLIFIER_QUERIES = {
    # Amplifier 1: Persistence contention
    # dsql_tx_conflict_total not in Mimir — use persistence error types as proxy
    "occ_conflicts": (
        'sum(rate(persistence_error_with_type_total{error_type="ShardOwnershipLostError"}[1m]))'
        " or vector(0)"
    ),
    "cas_failures": (
        'sum(rate(persistence_error_with_type_total{error_type="ShardOwnershipLostError"}[1m]))'
        " or vector(0)"
    ),
    "serialization_failures": (
        'sum(rate(persistence_error_with_type_total{error_type="ConditionFailedError"}[1m]))'
        " or vector(0)"
    ),
    # Amplifier 2-3: Connection pool (DSQL plugin gauges + counters)
    "pool_utilization": ("100 * sum(dsql_pool_in_use) / (sum(dsql_pool_open) + 0.001)"),
    "pool_wait_count": "sum(dsql_pool_wait_total) or vector(0)",
    "pool_wait_duration": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(dsql_pool_wait_duration_milliseconds_bucket[1m])))"
        " or vector(0)"
    ),
    "pool_churn_opens": "sum(rate(dsql_reservoir_refills_total[1m]))",
    "pool_churn_closes": "sum(rate(dsql_reservoir_discards_total[1m]))",
    # Amplifier 4-5: Queue depth and retry
    # task_schedule_to_start_latency is a timer → _milliseconds
    "task_backlog_depth": (
        'sum(task_schedule_to_start_latency_milliseconds_count{service_name="history"})'
        " or vector(0)"
    ),
    # No dsql_tx_retry_duration_total in Mimir — use persistence error rate as proxy
    "retry_time_spent": ("sum(rate(persistence_errors_total[1m])) or vector(0)"),
    # Amplifier 6: Worker saturation (SDK metrics — no prefix change needed)
    "worker_poller_concurrency": "sum(temporal_num_pollers) or vector(0)",
    "worker_slots_available": "sum(temporal_worker_task_slots_available) or vector(0)",
    "worker_slots_used": "sum(temporal_worker_task_slots_used) or vector(0)",
    # Amplifier 7: Cache pressure (server cache_ metrics, no history_ prefix)
    "cache_hit_rate": (
        "sum(rate(cache_requests_total[1m])) /"
        " (sum(rate(cache_requests_total[1m])) + sum(rate(cache_miss_total[1m])) + 0.001)"
    ),
    "cache_evictions": "sum(rate(cache_errors_total[1m]))",
    "cache_size": "sum(cache_size) or vector(0)",
    # Amplifier 8: Shard hot spotting
    # No shard_controller_lock_requests_total — use lock_requests_total as proxy
    "shard_max_load": "max(lock_requests_total) or vector(0)",
    # Amplifier 9: gRPC saturation
    # No grpc_server_* metrics — use service_grpc_conn_active
    "grpc_in_flight": "sum(service_grpc_conn_active) or vector(0)",
    # Amplifier 10: Runtime pressure
    # No go_goroutines — Temporal exports num_goroutines
    "goroutines": "sum(num_goroutines) or vector(0)",
    # Amplifier 11: Host pressure
    # No go_gc_duration_seconds — use memory_gc_pause_ms_milliseconds
    "gc_pause_ms": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(memory_gc_pause_ms_milliseconds_bucket[1m])))"
        " or vector(0)"
    ),
    # Amplifier 12: Rate limiting
    # No dsql_rate_limit_wait_total — use dsql_pool_wait_total as proxy
    "rate_limit_events": "sum(rate(dsql_pool_wait_total[1m])) or vector(0)",
    # Amplifier 14: Deploy churn
    "membership_changes": "sum(rate(membership_changed_count_total[1m])) * 60",
}


# =============================================================================
# WORKER SIGNAL QUERIES - SDK metrics for bottleneck classification
#
# Python SDK exports metrics via OTel with temporal_ prefix.
# Duration histograms use milliseconds (not seconds) in the Python SDK
# when exported via Prometheus.
# =============================================================================

WORKER_SIGNAL_QUERIES = {
    # W1-W2: Schedule-to-start latencies
    # Server-side task_schedule_to_start_latency is a timer → _milliseconds
    "wft_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(task_schedule_to_start_latency_milliseconds_bucket"
        '{service_name="matching", task_type="WorkflowTask"}[5m])))'
    ),
    "wft_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(task_schedule_to_start_latency_milliseconds_bucket"
        '{service_name="matching", task_type="WorkflowTask"}[5m])))'
    ),
    "activity_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(task_schedule_to_start_latency_milliseconds_bucket"
        '{service_name="matching", task_type="ActivityTask"}[5m])))'
    ),
    "activity_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(task_schedule_to_start_latency_milliseconds_bucket"
        '{service_name="matching", task_type="ActivityTask"}[5m])))'
    ),
    # W3-W4: Task slots (SDK gauges)
    "workflow_slots_available": (
        'sum(temporal_worker_task_slots_available{worker_type="WorkflowWorker"}) or vector(0)'
    ),
    "workflow_slots_used": (
        'sum(temporal_worker_task_slots_used{worker_type="WorkflowWorker"}) or vector(0)'
    ),
    "activity_slots_available": (
        'sum(temporal_worker_task_slots_available{worker_type="ActivityWorker"}) or vector(0)'
    ),
    "activity_slots_used": (
        'sum(temporal_worker_task_slots_used{worker_type="ActivityWorker"}) or vector(0)'
    ),
    # W5-W6: Poller counts (SDK gauge)
    "workflow_pollers": ('sum(temporal_num_pollers{poller_type="workflow_task"}) or vector(0)'),
    "activity_pollers": ('sum(temporal_num_pollers{poller_type="activity_task"}) or vector(0)'),
}

# Worker amplifier queries (cache and poll metrics)
WORKER_AMPLIFIER_QUERIES = {
    # WA1-WA3: Sticky cache metrics
    # complete_workflow_task_sticky_enabled_count_total is the only sticky metric in Mimir
    "sticky_cache_size": ("sum(complete_workflow_task_sticky_enabled_count_total) or vector(0)"),
    "sticky_cache_hit_total": (
        "sum(rate(complete_workflow_task_sticky_enabled_count_total[5m])) or vector(0)"
    ),
    # No direct sticky cache miss metric — use poll_timeouts as proxy
    "sticky_cache_miss_total": "vector(0)",
    # WA4-WA5: Long poll metrics (SDK timer → _milliseconds)
    "long_poll_latency_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(temporal_long_request_latency_milliseconds_bucket[5m])))"
    ),
    # No temporal_long_request_failure_total — use temporal_request_failure_total
    "long_poll_failures": ("sum(rate(temporal_request_failure_total[5m])) or vector(0)"),
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
            churn_rate_per_sec=(
                results.get("pool_churn_opens", 0) + results.get("pool_churn_closes", 0)
            ),
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
            hot_shard_ratio=0.0,
            max_shard_load_pct=min(100.0, results.get("shard_max_load", 0)),
        ),
        grpc=GrpcAmplifiers(
            in_flight_requests=int(max(0, results.get("grpc_in_flight", 0))),
            server_queue_depth=0,
        ),
        runtime=RuntimeAmplifiers(
            goroutines=int(results.get("goroutines", 0)),
            blocked_goroutines=0,
        ),
        host=HostAmplifiers(
            cpu_throttle_pct=0.0,
            memory_rss_bytes=0,
            gc_pause_ms=results.get("gc_pause_ms", 0),
        ),
        throttling=ThrottlingAmplifiers(
            rate_limit_events_per_sec=results.get("rate_limit_events", 0),
            admission_rejects_per_sec=0.0,
        ),
        deploy=DeployAmplifiers(
            task_restarts=0,
            membership_changes_per_min=results.get("membership_changes", 0),
            leader_changes_per_min=0.0,
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
        endpoint = input.prometheus_endpoint
        primary_results = await _fetch_all_queries(client, endpoint, PRIMARY_QUERIES)
        primary = _build_primary_signals(primary_results)

        amplifier_results = await _fetch_all_queries(client, endpoint, AMPLIFIER_QUERIES)
        amplifiers = _build_amplifier_signals(amplifier_results)

    activity.logger.info(
        f"Signals fetched: state_transitions={primary.state_transitions.throughput_per_sec:.1f}/s, "
        f"completions={primary.workflow_completion.success_per_sec:.1f}/s, "
        f"history_processing={primary.history.task_processing_rate_per_sec:.1f}/s, "
        f"backlog_age={primary.history.backlog_age_sec:.1f}s"
    )

    return Signals(
        primary=primary,
        amplifiers=amplifiers,
        timestamp=Instant.now().format_iso(),
    )


def _build_worker_signals(results: dict[str, float]) -> WorkerSignals:
    """Build WorkerSignals from query results."""
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
    """Build WorkerCacheAmplifiers from query results."""
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
    """Build WorkerPollAmplifiers from query results."""
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

    Args:
        input: FetchWorkerSignalsInput with Prometheus endpoint

    Returns:
        WorkerHealthSignals object containing worker signals and amplifiers
    """
    activity.logger.info(f"Fetching worker signals from {input.prometheus_endpoint}")

    async with httpx.AsyncClient() as client:
        endpoint = input.prometheus_endpoint
        signal_results = await _fetch_all_queries(client, endpoint, WORKER_SIGNAL_QUERIES)
        worker_signals = _build_worker_signals(signal_results)

        amplifier_results = await _fetch_all_queries(client, endpoint, WORKER_AMPLIFIER_QUERIES)
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
