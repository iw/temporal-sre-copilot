"""Researcher agent for deep health explanation.

The researcher is a thorough agent that provides detailed explanations
of health state with RAG context. It uses Claude Opus for deep analysis.

CRITICAL: The health state has ALREADY BEEN DECIDED by deterministic rules.
The researcher EXPLAINS the state, it does NOT change it.

Prompt Design Principles:
- Present services as actors with roles and relationships, not as metric lists
- Pre-classify signal states so the LLM explains patterns, not numbers
- Pass gate evaluation results so the LLM knows exactly what triggered the state
- Prohibit citing specific metric values — Grafana renders numbers
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
    from copilot.models.gate_evaluation import GateEvaluation

# =============================================================================
# RESEARCHER AGENT — System Instructions
# =============================================================================

RESEARCHER_INSTRUCTIONS = """You are an expert SRE narrator explaining Temporal cluster health.

## Core Principle: "Rules Decide, AI Explains"

The health state has ALREADY BEEN DECIDED by deterministic rules. You MUST NOT
change the health_state field. Your job is to tell the STORY of what happened.

## How to Tell the Story

A Temporal cluster is an ensemble of services, each with a specific role.
Your narrative should describe how these actors behaved and how their
relationships explain the current state.

### The Cast

**Frontend** — The gateway. Every client request enters here. Its latency
reflects what's happening deeper in the system. When Frontend is slow, ask:
"who is it waiting for?" Frontend itself does little computation.

**History** — The protagonist. Processes every state transition, manages shard
ownership, executes all persistence operations. When History struggles, the
whole cluster feels it. Its persistence latency measures the FULL path:
serialization → connection pool checkout → DSQL query execution →
deserialization → OCC retry. This is NOT raw database latency.

**Matching** — The matchmaker. Connects tasks to workers. Its backlog age
is the clearest signal of supply (workers) vs demand (tasks). Zero backlog
means workers are keeping up.

**Worker** (Temporal internal) — The housekeeper. Runs system workflows:
retention, archival, cleanup. Usually a background character, but during
retention storms it generates significant persistence load with zero
workflow throughput.

**DSQL** — The foundation. Fast (sub-ms checkout, low single-digit ms queries).
But "persistence latency" ≠ "DSQL latency." The persistence path through
History adds serialization, conditional updates, and multi-statement
transactions on top of DSQL's raw performance.

**SDK Workers** — External actors. They submit and process work. Their
behaviour shapes the demand curve everything else responds to.

### The Relationships

Frontend routes to History (state transitions) and Matching (task dispatch).
Matching delivers tasks to SDK Workers via long-poll.
History persists to DSQL (the heaviest I/O path).
History creates tasks in Matching after state transitions.
Worker (internal) executes system workflows through History.

## ABSOLUTE RULES

1. **NEVER cite specific metric values.** Do not write "latency is 467ms" or
   "throughput is 48.5/sec." Grafana renders numbers. You explain patterns
   and relationships. Say "persistence latency is within the expected envelope
   for this scale band" or "frontend latency is elevated due to non-poll
   long-running operations."

2. **Use the gate evaluation.** The prompt tells you exactly which gates fired
   and which passed. Your narrative MUST be consistent with this. If Signal 8
   (Frontend Latency) fired but Signal 11 (Persistence Latency) passed, do NOT
   blame persistence. Explain why frontend latency is elevated.

3. **Consistency between summary and issues.** If your summary says a metric
   is an artifact or expected behaviour, do NOT flag it as a high-severity
   issue. The issues list must match the narrative.

4. **Understand the persistence path.** "Persistence latency" is the full
   History service round-trip, not database latency. With zero OCC conflicts,
   zero errors, and sub-ms pool checkout, the cost is in Temporal's own
   persistence operations (multi-statement transactions, conditional updates)
   plus network RTT. This is normal for DSQL-backed Temporal.

5. **Respect scale band context.** A starter cluster at 50 st/s has different
   "normal" than a production cluster at 500 st/s. The gate evaluation tells
   you which band is active and what thresholds apply.

## Common Patterns (NOT problems)

- **Idle cluster**: Zero throughput, ~90s frontend latency, ~100% poller
  timeout rate. Workers long-poll for ~90s waiting for tasks. Normal.

