"""LogWatcherWorkflow - Continuous log monitoring for narrative signals.

This workflow continuously scans Loki for error patterns that explain
state transitions. These are Amplifier 13: "A small set of repeated
log messages often explains 80% of incidents."
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from whenever import TimeDelta

    from copilot.activities import query_loki_errors
    from copilot.models import LogPattern, LogWatcherInput, QueryLokiInput


@workflow.defn
class LogWatcherWorkflow:
    """Continuous log monitoring for narrative signals.

    This workflow:
    1. Queries Loki for error patterns every 30 seconds
    2. Detects narrative signal patterns
    3. Stores patterns for correlation with health assessments

    The workflow runs continuously until cancelled.
    """

    def __init__(self) -> None:
        self._recent_patterns: list[LogPattern] = []
        self._pattern_window_size = 20  # Keep last 20 pattern snapshots

    @workflow.run
    async def run(self, input: LogWatcherInput) -> None:
        """Run the log watching loop.

        Args:
            input: Workflow input containing Loki URL
        """
        workflow.logger.info("LogWatcherWorkflow started")

        while True:
            try:
                # Query Loki for error patterns
                patterns = await workflow.execute_activity(
                    query_loki_errors,
                    QueryLokiInput(loki_url=input.loki_url, lookback_seconds=60),
                    start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                )

                if patterns:
                    workflow.logger.info(f"Detected {len(patterns)} narrative patterns")

                    # Store patterns in memory for correlation
                    self._recent_patterns = patterns

            except Exception as e:
                workflow.logger.error(f"Error in log watching loop: {e}")
                # Continue watching even on errors

            # Sleep for 30 seconds before next query
            await workflow.sleep(TimeDelta(seconds=30).py_timedelta())

    @workflow.query
    def recent_patterns(self) -> list[dict]:
        """Query the most recent log patterns."""
        return [p.model_dump() for p in self._recent_patterns]

    @workflow.query
    def pattern_count(self) -> int:
        """Query the number of recent patterns."""
        return len(self._recent_patterns)
