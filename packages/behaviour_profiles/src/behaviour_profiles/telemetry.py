"""AMP telemetry collection for behaviour profiles.

Queries Amazon Managed Prometheus for curated metric aggregates over a time window.
Uses range queries with step intervals to compute min/max/mean/p50/p95/p99.
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

# PromQL queries keyed by metric name.
# Each returns a single time series; we collect samples over the window.
_QUERIES: dict[str, str] = {
    # Throughput
    "workflows_started_per_sec": (
        "sum(rate(workflow_success_total[1m]) + rate(workflow_failed_total[1m]))"
    ),
    "workflows_completed_per_sec": "sum(rate(workflow_success_total[1m]))",
    "state_transitions_per_sec": "sum(rate(state_transition_count_count[1m]))",
    # Latency
    "workflow_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(schedule_to_start_latency_bucket"
        "{operation_type='workflow'}[5m]))) * 1000"
    ),
    "workflow_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(schedule_to_start_latency_bucket"
        "{operation_type='workflow'}[5m]))) * 1000"
    ),
    "activity_schedule_to_start_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(schedule_to_start_latency_bucket"
        "{operation_type='activity'}[5m]))) * 1000"
    ),
    "activity_schedule_to_start_p99": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(schedule_to_start_latency_bucket"
        "{operation_type='activity'}[5m]))) * 1000"
    ),
    "persistence_latency_p95": (
        "histogram_quantile(0.95, sum by (le) (rate(persistence_latency_bucket[5m]))) * 1000"
    ),
    "persistence_latency_p99": (
        "histogram_quantile(0.99, sum by (le) (rate(persistence_latency_bucket[5m]))) * 1000"
    ),
    # Matching
    "sync_match_rate": "sum(rate(sync_match_total[1m]))",
    "async_match_rate": "sum(rate(async_match_total[1m]))",
    "task_dispatch_latency": (
        "histogram_quantile(0.95, sum by (le) (rate(task_dispatch_latency_bucket[5m]))) * 1000"
    ),
    "backlog_count": "sum(task_backlog_count)",
    "backlog_age": "max(task_backlog_age_seconds)",
    # DSQL pool
    "pool_open_count": "sum(dsql_pool_open_connections)",
    "pool_in_use_count": "sum(dsql_pool_in_use_connections)",
    "pool_idle_count": "sum(dsql_pool_idle_connections)",
    "reservoir_size": "sum(dsql_reservoir_ready)",
    "reservoir_empty_events": "sum(rate(dsql_reservoir_empty_total[1m]))",
    "open_failures": "sum(rate(dsql_open_failures_total[1m]))",
    "reconnect_count": "sum(rate(dsql_reconnect_total[1m]))",
    # Errors
    "occ_conflicts_per_sec": "sum(rate(dsql_occ_conflict_total[1m]))",
    "exhausted_retries_per_sec": "sum(rate(dsql_exhausted_retries_total[1m]))",
    "dsql_auth_failures": "sum(rate(dsql_auth_failure_total[1m]))",
    # Resources (per-service CPU/memory handled separately)
    "worker_task_slot_utilization": (
        "avg(temporal_worker_task_slots_used / temporal_worker_task_slots_available)"
    ),
}

# Per-service resource queries — {service} is substituted at query time
_SERVICE_CPU_QUERY = 'avg(rate(container_cpu_usage_seconds_total{{service="{service}"}}[1m])) * 100'
_SERVICE_MEM_QUERY = (
    'avg(container_memory_usage_bytes{{service="{service}"}})'
    " / avg(container_memory_limit_bytes"
    '{{service="{service}"}}) * 100'
)
_SERVICES = ("history", "matching", "frontend", "worker")


async def collect_telemetry(
    *,
    amp_endpoint: str,
    start: str,
    end: str,
    step: str = "60s",
) -> TelemetrySummary:
    """Query AMP for all telemetry metrics over the given time window.

    Args:
        amp_endpoint: AMP workspace query endpoint (e.g. https://aps-workspaces.../api/v1).
        start: ISO 8601 start time.
        end: ISO 8601 end time.
        step: Prometheus range query step interval.
    """
    start_ts = str(Instant.parse_iso(start).timestamp())
    end_ts = str(Instant.parse_iso(end).timestamp())

    async with httpx.AsyncClient() as client:
        # Fetch all scalar metrics
        results: dict[str, MetricAggregate] = {}
        for name, query in _QUERIES.items():
            samples = await _range_query(client, amp_endpoint, query, start_ts, end_ts, step)
            results[name] = _aggregate(samples)

        # Fetch per-service resource metrics
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
            logger.warning("Range query failed: %s, status: %s", query, data.get("status"))
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

    except Exception:
        logger.warning("Range query error: %s", query, exc_info=True)
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
