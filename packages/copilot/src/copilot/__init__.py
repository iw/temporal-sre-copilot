"""Temporal SRE Copilot - AI-powered observability agent for Temporal deployments.

Quick Start:
    from copilot.temporal import create_client, create_worker
    from copilot.workflows import ObserveClusterInput, ObserveClusterWorkflow

    # Create client with Pydantic data converter
    client = await create_client("localhost:7233")

    # Start a workflow
    handle = await client.start_workflow(
        ObserveClusterWorkflow.run,
        ObserveClusterInput(
            prometheus_endpoint="http://prometheus:9090",
            dsql_endpoint="dsql.example.com",
        ),
        id="observe-cluster",
        task_queue="copilot-task-queue",
    )
"""

__version__ = "0.1.0"
