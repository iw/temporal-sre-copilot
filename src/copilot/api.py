"""FastAPI service exposing health assessments to Grafana.

Principle: "Grafana Consumes, Not Computes"
All computation happens in Copilot workflows. This API serves
pre-computed values from the DSQL state store.

Response models use native whenever.Instant fields — FastAPI + Pydantic
serialize them to ISO 8601 automatically.
"""

import json
import logging
import os
from contextlib import asynccontextmanager

import asyncpg  # noqa: TCH002 — used at runtime for module-level pool annotation
import aurora_dsql_asyncpg as dsql
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from whenever import Instant, TimeDelta

from copilot.models import (
    ErrorResponse,
    IssueResponse,
    IssuesResponse,
    ServicesResponse,
    ServiceStatus,
    StatusResponse,
    SummaryResponse,
    TimelineEntry,
    TimelineResponse,
)
from copilot.models.signals import HealthState

logger = logging.getLogger("copilot.api")


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return Instant.now().format_iso()


# =============================================================================
# DSQL CONNECTION (aurora-dsql-python-connector handles IAM token refresh)
# =============================================================================

# Module-level pool — set during lifespan startup
_pool: asyncpg.Pool | None = None


async def _dsql_reset_connection(conn: asyncpg.Connection) -> None:
    """Custom connection reset for DSQL — skip pg_advisory_unlock_all (unsupported)."""
    await conn.execute("""
        RESET ALL;
        DEALLOCATE ALL;
    """)


async def _create_pool() -> asyncpg.Pool:
    """Create a DSQL pool with automatic IAM token refresh per connection."""
    endpoint = os.environ.get("DSQL_ENDPOINT", "localhost")
    logger.info("Creating DSQL pool via aurora_dsql_asyncpg (auto token refresh)")
    return await dsql.create_pool(
        user="admin",
        host=endpoint,
        ssl="require",
        min_size=2,
        max_size=5,
        statement_cache_size=0,
        reset=_dsql_reset_connection,
    )


# =============================================================================
# DB QUERY HELPERS
# =============================================================================


def _instant_from_row(dt) -> str:
    """Convert asyncpg datetime to ISO 8601 string."""
    return Instant.from_py_datetime(dt).format_iso()


async def _fetch_latest_assessment(pool: asyncpg.Pool) -> dict | None:
    """Fetch the most recent health assessment from DSQL.

    Returns raw row data as a dict (not a response model) since multiple
    endpoints consume this with different projections.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, timestamp, trigger, overall_status, issues,
                   natural_language_summary, metrics_snapshot
            FROM health_assessments
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
        if not row:
            return None

        metrics = json.loads(row["metrics_snapshot"]) if row["metrics_snapshot"] else {}
        issues_data = json.loads(row["issues"]) if row["issues"] else []

        return {
            "id": str(row["id"]),
            "timestamp": _instant_from_row(row["timestamp"]),
            "trigger": row["trigger"],
            "health_state": row["overall_status"],
            "primary_signals": metrics.get("primary_signals", {}),
            "amplifiers": metrics.get("amplifiers", {}),
            "issues": issues_data,
            "natural_language_summary": row["natural_language_summary"],
        }


async def _fetch_issues_for_assessment(
    pool: asyncpg.Pool,
    assessment_id: str,
    *,
    severity: str | None = None,
    limit: int = 10,
) -> list[IssueResponse]:
    """Fetch issues for a specific assessment, returned as response models."""
    async with pool.acquire() as conn:
        if severity:
            rows = await conn.fetch(
                """
                SELECT id, severity, title, description, likely_cause,
                       suggested_actions, related_metrics, created_at, resolved_at
                FROM issues
                WHERE assessment_id = $1 AND severity = $2
                ORDER BY created_at DESC
                LIMIT $3
                """,
                assessment_id,
                severity,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, severity, title, description, likely_cause,
                       suggested_actions, related_metrics, created_at, resolved_at
                FROM issues
                WHERE assessment_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                assessment_id,
                limit,
            )

        return [
            IssueResponse(
                id=str(row["id"]),
                severity=row["severity"],
                title=row["title"],
                description=row["description"],
                likely_cause=row["likely_cause"],
                suggested_actions=(
                    json.loads(row["suggested_actions"]) if row["suggested_actions"] else []
                ),
                related_signals=(
                    json.loads(row["related_metrics"]) if row["related_metrics"] else []
                ),
                created_at=_instant_from_row(row["created_at"]),
                resolved_at=(_instant_from_row(row["resolved_at"]) if row["resolved_at"] else None),
            )
            for row in rows
        ]


async def _fetch_assessments_in_range(
    pool: asyncpg.Pool,
    start_iso: str,
    end_iso: str,
) -> list[TimelineEntry]:
    """Fetch health assessments within a time range as timeline entries."""
    start_dt = Instant.parse_iso(start_iso).py_datetime()
    end_dt = Instant.parse_iso(end_iso).py_datetime()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, trigger, overall_status, issues,
                   natural_language_summary, metrics_snapshot
            FROM health_assessments
            WHERE timestamp >= $1 AND timestamp <= $2
            ORDER BY timestamp DESC
            """,
            start_dt,
            end_dt,
        )

        return [
            TimelineEntry(
                id=str(row["id"]),
                timestamp=_instant_from_row(row["timestamp"]),
                trigger=row["trigger"],
                health_state=row["overall_status"],
                primary_signals=(
                    json.loads(row["metrics_snapshot"]).get("primary_signals", {})
                    if row["metrics_snapshot"]
                    else {}
                ),
                issue_count=len(json.loads(row["issues"])) if row["issues"] else 0,
            )
            for row in rows
        ]


