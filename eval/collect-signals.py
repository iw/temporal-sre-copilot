#!/usr/bin/env python3
"""Collect signals from Mimir for a given time window.

Usage:
    python eval/collect-signals.py --start 2026-02-23T18:43:00Z --end 2026-02-23T19:02:00Z
    python eval/collect-signals.py --start 2026-02-23T18:43:00Z --end 2026-02-23T19:02:00Z --mimir http://host:9009/prometheus
    python eval/collect-signals.py --start 2026-02-23T18:43:00Z --end 2026-02-23T19:02:00Z --name "50-wps-starter"

Output is written to eval/data/<name>-<date>.json and a summary table is printed.
The data/ directory is gitignored — reports are ephemeral, the tooling is permanent.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

DEFAULT_MIMIR = "http://localhost:9009/prometheus"
DEFAULT_STEP = "30s"


# ── Queries ──────────────────────────────────────────────────────────────────
# These mirror the Copilot's PRIMARY_QUERIES and AMPLIFIER_QUERIES from
# packages/copilot/src/copilot/activities/amp.py. Keep them in sync.

QUERIES = {
    # === PRIMARY SIGNALS ===
    "state_transitions_throughput": "sum(rate(state_transition_count_ratio_sum[1m]))",
    "state_transitions_latency_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(state_transition_count_ratio_bucket[1m])))"
    ),
    "state_transitions_latency_p99": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(state_transition_count_ratio_bucket[1m])))"
    ),
    "workflow_success_rate": "sum(rate(workflow_success_total[1m]))",
    "workflow_failed_rate": "sum(rate(workflow_failed_total[1m]))",
    "history_backlog_age_p95_sec": (
        "histogram_quantile(0.95, sum by (le)"
        ' (rate(task_latency_queue_milliseconds_bucket{service_name="history"}[1m])))'
        " / 1000"
    ),
    "history_processing_rate": (
        'sum(rate(task_requests_total{service_name="history"}[1m]))'
    ),
    "history_shard_churn": "sum(rate(sharditem_created_count_total[1m]))",
    "frontend_error_rate": (
        'sum(rate(service_error_with_type_total{service_name="frontend"}[1m]))'
    ),
    "frontend_latency_p99_filtered": (
        "histogram_quantile(0.99, sum by (le)"
        " (rate(service_latency_milliseconds_bucket"
        '{service_name="frontend", operation!~"Poll.*TaskQueue"}[1m])))'
    ),
    "frontend_latency_p99_raw": (
        "histogram_quantile(0.99, sum by (le)"
        ' (rate(service_latency_milliseconds_bucket{service_name="frontend"}[1m])))'
    ),
    "matching_wf_backlog_sec": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(task_latency_queue_milliseconds_bucket"
        '{service_name="matching", task_type="WorkflowTask"}[1m])))'
        " / 1000"
    ),
    "matching_act_backlog_sec": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(task_latency_queue_milliseconds_bucket"
        '{service_name="matching", task_type="ActivityTask"}[1m])))'
        " / 1000"
    ),
    "poller_timeout_rate": (
        "sum(rate(poll_timeouts_total[1m])) /"
        " (sum(rate(poll_success_total[1m])) + sum(rate(poll_timeouts_total[1m])) + 0.001)"
    ),
    "persistence_latency_p95": (
        "histogram_quantile(0.95, sum by (le)"
        ' (rate(persistence_latency_milliseconds_bucket{service_name="history"}[1m])))'
    ),
    "persistence_latency_p99": (
        "histogram_quantile(0.99, sum by (le)"
        ' (rate(persistence_latency_milliseconds_bucket{service_name="history"}[1m])))'
    ),
    "persistence_error_rate": (
        'sum(rate(persistence_errors_total{service_name="history"}[1m]))'
    ),
    # === AMPLIFIERS ===
    "occ_conflicts": (
        'sum(rate(persistence_error_with_type_total{error_type="ShardOwnershipLostError"}[1m]))'
        " or vector(0)"
    ),
    "pool_utilization_pct": (
        "100 * sum(dsql_pool_in_use) / (sum(dsql_pool_open) + 0.001)"
    ),
    "pool_wait_duration_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(dsql_pool_wait_duration_milliseconds_bucket[1m])))"
        " or vector(0)"
    ),
    "reservoir_checkout_p95": (
        "histogram_quantile(0.95, sum by (le)"
        " (rate(dsql_reservoir_checkout_duration_milliseconds_bucket[1m])))"
        " or vector(0)"
    ),
    "reservoir_discards": "sum(rate(dsql_reservoir_discards_total[1m]))",
    "reservoir_refills": "sum(rate(dsql_reservoir_refills_total[1m]))",
    "worker_slots_available": "sum(temporal_worker_task_slots_available) or vector(0)",
    "worker_slots_used": "sum(temporal_worker_task_slots_used) or vector(0)",
    "goroutines": "sum(num_goroutines) or vector(0)",
    "membership_changes": "sum(rate(membership_changed_count_total[1m])) * 60",
    "cache_hit_rate": (
        "sum(rate(cache_requests_total[1m])) /"
        " (sum(rate(cache_requests_total[1m])) + sum(rate(cache_miss_total[1m])) + 0.001)"
    ),
    # === PER-SERVICE PERSISTENCE ===
    "persistence_p99_history": (
        "histogram_quantile(0.99, sum by (le)"
        ' (rate(persistence_latency_milliseconds_bucket{service_name="history"}[1m])))'
    ),
    "persistence_p99_matching": (
        "histogram_quantile(0.99, sum by (le)"
        ' (rate(persistence_latency_milliseconds_bucket{service_name="matching"}[1m])))'
    ),
    "persistence_p99_frontend": (
        "histogram_quantile(0.99, sum by (le)"
        ' (rate(persistence_latency_milliseconds_bucket{service_name="frontend"}[1m])))'
    ),
    # === SYSTEM OPS ===
    "system_deletion_rate": (
        'sum(rate(task_requests_total{task_type=~".*Delete.*"}[1m]))'
    ),
    "system_cleanup_rate": "sum(rate(workflow_cleanup_delete_total[1m]))",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def query_range(
    client: httpx.Client, endpoint: str, query: str, start: str, end: str, step: str
) -> list:
    """Execute a PromQL range query."""
    resp = client.get(
        f"{endpoint}/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "step": step},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if data["status"] != "success":
        return []
    return data.get("data", {}).get("result", [])


def extract_values(result: list) -> list[tuple[str, float]]:
    """Extract (timestamp, value) pairs from a range query result."""
    if not result:
        return []
    values = []
    for series in result:
        for ts, val in series.get("values", []):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")
            v = float(val) if val != "NaN" else 0.0
            values.append((dt, v))
    return values


def summarize(values: list[tuple[str, float]]) -> dict:
    """Compute min/max/avg/last from time series values."""
    if not values:
        return {"min": 0, "max": 0, "avg": 0, "last": 0, "samples": 0}
    nums = [v for _, v in values]
    return {
        "min": round(min(nums), 2),
        "max": round(max(nums), 2),
        "avg": round(sum(nums) / len(nums), 2),
        "last": round(nums[-1], 2),
        "samples": len(nums),
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect signals from Mimir for post-test analysis")
    parser.add_argument("--start", required=True, help="Start time (ISO 8601, e.g. 2026-02-23T18:43:00Z)")
    parser.add_argument("--end", required=True, help="End time (ISO 8601, e.g. 2026-02-23T19:02:00Z)")
    parser.add_argument("--step", default=DEFAULT_STEP, help=f"Query step (default: {DEFAULT_STEP})")
    parser.add_argument("--mimir", default=DEFAULT_MIMIR, help=f"Mimir endpoint (default: {DEFAULT_MIMIR})")
    parser.add_argument("--name", default="test", help="Test name for output file (default: test)")
    args = parser.parse_args()

    # Derive output path
    date_str = args.start[:10]
    data_dir = Path("eval/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / f"{args.name}-{date_str}.json"

    output = {
        "window": {"start": args.start, "end": args.end, "step": args.step},
        "metrics": {},
    }

    with httpx.Client() as client:
        for name, query in QUERIES.items():
            try:
                result = query_range(client, args.mimir, query, args.start, args.end, args.step)
                values = extract_values(result)
                output["metrics"][name] = {"summary": summarize(values), "series": values}
            except Exception as e:
                output["metrics"][name] = {"error": str(e), "summary": {}, "series": []}
                print(f"  WARN: {name}: {e}", file=sys.stderr)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary table
    print(f"\n{'=' * 90}")
    print(f"SIGNAL COLLECTION: {args.start} → {args.end}")
    print(f"{'=' * 90}\n")
    print(f"{'Metric':<40} {'Min':>10} {'Max':>10} {'Avg':>10} {'Last':>10}")
    print("-" * 90)
    for name, data in output["metrics"].items():
        s = data.get("summary", {})
        if not s:
            print(f"{name:<40} {'ERROR':>10}")
            continue
        print(f"{name:<40} {s['min']:>10.2f} {s['max']:>10.2f} {s['avg']:>10.2f} {s['last']:>10.2f}")

    print(f"\nData written to {out_path}")


if __name__ == "__main__":
    main()
