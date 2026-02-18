"""Workload shape modifiers that adjust preset defaults for specific workflow patterns.

Modifiers are applied on top of a Scale Preset to tune parameters for the
adopter's dominant workload shape. Each modifier produces a dict of parameter
key → override value that the compiler layers over the preset defaults.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkloadModifier:
    """A named set of parameter adjustments for a specific workload shape."""

    name: str
    description: str
    adjustments: dict[str, int | float | str | bool]


SIMPLE_CRUD = WorkloadModifier(
    name="simple-crud",
    description=(
        "Short-lived workflows with 1-2 activities; optimised for low latency via eager execution"
    ),
    adjustments={
        # Enable eager activities for minimal round-trip latency
        "system.enableActivityEagerExecution": True,
        "sdk.disable_eager_activities": False,
        # Lower matching partitions — simple workloads don't need high dispatch parallelism
        "matching.numTaskqueueReadPartitions": 4,
        "matching.numTaskqueueWritePartitions": 4,
        # Moderate concurrency — simple workflows are fast, don't need deep queues
        "sdk.max_concurrent_activities": 100,
        "sdk.max_concurrent_workflow_tasks": 100,
    },
)

ORCHESTRATOR = WorkloadModifier(
    name="orchestrator",
    description=(
        "Workflows that coordinate child workflows and multiple activity types; balanced dispatch"
    ),
    adjustments={
        # Balanced matching partitions for mixed task queue patterns
        "matching.numTaskqueueReadPartitions": 8,
        "matching.numTaskqueueWritePartitions": 8,
        # Moderate workflow task concurrency — orchestrators are CPU-light but coordination-heavy
        "sdk.max_concurrent_workflow_tasks": 150,
        "sdk.max_concurrent_activities": 150,
        # Slightly more workflow pollers for child workflow dispatch
        "sdk.workflow_task_pollers": 16,
        "sdk.activity_task_pollers": 8,
    },
)

BATCH_PROCESSOR = WorkloadModifier(
    name="batch-processor",
    description="High-volume activity processing with many parallel activities per workflow",
    adjustments={
        # Higher matching partitions for high activity dispatch throughput
        "matching.numTaskqueueReadPartitions": 16,
        "matching.numTaskqueueWritePartitions": 16,
        # High activity concurrency — batch workloads are activity-heavy
        "sdk.max_concurrent_activities": 500,
        "sdk.max_concurrent_local_activities": 500,
        # More activity pollers to keep up with dispatch rate
        "sdk.activity_task_pollers": 16,
        "sdk.workflow_task_pollers": 16,
    },
)

LONG_RUNNING = WorkloadModifier(
    name="long-running",
    description=(
        "Workflows that run for minutes to hours; optimised for sticky execution and state caching"
    ),
    adjustments={
        # Enable sticky execution with longer timeout for workflow state caching
        "sdk.sticky_schedule_to_start_timeout": "10s",
        # Lower matching partitions — long-running workflows have low dispatch rate
        "matching.numTaskqueueReadPartitions": 4,
        "matching.numTaskqueueWritePartitions": 4,
        # Fewer pollers — workflows are long-lived, not high-throughput
        "sdk.workflow_task_pollers": 8,
        "sdk.activity_task_pollers": 4,
    },
)


# Modifier registry for lookup by name
MODIFIERS: dict[str, WorkloadModifier] = {
    "simple-crud": SIMPLE_CRUD,
    "orchestrator": ORCHESTRATOR,
    "batch-processor": BATCH_PROCESSOR,
    "long-running": LONG_RUNNING,
}


def get_modifier(name: str) -> WorkloadModifier | None:
    """Look up a workload modifier by name."""
    return MODIFIERS.get(name)


def list_modifier_names() -> list[str]:
    """Return all available modifier names."""
    return list(MODIFIERS.keys())
