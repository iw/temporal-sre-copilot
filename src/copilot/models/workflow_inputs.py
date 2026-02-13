"""Pydantic models for workflow inputs.

Each workflow takes a single Pydantic model as its input parameter.
This provides:
- Type safety and validation
- Clear documentation of required/optional parameters
- Easy serialization for Temporal
- Consistent API across all workflows

IMPORTANT: When creating a Temporal Client or Worker, you MUST use
PydanticAIPlugin to properly serialize these Pydantic models:

    from temporalio.client import Client
    from pydantic_ai.durable_exec.temporal import PydanticAIPlugin

    client = await Client.connect(
        "localhost:7233",
        plugins=[PydanticAIPlugin()],
    )
"""

from pydantic import BaseModel, Field

from .signals import HealthState, Signals  # noqa: TC001 — Pydantic needs runtime imports


class ObserveClusterInput(BaseModel):
    """Input for ObserveClusterWorkflow.

    This workflow continuously observes cluster signals and evaluates
    health state using deterministic rules.
    """

    amp_endpoint: str = Field(description="Amazon Managed Prometheus query endpoint URL")
    dsql_endpoint: str = Field(description="DSQL cluster endpoint for state storage")


class LogWatcherInput(BaseModel):
    """Input for LogWatcherWorkflow.

    This workflow continuously scans Loki for error patterns that
    explain state transitions (narrative signals).
    """

    loki_url: str = Field(description="Loki query endpoint URL")


class AssessHealthInput(BaseModel):
    """Input for AssessHealthWorkflow.

    This workflow uses the dispatcher → researcher pattern to explain
    health state. The health state has ALREADY BEEN DECIDED by
    deterministic rules - this workflow only explains it.

    CRITICAL: health_state is passed in, NOT decided by LLM.
    """

    health_state: HealthState = Field(
        description="The health state (ALREADY DECIDED by deterministic rules)"
    )
    signals: Signals = Field(description="Current signals snapshot")
    trigger: str = Field(
        description="What triggered this assessment (e.g., 'state_change', 'scheduled')"
    )
    dsql_endpoint: str = Field(default="localhost", description="DSQL endpoint for storage")
    kb_id: str | None = Field(default=None, description="Bedrock Knowledge Base ID for RAG context")
    loki_url: str | None = Field(default=None, description="Loki URL for fetching log patterns")


class ScheduledAssessmentInput(BaseModel):
    """Input for ScheduledAssessmentWorkflow.

    This workflow runs periodic health assessments even without state
    changes, ensuring regular health checks.
    """

    amp_endpoint: str = Field(description="Amazon Managed Prometheus query endpoint URL")
    dsql_endpoint: str = Field(description="DSQL cluster endpoint for state storage")
    kb_id: str | None = Field(default=None, description="Bedrock Knowledge Base ID for RAG context")
    loki_url: str | None = Field(default=None, description="Loki URL for fetching log patterns")
