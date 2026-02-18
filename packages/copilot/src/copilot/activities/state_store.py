"""State store activities for persisting health assessments to DSQL.

Uses Aurora DSQL for durable storage of assessments and signal snapshots.

Date/Time: Uses `whenever` library (UTC-first, Rust-backed).
Converts to/from Python datetime for asyncpg TIMESTAMPTZ compatibility.
"""

import json
from datetime import datetime  # noqa: TC003 — asyncpg requires runtime datetime
from uuid import uuid4

import asyncpg
import boto3
from temporalio import activity
from whenever import Instant, TimeDelta

from copilot.models import (
    CheckRecentAssessmentInput,
    FetchSignalHistoryInput,
    GetAssessmentsInRangeInput,
    GetLatestAssessmentInput,
    HealthAssessment,
    StoreAssessmentInput,
    StoreSignalsInput,
)


def _iso_to_datetime(iso_str: str) -> datetime:
    """Convert ISO 8601 string to Python datetime for asyncpg."""
    return Instant.parse_iso(iso_str).py_datetime()


def _datetime_to_iso(dt) -> str:
    """Convert Python datetime to ISO 8601 string."""
    return Instant.from_py_datetime(dt).format_iso()


def _get_dsql_token(endpoint: str, region: str) -> str:
    """Generate IAM auth token for DSQL."""
    client = boto3.client("dsql", region_name=region)
    return client.generate_db_connect_admin_auth_token(endpoint, region)


async def _get_connection(
    endpoint: str,
    database: str,
    region: str,
) -> asyncpg.Connection:
    """Get a connection to DSQL with IAM auth."""
    token = _get_dsql_token(endpoint, region)
    return await asyncpg.connect(
        host=endpoint,
        port=5432,
        user="admin",
        password=token,
        database=database,
        ssl="require",
    )