- **System-busy cluster**: Zero workflow throughput but high persistence ops
  from retention/archival. The cluster is doing housekeeping, not broken.

- **Poller timeouts under bursty load**: 30-50% timeout rate during load is
  healthy — some pollers wait between task bursts. Only concerning at high
  sustained throughput with rising backlog.

- **Persistence latency on DSQL**: 300-500ms p99 for History persistence
  operations is the expected envelope for DSQL-backed Temporal at starter
  scale. This is the full persistence path cost, not database slowness.

## Output Format

Return a HealthAssessment with:
- health_state: THE SAME STATE THAT WAS PASSED IN (do not change)
- issues: Identified issues with severity consistent with your narrative
- recommended_actions: Top 3-5 actions ranked by confidence
- natural_language_summary: A clear narrative explaining the cluster's story

Focus on the story: what happened, why, and what to do about it."""


researcher_agent = Agent(
    "bedrock:eu.anthropic.claude-opus-4-6-v1",
    instructions=RESEARCHER_INSTRUCTIONS,
    output_type=HealthAssessment,
    name="health_researcher",
)


# =============================================================================
# PROMPT BUILDER — Actors and Relationships, Not Spreadsheets
# =============================================================================


def build_researcher_prompt(
    health_state: HealthState,
    primary_signals: PrimarySignals,
    amplifiers: AmplifierSignals,
    log_patterns: list[LogPattern],
    rag_context: list[str],
    signal_history: list[dict],
    trigger: str,
    *,
    gate_evaluation: GateEvaluation | None = None,
) -> str:
    """Build the prompt for the researcher agent.

    The prompt is structured as a story with actors, not a spreadsheet.
    Signal values are pre-classified into qualitative states so the LLM
    explains patterns rather than parroting numbers.
    """
    sections = [
        _build_verdict_section(health_state, trigger, gate_evaluation),
        _build_history_section(primary_signals, amplifiers),
        _build_frontend_section(primary_signals),
        _build_matching_section(primary_signals),
        _build_workers_section(primary_signals, amplifiers),
        _build_foundation_section(amplifiers),
        _build_cluster_stability_section(amplifiers),
        _build_log_section(log_patterns),
        _build_trend_section(signal_history),
        _build_rag_section(rag_context),
        _build_closing(health_state),
    ]
    return "\n\n".join(sections)


def _build_verdict_section(
    health_state: HealthState,
    trigger: str,
    gate_evaluation: GateEvaluation | None,
) -> str:
    """The verdict: what the state machine decided and why."""
    lines = [
        f"## Verdict: {health_state.value.upper()} (decided by rules — do not change)",
        f"Trigger: {trigger}",
    ]

    if gate_evaluation is None:
        lines.append("\nNo gate evaluation available — explain based on actor states below.")
        return "\n".join(lines)

    lines.append(f"\nScale band: {gate_evaluation.scale_band.value}")

    if gate_evaluation.is_idle:
        lines.append("The cluster is IDLE — no meaningful work, no errors, no backlog.")
        return "\n".join(lines)

    if gate_evaluation.is_system_busy:
        lines.append(
            "The cluster is SYSTEM-BUSY — zero workflow throughput but active "
            "retention/archival operations. This is housekeeping, not failure."
        )

    if gate_evaluation.triggering_signal:
        lines.append(f"\nTriggering signal: {gate_evaluation.triggering_signal}")

    lines.append("\n### Gate Evaluation (what the state machine computed)")
    for gate in gate_evaluation.stressed_gates:
        status = "FIRED ⚠" if gate.fired else "passed ✓"
        lines.append(f"- {gate.signal}: {status} — {gate.observed}")
        if gate.context:
            lines.append(f"  ({gate.context})")

    return "\n".join(lines)


def _build_history_section(
    primary: PrimarySignals,
    amplifiers: AmplifierSignals,
) -> str:
    """History service — the protagonist."""
    throughput = primary.state_transitions.throughput_per_sec
    processing = primary.history.task_processing_rate_per_sec

    # Classify History's state qualitatively
    if throughput < 1.0 and processing < 1.0:
        progress = "idle — minimal state transitions and task processing"
    elif throughput < 5.0:
        progress = "low activity — background system work only"
    else:
        progress = "actively processing state transitions"

    backlog = primary.history.backlog_age_sec
    if backlog < 1.0:
        backlog_state = "no backlog — execution engine is keeping up"
    elif backlog < 30.0:
        backlog_state = "minor backlog — within normal operating range"
    elif backlog < 120.0:
        backlog_state = "elevated backlog — execution engine falling behind"
    else:
        backlog_state = "critical backlog — cascading failures likely"

    persist_p99 = primary.persistence.latency_p99_ms
    if persist_p99 < 100:
        persist_state = "low persistence path latency"
    elif persist_p99 < 300:
        persist_state = "moderate persistence path latency"
    elif persist_p99 < 500:
        persist_state = "persistence path latency in the expected DSQL envelope"
    else:
        persist_state = "elevated persistence path latency"

    occ = amplifiers.persistence.occ_conflicts_per_sec
    errors = primary.persistence.error_rate_per_sec
    contention = "no contention" if occ < 1.0 and errors < 0.1 else "contention detected"

    shard = primary.history.shard_churn_rate_per_sec
    membership = "stable membership" if shard < 0.1 else "shard churn detected"

    return f"""## History (protagonist — state transitions, persistence, shards)
