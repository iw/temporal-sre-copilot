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
        fetch_signals_from_amp,
        get_latest_assessment,
        store_signals_snapshot,
    )
    from copilot.models import (
        AssessHealthInput,
        FetchSignalsInput,
        GetLatestAssessmentInput,
        HealthState,
        ObserveClusterInput,
        Signals,
        StoreSignalsInput,
    )
    from copilot.models.state_machine import evaluate_health_state


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

    @workflow.run
    async def run(self, input: ObserveClusterInput) -> None:
        """Run the observation loop."""
        workflow.logger.info("ObserveClusterWorkflow started")

        # Reconcile with stored state before entering the loop.
        # This catches the case where a code deploy changes health
        # evaluation logic and the stored assessment is now stale.
        await self._reconcile_stored_state(input.dsql_endpoint)

        while True:
            try:
                # Fetch current signals from AMP
                signals = await workflow.execute_activity(
                    fetch_signals_from_amp,
                    FetchSignalsInput(amp_endpoint=input.amp_endpoint),
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
                new_state, self._consecutive_critical_count = evaluate_health_state(
                    signals.primary,
                    self._current_state,
                    consecutive_critical_count=self._consecutive_critical_count,
                )

                # Trigger assessment if state changed
                if new_state != self._current_state:
                    workflow.logger.info(
                        f"Health state changed: {self._current_state.value} → {new_state.value}"
                    )

                    await workflow.start_child_workflow(
                        "AssessHealthWorkflow",
                        args=[
                            AssessHealthInput(
                                health_state=new_state,
                                signals=signals,
                                trigger="state_change",
                                dsql_endpoint=input.dsql_endpoint,
                            )
                        ],
                        id=f"assess-health-{workflow.now().isoformat()}",
                    )

                    self._current_state = new_state

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
