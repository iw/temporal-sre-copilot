"""Workflow starter for the Copilot.

Starts the long-running observation workflows:
- ObserveClusterWorkflow  (continuous signal observation, 30s cycle)
- LogWatcherWorkflow      (continuous log scanning, 30s cycle)
- ScheduledAssessmentWorkflow (periodic LLM assessment, 5min cycle)

Each workflow uses a deterministic ID so restarts are idempotent.

Usage:
    python -m copilot.starter
    # or
    uv run python -m copilot.starter

Environment variables:
    TEMPORAL_ADDRESS   - Temporal server address (default: localhost:7233)
    TEMPORAL_NAMESPACE - Temporal namespace (default: default)
    COPILOT_TASK_QUEUE - Task queue name (default: copilot-task-queue)
    AMP_ENDPOINT       - Amazon Managed Prometheus query endpoint
    DSQL_ENDPOINT      - Aurora DSQL cluster endpoint
    LOKI_URL           - Loki query endpoint
    KNOWLEDGE_BASE_ID  - Bedrock Knowledge Base ID (optional)
"""

import asyncio
import logging
import os

from temporalio.common import WorkflowIDConflictPolicy

from copilot.models import LogWatcherInput, ObserveClusterInput, ScheduledAssessmentInput
from copilot.temporal import COPILOT_TASK_QUEUE, create_client

logger = logging.getLogger(__name__)

# Deterministic workflow IDs for idempotent starts
OBSERVE_WORKFLOW_ID = "copilot-observe-cluster"
LOG_WATCHER_WORKFLOW_ID = "copilot-log-watcher"
SCHEDULED_WORKFLOW_ID = "copilot-scheduled-assessment"


async def start_workflows() -> None:
    """Start all long-running Copilot workflows.

    Uses start_workflow with WorkflowIDConflictPolicy.USE_EXISTING
    so re-running this starter is safe — it won't duplicate workflows.
    """
    temporal_address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("COPILOT_TASK_QUEUE", COPILOT_TASK_QUEUE)

    amp_endpoint = os.environ.get("AMP_ENDPOINT", "")
    dsql_endpoint = os.environ.get("DSQL_ENDPOINT", "")
    loki_url = os.environ.get("LOKI_URL", "")
    kb_id = os.environ.get("KNOWLEDGE_BASE_ID")

    if not amp_endpoint:
        logger.error("AMP_ENDPOINT is required")
        return
    if not dsql_endpoint:
        logger.error("DSQL_ENDPOINT is required")
        return

    client = await create_client(temporal_address, namespace)

    # 1. Start ObserveClusterWorkflow
    logger.info("Starting ObserveClusterWorkflow: %s", OBSERVE_WORKFLOW_ID)
    await client.start_workflow(
        "ObserveClusterWorkflow",
        ObserveClusterInput(
            amp_endpoint=amp_endpoint,
            dsql_endpoint=dsql_endpoint,
        ),
        id=OBSERVE_WORKFLOW_ID,
        task_queue=task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    logger.info("ObserveClusterWorkflow started")

    # 2. Start LogWatcherWorkflow
    if loki_url:
        logger.info("Starting LogWatcherWorkflow: %s", LOG_WATCHER_WORKFLOW_ID)
        await client.start_workflow(
            "LogWatcherWorkflow",
            LogWatcherInput(loki_url=loki_url),
            id=LOG_WATCHER_WORKFLOW_ID,
            task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        logger.info("LogWatcherWorkflow started")
    else:
        logger.warning("LOKI_URL not set, skipping LogWatcherWorkflow")

    # 3. Start ScheduledAssessmentWorkflow
    logger.info("Starting ScheduledAssessmentWorkflow: %s", SCHEDULED_WORKFLOW_ID)
    await client.start_workflow(
        "ScheduledAssessmentWorkflow",
        ScheduledAssessmentInput(
            amp_endpoint=amp_endpoint,
            dsql_endpoint=dsql_endpoint,
            kb_id=kb_id,
            loki_url=loki_url or None,
        ),
        id=SCHEDULED_WORKFLOW_ID,
        task_queue=task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    logger.info("ScheduledAssessmentWorkflow started")

    logger.info("All Copilot workflows started successfully")


def main() -> None:
    """Entry point for the workflow starter."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(start_workflows())


if __name__ == "__main__":
    main()
