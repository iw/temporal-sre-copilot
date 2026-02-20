"""Test that Pydantic models survive the Temporal workflow sandbox.

Reproduces the exact pattern from ObserveClusterWorkflow:
1. Activity returns a Signals model
2. Workflow passes that Signals into StoreSignalsInput(signals=signals)
3. Workflow calls another activity with StoreSignalsInput

The production error was:
    1 validation error for StoreSignalsInput
    signals
      Input should be a valid dictionary or instance of Signals
      [type=model_type, input_value=Signals(primary=PrimarySi...]
"""

import uuid
from datetime import timedelta

import pytest
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from whenever import Instant

with workflow.unsafe.imports_passed_through():
    from copilot.models import (
        FetchSignalsInput,
        Signals,
        StoreSignalsInput,
    )
    from copilot.models.signals import (
        AmplifierSignals,
        CacheAmplifiers,
        ConnectionPoolAmplifiers,
        DeployAmplifiers,
        FrontendSignals,
        GrpcAmplifiers,
        HistorySignals,
        HostAmplifiers,
        MatchingSignals,
        PersistenceAmplifiers,
        PersistenceSignals,
        PollerSignals,
        PrimarySignals,
        QueueAmplifiers,
        RuntimeAmplifiers,
        ShardAmplifiers,
        StateTransitionSignals,
        ThrottlingAmplifiers,
        WorkerAmplifiers,
        WorkflowCompletionSignals,
    )


def _make_signals() -> Signals:
    """Build a complete Signals object with realistic zero values."""
    return Signals(
        primary=PrimarySignals(
            state_transitions=StateTransitionSignals(
                throughput_per_sec=100.0, latency_p95_ms=15.0, latency_p99_ms=25.0
            ),
            workflow_completion=WorkflowCompletionSignals(
                completion_rate=0.99, success_per_sec=95.0, failed_per_sec=1.0
            ),
            history=HistorySignals(
                backlog_age_sec=0.5,
                task_processing_rate_per_sec=200.0,
                shard_churn_rate_per_sec=0.0,
            ),
            frontend=FrontendSignals(
                error_rate_per_sec=0.1, latency_p95_ms=10.0, latency_p99_ms=20.0
            ),
            matching=MatchingSignals(workflow_backlog_age_sec=0.1, activity_backlog_age_sec=0.2),
            poller=PollerSignals(
                poll_success_rate=0.95, poll_timeout_rate=0.05, long_poll_latency_ms=100.0
            ),
            persistence=PersistenceSignals(
                latency_p95_ms=5.0,
                latency_p99_ms=10.0,
                error_rate_per_sec=0.0,
                retry_rate_per_sec=0.0,
            ),
        ),
        amplifiers=AmplifierSignals(
            persistence=PersistenceAmplifiers(
                occ_conflicts_per_sec=0.0,
                cas_failures_per_sec=0.0,
                serialization_failures_per_sec=0.0,
            ),
            connection_pool=ConnectionPoolAmplifiers(
                utilization_pct=30.0,
                wait_count=0,
                wait_duration_ms=0.0,
                churn_rate_per_sec=0.0,
                opens_per_sec=0.0,
                closes_per_sec=0.0,
            ),
            queue=QueueAmplifiers(task_backlog_depth=0, retry_time_spent_sec=0.0),
            worker=WorkerAmplifiers(
                poller_concurrency=8, task_slots_available=100, task_slots_used=50
            ),
            cache=CacheAmplifiers(hit_rate=0.95, evictions_per_sec=0.0, size_bytes=1000000),
            shard=ShardAmplifiers(hot_shard_ratio=0.0, max_shard_load_pct=10.0),
            grpc=GrpcAmplifiers(in_flight_requests=5, server_queue_depth=0),
            runtime=RuntimeAmplifiers(goroutines=500, blocked_goroutines=0),
            host=HostAmplifiers(cpu_throttle_pct=0.0, memory_rss_bytes=500000000, gc_pause_ms=1.0),
            throttling=ThrottlingAmplifiers(
                rate_limit_events_per_sec=0.0, admission_rejects_per_sec=0.0
            ),
            deploy=DeployAmplifiers(
                task_restarts=0, membership_changes_per_min=0.0, leader_changes_per_min=0.0
            ),
        ),
        timestamp=Instant.now().format_iso(),
    )


# ---------------------------------------------------------------------------
# Stub activities that mirror the real ones
# ---------------------------------------------------------------------------


@activity.defn(name="fetch_signals_from_amp")
async def fake_fetch_signals(input: FetchSignalsInput) -> Signals:
    """Return a canned Signals object, same as the real activity would."""
    return _make_signals()


@activity.defn(name="store_signals_snapshot")
async def fake_store_signals(input: StoreSignalsInput) -> None:
    """Accept StoreSignalsInput — this is where the production error occurs."""
    # If we get here without a validation error, the test passes.
    assert isinstance(input.signals, Signals)


# ---------------------------------------------------------------------------
# Minimal workflow that reproduces the exact ObserveClusterWorkflow pattern
# ---------------------------------------------------------------------------