# =============================================================================
# SERVICE HEALTH DERIVATION
# =============================================================================


def _is_cluster_idle(primary_signals: dict) -> bool:
    """Detect an idle cluster from signal dict.

    Handles both nested (Pydantic model_dump) and flat (legacy) formats.
    Mirrors the logic in state_machine._is_idle.
    """
    # Nested format: {"state_transitions": {"throughput_per_sec": 0.0}, ...}
    if "state_transitions" in primary_signals and isinstance(
        primary_signals["state_transitions"], dict
    ):
        st = primary_signals.get("state_transitions", {})
        throughput = st.get("throughput_per_sec", 0)
        hist = primary_signals.get("history", {})
        processing = hist.get("task_processing_rate_per_sec", 0)
        fe = primary_signals.get("frontend", {})
        frontend_errors = fe.get("error_rate_per_sec", 0)
        pers = primary_signals.get("persistence", {})
        persistence_errors = pers.get("error_rate_per_sec", 0)
        backlog = hist.get("backlog_age_sec", 0)
        match = primary_signals.get("matching", {})
        wf_backlog = match.get("workflow_backlog_age_sec", 0)
        act_backlog = match.get("activity_backlog_age_sec", 0)
    else:
        # Flat format (legacy): {"state_transitions_throughput": 0.0, ...}
        throughput = primary_signals.get("state_transitions_throughput", 0)
        processing = primary_signals.get("history_processing_rate", 0)
        frontend_errors = primary_signals.get("frontend_error_rate", 0)
        persistence_errors = primary_signals.get("persistence_error_rate", 0)
        backlog = primary_signals.get("history_backlog_age", 0)
        wf_backlog = primary_signals.get("matching_workflow_backlog_age", 0)
        act_backlog = primary_signals.get("matching_activity_backlog_age", 0)

    has_no_throughput = throughput < 1.0 and processing < 1.0
    has_no_errors = frontend_errors < 0.1 and persistence_errors < 0.1
    has_no_backlog = backlog < 1.0 and wf_backlog < 1.0 and act_backlog < 1.0

    return has_no_throughput and has_no_errors and has_no_backlog


def _get_signal(primary_signals: dict, nested_path: str, flat_key: str, default=0):
    """Extract a signal value from either nested or flat format.

    nested_path: e.g. "history.backlog_age_sec"
    flat_key: e.g. "history_backlog_age"
    """
    if "state_transitions" in primary_signals and isinstance(
        primary_signals["state_transitions"], dict
    ):
        parts = nested_path.split(".")
        val = primary_signals
        for p in parts:
            val = val.get(p, default) if isinstance(val, dict) else default
        return val
    return primary_signals.get(flat_key, default)