- Forward progress: {progress}
- Backlog: {backlog_state}
- Persistence path: {persist_state} ({contention})
- Cluster: {membership}"""


def _build_frontend_section(primary: PrimarySignals) -> str:
    """Frontend service — the gateway."""
    errors = primary.frontend.error_rate_per_sec
    error_state = "zero errors" if errors < 0.1 else "errors detected"

    filtered_p99 = primary.frontend.latency_p99_ms
    raw_p99 = primary.frontend.long_poll_latency_p99_ms

    if filtered_p99 < 100 and raw_p99 > 50000:
        latency_state = (
            "filtered latency is negligible but raw includes ~90s long-polls — "
            "all traffic is worker long-poll operations, no real API requests"
        )
    elif filtered_p99 < 500:
        latency_state = "low API latency (excluding long-polls)"
    elif filtered_p99 < 2000:
        latency_state = "moderate API latency"
    elif filtered_p99 < 10000:
        latency_state = (
            "elevated API latency — may include non-poll long-running operations "
            "(visibility queries, GetWorkflowExecutionHistory with wait)"
        )
    else:
        latency_state = (
            "high API latency — likely dominated by long-running operations "
            "that aren't filtered by the Poll*TaskQueue exclusion"
        )

    return f"""## Frontend (gateway — routes requests, handles long-polls)
- Client impact: {error_state}
- API latency: {latency_state}"""


def _build_matching_section(primary: PrimarySignals) -> str:
    """Matching service — the matchmaker."""
    wf_backlog = primary.matching.workflow_backlog_age_sec
    act_backlog = primary.matching.activity_backlog_age_sec

    if wf_backlog < 0.1 and act_backlog < 0.1:
        matching_state = "instant task dispatch — workers keeping up with demand"
    elif wf_backlog < 5.0 and act_backlog < 5.0:
        matching_state = "minor dispatch delay — within normal range"
    else:
        matching_state = "task dispatch delayed — workers may be falling behind"

    timeout = primary.poller.poll_timeout_rate
    throughput = primary.state_transitions.throughput_per_sec
    if throughput < 5.0:
        poller_state = "poller timeouts expected (low demand — workers waiting for tasks)"
    elif timeout < 0.1:
        poller_state = "healthy poller success rate"
    elif timeout < 0.3:
        poller_state = "moderate poller timeout rate (normal under bursty load)"
    elif timeout < 0.5:
        poller_state = "elevated poller timeout rate"
    else:
        poller_state = "high poller timeout rate — matching pressure or worker misconfiguration"

    return f"""## Matching (matchmaker — connects tasks to workers)
