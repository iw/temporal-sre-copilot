"""Dispatcher agent for fast health triage.

The dispatcher is a lightweight agent that decides how much explanation is needed.
It uses Claude Sonnet for fast, cost-effective triage.

CRITICAL: The health state has ALREADY BEEN DECIDED by deterministic rules.
The dispatcher decides explanation depth, NOT health state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic_ai import Agent

if TYPE_CHECKING:
    from copilot.models import AmplifierSignals, HealthState, PrimarySignals

# =============================================================================
# DISPATCHER OUTPUT TYPES
# =============================================================================


class NoExplanationNeeded(BaseModel):
    """State is clear from signals, no detailed explanation required.

    Used when:
    - State is HAPPY and all signals are healthy
    - State change is obvious from a single dominant signal
    """

    reason: str = Field(description="Brief reason why no explanation is needed")


class QuickExplanation(BaseModel):
    """Simple explanation without deep analysis.

    Used when:
    - State is STRESSED with clear cause
    - Single amplifier is obviously responsible
    """

    summary: str = Field(description="Brief summary of why the cluster is in this state")
    primary_factor: str = Field(description="The main contributing factor")


class NeedsDeepExplanation(BaseModel):
    """Complex situation requiring detailed analysis.

    Used when:
    - Multiple amplifiers are elevated
    - State is CRITICAL
    - Root cause is unclear
    """

    contributing_factors: list[str] = Field(
        description="List of factors that may be contributing to the state"
    )
    priority: str = Field(description="Priority level: low, medium, high")
    complexity_reason: str = Field(description="Why this situation needs deep analysis")


DispatcherOutput = NoExplanationNeeded | QuickExplanation | NeedsDeepExplanation


# =============================================================================
# DISPATCHER AGENT
# =============================================================================

DISPATCHER_INSTRUCTIONS = """You are a quick triage agent for Temporal cluster health explanation.

CRITICAL PRINCIPLE: "Rules Decide, AI Explains"
- The health state has ALREADY BEEN DECIDED by deterministic rules
- Your job is to decide how much EXPLANATION is needed, NOT to change the state
- You CANNOT and MUST NOT suggest a different health state

Given the health state and signals, determine the appropriate response:

1. **NoExplanationNeeded** - Use when:
   - State is HAPPY and all signals are within healthy thresholds
   - The state is obvious and self-explanatory
   - No amplifiers are elevated

2. **QuickExplanation** - Use when:
   - State is STRESSED with a clear, single cause
   - One amplifier is obviously responsible
   - The situation is straightforward

3. **NeedsDeepExplanation** - Use when:
   - State is CRITICAL (always needs explanation)
   - Multiple amplifiers are elevated
   - Root cause is unclear or complex
   - State changed unexpectedly

SIGNAL TAXONOMY:
- **Primary Signals**: Forward progress indicators (decide state)
  - State transitions, workflow completions, backlog age, processing rates
- **Amplifiers**: Resource pressure indicators (explain why)
  - Persistence contention, connection pool, queue depth, worker saturation

Be fast and decisive. Only escalate to deep explanation when truly needed.
Typical response time should be 1-2 seconds."""

dispatcher_agent = Agent(
    "bedrock:eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    instructions=DISPATCHER_INSTRUCTIONS,
    output_type=[NoExplanationNeeded, QuickExplanation, NeedsDeepExplanation],  # type: ignore
    name="health_dispatcher",
)


def build_dispatcher_prompt(
    health_state: HealthState,
    primary_signals: PrimarySignals,
    amplifiers: AmplifierSignals,
    trigger: str,
) -> str:
    """Build the prompt for the dispatcher agent.

    Args:
        health_state: The health state (ALREADY DECIDED by rules)
        primary_signals: Forward progress indicators
        amplifiers: Resource pressure indicators
        trigger: What triggered this assessment (state_change, scheduled)

    Returns:
        Formatted prompt string
    """
    st_throughput = primary_signals.state_transitions.throughput_per_sec
    st_p99 = primary_signals.state_transitions.latency_p99_ms
    fe_err = primary_signals.frontend.error_rate_per_sec
    fe_p99 = primary_signals.frontend.latency_p99_ms

    return f"""## Health State (ALREADY DECIDED)
**{health_state.value.upper()}**

## Trigger
{trigger}

## Primary Signals (Forward Progress)
- State Transitions: {st_throughput:.1f}/sec (p99: {st_p99:.0f}ms)
- Workflow Completion Rate: {primary_signals.workflow_completion.completion_rate:.1%}
- History Backlog Age: {primary_signals.history.backlog_age_sec:.1f}s
- History Processing Rate: {primary_signals.history.task_processing_rate_per_sec:.1f}/sec
- History Shard Churn: {primary_signals.history.shard_churn_rate_per_sec:.2f}/sec
- Frontend Error Rate: {fe_err:.2f}/sec (p99: {fe_p99:.0f}ms)
- Matching Workflow Backlog: {primary_signals.matching.workflow_backlog_age_sec:.1f}s
- Matching Activity Backlog: {primary_signals.matching.activity_backlog_age_sec:.1f}s
- Poller Success Rate: {primary_signals.poller.poll_success_rate:.1%}
- Persistence Latency p99: {primary_signals.persistence.latency_p99_ms:.0f}ms
- Persistence Error Rate: {primary_signals.persistence.error_rate_per_sec:.2f}/sec

## Amplifiers (Resource Pressure)
- OCC Conflicts: {amplifiers.persistence.occ_conflicts_per_sec:.1f}/sec
- Connection Pool Utilization: {amplifiers.connection_pool.utilization_pct:.0f}%
- Connection Pool Wait Count: {amplifiers.connection_pool.wait_count}
- Connection Churn: {amplifiers.connection_pool.churn_rate_per_sec:.1f}/sec
- Task Backlog Depth: {amplifiers.queue.task_backlog_depth}
- Retry Time Spent: {amplifiers.queue.retry_time_spent_sec:.1f}s
- Worker Slots Available: {amplifiers.worker.task_slots_available}
- Cache Hit Rate: {amplifiers.cache.hit_rate:.1%}
- Goroutines: {amplifiers.runtime.goroutines}
- GC Pause: {amplifiers.host.gc_pause_ms:.1f}ms
- Rate Limit Events: {amplifiers.throttling.rate_limit_events_per_sec:.1f}/sec
- Membership Changes: {amplifiers.deploy.membership_changes_per_min:.1f}/min

Decide: NoExplanationNeeded, QuickExplanation, or NeedsDeepExplanation?"""