@activity.defn
async def store_health_assessment(input: StoreAssessmentInput) -> str:
    """Store a health assessment in DSQL.

    Args:
        input: StoreAssessmentInput with assessment and DSQL config

    Returns:
        The UUID of the stored assessment
    """
    assessment = input.assessment
    activity.logger.info(f"Storing health assessment: {assessment.health_state.value}")

    assessment_id = str(uuid4())

    conn = await _get_connection(input.dsql_endpoint, input.dsql_database, input.region)
    try:
        await conn.execute(
            """
            INSERT INTO health_assessments (
                id, timestamp, trigger, overall_status, services, issues,
                natural_language_summary, metrics_snapshot
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            assessment_id,
            _iso_to_datetime(assessment.timestamp),
            assessment.trigger,
            assessment.health_state.value,
            json.dumps({}),  # services derived from signals
            json.dumps([i.model_dump() for i in assessment.issues]),
            assessment.natural_language_summary,
            json.dumps(
                {
                    "primary_signals": assessment.primary_signals,
                    "amplifiers": assessment.amplifiers,
                }
            ),
        )

        # Store issues separately for efficient querying
        for issue in assessment.issues:
            await conn.execute(
                """
                INSERT INTO issues (
                    id, assessment_id, severity, title, description,
                    likely_cause, suggested_actions, related_metrics
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                str(uuid4()),
                assessment_id,
                issue.severity.value,
                issue.title,
                issue.description,
                issue.likely_cause,
                json.dumps([a.model_dump() for a in issue.suggested_actions]),
                json.dumps(issue.related_signals),
            )

        activity.logger.info(f"Stored assessment {assessment_id}")
        return assessment_id

    finally:
        await conn.close()


@activity.defn
async def store_signals_snapshot(input: StoreSignalsInput) -> str:
    """Store a signals snapshot in DSQL.

    Args:
        input: StoreSignalsInput with signals and DSQL config

    Returns:
        The UUID of the stored snapshot
    """
    signals = input.signals
    activity.logger.debug("Storing signals snapshot")

    snapshot_id = str(uuid4())

    conn = await _get_connection(input.dsql_endpoint, input.dsql_database, input.region)
    try:
        await conn.execute(
            """
            INSERT INTO metrics_snapshots (id, timestamp, metrics)
            VALUES ($1, $2, $3)
            """,
            snapshot_id,
            _iso_to_datetime(signals.timestamp),
            json.dumps(
                {
                    "primary": signals.primary.model_dump(),
                    "amplifiers": signals.amplifiers.model_dump(),
                }
            ),
        )
        return snapshot_id

    finally:
        await conn.close()


@activity.defn
async def get_latest_assessment(
    input: GetLatestAssessmentInput,
) -> HealthAssessment | None:
    """Get the most recent health assessment.

    Args:
        input: GetLatestAssessmentInput with DSQL config

    Returns:
        The latest HealthAssessment or None
    """
    activity.logger.debug("Fetching latest assessment")

    conn = await _get_connection(input.dsql_endpoint, input.dsql_database, input.region)
    try:
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

        return HealthAssessment(
            timestamp=_datetime_to_iso(row["timestamp"]),
            trigger=row["trigger"],
            health_state=row["overall_status"],
            primary_signals=metrics.get("primary_signals", {}),
            amplifiers=metrics.get("amplifiers", {}),
            log_patterns=[],
            issues=[],  # Would need to fetch from issues table
            recommended_actions=[],
            natural_language_summary=row["natural_language_summary"],
        )

    finally:
        await conn.close()


@activity.defn
async def get_assessments_in_range(
    input: GetAssessmentsInRangeInput,
) -> list[HealthAssessment]:
    """Get health assessments within a time range.

    Args:
        input: GetAssessmentsInRangeInput with time range and DSQL config

    Returns:
        List of HealthAssessment objects
    """
    activity.logger.debug(f"Fetching assessments from {input.start} to {input.end}")

    conn = await _get_connection(input.dsql_endpoint, input.dsql_database, input.region)
    try:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, trigger, overall_status, issues,
                   natural_language_summary, metrics_snapshot
            FROM health_assessments
            WHERE timestamp >= $1 AND timestamp <= $2
            ORDER BY timestamp DESC
            """,
            _iso_to_datetime(input.start),
            _iso_to_datetime(input.end),
        )

        assessments = []
        for row in rows:
            metrics = json.loads(row["metrics_snapshot"]) if row["metrics_snapshot"] else {}
            assessments.append(
                HealthAssessment(
                    timestamp=_datetime_to_iso(row["timestamp"]),
                    trigger=row["trigger"],
                    health_state=row["overall_status"],
                    primary_signals=metrics.get("primary_signals", {}),
                    amplifiers=metrics.get("amplifiers", {}),
                    log_patterns=[],
                    issues=[],
                    recommended_actions=[],
                    natural_language_summary=row["natural_language_summary"],
                )
            )

        return assessments

    finally:
        await conn.close()


@activity.defn
async def check_recent_assessment(input: CheckRecentAssessmentInput) -> bool:
    """Check if a recent assessment exists within the window.

    Used for deduplication in scheduled assessments.

    Args:
        input: CheckRecentAssessmentInput with window and DSQL config

    Returns:
        True if a recent assessment exists
    """
    activity.logger.debug(f"Checking for recent assessment within {input.window}")

    cutoff = Instant.now() - input.window

    conn = await _get_connection(input.dsql_endpoint, input.dsql_database, input.region)
    try:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) as count
            FROM health_assessments
            WHERE timestamp >= $1
            """,
            cutoff.py_datetime(),
        )

        return row["count"] > 0 if row else False

    finally:
        await conn.close()


@activity.defn
async def fetch_signal_history(input: FetchSignalHistoryInput) -> list[dict]:
    """Fetch recent signal snapshots for trend analysis.

    Args:
        input: FetchSignalHistoryInput with lookback and DSQL config

    Returns:
        List of signal snapshot dicts
    """
    activity.logger.debug(f"Fetching signal history for last {input.lookback_minutes} minutes")

    cutoff = Instant.now() - TimeDelta(minutes=input.lookback_minutes)

    conn = await _get_connection(input.dsql_endpoint, input.dsql_database, input.region)
    try:
        rows = await conn.fetch(
            """
            SELECT timestamp, metrics
            FROM metrics_snapshots
            WHERE timestamp >= $1
            ORDER BY timestamp DESC
            """,
            cutoff.py_datetime(),
        )

        return [
            {
                "timestamp": _datetime_to_iso(row["timestamp"]),
                "metrics": json.loads(row["metrics"]) if row["metrics"] else {},
            }
            for row in rows
        ]

    finally:
        await conn.close()
