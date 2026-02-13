"""Copilot worker entry point.

Starts a Temporal worker that runs all Copilot workflows and activities.
On boot, starts the three long-running workflows (idempotent via fixed
workflow IDs), then enters the polling loop.

Uses PydanticAIPlugin for durable LLM execution.

Usage:
    python -m copilot.worker
    # or
    uv run python -m copilot.worker

Environment variables:
    TEMPORAL_ADDRESS   - Temporal server address (default: localhost:7233)
    TEMPORAL_NAMESPACE - Temporal namespace (default: default)
    COPILOT_TASK_QUEUE - Task queue name (default: copilot-task-queue)
    AMP_ENDPOINT       - Amazon Managed Prometheus query endpoint
    DSQL_ENDPOINT      - Aurora DSQL cluster endpoint
    LOKI_URL           - Loki query endpoint (optional)
    KNOWLEDGE_BASE_ID  - Bedrock Knowledge Base ID (optional)
"""

import asyncio
import logging
import os
import signal

from temporalio.client import Client  # noqa: TC002
from temporalio.common import WorkflowIDConflictPolicy

from copilot.models import (
    LogWatcherInput,
    ObserveClusterInput,
    ScheduledAssessmentInput,
)
from copilot.temporal import COPILOT_TASK_QUEUE, create_client, create_worker

logger = logging.getLogger(__name__)

# Deterministic workflow IDs for idempotent starts
OBSERVE_WORKFLOW_ID = "copilot-observe-cluster"
LOG_WATCHER_WORKFLOW_ID = "copilot-log-watcher"
SCHEDULED_WORKFLOW_ID = "copilot-scheduled-assessment"


async def _start_workflows(
    client: Client,
    task_queue: str,
) -> None:
    """Start all long-running Copilot workflows.

    Uses WorkflowIDConflictPolicy.USE_EXISTING so this is idempotent —
    safe to call on every worker boot without duplicating workflows.
    """
    amp_endpoint = os.environ.get("AMP_ENDPOINT", "")
    dsql_endpoint = os.environ.get("DSQL_ENDPOINT", "")
    loki_url = os.environ.get("LOKI_URL", "")
    kb_id = os.environ.get("KNOWLEDGE_BASE_ID")

    if not amp_endpoint:
        logger.warning("AMP_ENDPOINT not set, skipping workflow start")
        return
    if not dsql_endpoint:
        logger.warning("DSQL_ENDPOINT not set, skipping workflow start")
        return

    # 1. ObserveClusterWorkflow
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

    # 2. LogWatcherWorkflow (only if Loki configured)
    if loki_url:
        logger.info("Starting LogWatcherWorkflow: %s", LOG_WATCHER_WORKFLOW_ID)
        await client.start_workflow(
            "LogWatcherWorkflow",
            LogWatcherInput(loki_url=loki_url),
            id=LOG_WATCHER_WORKFLOW_ID,
            task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    else:
        logger.warning("LOKI_URL not set, skipping LogWatcherWorkflow")

    # 3. ScheduledAssessmentWorkflow
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

    logger.info("All Copilot workflows started")


async def run_worker() -> None:
    """Start workflows, then run the Copilot worker until interrupted."""
    temporal_address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("COPILOT_TASK_QUEUE", COPILOT_TASK_QUEUE)

    logger.info(
        "Starting Copilot worker: address=%s namespace=%s task_queue=%s",
        temporal_address,
        namespace,
        task_queue,
    )

    client = await create_client(temporal_address, namespace)

    # Start workflows before entering the polling loop
    await _start_workflows(client, task_queue)

    worker = create_worker(client, task_queue)
    logger.info("Copilot worker polling for tasks")
    await worker.run()


def main() -> None:
    """Entry point for the worker process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    loop = asyncio.new_event_loop()

    # Graceful shutdown on SIGTERM/SIGINT
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: loop.stop())

    try:
        loop.run_until_complete(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker interrupted, shutting down")
    finally:
        loop.close()
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
