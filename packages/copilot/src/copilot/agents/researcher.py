"""Researcher agent for deep health explanation.

The researcher is a thorough agent that provides detailed explanations
of health state with RAG context. It uses Claude Opus for deep analysis.

CRITICAL: The health state has ALREADY BEEN DECIDED by deterministic rules.
The researcher EXPLAINS the state, it does NOT change it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent

from copilot.models import HealthAssessment

if TYPE_CHECKING:
    from copilot.models import (
        AmplifierSignals,
        HealthState,
        LogPattern,
        PrimarySignals,
    )

# =============================================================================
# RESEARCHER AGENT
# =============================================================================

RESEARCHER_INSTRUCTIONS = """You are an expert SRE EXPLAINING Temporal cluster health.

CRITICAL PRINCIPLE: "Rules Decide, AI Explains"
- The health state has ALREADY BEEN DECIDED by deterministic rules
- You MUST NOT change the health_state field
- Your job is to EXPLAIN why the cluster is in this state

## Your Responsibilities

1. **Explain the Current State**
   - Why is the cluster in this health state?
   - What signals led to this determination?
   - How does forward progress look?

2. **Identify Issues**
   - What problems are affecting the cluster?
   - Rank issues by severity and impact
   - Connect issues to specific signals

3. **Suggest Remediation Actions**
   - What can be done to improve the situation?
   - Provide confidence scores (0.0-1.0) for each action
   - Consider risk levels (low, medium, high)

4. **Provide Natural Language Summary**
   - Write a clear, concise summary for operators
   - Focus on actionable insights
   - Avoid jargon where possible

## Signal Taxonomy

**Primary Signals** (decide state - forward progress indicators):
1. State Transition Throughput - Real forward progress
2. State Transition Latency - Early warning of contention
3. Workflow Completion Rate - User-visible "is work finishing?"
4. History Backlog Age - Strongest predictor of cascading failures
5. History Processing Rate - Capacity vs demand
6. History Shard Churn - Membership instability
7. Frontend Error Rate - Client impact
8. Frontend Latency - API degradation
9. Matching Backlog Age - Work waiting
10. Poller Health - Starvation and matching pressure
11. Persistence Latency - Primary systemic dependency
12. Persistence Error Rate - "Slow but working" vs "failing"

**Amplifiers** (explain why - resource pressure):
1. Persistence Contention → tune retries, increase History capacity
2. Connection Pool Saturation → pool sizing, reduce churn
3. DB Connection Churn → fix token caching, tune reservoir
4. Queue Depth → scale capacity, tune concurrency
5. Retry Time → tune retry policies, fix root cause
6. Worker Saturation → scale workers, increase limits
7. Cache Pressure → increase cache size
8. Shard Hot Spotting → rebalance shards
9. gRPC Saturation → tune connection pools
10. Runtime Pressure → scale instances
11. Host Pressure → scale instances, tune memory
12. Rate Limiting → increase quotas
13. Log Patterns → address root cause
14. Deploy Churn → stabilize deployments

## Output Format

Return a HealthAssessment with:
- timestamp: Current time (ISO 8601)
- trigger: What triggered this assessment
- health_state: THE SAME STATE THAT WAS PASSED IN (do not change!)
- primary_signals: Summary of forward progress indicators
- amplifiers: Summary of resource pressure indicators
- log_patterns: Relevant log patterns
- issues: List of identified issues with severity, cause, and actions
- recommended_actions: Top 3-5 actions ranked by confidence
- natural_language_summary: Clear summary for operators

Be thorough but concise. Focus on actionable insights."""


# Note: We define a custom result type that matches HealthAssessment structure
# but allows the LLM to populate it. The workflow will enforce health_state.

researcher_agent = Agent(
    "bedrock:eu.anthropic.claude-opus-4-6-v1",
    instructions=RESEARCHER_INSTRUCTIONS,
    output_type=HealthAssessment,
    name="health_researcher",
)


def build_researcher_prompt(
    health_state: HealthState,
    primary_signals: PrimarySignals,
    amplifiers: AmplifierSignals,
    log_patterns: list[LogPattern],
    rag_context: list[str],
    signal_history: list[dict],
    trigger: str,
) -> str:
    """Build the prompt for the researcher agent.

    Args:
        health_state: The health state (ALREADY DECIDED by rules)
        primary_signals: Forward progress indicators
        amplifiers: Resource pressure indicators
        log_patterns: Narrative signals from logs
        rag_context: Relevant documentation from knowledge base
        signal_history: Recent signal snapshots for trend analysis
        trigger: What triggered this assessment

    Returns:
        Formatted prompt string
    """
    # Format log patterns
    log_section = "None detected"
    if log_patterns:
        log_lines = []
        for p in log_patterns[:10]:  # Limit to top 10
            log_lines.append(f"- [{p.service}] {p.pattern}: {p.count} occurrences")
        log_section = "\n".join(log_lines)

    # Format RAG context
    rag_section = "No relevant documentation found"
    if rag_context:
        rag_section = "\n\n".join(rag_context[:5])  # Limit to 5 chunks

    # Format signal history (trends)
    trend_section = "No historical data available"
    if signal_history and len(signal_history) >= 2:
        trend_section = f"Comparing {len(signal_history)} snapshots over recent window"

    return f"""## Health State (ALREADY DECIDED - DO NOT CHANGE)