@workflow.defn
class SignalsRoundTripWorkflow:
    """Fetch signals from activity, pass into StoreSignalsInput, call store activity."""

    @workflow.run
    async def run(self, dsql_endpoint: str) -> str:
        # Step 1: Activity returns Signals
        signals = await workflow.execute_activity(
            fake_fetch_signals,
            FetchSignalsInput(prometheus_endpoint="http://fake-amp"),
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Step 2: Pass Signals into StoreSignalsInput (this is where it broke)
        store_input = StoreSignalsInput(
            signals=signals,
            dsql_endpoint=dsql_endpoint,
        )

        # Step 3: Call store activity
        await workflow.execute_activity(
            fake_store_signals,
            store_input,
            start_to_close_timeout=timedelta(seconds=10),
        )

        return "ok"


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.anyio


async def test_signals_survive_sandbox_round_trip():
    """Activity returns Signals → workflow wraps in StoreSignalsInput → no validation error."""
    async with await WorkflowEnvironment.start_local() as env:
        client = await Client.connect(
            env.client.service_client.config.target_host,
            plugins=[PydanticAIPlugin()],
        )
        task_queue = f"test-{uuid.uuid4()}"

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[SignalsRoundTripWorkflow],
            activities=[fake_fetch_signals, fake_store_signals],
        ):
            result = await client.execute_workflow(
                SignalsRoundTripWorkflow.run,
                "test.dsql.eu-west-1.on.aws",
                id=f"test-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            assert result == "ok"


# ---------------------------------------------------------------------------
# Scale-aware threshold workflow integration tests
# ---------------------------------------------------------------------------

with workflow.unsafe.imports_passed_through():
    from copilot.activities.inspect import FetchDeploymentContextInput
    from copilot.models import ObserveClusterInput, ThresholdOverrides
    from copilot_core.deployment import DeploymentContext, ResourceIdentity, ServiceReplicaState


@activity.defn(name="fetch_deployment_context")
async def fake_fetch_deployment_context(
    input: FetchDeploymentContextInput,
) -> DeploymentContext | None:
    """Return a canned DeploymentContext."""
    return DeploymentContext(
        history=ServiceReplicaState(running=2, desired=2),
        matching=ServiceReplicaState(running=1, desired=1),
        frontend=ServiceReplicaState(running=1, desired=1),
        worker=ServiceReplicaState(running=1, desired=1),
        timestamp=Instant.now().format_iso(),
    )


async def test_observe_cluster_input_with_scale_fields():
    """ObserveClusterInput with resource_identity and threshold_overrides
    serializes through Temporal."""
    identity = ResourceIdentity(
        dsql_endpoint="test.dsql.eu-west-1.on.aws",
        platform_identifier="temporal-dev",
        platform_type="compose",
    )
    overrides = ThresholdOverrides(persistence_latency_p99_max_ms=300.0)

    original = ObserveClusterInput(
        prometheus_endpoint="http://mimir:9009/prometheus",
        dsql_endpoint="test.dsql.eu-west-1.on.aws",
        resource_identity_json=identity.model_dump_json(),
        threshold_overrides_json=overrides.model_dump_json(),
    )

    from pydantic import TypeAdapter
    from pydantic_core import to_json

    json_bytes = to_json(original)
    restored = TypeAdapter(ObserveClusterInput).validate_json(json_bytes)
    assert restored.resource_identity_json is not None
    assert restored.threshold_overrides_json is not None

    # Verify the JSON can be parsed back into the models
    ri = ResourceIdentity.model_validate_json(restored.resource_identity_json)
    assert ri.platform_type == "compose"
    ov = ThresholdOverrides.model_validate_json(restored.threshold_overrides_json)
    assert ov.persistence_latency_p99_max_ms == 300.0


async def test_fetch_deployment_context_input_serializes():
    """FetchDeploymentContextInput survives the Temporal data converter."""
    from pydantic import TypeAdapter
    from pydantic_core import to_json

    identity = ResourceIdentity(
        dsql_endpoint="test.dsql.eu-west-1.on.aws",
        platform_identifier="temporal-dev",
        platform_type="compose",
    )
    original = FetchDeploymentContextInput(resource_identity=identity)
    json_bytes = to_json(original)
    restored = TypeAdapter(FetchDeploymentContextInput).validate_json(json_bytes)
    assert restored.resource_identity.platform_type == "compose"


@workflow.defn
class DeploymentContextWorkflow:
    """Test workflow that fetches deployment context from an activity."""

    @workflow.run
    async def run(self, dsql_endpoint: str) -> str:
        ctx = await workflow.execute_activity(
            fake_fetch_deployment_context,
            FetchDeploymentContextInput(
                resource_identity=ResourceIdentity(
                    dsql_endpoint=dsql_endpoint,
                    platform_identifier="test",
                    platform_type="compose",
                )
            ),
            start_to_close_timeout=timedelta(seconds=10),
        )
        assert ctx is not None
        assert ctx.history.running == 2
        return "ok"


async def test_deployment_context_survives_sandbox():
    """DeploymentContext returned from activity survives the workflow sandbox."""
    async with await WorkflowEnvironment.start_local() as env:
        client = await Client.connect(
            env.client.service_client.config.target_host,
            plugins=[PydanticAIPlugin()],
        )
        task_queue = f"test-ctx-{uuid.uuid4()}"

        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[DeploymentContextWorkflow],
            activities=[fake_fetch_deployment_context],
        ):
            result = await client.execute_workflow(
                DeploymentContextWorkflow.run,
                "test.dsql.eu-west-1.on.aws",
                id=f"test-ctx-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            assert result == "ok"
