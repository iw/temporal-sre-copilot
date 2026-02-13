"""Loki log querying activity for narrative signals.

Fetches log patterns that explain state transitions.
These are Amplifier 13: "A small set of repeated log messages often explains 80% of incidents."

Date/Time: Uses `whenever` library (UTC-first, Rust-backed).
"""

from typing import Any

import httpx
from temporalio import activity
from whenever import Instant, TimeDelta

from copilot.models import FetchLogPatternsInput, LogPattern, QueryLokiInput

# Narrative signal patterns to detect
# Pattern → (service filter, description)
NARRATIVE_PATTERNS: dict[str, tuple[str, str]] = {
    "deadline exceeded": (".*", "Timeout pressure"),
    "context canceled": (".*", "Cancellation cascade"),
    "shard ownership": ("history", "Membership instability"),
    "member joined": (".*", "Ringpop membership change"),
    "member left": (".*", "Ringpop membership change"),
    "no poller": ("matching", "Worker misconfiguration"),
    "reservoir discard": ("history", "Connection pool pressure"),
    "SQLSTATE 40001": (".*", "OCC serialization failure"),
    "rate limit exceeded": (".*", "DSQL connection rate limit"),
    "shard acquired": ("history", "Shard ownership change"),
    "shard released": ("history", "Shard ownership change"),
    "serialization failure": (".*", "OCC serialization failure"),
    "connection refused": (".*", "Service connectivity issue"),
    "pool exhausted": (".*", "Connection pool exhaustion"),
}


async def _query_loki(
    client: httpx.AsyncClient,
    loki_url: str,
    query: str,
    start: Instant,
    end: Instant,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Execute a LogQL query and return log entries."""
    try:
        response = await client.get(
            f"{loki_url}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": start.format_iso(),
                "end": end.format_iso(),
                "limit": limit,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "success":
            activity.logger.warning(f"Loki query failed: {query}")
            return []

        results = data.get("data", {}).get("result", [])
        entries = []
        for stream in results:
            labels = stream.get("stream", {})
            for value in stream.get("values", []):
                entries.append(
                    {
                        "timestamp": value[0],
                        "message": value[1],
                        "labels": labels,
                    }
                )
        return entries

    except Exception as e:
        activity.logger.warning(f"Loki query error: {e}")
        return []


def _detect_patterns(
    entries: list[dict[str, Any]],
    patterns: dict[str, tuple[str, str]],
) -> list[LogPattern]:
    """Detect narrative patterns in log entries."""
    pattern_counts: dict[str, dict[str, Any]] = {}

    for entry in entries:
        message = entry.get("message", "").lower()
        labels = entry.get("labels", {})
        service = labels.get("service_name", labels.get("job", "unknown"))

        for pattern, (service_filter, description) in patterns.items():
            if pattern.lower() in message:
                # Check service filter
                if service_filter != ".*" and service_filter not in service:
                    continue

                key = f"{pattern}:{service}"
                if key not in pattern_counts:
                    pattern_counts[key] = {
                        "pattern": pattern,
                        "service": service,
                        "description": description,
                        "count": 0,
                        "sample": entry.get("message", "")[:500],
                    }
                pattern_counts[key]["count"] += 1

    # Convert to LogPattern objects, sorted by count
    results = []
    for data in sorted(pattern_counts.values(), key=lambda x: x["count"], reverse=True):
        results.append(
            LogPattern(
                count=data["count"],
                pattern=data["pattern"],
                service=data["service"],
                sample_message=data["sample"],
            )
        )

    return results


@activity.defn
async def query_loki_errors(input: QueryLokiInput) -> list[LogPattern]:
    """Query Loki for error patterns (narrative signals).

    This activity fetches log entries and detects patterns that explain
    state transitions. These are Amplifier 13 signals.

    Args:
        input: QueryLokiInput with Loki URL and lookback window

    Returns:
        List of LogPattern objects with detected patterns
    """
    activity.logger.info(f"Querying Loki for error patterns: {input.loki_url}")

    end = Instant.now()
    start = end - TimeDelta(seconds=input.lookback_seconds)

    # Query for error-level logs from Temporal services
    query = '{job=~"temporal.*"} |~ "(?i)(error|warn|fatal|panic)"'

    async with httpx.AsyncClient() as client:
        entries = await _query_loki(client, input.loki_url, query, start, end, limit=1000)

    patterns = _detect_patterns(entries, NARRATIVE_PATTERNS)

    activity.logger.info(
        f"Detected {len(patterns)} narrative patterns from {len(entries)} log entries"
    )

    return patterns


@activity.defn
async def fetch_recent_log_patterns(input: FetchLogPatternsInput) -> list[LogPattern]:
    """Fetch recent log patterns for correlation with health assessments.

    Shorter lookback than query_loki_errors, used during assessment.

    Args:
        input: FetchLogPatternsInput with Loki URL and lookback window

    Returns:
        List of LogPattern objects
    """
    return await query_loki_errors(
        QueryLokiInput(
            loki_url=input.loki_url,
            lookback_seconds=input.lookback_seconds,
        )
    )
