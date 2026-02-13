"""Temporal workflows for the SRE Copilot.

Workflow Architecture:
- ObserveClusterWorkflow: Continuous signal observation, evaluates health state
- LogWatcherWorkflow: Continuous log monitoring for narrative signals
- AssessHealthWorkflow: LLM-powered explanation of health state
- ScheduledAssessmentWorkflow: Periodic assessments

Key Principle: "Rules Decide, AI Explains"
- ObserveClusterWorkflow evaluates health state using deterministic rules
- AssessHealthWorkflow receives the state and explains it (LLM never decides state)

Each workflow takes a single Pydantic model as input for type safety and clarity.
"""

from copilot.models import (
    AssessHealthInput,
    LogWatcherInput,
    ObserveClusterInput,
    ScheduledAssessmentInput,
)
from copilot.workflows.assess import AssessHealthWorkflow
from copilot.workflows.log_watcher import LogWatcherWorkflow
from copilot.workflows.observe import ObserveClusterWorkflow
from copilot.workflows.scheduled import ScheduledAssessmentWorkflow

__all__ = [
    # Workflows
    "ObserveClusterWorkflow",
    "LogWatcherWorkflow",
    "AssessHealthWorkflow",
    "ScheduledAssessmentWorkflow",
    # Workflow Inputs
    "ObserveClusterInput",
    "LogWatcherInput",
    "AssessHealthInput",
    "ScheduledAssessmentInput",
]
