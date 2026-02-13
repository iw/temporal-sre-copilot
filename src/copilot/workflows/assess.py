"""AssessHealthWorkflow - LLM-powered health explanation.

This workflow uses the dispatcher → researcher pattern to explain
health state. Following "Rules decide, AI explains" principle.

CRITICAL: The health state has ALREADY BEEN DECIDED by deterministic rules.
This workflow EXPLAINS the state, it does NOT change it.
"""

from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow, TemporalAgent
from temporalio import workflow

from copilot.agents import (
    NeedsDeepExplanation,
    NoExplanationNeeded,
    QuickExplanation,
    build_dispatcher_prompt,
    build_researcher_prompt,
    dispatcher_agent,
    researcher_agent,
)

temporal_dispatcher = TemporalAgent(dispatcher_agent)
temporal_researcher = TemporalAgent(researcher_agent)

with workflow.unsafe.imports_passed_through():
    from whenever import TimeDelta

    from copilot.activities import (
        fetch_rag_context,
        fetch_recent_log_patterns,
        fetch_signal_history,
        store_health_assessment,
    )
    from copilot.models import (
        AssessHealthInput,
        FetchLogPatternsInput,
        FetchRagContextInput,
        FetchSignalHistoryInput,
        HealthAssessment,
        HealthState,
        Signals,
        StoreAssessmentInput,
    )


def _create_minimal_assessment(
    health_state: HealthState,
    signals: Signals,
    trigger: str,
) -> HealthAssessment:
    """Create a minimal assessment when no explanation is needed."""
    return HealthAssessment(
        timestamp=workflow.now().isoformat(),
        trigger=trigger,
        health_state=health_state,
        primary_signals=signals.primary.model_dump(),
        amplifiers=signals.amplifiers.model_dump(),
        log_patterns=[],
        issues=[],
        recommended_actions=[],
        natural_language_summary=(
            f"Cluster is {health_state.value}. All signals within normal ranges."
        ),
    )


def _create_quick_assessment(
    health_state: HealthState,
    signals: Signals,
    trigger: str,
    summary: str,
    primary_factor: str,
) -> HealthAssessment:
    """Create a quick assessment with brief explanation."""
    return HealthAssessment(
        timestamp=workflow.now().isoformat(),
        trigger=trigger,
        health_state=health_state,
        primary_signals=signals.primary.model_dump(),
        amplifiers=signals.amplifiers.model_dump(),
        log_patterns=[],
        issues=[],
        recommended_actions=[],
        natural_language_summary=f"{summary} Primary factor: {primary_factor}",
    )


@workflow.defn
class AssessHealthWorkflow(PydanticAIWorkflow):
    """LLM-powered health explanation workflow.

    This workflow:
    1. Runs dispatcher for fast triage
    2. If needed, runs researcher for deep explanation
    3. Stores the assessment

    CRITICAL: health_state is passed in, NOT decided by LLM.
    """

    __pydantic_ai_agents__ = [temporal_dispatcher, temporal_researcher]

    @workflow.run
    async def run(self, input: AssessHealthInput) -> HealthAssessment:
        """Run the assessment workflow.

        Args:
            input: Workflow input containing health state, signals, and config

        Returns:
            HealthAssessment with explanation
        """
        workflow.logger.info(
            f"AssessHealthWorkflow started: "
            f"state={input.health_state.value}, trigger={input.trigger}"
        )

        # Build dispatcher prompt
        dispatcher_prompt = build_dispatcher_prompt(
            input.health_state,
            input.signals.primary,
            input.signals.amplifiers,
            input.trigger,
        )

        # Run dispatcher for fast triage
        dispatch_result = await temporal_dispatcher.run(dispatcher_prompt)

        # Handle dispatcher output
        if isinstance(dispatch_result.output, NoExplanationNeeded):
            workflow.logger.info("Dispatcher: No explanation needed")
            assessment = _create_minimal_assessment(
                input.health_state, input.signals, input.trigger
            )

        elif isinstance(dispatch_result.output, QuickExplanation):
            workflow.logger.info("Dispatcher: Quick explanation")
            assessment = _create_quick_assessment(
                input.health_state,
                input.signals,
                input.trigger,
                dispatch_result.output.summary,
                dispatch_result.output.primary_factor,
            )

        elif isinstance(dispatch_result.output, NeedsDeepExplanation):
            workflow.logger.info(
                f"Dispatcher: Deep explanation needed - {dispatch_result.output.complexity_reason}"
            )

            # Fetch RAG context based on contributing factors
            rag_context: list[str] = []
            if input.kb_id:
                try:
                    rag_context = await workflow.execute_activity(
                        fetch_rag_context,
                        FetchRagContextInput(
                            knowledge_base_id=input.kb_id,
                            contributing_factors=dispatch_result.output.contributing_factors,
                        ),
                        start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                    )
                except Exception as e:
                    workflow.logger.warning(f"Failed to fetch RAG context: {e}")

            # Fetch recent log patterns
            log_patterns = []
            if input.loki_url:
                try:
                    log_patterns = await workflow.execute_activity(
                        fetch_recent_log_patterns,
                        FetchLogPatternsInput(
                            loki_url=input.loki_url,
                            lookback_seconds=60,
                        ),
                        start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                    )
                except Exception as e:
                    workflow.logger.warning(f"Failed to fetch log patterns: {e}")

            # Fetch signal history
            signal_history = []
            try:
                signal_history = await workflow.execute_activity(
                    fetch_signal_history,
                    FetchSignalHistoryInput(
                        lookback_minutes=10,
                        dsql_endpoint=input.dsql_endpoint,
                    ),
                    start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                )
            except Exception as e:
                workflow.logger.warning(f"Failed to fetch signal history: {e}")

            # Build researcher prompt
            researcher_prompt = build_researcher_prompt(
                input.health_state,
                input.signals.primary,
                input.signals.amplifiers,
                log_patterns,
                rag_context,
                signal_history,
                input.trigger,
            )

            # Run deep explanation via researcher agent
            research_result = await temporal_researcher.run(researcher_prompt)

            # Use researcher output — trust the TemporalAgent to return the right type.
            # Narrow from HealthAssessment | str to HealthAssessment.
            if isinstance(research_result.output, str):
                workflow.logger.warning(
                    "Researcher returned raw string, creating minimal assessment"
                )
                assessment = _create_minimal_assessment(
                    input.health_state, input.signals, input.trigger
                )
            else:
                assessment = research_result.output

                # CRITICAL: Override fields the LLM may have hallucinated.
                # The LLM invents its own key names for signals/amplifiers,
                # but Grafana expects the Pydantic model's field names.
                assessment.timestamp = workflow.now().isoformat()
                assessment.health_state = input.health_state
                assessment.trigger = input.trigger
                assessment.primary_signals = input.signals.primary.model_dump()
                assessment.amplifiers = input.signals.amplifiers.model_dump()

        else:
            # Fallback - shouldn't happen
            workflow.logger.warning("Unexpected dispatcher output type")
            assessment = _create_minimal_assessment(
                input.health_state, input.signals, input.trigger
            )

        # Store assessment
        try:
            await workflow.execute_activity(
                store_health_assessment,
                StoreAssessmentInput(
                    assessment=assessment,
                    dsql_endpoint=input.dsql_endpoint,
                ),
                start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
            )
            workflow.logger.info("Assessment stored successfully")
        except Exception as e:
            workflow.logger.error(f"Failed to store assessment: {e}")

        return assessment
