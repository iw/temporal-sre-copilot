"""Gate evaluation context for the researcher agent.

The state machine evaluates gates deterministically. This module captures
WHICH gates fired and which passed, so the LLM knows exactly what triggered
the health state — it doesn't have to guess from raw numbers.

This is the bridge between "Rules Decide" and "AI Explains."
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .config import ScaleBand, ThresholdOverrides, get_threshold_profile
from .signals import HealthState, PrimarySignals  # noqa: TC001 — Pydantic + function sigs


class GateResult(BaseModel):
    """Result of evaluating a single signal gate."""

    signal: str = Field(description="Signal name (e.g., 'Signal 8: Frontend Latency')")
    fired: bool = Field(description="Whether this gate triggered")
    observed: str = Field(description="What was observed (qualitative, not raw number)")
    threshold: str = Field(description="What the threshold was (qualitative)")
    context: str = Field(
        default="",
        description="Why this matters or why it's expected",
    )


class GateEvaluation(BaseModel):
    """Complete gate evaluation context for the researcher.

    Captures the state machine's reasoning so the LLM doesn't have to
    reverse-engineer it from raw numbers.
    """

    scale_band: ScaleBand = Field(description="Active scale band")
    health_state: HealthState = Field(description="Determined health state")
    is_idle: bool = Field(default=False, description="Cluster detected as idle")
    is_system_busy: bool = Field(
        default=False, description="Cluster busy with system ops (retention/archival)"
    )
    stressed_gates: list[GateResult] = Field(
        default_factory=list,
        description="STRESSED gate evaluations (which fired, which passed)",
    )
    critical_gates: list[GateResult] = Field(
        default_factory=list,
        description="CRITICAL gate evaluations (only populated if relevant)",
    )
    triggering_signal: str | None = Field(
        default=None,
        description="The primary signal that triggered the state change, if any",
    )


def evaluate_gates(
    primary: PrimarySignals,
    health_state: HealthState,
    scale_band: ScaleBand,
    *,
    overrides: ThresholdOverrides | None = None,
) -> GateEvaluation:
    """Evaluate all gates and capture which fired and which passed.

    This runs the same logic as the state machine but captures the
    individual gate results for the LLM to explain.
    """
    profile = get_threshold_profile(scale_band, overrides=overrides)
    stressed = profile.stressed
    has_demand = primary.state_transitions.throughput_per_sec >= 5.0

    # Detect idle / system-busy
    is_idle = _check_idle(primary)
    is_system_busy = _check_system_busy(primary)

    if is_idle:
        return GateEvaluation(
            scale_band=scale_band,
            health_state=health_state,
            is_idle=True,
        )

    # Evaluate stressed gates
    gates: list[GateResult] = []
    triggering: str | None = None

    # Signal 2: State transition latency
    st_latency = primary.state_transitions.latency_p99_ms
    st_threshold = stressed.state_transition_latency_p99_max_ms
    s2_fired = st_latency > st_threshold
    gates.append(
        GateResult(
            signal="Signal 2: State Transition Latency",
            fired=s2_fired,
            observed=_classify_latency(st_latency, st_threshold),
            threshold=f"{scale_band.value} band threshold",
            context="Early warning of contention in the execution engine",
        )
    )
    if s2_fired and not triggering:
        triggering = "Signal 2: State Transition Latency"

    # Signal 4: History backlog age
    backlog = primary.history.backlog_age_sec
    backlog_threshold = stressed.history_backlog_age_stress_sec
    s4_fired = backlog > backlog_threshold
    gates.append(
        GateResult(
            signal="Signal 4: History Backlog Age",
            fired=s4_fired,
            observed=_classify_backlog(backlog, backlog_threshold),
            threshold=f"{scale_band.value} band threshold",
            context=(
                "Strongest predictor of cascading failures"
                " — is the execution engine falling behind?"
            ),
        )
    )
    if s4_fired and not triggering:
        triggering = "Signal 4: History Backlog Age"

    # Signal 8: Frontend latency (demand-gated)
    fe_latency = primary.frontend.latency_p99_ms
    fe_threshold = stressed.frontend_latency_p99_max_ms
    s8_fired = has_demand and fe_latency > fe_threshold
    s8_context = "Excludes long-poll operations. " + (
        "Demand-gated: active throughput means this reflects real API latency"
        if has_demand
        else "Demand gate not met — low throughput, metric may reflect non-poll long operations"
    )
    demand_suffix = " (demand-gated)" if not has_demand else ""
    gates.append(
        GateResult(
            signal="Signal 8: Frontend Latency",
            fired=s8_fired,
            observed=_classify_latency(fe_latency, fe_threshold),
            threshold=f"{scale_band.value} band threshold{demand_suffix}",
            context=s8_context,
        )
    )
    if s8_fired and not triggering:
        triggering = "Signal 8: Frontend Latency"

    # Signal 11: Persistence latency
    persist_latency = primary.persistence.latency_p99_ms
    persist_threshold = stressed.persistence_latency_p99_max_ms
    s11_fired = persist_latency > persist_threshold
    gates.append(
        GateResult(
            signal="Signal 11: Persistence Latency",
            fired=s11_fired,
            observed=_classify_latency(persist_latency, persist_threshold),
            threshold=f"{scale_band.value} band threshold",
            context=(
                "Measures the full History persistence path (serialization + pool checkout "
                "+ DSQL query + deserialization), not raw database latency"
            ),
        )
    )
    if s11_fired and not triggering:
        triggering = "Signal 11: Persistence Latency"

    # Signal 6: Shard churn
    s6_fired = primary.history.shard_churn_rate_per_sec > stressed.shard_churn_rate_max_per_sec
    gates.append(
        GateResult(
            signal="Signal 6: Shard Churn",
            fired=s6_fired,
            observed="elevated" if s6_fired else "stable",
            threshold=f"{scale_band.value} band threshold",
            context="Membership instability causes shard rebalancing and temporary progress stalls",
        )
    )
    if s6_fired and not triggering:
        triggering = "Signal 6: Shard Churn"

    # Signal 10: Poller timeout rate (demand-gated)
    timeout_rate = primary.poller.poll_timeout_rate
    s10_fired = has_demand and timeout_rate > stressed.poller_timeout_rate_max
    poller_suffix = " (demand-gated)" if not has_demand else ""
    gates.append(
        GateResult(
            signal="Signal 10: Poller Timeout Rate",
            fired=s10_fired,
            observed=_classify_poller(timeout_rate, has_demand),
            threshold=f"{scale_band.value} band threshold{poller_suffix}",
            context="On idle clusters, high timeout rate is normal (workers waiting for tasks)",
        )
    )
    if s10_fired and not triggering:
        triggering = "Signal 10: Poller Timeout Rate"

    return GateEvaluation(
        scale_band=scale_band,
        health_state=health_state,
        is_idle=False,
        is_system_busy=is_system_busy,
        stressed_gates=gates,
        triggering_signal=triggering,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _classify_latency(observed_ms: float, threshold_ms: float) -> str:
    """Classify a latency value relative to its threshold."""
    if observed_ms <= 0:
        return "negligible"
    ratio = observed_ms / threshold_ms if threshold_ms > 0 else 0
    if ratio < 0.5:
        return "well within threshold"
    if ratio < 0.9:
        return "approaching threshold"
    if ratio <= 1.0:
        return "near threshold"
    if ratio < 2.0:
        return "above threshold"
    return "significantly above threshold"


def _classify_backlog(observed_sec: float, threshold_sec: float) -> str:
    """Classify backlog age relative to its threshold."""
    if observed_sec < 1.0:
        return "negligible"
    ratio = observed_sec / threshold_sec if threshold_sec > 0 else 0
    if ratio < 0.5:
        return "well within threshold"
    if ratio < 0.9:
        return "approaching threshold"
    if ratio <= 1.0:
        return "near threshold"
    return "above threshold"


def _classify_poller(timeout_rate: float, has_demand: bool) -> str:
    """Classify poller timeout rate."""
    if not has_demand:
        return "not evaluated (low demand — timeouts expected)"
    if timeout_rate < 0.1:
        return "healthy"
    if timeout_rate < 0.3:
        return "moderate"
    if timeout_rate < 0.5:
        return "elevated"
    return "high"


def _check_idle(primary: PrimarySignals) -> bool:
    """Mirror the state machine's idle detection."""
    return (
        primary.state_transitions.throughput_per_sec < 5.0
        and primary.history.task_processing_rate_per_sec < 5.0
        and primary.frontend.error_rate_per_sec < 0.1
        and primary.persistence.error_rate_per_sec < 0.1
        and primary.workflow_completion.failed_per_sec < 0.1
        and primary.history.backlog_age_sec < 5.0
        and primary.matching.workflow_backlog_age_sec < 5.0
        and primary.matching.activity_backlog_age_sec < 5.0
        and primary.system_operations.deletion_rate_per_sec < 1.0
        and primary.system_operations.cleanup_delete_rate_per_sec < 0.5
    )


def _check_system_busy(primary: PrimarySignals) -> bool:
    """Mirror the state machine's system-busy detection."""
    return primary.state_transitions.throughput_per_sec < 5.0 and (
        primary.system_operations.deletion_rate_per_sec >= 5.0
        or primary.system_operations.cleanup_delete_rate_per_sec >= 1.0
    )
