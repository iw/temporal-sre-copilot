"""Pydantic response models for the FastAPI JSON API.

These models define the shape of every API response. FastAPI serializes
them automatically — whenever's native Pydantic support handles Instant → ISO 8601.

Principle: "Grafana Consumes, Not Computes"
All computation happens in workflows. The API serves pre-computed values.
"""

from pydantic import BaseModel, Field

from .assessment import SuggestedAction  # noqa: TC001
from .signals import HealthState  # noqa: TC001

# =============================================================================
# GET /status
# =============================================================================


class StatusResponse(BaseModel):
    """Current health status with signal taxonomy."""

    health_state: HealthState
    timestamp: str
    primary_signals: dict = Field(default_factory=dict)
    amplifiers: dict = Field(default_factory=dict)
    log_patterns: list[str] = Field(default_factory=list)
    recommended_actions: list[dict] = Field(default_factory=list)
    issue_count: int = 0


# =============================================================================
# GET /status/services
# =============================================================================


class ServiceStatus(BaseModel):
    """Health status for a single Temporal service."""

    name: str
    status: str
    key_signals: dict = Field(default_factory=dict)


class ServicesResponse(BaseModel):
    """Per-service health status for Grafana grid panel."""

    services: list[ServiceStatus] = Field(default_factory=list)


# =============================================================================
# GET /status/issues
# =============================================================================


class IssueResponse(BaseModel):
    """An issue from the issues table."""

    id: str
    severity: str
    title: str
    description: str
    likely_cause: str
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    related_signals: list[str] = Field(default_factory=list)
    created_at: str
    resolved_at: str | None = None


class IssuesResponse(BaseModel):
    """Active issues list."""

    issues: list[IssueResponse] = Field(default_factory=list)


# =============================================================================
# GET /status/summary
# =============================================================================


class SummaryResponse(BaseModel):
    """Natural language summary for Grafana text panel."""

    summary: str
    timestamp: str
    health_state: HealthState


# =============================================================================
# GET /status/timeline
# =============================================================================


class TimelineEntry(BaseModel):
    """A single health state change in the timeline."""

    id: str
    timestamp: str
    trigger: str
    health_state: HealthState
    primary_signals: dict = Field(default_factory=dict)
    issue_count: int = 0


class TimelineResponse(BaseModel):
    """Health status changes over time for Grafana state timeline."""

    timeline: list[TimelineEntry] = Field(default_factory=list)


# =============================================================================
# POST /actions
# =============================================================================


class ErrorResponse(BaseModel):
    """Generic error response."""

    error: str
    message: str
