"""Pydantic models for activity inputs.

Every activity takes a single Pydantic model as its input parameter.
This ensures Temporal's PydanticAIPlugin properly serializes/deserializes
all arguments — avoiding the dict-instead-of-model bug where Pydantic
models arrive as plain dicts when passed as positional args.

Pattern:
    @activity.defn
    async def my_activity(input: MyActivityInput) -> MyOutput:
        ...

    # In workflow:
    await workflow.execute_activity(
        my_activity,
        MyActivityInput(field="value"),
        start_to_close_timeout=...,
    )
"""

from pydantic import BaseModel, Field
from whenever import TimeDelta  # noqa: TC002

from .assessment import HealthAssessment  # noqa: TC001
from .signals import Signals  # noqa: TC001

# =============================================================================
# AMP Activities
# =============================================================================


class FetchSignalsInput(BaseModel):
    """Input for fetch_signals_from_amp activity."""

    prometheus_endpoint: str = Field(description="Prometheus-compatible query endpoint URL")


class FetchWorkerSignalsInput(BaseModel):
    """Input for fetch_worker_signals_from_amp activity."""

    prometheus_endpoint: str = Field(description="Prometheus-compatible query endpoint URL")


# =============================================================================
# Loki Activities
# =============================================================================


class QueryLokiInput(BaseModel):
    """Input for query_loki_errors activity."""

    loki_url: str = Field(description="Loki query endpoint URL")
    lookback_seconds: int = Field(default=300, description="How far back to query")


class FetchLogPatternsInput(BaseModel):
    """Input for fetch_recent_log_patterns activity."""

    loki_url: str = Field(description="Loki query endpoint URL")
    lookback_seconds: int = Field(default=60, description="How far back to query")


# =============================================================================
# RAG Activities
# =============================================================================


class FetchRagContextInput(BaseModel):
    """Input for fetch_rag_context activity."""

    knowledge_base_id: str = Field(description="Bedrock Knowledge Base ID")
    contributing_factors: list[str] = Field(
        description="Factors to search for in the knowledge base"
    )
    region: str = Field(default="eu-west-1", description="AWS region")
    max_results: int = Field(default=5, description="Maximum number of results")


# =============================================================================
# State Store Activities
# =============================================================================


class StoreAssessmentInput(BaseModel):
    """Input for store_health_assessment activity."""

    assessment: HealthAssessment
    dsql_endpoint: str = Field(description="DSQL cluster endpoint")
    dsql_database: str = Field(default="postgres", description="Database name")
    region: str = Field(default="eu-west-1", description="AWS region")


class StoreSignalsInput(BaseModel):
    """Input for store_signals_snapshot activity."""

    signals: Signals
    dsql_endpoint: str = Field(description="DSQL cluster endpoint")
    dsql_database: str = Field(default="postgres", description="Database name")
    region: str = Field(default="eu-west-1", description="AWS region")


class GetLatestAssessmentInput(BaseModel):
    """Input for get_latest_assessment activity."""

    dsql_endpoint: str = Field(description="DSQL cluster endpoint")
    dsql_database: str = Field(default="postgres", description="Database name")
    region: str = Field(default="eu-west-1", description="AWS region")


class GetAssessmentsInRangeInput(BaseModel):
    """Input for get_assessments_in_range activity."""

    start: str = Field(description="Start of time range (ISO 8601 UTC)")
    end: str = Field(description="End of time range (ISO 8601 UTC)")
    dsql_endpoint: str = Field(description="DSQL cluster endpoint")
    dsql_database: str = Field(default="postgres", description="Database name")
    region: str = Field(default="eu-west-1", description="AWS region")


class CheckRecentAssessmentInput(BaseModel):
    """Input for check_recent_assessment activity."""

    window: TimeDelta = Field(description="Time window to check for recent assessments")
    dsql_endpoint: str = Field(description="DSQL cluster endpoint")
    dsql_database: str = Field(default="postgres", description="Database name")
    region: str = Field(default="eu-west-1", description="AWS region")


class FetchSignalHistoryInput(BaseModel):
    """Input for fetch_signal_history activity."""

    lookback_minutes: int = Field(description="How far back to look")
    dsql_endpoint: str = Field(description="DSQL cluster endpoint")
    dsql_database: str = Field(default="postgres", description="Database name")
    region: str = Field(default="eu-west-1", description="AWS region")
