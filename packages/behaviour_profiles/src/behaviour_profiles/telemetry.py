"""Telemetry collection for behaviour profiles.

Queries a Prometheus-compatible endpoint for curated metric aggregates over a time window.
Uses range queries with step intervals to compute min/max/mean/p50/p95/p99.

Metric names are aligned with the Grafana dashboards:
  - grafana/server/server.json (Temporal Server Health)
  - grafana/dsql/persistence.json (DSQL Persistence)
"""

from __future__ import annotations

import logging
import statistics

import httpx
from whenever import Instant

from behaviour_profiles.models import (
    DSQLPoolMetrics,
    ErrorMetrics,
    LatencyMetrics,
    MatchingMetrics,
    ResourceMetrics,
    TelemetrySummary,
    ThroughputMetrics,
)
from copilot_core.models import MetricAggregate, ServiceMetrics

logger = logging.getLogger("behaviour_profiles.telemetry")

# ---------------------------------------------------------------------------
# PromQL queries — aligned with actual Temporal server + DSQL plugin metrics
# ---------------------------------------------------------------------------

_QUERIES: dict[str, str] = {
    # -- Throughput --
    # workflow_timeout_total and workflow_terminate_total don't exist in Mimir;
    # use workflow_failed_total which captures all non-success terminal states.
    "workflows_started_per_sec": (
        "sum(rate(workflow_success_total[1m]) + rate(workflow_failed_total[1m]))"
    ),
    "workflows_completed_per_sec": "sum(rate(workflow_success_total[1m]))",
    "state_transitions_per_sec": "sum(rate(state_transition_count_ratio_sum[1m]))",
    # -- Latency (timers → _milliseconds suffix) --
    "workflow_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(service_latency_milliseconds_bucket{service_name='matching'}[5m])))"
    ),
    "workflow_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(service_latency_milliseconds_bucket{service_name='matching'}[5m])))"
    ),
    "activity_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(asyncmatch_latency_milliseconds_bucket{service_name='matching'}[5m])))"
    ),
    "activity_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(asyncmatch_latency_milliseconds_bucket{service_name='matching'}[5m])))"
    ),
    "persistence_latency_p95": (
        "histogram_quantile(0.95, sum by (le) (rate(persistence_latency_milliseconds_bucket[5m])))"
    ),
    "persistence_latency_p99": (
        "histogram_quantile(0.99, sum by (le) (rate(persistence_latency_milliseconds_bucket[5m])))"
    ),
    # -- Matching --
    "sync_match_rate": "sum(rate(poll_success_total[1m]))",
    "async_match_rate": "sum(rate(poll_timeouts_total[1m]))",
    "task_dispatch_latency": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(asyncmatch_latency_milliseconds_bucket{service_name='matching'}[5m])))"
    ),
    # no_poller_tasks_total doesn't exist; use approximate_backlog_count gauge
    "backlog_count": "sum(approximate_backlog_count) or vector(0)",
    "backlog_age": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(task_latency_queue_milliseconds_bucket{service_name='history'}[5m])))"
    ),
    # -- DSQL pool --
    "pool_open_count": "sum(dsql_reservoir_size) or sum(dsql_pool_idle) or vector(0)",
    "pool_in_use_count": "sum(dsql_pool_in_use) or vector(0)",
    "pool_idle_count": "sum(dsql_pool_idle) or vector(0)",
    "reservoir_size": "sum(dsql_reservoir_size) or vector(0)",
    # dsql_reservoir_empty_total doesn't exist; use dsql_pool_wait_total as proxy
    "reservoir_empty_events": "sum(rate(dsql_pool_wait_total[1m])) or vector(0)",
    "open_failures": "sum(rate(persistence_errors_total[1m]))",
    "reconnect_count": "sum(rate(dsql_reservoir_refills_total[1m]))",
    # -- Errors --
    # dsql_tx_conflict/exhausted/retry_total don't exist in Mimir;
    # use persistence_error_with_type_total as proxy.
    "occ_conflicts_per_sec": (
        'sum(rate(persistence_error_with_type_total{error_type="ShardOwnershipLostError"}[1m]))'
        " or vector(0)"
    ),
    "exhausted_retries_per_sec": (
        'sum(rate(persistence_error_with_type_total{error_type="ConditionFailedError"}[1m]))'
        " or vector(0)"
    ),
    "dsql_auth_failures": (
        "sum(rate(persistence_session_refresh_attempts_total[1m])) or vector(0)"
    ),
    # -- Resources --
    "worker_task_slot_utilization": "vector(0)",
}

# Per-service resource queries.
# Temporal server doesn't export process_cpu_seconds_total or process_resident_memory_bytes.
# It exports memory_heap, memory_allocated, num_goroutines as gauges.
# These are not per-service_name — they're per scrape job.
# Use vector(0) gracefully when metrics are absent.
_SERVICE_CPU_QUERY = "vector(0)"
_SERVICE_MEM_QUERY = 'sum(memory_heap{{job="temporal-{service}"}}) or vector(0)'
_SERVICES = ("history", "matching", "frontend", "worker")