def _derive_service_status(service: str, primary_signals: dict) -> str:
    """Derive per-service health status from pre-computed signals.

    Handles both nested (Pydantic model_dump) and flat (legacy) formats.
    An idle cluster means all services are happy.
    """
    if _is_cluster_idle(primary_signals):
        return "happy"

    if service == "history":
        backlog = _get_signal(primary_signals, "history.backlog_age_sec", "history_backlog_age")
        processing = _get_signal(
            primary_signals, "history.task_processing_rate_per_sec", "history_processing_rate"
        )
        if backlog > 120 or processing < 10:
            return "critical"
        if backlog > 30:
            return "stressed"
        return "happy"

    if service == "matching":
        wf_backlog = _get_signal(
            primary_signals, "matching.workflow_backlog_age_sec", "matching_workflow_backlog_age"
        )
        act_backlog = _get_signal(
            primary_signals, "matching.activity_backlog_age_sec", "matching_activity_backlog_age"
        )
        if wf_backlog > 60 or act_backlog > 60:
            return "stressed"
        return "happy"

    if service == "frontend":
        error_rate = _get_signal(
            primary_signals, "frontend.error_rate_per_sec", "frontend_error_rate"
        )
        latency = _get_signal(primary_signals, "frontend.latency_p99_ms", "frontend_latency_p99")
        if error_rate > 5:
            return "critical"
        if latency > 1000:
            return "stressed"
        return "happy"

    if service == "persistence":
        latency = _get_signal(
            primary_signals, "persistence.latency_p99_ms", "persistence_latency_p99"
        )
        error_rate = _get_signal(
            primary_signals, "persistence.error_rate_per_sec", "persistence_error_rate"
        )
        if error_rate > 10:
            return "critical"
        if latency > 100:
            return "stressed"
        return "happy"

    return "unknown"


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DSQL pool on startup, close on shutdown."""
    global _pool
    try:
        _pool = await _create_pool()
        yield
    except Exception:
        logger.exception("Failed to create DSQL pool")
        yield
    finally:
        if _pool:
            await _pool.close()
            _pool = None


app = FastAPI(
    title="Temporal SRE Copilot API",
    description="Health assessments for Temporal deployments. Grafana consumes, not computes.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]  # Starlette middleware typing
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


async def _get_pool_or_503() -> asyncpg.Pool:
    """Get the connection pool or raise 503 if unavailable."""
    if _pool is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "State store unavailable",
                "health_state": "unknown",
                "degraded": True,
            },
        )
    return _pool


# =============================================================================
# ENDPOINTS
# =============================================================================

_SERVICES = ["history", "matching", "frontend", "persistence"]


@app.get("/status")
async def get_status() -> StatusResponse:
    """Current health status with signal taxonomy."""
    pool = await _get_pool_or_503()
    assessment = await _fetch_latest_assessment(pool)

    if not assessment:
        return StatusResponse(
            health_state=HealthState.HAPPY,
            timestamp=_now_iso(),
        )

    issues = await _fetch_issues_for_assessment(pool, assessment["id"])

    recommended_actions = [
        action.model_dump() for issue in issues for action in issue.suggested_actions
    ]

    # If the stored assessment says non-happy but current signals show
    # an idle cluster, override to HAPPY. This handles the case where
    # the observe workflow restarted fresh and didn't trigger a new
    # assessment because it initialized at HAPPY (no state change).
    health_state = HealthState(assessment["health_state"])
    if health_state != HealthState.HAPPY and _is_cluster_idle(assessment["primary_signals"]):
        health_state = HealthState.HAPPY

    return StatusResponse(
        health_state=health_state,
        timestamp=assessment["timestamp"],
        primary_signals=assessment["primary_signals"],
        amplifiers=assessment["amplifiers"],
        recommended_actions=recommended_actions[:5] if health_state != HealthState.HAPPY else [],
        issue_count=len(issues) if health_state != HealthState.HAPPY else 0,
    )


@app.get("/status/services")
async def get_services() -> ServicesResponse:
    """Per-service health status for Grafana grid panel."""
    pool = await _get_pool_or_503()
    assessment = await _fetch_latest_assessment(pool)

    if not assessment:
        return ServicesResponse()

    primary = assessment["primary_signals"]

    return ServicesResponse(
        services=[
            ServiceStatus(
                name=svc,
                status=_derive_service_status(svc, primary),
                key_signals={
                    k: v for k, v in primary.items() if k.startswith(svc) and not isinstance(v, str)
                },
            )
            for svc in _SERVICES
        ]
    )


@app.get("/status/issues")
async def get_issues(
    severity: str | None = None,
    limit: int = Query(default=10, le=100),
) -> IssuesResponse:
    """Active issues list with contributing factors."""
    pool = await _get_pool_or_503()
    assessment = await _fetch_latest_assessment(pool)

    if not assessment:
        return IssuesResponse()

    issues = await _fetch_issues_for_assessment(
        pool, assessment["id"], severity=severity, limit=limit
    )

    return IssuesResponse(issues=issues)


@app.get("/status/summary")
async def get_summary() -> SummaryResponse:
    """Natural language summary for Grafana text panel."""
    pool = await _get_pool_or_503()
    assessment = await _fetch_latest_assessment(pool)

    if not assessment:
        return SummaryResponse(
            summary="No assessment available yet.",
            timestamp=_now_iso(),
            health_state=HealthState.HAPPY,
        )

    health_state = HealthState(assessment["health_state"])
    summary = assessment["natural_language_summary"]

    # Override stale non-happy state when cluster is actually idle
    if health_state != HealthState.HAPPY and _is_cluster_idle(assessment["primary_signals"]):
        health_state = HealthState.HAPPY
        summary = "Cluster is idle and healthy. No workflows in progress, no errors detected."

    return SummaryResponse(
        summary=summary,
        timestamp=assessment["timestamp"],
        health_state=health_state,
    )


@app.get("/status/timeline")
async def get_timeline(
    start: str | None = None,
    end: str | None = None,
) -> TimelineResponse:
    """Health status changes over time for Grafana state timeline.

    Accepts ISO 8601 timestamps for start/end range.
    Defaults to last 24 hours.
    """
    pool = await _get_pool_or_503()

    start_iso = start if start else (Instant.now() - TimeDelta(hours=24)).format_iso()
    end_iso = end if end else Instant.now().format_iso()

    entries = await _fetch_assessments_in_range(pool, start_iso, end_iso)

    return TimelineResponse(timeline=entries)


@app.post("/actions", status_code=501)
async def execute_action() -> ErrorResponse:
    """Future: Execute remediation action (501 Not Implemented)."""
    return ErrorResponse(
        error="Not implemented",
        message="Automated remediation is planned for a future release.",
    )
