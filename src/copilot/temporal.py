"""Temporal client and worker utilities.

This module provides properly configured Temporal client and worker
creation using PydanticAIPlugin for Pydantic serialization and
automatic agent activity registration.

Usage:
    from copilot.temporal import create_client, create_worker

    client = await create_client("localhost:7233")
    worker = create_worker(client, "copilot-task-queue")
"""

from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from copilot.activities import (
    check_recent_assessment,
    fetch_rag_context,
    fetch_recent_log_patterns,
    fetch_signal_history,
    fetch_signals_from_amp,
    get_latest_assessment,
    query_loki_errors,
    store_health_assessment,
    store_signals_snapshot,
)
from copilot.workflows import (
    AssessHealthWorkflow,
    LogWatcherWorkflow,
    ObserveClusterWorkflow,
    ScheduledAssessmentWorkflow,
)

# Default task queue for Copilot workflows
COPILOT_TASK_QUEUE = "copilot-task-queue"

# All workflows registered with the Copilot worker
COPILOT_WORKFLOWS = [
    ObserveClusterWorkflow,
    LogWatcherWorkflow,
    AssessHealthWorkflow,
    ScheduledAssessmentWorkflow,
]

# Non-agent activities registered with the Copilot worker.
# Agent activities (model requests, tool calls) are auto-registered
# by PydanticAIPlugin via __pydantic_ai_agents__ on the workflow.
COPILOT_ACTIVITIES = [
    # AMP activities
    fetch_signals_from_amp,
    # Loki activities
    query_loki_errors,
    fetch_recent_log_patterns,
    # RAG activities
    fetch_rag_context,
    # State store activities
    store_health_assessment,
    store_signals_snapshot,
    fetch_signal_history,
    check_recent_assessment,
    get_latest_assessment,
]


async def create_client(
    target_host: str = "localhost:7233",
    namespace: str = "default",
) -> Client:
    """Create a Temporal client with PydanticAIPlugin.

    PydanticAIPlugin handles:
    - Pydantic serialization/deserialization
    - UserError as non-retryable
    - Auto-registration of agent activities from __pydantic_ai_agents__

    Args:
        target_host: Temporal server address (default: localhost:7233)
        namespace: Temporal namespace (default: default)

    Returns:
        Configured Temporal client
    """
    return await Client.connect(
        target_host,
        namespace=namespace,
        plugins=[PydanticAIPlugin()],
    )


def create_worker(
    client: Client,
    task_queue: str = COPILOT_TASK_QUEUE,
) -> Worker:
    """Create a Temporal worker with all Copilot workflows and activities.

    Agent activities (model requests, tool calls) are auto-registered
    by PydanticAIPlugin from __pydantic_ai_agents__ on each workflow.

    Args:
        client: Temporal client (must be created with PydanticAIPlugin)
        task_queue: Task queue name (default: copilot-task-queue)

    Returns:
        Configured Temporal worker
    """
    return Worker(
        client,
        task_queue=task_queue,
        workflows=COPILOT_WORKFLOWS,
        activities=COPILOT_ACTIVITIES,
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxedWorkflowRunner().restrictions.with_passthrough_modules(
                "copilot",
            )
        ),
    )
