"""ScheduledAssessmentWorkflow - Periodic health assessment.

This workflow runs periodic health assessments even without state changes.
It ensures regular health checks and avoids duplicate assessments.
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from whenever import TimeDelta

    from copilot.activities import (
        check_recent_assessment,
        fetch_signals_from_amp,
    )
    from copilot.models import (
        AssessHealthInput,
        CheckRecentAssessmentInput,
        FetchSignalsInput,
        HealthState,
        ScheduledAssessmentInput,
    )
    from copilot.models.state_machine import evaluate_health_state


@workflow.defn
class ScheduledAssessmentWorkflow:
    """Scheduled periodic health assessment.

    This workflow:
    1. Runs every 5 minutes
    2. Checks if a recent assessment exists (deduplication)
    3. If not, evaluates health state and triggers assessment

    The workflow runs continuously until cancelled.
    """

    @workflow.run
    async def run(self, input: ScheduledAssessmentInput) -> None:
        """Run the scheduled assessment loop.

        Args:
            input: Workflow input containing endpoints and optional KB/Loki config
        """
        workflow.logger.info("ScheduledAssessmentWorkflow started")

        while True:
            try:
                # Check if recent assessment exists (avoid duplicate work)
                # Use 4-minute window to allow some overlap
                recent = await workflow.execute_activity(
                    check_recent_assessment,
                    CheckRecentAssessmentInput(
                        window=TimeDelta(minutes=4),
                        dsql_endpoint=input.dsql_endpoint,
                    ),
                    start_to_close_timeout=TimeDelta(seconds=10).py_timedelta(),
                )

                if not recent:
                    workflow.logger.info("No recent assessment, triggering scheduled assessment")

                    # Fetch current signals
                    signals = await workflow.execute_activity(
                        fetch_signals_from_amp,
                        FetchSignalsInput(prometheus_endpoint=input.prometheus_endpoint),
                        start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                    )

                    # Evaluate health state (deterministic)
                    # Only primary signals decide state — amplifiers explain WHY later
                    # Scheduled assessments use count=0 since they don't track
                    # consecutive observations (that's ObserveClusterWorkflow's job)
                    health_state, _ = evaluate_health_state(
                        signals.primary,
                        HealthState.HAPPY,  # Default for scheduled
                    )

                    # Build input for child workflow
                    assess_input = AssessHealthInput(
                        health_state=health_state,
                        signals=signals,
                        trigger="scheduled",
                        dsql_endpoint=input.dsql_endpoint,
                        kb_id=input.kb_id,
                        loki_url=input.loki_url,
                    )

                    # Start child workflow for assessment
                    await workflow.start_child_workflow(
                        "AssessHealthWorkflow",
                        args=[assess_input],
                        id=f"scheduled-assessment-{workflow.now().isoformat()}",
                    )
                else:
                    workflow.logger.debug("Recent assessment exists, skipping")

            except Exception as e:
                workflow.logger.error(f"Error in scheduled assessment loop: {e}")
                # Continue even on errors

            # Sleep for 5 minutes before next check
            await workflow.sleep(TimeDelta(minutes=5).py_timedelta())
