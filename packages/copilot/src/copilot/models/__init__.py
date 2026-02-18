"""Pydantic models for the SRE Copilot.

Signal Taxonomy (26 signals total):
- Primary (12): Decide health state (forward progress indicators)
- Amplifiers (14): Explain why (resource pressure, contention)
- Narrative: Logs that explain transitions
- Worker (6+): Worker-side health (schedule-to-start, slots, pollers)

Health State Gates:
- CRITICAL: Forward progress collapsed (signals 1/3/4/5) or backlog age critical
- STRESSED: Progress continues but latency + backlog trending wrong (signals 2/4/8/11)
- HAPPY: Otherwise

Bottleneck Classification:
- SERVER_LIMITED: Server can't keep up (high backlog, persistence latency)
- WORKER_LIMITED: Workers can't keep up (slots exhausted, high schedule-to-start)
- MIXED: Both under pressure
- HEALTHY: Neither constrained

Key Principle: "Rules decide, AI explains"
- Health state is determined by deterministic rules in the Health State Machine
- The LLM receives the state and explains/ranks issues—it never decides state
"""

from .activity_inputs import (
    CheckRecentAssessmentInput,
    FetchLogPatternsInput,
    FetchRagContextInput,
    FetchSignalHistoryInput,
    FetchSignalsInput,
    FetchWorkerSignalsInput,
    GetAssessmentsInRangeInput,
    GetLatestAssessmentInput,
    QueryLokiInput,
    StoreAssessmentInput,
    StoreSignalsInput,
)
from .api_responses import (
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
from .assessment import (
    ActionType,
    HealthAssessment,
    Issue,
    Severity,
    SuggestedAction,
)
from .config import (
    AmplifierThresholds,
    CopilotConfig,
    CriticalThresholds,
    HealthyThresholds,
    NarrativePatterns,
    StressedThresholds,
)
from .signals import (
    # Primary signal components
    AmplifierSignals,
    BottleneckClassification,
    CacheAmplifiers,
    ConnectionPoolAmplifiers,
    DeployAmplifiers,
    FrontendSignals,
    GrpcAmplifiers,
    HealthState,
    HistorySignals,
    HostAmplifiers,
    LogPattern,
    MatchingSignals,
    PersistenceAmplifiers,
    PersistenceSignals,
    PollerSignals,
    PrimarySignals,
    QueueAmplifiers,
    RuntimeAmplifiers,
    ShardAmplifiers,
    Signals,
    StateTransitionSignals,
    ThrottlingAmplifiers,
    WorkerAmplifiers,
    WorkerCacheAmplifiers,
    WorkerHealthSignals,
    WorkerPollAmplifiers,
    WorkerSignals,
    WorkflowCompletionSignals,
)
from .state_machine import (
    WorkerScalingContext,
    WorkerScalingWarning,
    classify_bottleneck,
    evaluate_health_state,
    evaluate_worker_scaling_rules,
)
from .workflow_inputs import (
    AssessHealthInput,
    LogWatcherInput,
    ObserveClusterInput,
    ScheduledAssessmentInput,
)

__all__ = [
    # API Response Models
    "StatusResponse",
    "ServiceStatus",
    "ServicesResponse",
    "IssueResponse",
    "IssuesResponse",
    "SummaryResponse",
    "TimelineEntry",
    "TimelineResponse",
    "ErrorResponse",
    # Health State
    "HealthState",
    # Primary Signals (12)
    "PrimarySignals",
    "StateTransitionSignals",
    "WorkflowCompletionSignals",
    "HistorySignals",
    "FrontendSignals",
    "MatchingSignals",
    "PollerSignals",
    "PersistenceSignals",
    # Amplifier Signals (14)
    "AmplifierSignals",
    "PersistenceAmplifiers",
    "ConnectionPoolAmplifiers",
    "QueueAmplifiers",
    "WorkerAmplifiers",
    "CacheAmplifiers",
    "ShardAmplifiers",
    "GrpcAmplifiers",
    "RuntimeAmplifiers",
    "HostAmplifiers",
    "ThrottlingAmplifiers",
    "DeployAmplifiers",
    # Narrative Signals
    "LogPattern",
    # Combined
    "Signals",
    # Worker Health Model
    "WorkerSignals",
    "WorkerCacheAmplifiers",
    "WorkerPollAmplifiers",
    "WorkerHealthSignals",
    "BottleneckClassification",
    # Assessment
    "Severity",
    "ActionType",
    "SuggestedAction",
    "Issue",
    "HealthAssessment",
    # Config
    "CriticalThresholds",
    "StressedThresholds",
    "HealthyThresholds",
    "AmplifierThresholds",
    "NarrativePatterns",
    "CopilotConfig",
    # State Machine
    "evaluate_health_state",
    "classify_bottleneck",
    "evaluate_worker_scaling_rules",
    "WorkerScalingWarning",
    "WorkerScalingContext",
    # Workflow Inputs
    "ObserveClusterInput",
    "LogWatcherInput",
    "AssessHealthInput",
    "ScheduledAssessmentInput",
    # Activity Inputs
    "FetchSignalsInput",
    "FetchWorkerSignalsInput",
    "QueryLokiInput",
    "FetchLogPatternsInput",
    "FetchRagContextInput",
    "StoreAssessmentInput",
    "StoreSignalsInput",
    "GetLatestAssessmentInput",
    "GetAssessmentsInRangeInput",
    "CheckRecentAssessmentInput",
    "FetchSignalHistoryInput",
]
