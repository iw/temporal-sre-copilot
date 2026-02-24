"""ObserveClusterWorkflow - Continuous signal observation.

This workflow continuously observes cluster signals and evaluates health state
using deterministic rules. When state changes, it triggers AssessHealthWorkflow.

Key Principle: "Rules Decide, AI Explains"
- Health state is evaluated by deterministic rules (no LLM)
- State changes trigger LLM-powered explanation

Reconciliation: On startup, the workflow fetches the latest stored assessment
from DSQL and uses its health state as the starting point. This ensures that
after a restart (e.g., code deploy), the workflow detects disagreements between
the stored state and the current evaluation and triggers a corrective assessment.
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from whenever import TimeDelta

    from copilot.activities import (
        fetch_deployment_context,
        fetch_signals_from_amp,
        get_latest_assessment,
        store_signals_snapshot,
    )
    from copilot.activities.inspect import FetchDeploymentContextInput
    from copilot.models import (
        AssessHealthInput,
        FetchSignalsInput,
        GetLatestAssessmentInput,
        HealthState,
        ObserveClusterInput,
        ScaleBand,
        Signals,
        StoreSignalsInput,
    )
    from copilot.models.gate_evaluation import evaluate_gates
    from copilot.models.state_machine import evaluate_health_state
    from copilot_core.deployment import (
        DeploymentContext,  # noqa: TC001 — used at runtime in workflow
    )


@workflow.defn
class ObserveClusterWorkflow:
    """Continuous signal observation with health state evaluation.

    This workflow:
    1. On startup, reconciles with the latest stored assessment
    2. Fetches signals from AMP every 30 seconds
    3. Stores signals in a sliding window
    4. Evaluates health state using deterministic rules
    5. Triggers AssessHealthWorkflow on state change (including corrections)

    The workflow runs continuously until cancelled.
    """

    def __init__(self) -> None:
        self._current_state = HealthState.HAPPY
        self._reconciled = False
        self._signal_window: list[Signals] = []
        self._window_size = 10  # Keep last 10 signal snapshots (5 minutes)
        self._consecutive_critical_count = 0  # Debounce counter for Critical transitions
        self._current_scale_band: ScaleBand | None = None
        self._deployment_context: DeploymentContext | None = None
        self._cycles_since_context_fetch = 0
        self._context_fetch_interval = 10  # Every 10 cycles = 5 minutes

    @workflow.run
    async def run(self, input: ObserveClusterInput) -> None:
        """Run the observation loop."""
        workflow.logger.info("ObserveClusterWorkflow started")

        # Extract resource identity and derive initial scale band from deployment profile
        resource_identity = None
        if input.deployment_profile:
            resource_identity = input.deployment_profile.resource_identity
            self._current_scale_band = _preset_to_scale_band(input.deployment_profile.preset_name)
            workflow.logger.info(
                "Deployment profile loaded: preset=%s initial_band=%s",
                input.deployment_profile.preset_name,
                self._current_scale_band.value if self._current_scale_band else "none",
            )

        # Reconcile with stored state before entering the loop.
        await self._reconcile_stored_state(input.dsql_endpoint)

        while True:
            try:
                # Fetch deployment context every N cycles
                should_fetch = (
                    resource_identity is not None
                    and self._cycles_since_context_fetch >= self._context_fetch_interval
                )
                if should_fetch:
                    assert resource_identity is not None  # narrowing for ty
                    self._deployment_context = await workflow.execute_activity(
                        fetch_deployment_context,
                        FetchDeploymentContextInput(resource_identity=resource_identity),
                        start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                    )
                    self._cycles_since_context_fetch = 0

                # Fetch current signals from AMP
                signals = await workflow.execute_activity(
                    fetch_signals_from_amp,
                    FetchSignalsInput(prometheus_endpoint=input.prometheus_endpoint),
                    start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                )

                # Store signals in DSQL
                await workflow.execute_activity(
                    store_signals_snapshot,
                    StoreSignalsInput(
                        signals=signals,
                        dsql_endpoint=input.dsql_endpoint,
                    ),
                    start_to_close_timeout=TimeDelta(seconds=10).py_timedelta(),
                )

                # Maintain sliding window in memory
                self._signal_window.append(signals)
                if len(self._signal_window) > self._window_size:
                    self._signal_window.pop(0)

                # DETERMINISTIC: Evaluate health state (no LLM)
                new_state, self._consecutive_critical_count, self._current_scale_band = (
                    evaluate_health_state(
                        signals.primary,
                        self._current_state,
                        consecutive_critical_count=self._consecutive_critical_count,
                        current_scale_band=self._current_scale_band,
                        deployment_context=self._deployment_context,
                    )
                )

                # Trigger assessment if state changed
                if new_state != self._current_state:
                    workflow.logger.info(
                        f"Health state changed: {self._current_state.value} → {new_state.value}"
                    )

                    # Compute gate evaluation so the LLM knows exactly
                    # which gates fired and which passed.
                    gate_eval = evaluate_gates(
                        signals.primary,
                        new_state,
                        self._current_scale_band or ScaleBand.STARTER,
                    )

                    await workflow.start_child_workflow(
                        "AssessHealthWorkflow",
                        args=[
                            AssessHealthInput(
                                health_state=new_state,
                                signals=signals,
                                trigger="state_change",
                                dsql_endpoint=input.dsql_endpoint,
                                gate_evaluation=gate_eval,
                            )
                        ],
                        id=f"assess-health-{workflow.now().isoformat()}",
                    )

                    self._current_state = new_state

                self._cycles_since_context_fetch += 1

            except Exception as e:
                workflow.logger.error(f"Error in observation loop: {e}")

            await workflow.sleep(TimeDelta(seconds=30).py_timedelta())

    async def _reconcile_stored_state(self, dsql_endpoint: str) -> None:
        """Reconcile in-memory state with the latest stored assessment.

        On a fresh start, the workflow defaults to HAPPY. If the stored
        assessment says something different (e.g., STRESSED from before
        a code fix), we adopt the stored state so the first evaluation
        cycle can detect the disagreement and trigger a corrective
        assessment.
        """
        try:
            assessment = await workflow.execute_activity(
                get_latest_assessment,
                GetLatestAssessmentInput(dsql_endpoint=dsql_endpoint),
                start_to_close_timeout=TimeDelta(seconds=10).py_timedelta(),
            )

            if assessment is not None:
                stored_state = HealthState(assessment.health_state)
                workflow.logger.info(f"Reconciled with stored assessment: {stored_state.value}")
                self._current_state = stored_state
            else:
                workflow.logger.info("No stored assessment found, starting at HAPPY")

        except Exception as e:
            workflow.logger.warning(f"Could not reconcile stored state, starting at HAPPY: {e}")

        self._reconciled = True

    @workflow.query
    def current_state(self) -> str:
        """Query the current health state."""
        return self._current_state.value

    @workflow.query
    def signal_window_size(self) -> int:
        """Query the current signal window size."""
        return len(self._signal_window)

    @workflow.query
    def deployment_context(self) -> str | None:
        """Query the cached deployment context as JSON."""
        if self._deployment_context is None:
            return None
        return self._deployment_context.model_dump_json()

    @workflow.query
    def current_scale_band(self) -> str | None:
        """Query the current scale band."""
        if self._current_scale_band is None:
            return None
        return self._current_scale_band.value


# Mapping from Config Compiler preset names to ScaleBand values
_PRESET_SCALE_BAND_MAP: dict[str, ScaleBand] = {
    "starter": ScaleBand.STARTER,
    "mid-scale": ScaleBand.MID_SCALE,
    "high-throughput": ScaleBand.HIGH_THROUGHPUT,
}


def _preset_to_scale_band(preset_name: str) -> ScaleBand | None:
    """Map a Config Compiler preset name to a ScaleBand.

    Returns None if the preset name is not recognized.
    """
    return _PRESET_SCALE_BAND_MAP.get(preset_name)
