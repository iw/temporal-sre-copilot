"""Health assessment models for the SRE Copilot.

Key Principle: "Rules decide, AI explains"
- health_state is determined by deterministic rules in the Health State Machine
- The LLM receives the state and explains/ranks issues—it never decides state

Date/Time: All timestamps use `whenever` library (UTC-first, Rust-backed).
"""

from enum import StrEnum

from pydantic import BaseModel, Field
from whenever import Instant

from .signals import HealthState, LogPattern  # noqa: TC001 — Pydantic needs runtime imports


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return Instant.now().format_iso()


class Severity(StrEnum):
    """Issue severity levels."""

    WARNING = "warning"
    CRITICAL = "critical"


class ActionType(StrEnum):
    """Types of remediation actions."""

    SCALE = "scale"  # Scale a service up/down
    RESTART = "restart"  # Restart a service
    CONFIGURE = "configure"  # Change configuration
    ALERT = "alert"  # Send an alert


class SuggestedAction(BaseModel):
    """A suggested remediation action with confidence score.

    Actions are suggested by the LLM but NOT automatically executed.
    The structure supports future automation (Requirement 10.2).
    """

    action_type: ActionType
    target_service: str = Field(description="Service to apply the action to")
    description: str = Field(description="Human-readable description of the action")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    parameters: dict | None = Field(default=None, description="Action-specific parameters")
    risk_level: str = Field(default="low", description="Risk level: low, medium, high")


class Issue(BaseModel):
    """An identified issue with suggested remediation.

    Issues are identified by the LLM based on signals and logs.
    The LLM explains what's happening and suggests actions.
    """

    severity: Severity
    title: str = Field(description="Short title for the issue")
    description: str = Field(description="Detailed description of the issue")
    likely_cause: str = Field(description="Most likely root cause")
    suggested_actions: list[SuggestedAction] = Field(
        default_factory=list, description="Suggested remediation actions"
    )
    related_signals: list[str] = Field(
        default_factory=list, description="Signal names related to this issue"
    )
    related_logs: list[str] | None = Field(
        default=None, description="Log patterns related to this issue"
    )


class HealthAssessment(BaseModel):
    """Complete health assessment with signal taxonomy.

    CRITICAL: health_state is determined by rules, NOT by LLM.
    The LLM receives the state and explains it—it never changes it.

    Signal Taxonomy:
    - primary_signals: Forward progress indicators (decide state)
    - amplifiers: Resource pressure indicators (explain why)
    - log_patterns: Narrative signals from logs

    Date/Time: timestamp uses `whenever.Instant` (UTC).
    """

    timestamp: str = Field(
        default_factory=_now_iso, description="When assessment was created (ISO 8601 UTC)"
    )
    trigger: str = Field(description="What triggered this assessment: state_change, scheduled")
    health_state: HealthState = Field(description="Health state determined by rules, NOT by LLM")
    primary_signals: dict = Field(description="Forward progress indicators")
    amplifiers: dict = Field(description="Resource pressure indicators")
    log_patterns: list[LogPattern] = Field(
        default_factory=list, description="Narrative signals from logs"
    )
    issues: list[Issue] = Field(default_factory=list, description="Identified issues")
    recommended_actions: list[SuggestedAction] = Field(
        default_factory=list, description="Top recommended actions"
    )
    natural_language_summary: str = Field(description="Human-readable summary of the assessment")