**{health_state.value.upper()}**

## Trigger
{trigger}

## Primary Signals (Forward Progress)

### State Transitions
- Throughput: {primary_signals.state_transitions.throughput_per_sec:.1f}/sec
- Latency p95: {primary_signals.state_transitions.latency_p95_ms:.0f}ms
- Latency p99: {primary_signals.state_transitions.latency_p99_ms:.0f}ms

### Workflow Completion
- Completion Rate: {primary_signals.workflow_completion.completion_rate:.1%}
- Success Rate: {primary_signals.workflow_completion.success_per_sec:.1f}/sec
- Failed Rate: {primary_signals.workflow_completion.failed_per_sec:.2f}/sec

### History Service
- Backlog Age: {primary_signals.history.backlog_age_sec:.1f}s
- Processing Rate: {primary_signals.history.task_processing_rate_per_sec:.1f}/sec
- Shard Churn: {primary_signals.history.shard_churn_rate_per_sec:.2f}/sec

### Frontend Service
- Error Rate: {primary_signals.frontend.error_rate_per_sec:.2f}/sec
- Latency p95: {primary_signals.frontend.latency_p95_ms:.0f}ms
- Latency p99: {primary_signals.frontend.latency_p99_ms:.0f}ms

### Matching Service
- Workflow Backlog Age: {primary_signals.matching.workflow_backlog_age_sec:.1f}s
- Activity Backlog Age: {primary_signals.matching.activity_backlog_age_sec:.1f}s

### Poller Health
- Success Rate: {primary_signals.poller.poll_success_rate:.1%}
- Timeout Rate: {primary_signals.poller.poll_timeout_rate:.1%}
- Long Poll Latency: {primary_signals.poller.long_poll_latency_ms:.0f}ms

### Persistence
- Latency p95: {primary_signals.persistence.latency_p95_ms:.0f}ms
- Latency p99: {primary_signals.persistence.latency_p99_ms:.0f}ms
- Error Rate: {primary_signals.persistence.error_rate_per_sec:.2f}/sec
- Retry Rate: {primary_signals.persistence.retry_rate_per_sec:.2f}/sec

## Amplifiers (Resource Pressure)

### Persistence Contention
- OCC Conflicts: {amplifiers.persistence.occ_conflicts_per_sec:.1f}/sec
- CAS Failures: {amplifiers.persistence.cas_failures_per_sec:.2f}/sec
- Serialization Failures: {amplifiers.persistence.serialization_failures_per_sec:.2f}/sec

### Connection Pool
- Utilization: {amplifiers.connection_pool.utilization_pct:.0f}%
- Wait Count: {amplifiers.connection_pool.wait_count}
- Wait Duration: {amplifiers.connection_pool.wait_duration_ms:.0f}ms
- Churn Rate: {amplifiers.connection_pool.churn_rate_per_sec:.1f}/sec

### Queue Pressure
- Task Backlog Depth: {amplifiers.queue.task_backlog_depth}
- Retry Time Spent: {amplifiers.queue.retry_time_spent_sec:.1f}s

### Worker Saturation
- Poller Concurrency: {amplifiers.worker.poller_concurrency}
- Slots Available: {amplifiers.worker.task_slots_available}
- Slots Used: {amplifiers.worker.task_slots_used}

### Cache
- Hit Rate: {amplifiers.cache.hit_rate:.1%}
- Evictions: {amplifiers.cache.evictions_per_sec:.1f}/sec

### Runtime
- Goroutines: {amplifiers.runtime.goroutines}
- Blocked: {amplifiers.runtime.blocked_goroutines}

### Host
- GC Pause: {amplifiers.host.gc_pause_ms:.1f}ms
- CPU Throttle: {amplifiers.host.cpu_throttle_pct:.0f}%

### Throttling
- Rate Limit Events: {amplifiers.throttling.rate_limit_events_per_sec:.1f}/sec

### Deploy Churn
- Membership Changes: {amplifiers.deploy.membership_changes_per_min:.1f}/min
- Task Restarts: {amplifiers.deploy.task_restarts}

## Narrative Signals (Log Patterns)
{log_section}

## Signal Trends
{trend_section}

## Knowledge Base Context
{rag_section}

---

Provide a comprehensive HealthAssessment explaining this state.
Remember: The health_state is {health_state.value.upper()} - DO NOT CHANGE IT."""