async def collect_telemetry(
    *,
    amp_endpoint: str,
    start: str,
    end: str,
    step: str = "60s",
) -> TelemetrySummary:
    """Query Prometheus for all telemetry metrics over the given time window.

    Args:
        amp_endpoint: Prometheus-compatible query endpoint (Mimir or AMP).
        start: ISO 8601 start time.
        end: ISO 8601 end time.
        step: Prometheus range query step interval.
    """
    start_ts = str(Instant.parse_iso(start).timestamp())
    end_ts = str(Instant.parse_iso(end).timestamp())

    async with httpx.AsyncClient() as client:
        results: dict[str, MetricAggregate] = {}
        query_stats = {"total": 0, "empty": 0}

        for name, query in _QUERIES.items():
            query_stats["total"] += 1
            samples = await _range_query(client, amp_endpoint, query, start_ts, end_ts, step)
            if not samples:
                query_stats["empty"] += 1
                logger.info("No data for metric %s", name)
            results[name] = _aggregate(samples)

        # Per-service resource metrics (process-level, not container-level)
        service_cpu: dict[str, MetricAggregate] = {}
        service_mem: dict[str, MetricAggregate] = {}
        for svc in _SERVICES:
            cpu_samples = await _range_query(
                client, amp_endpoint, _SERVICE_CPU_QUERY.format(service=svc), start_ts, end_ts, step
            )
            service_cpu[svc] = _aggregate(cpu_samples)
            mem_samples = await _range_query(
                client, amp_endpoint, _SERVICE_MEM_QUERY.format(service=svc), start_ts, end_ts, step
            )
            service_mem[svc] = _aggregate(mem_samples)

        logger.info(
            "Telemetry collection complete: %d/%d queries returned data",
            query_stats["total"] - query_stats["empty"],
            query_stats["total"],
        )

    return TelemetrySummary(
        throughput=ThroughputMetrics(
            workflows_started_per_sec=results["workflows_started_per_sec"],
            workflows_completed_per_sec=results["workflows_completed_per_sec"],
            state_transitions_per_sec=results["state_transitions_per_sec"],
        ),
        latency=LatencyMetrics(
            workflow_schedule_to_start_p95=results["workflow_schedule_to_start_p95"],
            workflow_schedule_to_start_p99=results["workflow_schedule_to_start_p99"],
            activity_schedule_to_start_p95=results["activity_schedule_to_start_p95"],
            activity_schedule_to_start_p99=results["activity_schedule_to_start_p99"],
            persistence_latency_p95=results["persistence_latency_p95"],
            persistence_latency_p99=results["persistence_latency_p99"],
        ),
        matching=MatchingMetrics(
            sync_match_rate=results["sync_match_rate"],
            async_match_rate=results["async_match_rate"],
            task_dispatch_latency=results["task_dispatch_latency"],
            backlog_count=results["backlog_count"],
            backlog_age=results["backlog_age"],
        ),
        dsql_pool=DSQLPoolMetrics(
            pool_open_count=results["pool_open_count"],
            pool_in_use_count=results["pool_in_use_count"],
            pool_idle_count=results["pool_idle_count"],
            reservoir_size=results["reservoir_size"],
            reservoir_empty_events=results["reservoir_empty_events"],
            open_failures=results["open_failures"],
            reconnect_count=results["reconnect_count"],
        ),
        errors=ErrorMetrics(
            occ_conflicts_per_sec=results["occ_conflicts_per_sec"],
            exhausted_retries_per_sec=results["exhausted_retries_per_sec"],
            dsql_auth_failures=results["dsql_auth_failures"],
        ),
        resources=ResourceMetrics(
            cpu_utilization=ServiceMetrics(
                history=service_cpu["history"],
                matching=service_cpu["matching"],
                frontend=service_cpu["frontend"],
                worker=service_cpu["worker"],
            ),
            memory_utilization=ServiceMetrics(
                history=service_mem["history"],
                matching=service_mem["matching"],
                frontend=service_mem["frontend"],
                worker=service_mem["worker"],
            ),
            worker_task_slot_utilization=results["worker_task_slot_utilization"],
        ),
    )


async def _range_query(
    client: httpx.AsyncClient,
    endpoint: str,
    query: str,
    start: str,
    end: str,
    step: str,
) -> list[float]:
    """Execute a PromQL range query and return sample values."""
    try:
        resp = await client.get(
            f"{endpoint}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "success":
            logger.warning(
                "Non-success query status: %s, query: %s",
                data.get("status"),
                query,
            )
            return []

        result = data.get("data", {}).get("result", [])
        if not result:
            return []

        # Collect all sample values across all series
        values: list[float] = []
        for series in result:
            for _ts, val in series.get("values", []):
                v = float(val)
                if v == v:  # filter NaN
                    values.append(v)
        return values

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Query HTTP %d: %s, query: %s",
            exc.response.status_code,
            exc.response.text[:200],
            query,
        )
        return []
    except Exception:
        logger.warning("Query error, query: %s", query, exc_info=True)
        return []


def _aggregate(samples: list[float]) -> MetricAggregate:
    """Compute min/max/mean/p50/p95/p99 from a list of samples."""
    if not samples:
        return MetricAggregate(min=0, max=0, mean=0, p50=0, p95=0, p99=0)

    sorted_samples = sorted(samples)
    n = len(sorted_samples)

    return MetricAggregate(
        min=sorted_samples[0],
        max=sorted_samples[-1],
        mean=statistics.mean(sorted_samples),
        p50=sorted_samples[int(n * 0.50)],
        p95=sorted_samples[min(int(n * 0.95), n - 1)],
        p99=sorted_samples[min(int(n * 0.99), n - 1)],
    )