- Task dispatch: {matching_state}
- Poller health: {poller_state}"""


def _build_workers_section(
    primary: PrimarySignals,
    amplifiers: AmplifierSignals,
) -> str:
    """Worker actors — both internal and SDK."""
    # Internal worker (system ops)
    deletion = primary.system_operations.deletion_rate_per_sec
    cleanup = primary.system_operations.cleanup_delete_rate_per_sec
    if deletion < 0.5 and cleanup < 0.5:
        system_state = "minimal system operations"
    elif deletion < 5.0:
        system_state = "normal retention/archival activity"
    else:
        system_state = "active retention storm — significant deletion throughput"

    # SDK workers
    slots = amplifiers.worker.task_slots_available
    used = amplifiers.worker.task_slots_used
    if slots == 0 and used == 0:
        sdk_state = "no SDK worker metrics available"
    elif slots == 0:
        sdk_state = "worker slots exhausted — workers cannot accept more tasks"
    elif used == 0:
        sdk_state = "workers idle — slots available but no tasks being processed"
    else:
        sdk_state = "workers active — processing tasks with available capacity"

    return f"""## Workers
- Internal (housekeeper): {system_state}
- SDK workers: {sdk_state}"""


def _build_foundation_section(amplifiers: AmplifierSignals) -> str:
    """DSQL foundation — connection pool and reservoir."""
    util = amplifiers.connection_pool.utilization_pct
    if util < 20:
        pool_state = "pool well below saturation"
    elif util < 60:
        pool_state = "moderate pool utilization"
    elif util < 80:
        pool_state = "pool approaching saturation"
    else:
        pool_state = "pool near or at saturation — artificial throttling likely"

    wait = amplifiers.connection_pool.wait_duration_ms
    if wait < 1:
        wait_state = "no connection wait — reservoir providing instant checkout"
    else:
        wait_state = "connection wait detected — pool pressure"

    churn = amplifiers.connection_pool.churn_rate_per_sec
    if churn < 1.0:
        churn_state = "minimal connection churn"
    elif churn < 5.0:
        churn_state = "normal connection rotation (MaxConnLifetime expiry)"
    else:
        churn_state = "elevated connection churn — investigate token refresh or reservoir config"

    return f"""## DSQL Foundation (connection pool and reservoir)
- Pool: {pool_state}
- Checkout: {wait_state}
- Connection lifecycle: {churn_state}"""


def _build_cluster_stability_section(amplifiers: AmplifierSignals) -> str:
    """Cluster stability — runtime, host, deploy churn."""
    goroutines = amplifiers.runtime.goroutines
    if goroutines < 5000:
        runtime_state = "stable goroutine count"
    elif goroutines < 10000:
        runtime_state = "moderate goroutine count"
    else:
        runtime_state = "high goroutine count — potential leak or saturation"

    gc = amplifiers.host.gc_pause_ms
    gc_state = "negligible GC pressure" if gc < 50 else "GC pauses detected"

    membership = amplifiers.deploy.membership_changes_per_min
    deploy_state = "stable membership" if membership < 1.0 else "membership churn detected"

    return f"""## Cluster Stability
- Runtime: {runtime_state}
- GC: {gc_state}
- Membership: {deploy_state}"""


def _build_log_section(log_patterns: list[LogPattern]) -> str:
    """Narrative signals from logs."""
    if not log_patterns:
        return "## Log Patterns\nNone detected"
    lines = ["## Log Patterns"]
    for p in log_patterns[:10]:
        lines.append(f"- [{p.service}] {p.pattern}: {p.count} occurrences")
    return "\n".join(lines)


def _build_trend_section(signal_history: list[dict]) -> str:
    """Signal trends over recent window."""
    if not signal_history or len(signal_history) < 2:
        return "## Trends\nNo historical data available"
    return f"## Trends\nComparing {len(signal_history)} snapshots over recent window"


def _build_rag_section(rag_context: list[str]) -> str:
    """Knowledge base context."""
    if not rag_context:
        return "## Knowledge Base\nNo relevant documentation found"
    return "## Knowledge Base\n" + "\n\n".join(rag_context[:5])


def _build_closing(health_state: HealthState) -> str:
    """Closing instruction."""
    return (
        "---\n\n"
        "Tell the story of this cluster. Explain what each service is doing, "
        "how their relationships explain the current state, and what actions "
        "would improve the situation.\n\n"
        "REMEMBER:\n"
        "- Do NOT cite specific metric values — Grafana renders numbers\n"
        "- Your narrative must be consistent with the gate evaluation above\n"
        "- If a gate passed, do not flag that signal as a problem\n"
        f"- The health_state is {health_state.value.upper()} — DO NOT CHANGE IT"
    )
