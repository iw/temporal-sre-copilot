# Design Document: Narrative Coherence

## Overview

The Copilot's researcher agent receives 40+ signal values and produces health explanations. Today, qualitative classification of those signals happens inside string-building helper functions that produce prompt text — the structured understanding evaporates before it reaches either the LLM or Grafana. The LLM gets prose and must infer causality. Grafana gets a single summary string and cannot render per-service health.

This design introduces a deterministic narrative layer between raw signals and the LLM:

```
Raw Signals (40+ numbers)
        ↓ deterministic
ClusterNarrative (structured actor states + trends + context)
        ↓ prompt builder
Researcher Prompt (dramatic arc with pre-classified actors)
        ↓ LLM
NarrativeOutput (five-act structured explanation)
        ↓ API
Grafana (per-service panels + structured narrative)
```

Five components:

1. **ServiceHealth model** — Per-actor deterministic health classification
2. **Deployment context threading** — Setting act with replica counts and environment
3. **NarrativeOutput model** — Five-act structured output replacing unstructured summary
4. **Critical gate evaluation** — Structured gate context for CRITICAL transitions
5. **Signal trend computation** — Trajectory classification from the signal window

All computation is deterministic. The LLM's role is unchanged: it receives structured context and tells the story.

## Architecture

### Data Flow

```
ObserveClusterWorkflow (every 30s)
│
├── PrimarySignals + AmplifierSignals (from AMP)
├── GateEvaluation (from evaluate_gates)
├── DeploymentProfile (from startup)
├── DeploymentContext (from inspector, every 5min)
├── Signal Window (last 10 snapshots)
│
├──► compute_trend_summary(signal_window) → TrendSummary
├──► compute_cluster_narrative(
│        primary, amplifiers, gate_eval,
│        deployment_profile, deployment_context,
│        trend_summary
│    ) → ClusterNarrative
│
└──► AssessHealthInput(
         ...,
         cluster_narrative=narrative,
         deployment_profile=profile,
         deployment_context=context,
     )
         │
         ▼
     AssessHealthWorkflow
         │
         ├── build_researcher_prompt(cluster_narrative) → prompt
         ├── researcher_agent.run(prompt) → HealthAssessment with NarrativeOutput
         │
         └── /status/services → ServiceHealth[] from ClusterNarrative
             /status/summary → NarrativeOutput sections
```

### Package Placement

| Component | Package | Module | Rationale |
|-----------|---------|--------|-----------|
| `ServiceHealth` | `copilot.models` | `narrative.py` | Depends on gate evaluation, threshold profiles |
| `ClusterNarrative` | `copilot.models` | `narrative.py` | Orchestrator concern |
| `NarrativeOutput` | `copilot.models` | `assessment.py` | Part of HealthAssessment output |
| `SignalTrend`, `TrendSummary` | `copilot.models` | `narrative.py` | Depends on signal window |
| `compute_cluster_narrative()` | `copilot.models` | `narrative.py` | Pure function |
| `compute_trend_summary()` | `copilot.models` | `narrative.py` | Pure function |

No new packages. No new cross-package dependencies. Everything lives in `copilot.models`.

## Components and Interfaces

### Component 1: ServiceHealth Model

#### Models

```python
# copilot/models/narrative.py

class ForwardProgress(StrEnum):
    """Per-actor forward progress classification."""
    OK = "ok"              # Actor is making normal progress
    DEGRADED = "degraded"  # Progress continues but impaired
    BLOCKED = "blocked"    # Progress has stopped

class PressureLevel(StrEnum):
    """Per-actor resource pressure classification."""
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"

class ServiceHealth(BaseModel):
    """Deterministic health classification for a single actor."""
    service: str = Field(description="Actor name: history, matching, frontend, workers, dsql")
    forward_progress: ForwardProgress = Field(description="Is this actor making progress?")
    pressure: PressureLevel = Field(description="Resource pressure level")
    artifact_signals: list[str] = Field(
        default_factory=list,
        description="Signals that appear anomalous but are expected for current context",
    )
    dominant_signal: str | None = Field(
        default=None,
        description="The single most explanatory signal for this actor's state",
    )
    summary: str = Field(description="One-sentence qualitative description of actor state")
```

#### Classification Logic

The classification logic is extracted from the existing `_build_*_section` helpers in `researcher.py`. Each actor's classification is a pure function of signals + gate evaluation:

```python
def _classify_history(
    primary: PrimarySignals,
    amplifiers: AmplifierSignals,
    gate_eval: GateEvaluation | None,
) -> ServiceHealth:
    """Classify History — the Archivist."""
    throughput = primary.state_transitions.throughput_per_sec
    backlog = primary.history.backlog_age_sec
    persist_p99 = primary.persistence.latency_p99_ms
    occ = amplifiers.persistence.occ_conflicts_per_sec
    errors = primary.persistence.error_rate_per_sec

    # Forward progress
    if throughput < 1.0 and primary.history.task_processing_rate_per_sec < 1.0:
        progress = ForwardProgress.OK  # Idle is OK, not blocked
        summary_prefix = "idle — minimal state transitions"
    elif backlog > 120.0:
        progress = ForwardProgress.BLOCKED
        summary_prefix = "execution engine falling behind with critical backlog"
    elif backlog > 30.0 or errors > 1.0:
        progress = ForwardProgress.DEGRADED
        summary_prefix = "forward progress impaired"
    else:
        progress = ForwardProgress.OK
        summary_prefix = "actively processing state transitions"

    # Pressure
    if persist_p99 > 500 or occ > 5.0:
        pressure = PressureLevel.HIGH
    elif persist_p99 > 300 or occ > 1.0:
        pressure = PressureLevel.MODERATE
    else:
        pressure = PressureLevel.LOW

    # Artifacts
    artifacts = []
    if gate_eval and gate_eval.scale_band.value == "starter" and 300 <= persist_p99 <= 500:
        artifacts.append("persistence_latency_p99 (expected DSQL envelope at starter scale)")

    # Dominant signal
    dominant = None
    if backlog > 30.0:
        dominant = "history_backlog_age"
    elif persist_p99 > 500:
        dominant = "persistence_latency_p99"
    elif occ > 1.0:
        dominant = "occ_conflicts"

    contention = "no contention" if occ < 1.0 and errors < 0.1 else "contention detected"
    membership = "stable" if primary.history.shard_churn_rate_per_sec < 0.1 else "shard churn"

    return ServiceHealth(
        service="history",
        forward_progress=progress,
        pressure=pressure,
        artifact_signals=artifacts,
        dominant_signal=dominant,
        summary=f"{summary_prefix}, {_classify_persist_qualitative(persist_p99)} ({contention}), {membership} membership",
    )
```

Similar `_classify_matching`, `_classify_frontend`, `_classify_workers`, `_classify_dsql` functions follow the same pattern, extracting the logic currently in `_build_matching_section`, `_build_frontend_section`, etc.

#### ClusterNarrative

```python
class NarrativeSetting(BaseModel):
    """The 'Setting' act — where are we?"""
    scale_band: str
    preset_name: str | None = None
    platform_type: str | None = None
    environment_summary: str = Field(
        description="One-sentence description: 'Starter-scale Compose dev cluster with 1 History replica'",
    )
    history_replicas: int | None = None
    matching_replicas: int | None = None
    frontend_replicas: int | None = None
    worker_replicas: int | None = None

class ClusterNarrative(BaseModel):
    """Complete deterministic narrative context for the researcher.

    This is the structured layer between raw signals and the LLM.
    Everything here is computed by rules. The LLM consumes it and
    tells the story.
    """
    setting: NarrativeSetting
    gate_evaluation: GateEvaluation
    actors: list[ServiceHealth] = Field(description="Per-actor health classifications")
    trends: TrendSummary | None = Field(default=None, description="Signal trajectory over recent window")
    forward_progress_intact: bool = Field(
        description="Overall: is the cluster making forward progress?",
    )
    unaffected_actors: list[str] = Field(
        default_factory=list,
        description="Actors that are healthy and uninvolved in the current state",
    )
```

#### compute_cluster_narrative()

```python
def compute_cluster_narrative(
    primary: PrimarySignals,
    amplifiers: AmplifierSignals,
    gate_eval: GateEvaluation,
    *,
    deployment_profile: DeploymentProfile | None = None,
    deployment_context: DeploymentContext | None = None,
    trend_summary: TrendSummary | None = None,
) -> ClusterNarrative:
    """Compute the complete narrative context deterministically.

    This is a pure function. No I/O, no LLM, no async.
    """
    # Classify each actor
    actors = [
        _classify_history(primary, amplifiers, gate_eval),
        _classify_matching(primary, gate_eval),
        _classify_frontend(primary, gate_eval),
        _classify_workers(primary, amplifiers),
        _classify_dsql(amplifiers),
    ]

    # Build setting
    setting = _build_setting(gate_eval, deployment_profile, deployment_context)

    # Determine overall forward progress
    history_health = actors[0]  # History is the protagonist
    forward_progress_intact = history_health.forward_progress != ForwardProgress.BLOCKED

    # Identify unaffected actors
    unaffected = [
        a.service for a in actors
        if a.forward_progress == ForwardProgress.OK and a.pressure == PressureLevel.LOW
    ]

    return ClusterNarrative(
        setting=setting,
        gate_evaluation=gate_eval,
        actors=actors,
        trends=trend_summary,
        forward_progress_intact=forward_progress_intact,
        unaffected_actors=unaffected,
    )
```

### Component 2: Deployment Context in the Narrative

The `ObserveClusterWorkflow` already has `deployment_profile` and `deployment_context`. The change is threading them into `AssessHealthInput` and building the `NarrativeSetting`.

```python
def _build_setting(
    gate_eval: GateEvaluation,
    profile: DeploymentProfile | None,
    context: DeploymentContext | None,
) -> NarrativeSetting:
    """Build the Setting act from available deployment information."""
    band = gate_eval.scale_band.value

    if profile is None and context is None:
        return NarrativeSetting(
            scale_band=band,
            environment_summary=f"{band}-scale cluster (deployment details unavailable)",
        )

    preset = profile.preset_name if profile else None
    platform = profile.resource_identity.platform_type if profile and profile.resource_identity else None

    # Prefer runtime context for replica counts (actual), fall back to profile (intended)
    if context:
        h_replicas = context.history.running
        m_replicas = context.matching.running
        f_replicas = context.frontend.running
        w_replicas = context.worker.running
    elif profile and profile.scaling_topology:
        h_replicas = profile.scaling_topology.history.min_replicas
        m_replicas = profile.scaling_topology.matching.min_replicas
        f_replicas = profile.scaling_topology.frontend.min_replicas
        w_replicas = profile.scaling_topology.worker.min_replicas
    else:
        h_replicas = m_replicas = f_replicas = w_replicas = None

    # Build human-readable summary
    parts = [f"{band}-scale"]
    if platform:
        parts.append(platform.capitalize())
    if preset:
        parts.append(f"({preset} preset)")
    parts.append("cluster")
    if h_replicas is not None:
        parts.append(f"with {h_replicas} History replica{'s' if h_replicas != 1 else ''}")

    return NarrativeSetting(
        scale_band=band,
        preset_name=preset,
        platform_type=platform,
        environment_summary=" ".join(parts),
        history_replicas=h_replicas,
        matching_replicas=m_replicas,
        frontend_replicas=f_replicas,
        worker_replicas=w_replicas,
    )
```

#### AssessHealthInput Changes

```python
# copilot/models/workflow_inputs.py

class AssessHealthInput(BaseModel):
    # ... existing fields unchanged ...
    cluster_narrative: ClusterNarrative | None = Field(
        default=None,
        description="Pre-computed narrative context (actors, setting, trends, gates)",
    )
    deployment_profile: DeploymentProfile | None = Field(
        default=None,
        description="Deployment profile for setting context",
    )
    deployment_context: DeploymentContext | None = Field(
        default=None,
        description="Runtime deployment context for setting context",
    )
```

### Component 3: NarrativeOutput Model

```python
# copilot/models/assessment.py

class NarrativeOutput(BaseModel):
    """Five-act dramatic arc for health explanation.

    Each section corresponds to one act of the narrative structure.
    The LLM populates these sections; the structure ensures consistency.
    """
    setting: str = Field(
        description="Act 1: Where are we? Scale band, replicas, environment. Establish baseline.",
    )
    inciting_signal: str = Field(
        description="Act 2: Which gate fired? The specific trigger for this phase transition.",
    )
    character_reactions: str = Field(
        description="Act 3: Service-by-service behaviour. Builds causal isolation.",
    )
    tension_analysis: str = Field(
        description="Act 4: Why did the trigger fire? Explain causality, not symptoms.",
    )
    resolution: str = Field(
        description="Act 5: What does it mean? Forward progress intact? Artifact or real problem?",
    )
    watch_next: list[str] = Field(
        default_factory=list,
        description="What to monitor going forward (top 3 items).",
    )
```

#### HealthAssessment Changes

```python
class HealthAssessment(BaseModel):
    # ... all existing fields unchanged ...
    narrative: NarrativeOutput | None = Field(
        default=None,
        description="Structured five-act narrative (None for legacy assessments)",
    )
```

The `natural_language_summary` field remains. When `narrative` is present, it is populated by concatenating the five sections:

```python
# In assess.py, after researcher returns:
if assessment.narrative:
    assessment.natural_language_summary = "\n\n".join([
        assessment.narrative.setting,
        assessment.narrative.inciting_signal,
        assessment.narrative.character_reactions,
        assessment.narrative.tension_analysis,
        assessment.narrative.resolution,
    ])
```

#### Researcher Output Type

The researcher agent's output type changes from `HealthAssessment` to include the narrative:

```python
researcher_agent = Agent(
    "bedrock:eu.anthropic.claude-opus-4-6-v1",
    instructions=RESEARCHER_INSTRUCTIONS,
    output_type=HealthAssessment,  # unchanged — HealthAssessment now includes narrative
    name="health_researcher",
)
```

The system instructions are updated to describe the five-act structure:

```python
RESEARCHER_INSTRUCTIONS = """...

## Output Structure

Your response MUST populate the `narrative` field with all five acts:

1. **setting**: Describe the cluster's identity. Use the Setting from the prompt.
   Example: "A starter-scale Compose dev cluster with a single History replica,
   operating in the STARTER band."

2. **inciting_signal**: Name the gate that fired and what it means.
   Example: "Frontend filtered latency exceeded the STARTER threshold.
   This was the sole trigger — no other gates fired."

3. **character_reactions**: Describe each actor's behaviour. Name the unaffected.
   Example: "History continued steady forward progress with no backlog.
   Matching maintained instant task dispatch. Workers were not saturated.
   DSQL foundation showed no connection pressure."

4. **tension_analysis**: Explain WHY the trigger fired. Causality, not symptoms.
   Example: "The elevated frontend latency is likely driven by long-running
   visibility queries or GetWorkflowExecutionHistory calls that bypass the
   Poll*TaskQueue filter. This is a measurement artifact, not a forward
   progress problem."

5. **resolution**: What does it mean? Is forward progress intact?
   Example: "Forward progress remained intact throughout. All workflows
   completed successfully. The STRESSED state reflects a latency artifact
   rather than genuine cluster pressure."

Also populate `watch_next` with 2-3 forward-looking items.
..."""
```

#### Minimal NarrativeOutput for Non-Deep Assessments

When the dispatcher routes to `NoExplanationNeeded` or `QuickExplanation`, a minimal narrative is generated deterministically:

```python
def _create_minimal_narrative(
    cluster_narrative: ClusterNarrative | None,
    health_state: HealthState,
) -> NarrativeOutput:
    """Create a minimal narrative without LLM involvement."""
    if cluster_narrative:
        setting = cluster_narrative.setting.environment_summary
        unaffected = ", ".join(cluster_narrative.unaffected_actors) or "all actors"
    else:
        setting = f"Cluster in {health_state.value} state"
        unaffected = "unknown"

    return NarrativeOutput(
        setting=setting,
        inciting_signal="No significant gate activity.",
        character_reactions=f"All monitored actors operating normally. Unaffected: {unaffected}.",
        tension_analysis="No tension detected. All signals within expected ranges.",
        resolution=f"Cluster is {health_state.value}. Forward progress intact.",
        watch_next=[],
    )
```

### Component 4: Critical Gate Evaluation

Extend `evaluate_gates()` to populate `critical_gates`:

```python
# copilot/models/gate_evaluation.py — inside evaluate_gates()

    # After stressed gates evaluation...

    # Evaluate critical gates (only when relevant)
    critical_gates: list[GateResult] = []
    critical = profile.critical

    if health_state == HealthState.CRITICAL or _any_critical_gate_fires(primary, critical, has_demand):
        # Signal 1: State transition collapse
        s1_threshold = critical.state_transitions_min_per_sec
        s1_fired = has_demand and primary.state_transitions.throughput_per_sec < s1_threshold
        critical_gates.append(GateResult(
            signal="Signal 1: State Transition Throughput",
            fired=s1_fired,
            observed="collapsed" if s1_fired else "above critical floor",
            threshold=f"{scale_band.value} band critical floor",
            context="Forward progress has stopped if this fires with active demand",
        ))

        # Signal 3: Completion rate collapse
        s3_fired = (
            has_demand
            and primary.workflow_completion.completion_rate < critical.workflow_completion_rate_min
        )
        critical_gates.append(GateResult(
            signal="Signal 3: Workflow Completion Rate",
            fired=s3_fired,
            observed="collapsed" if s3_fired else "above critical floor",
            threshold=f"{scale_band.value} band critical floor",
            context="Workflows are not completing — user-visible impact",
        ))

        # Signal 4: Critical backlog age
        s4c_fired = primary.history.backlog_age_sec > critical.history_backlog_age_max_sec
        critical_gates.append(GateResult(
            signal="Signal 4: Critical Backlog Age",
            fired=s4c_fired,
            observed="critical" if s4c_fired else "below critical threshold",
            threshold=f"{scale_band.value} band critical ceiling",
            context="Execution engine has fallen critically behind — cascading failures imminent",
        ))

        # Signal 5: Persistence error storm
        s5_fired = primary.persistence.error_rate_per_sec > critical.persistence_error_rate_max_per_sec
        critical_gates.append(GateResult(
            signal="Signal 5: Persistence Error Rate",
            fired=s5_fired,
            observed="error storm" if s5_fired else "within tolerance",
            threshold=f"{scale_band.value} band critical ceiling",
            context="Persistence layer is failing, not just slow",
        ))

    return GateEvaluation(
        ...,
        critical_gates=critical_gates,
    )
```

### Component 5: Signal Trend Computation

```python
# copilot/models/narrative.py

class SignalTrend(StrEnum):
    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"

class TrendSummary(BaseModel):
    """Signal trajectory over the recent observation window."""
    throughput: SignalTrend = SignalTrend.STABLE
    persistence_latency: SignalTrend = SignalTrend.STABLE
    backlog_age: SignalTrend = SignalTrend.STABLE
    frontend_latency: SignalTrend = SignalTrend.STABLE
    error_rate: SignalTrend = SignalTrend.STABLE

_TREND_THRESHOLD = 0.10  # 10% change required to classify as improving/worsening

def compute_trend_summary(signal_window: list[Signals]) -> TrendSummary:
    """Compute signal trends from the observation window.

    Splits the window into first-half and second-half, compares averages.
    A 10% change threshold prevents noise from triggering trend changes.

    For latency/errors/backlog: lower second-half = IMPROVING
    For throughput: higher second-half = IMPROVING
    """
    if len(signal_window) < 4:
        return TrendSummary()  # All STABLE — insufficient data

    mid = len(signal_window) // 2
    first_half = signal_window[:mid]
    second_half = signal_window[mid:]

    return TrendSummary(
        throughput=_classify_trend_higher_is_better(
            _avg(s.primary.state_transitions.throughput_per_sec for s in first_half),
            _avg(s.primary.state_transitions.throughput_per_sec for s in second_half),
        ),
        persistence_latency=_classify_trend_lower_is_better(
            _avg(s.primary.persistence.latency_p99_ms for s in first_half),
            _avg(s.primary.persistence.latency_p99_ms for s in second_half),
        ),
        backlog_age=_classify_trend_lower_is_better(
            _avg(s.primary.history.backlog_age_sec for s in first_half),
            _avg(s.primary.history.backlog_age_sec for s in second_half),
        ),
        frontend_latency=_classify_trend_lower_is_better(
            _avg(s.primary.frontend.latency_p99_ms for s in first_half),
            _avg(s.primary.frontend.latency_p99_ms for s in second_half),
        ),
        error_rate=_classify_trend_lower_is_better(
            _avg(s.primary.persistence.error_rate_per_sec for s in first_half),
            _avg(s.primary.persistence.error_rate_per_sec for s in second_half),
        ),
    )


def _classify_trend_lower_is_better(first_avg: float, second_avg: float) -> SignalTrend:
    """For metrics where lower is better (latency, errors, backlog)."""
    if first_avg == 0:
        return SignalTrend.STABLE if second_avg == 0 else SignalTrend.WORSENING
    change = (second_avg - first_avg) / first_avg
    if change < -_TREND_THRESHOLD:
        return SignalTrend.IMPROVING
    if change > _TREND_THRESHOLD:
        return SignalTrend.WORSENING
    return SignalTrend.STABLE


def _classify_trend_higher_is_better(first_avg: float, second_avg: float) -> SignalTrend:
    """For metrics where higher is better (throughput)."""
    if first_avg == 0:
        return SignalTrend.STABLE if second_avg == 0 else SignalTrend.IMPROVING
    change = (second_avg - first_avg) / first_avg
    if change > _TREND_THRESHOLD:
        return SignalTrend.IMPROVING
    if change < -_TREND_THRESHOLD:
        return SignalTrend.WORSENING
    return SignalTrend.STABLE


def _avg(values) -> float:
    """Average of an iterable of floats."""
    items = list(values)
    return sum(items) / len(items) if items else 0.0
```

### Updated Researcher Prompt Builder

The prompt builder is simplified — it consumes `ClusterNarrative` instead of raw signals:

```python
def build_researcher_prompt(
    health_state: HealthState,
    cluster_narrative: ClusterNarrative,
    log_patterns: list[LogPattern],
    rag_context: list[str],
    trigger: str,
) -> str:
    """Build the researcher prompt from pre-computed narrative context."""
    sections = [
        _build_setting_section(cluster_narrative.setting),
        _build_verdict_section(health_state, trigger, cluster_narrative.gate_evaluation),
        _build_actors_section(cluster_narrative.actors, cluster_narrative.unaffected_actors),
        _build_trend_section(cluster_narrative.trends),
        _build_log_section(log_patterns),
        _build_rag_section(rag_context),
        _build_closing(health_state, cluster_narrative.forward_progress_intact),
    ]
    return "\n\n".join(sections)
```

The `_build_actors_section` iterates over `ServiceHealth` objects and renders their pre-classified states, rather than re-classifying from raw signals.

### API Changes

#### /status/services

```python
# copilot/api.py

@app.get("/status/services")
async def get_services() -> ServicesResponse:
    """Per-service health from the most recent ClusterNarrative."""
    narrative = await _get_latest_cluster_narrative()
    if narrative is None:
        return ServicesResponse(services=[])
    return ServicesResponse(
        services=[
            ServiceStatus(
                name=actor.service,
                status=actor.forward_progress.value,
                key_signals={
                    "pressure": actor.pressure.value,
                    "dominant_signal": actor.dominant_signal or "none",
                    "artifacts": actor.artifact_signals,
                    "summary": actor.summary,
                },
            )
            for actor in narrative.actors
        ]
    )
```

#### /status/summary

```python
@app.get("/status/summary")
async def get_summary() -> SummaryResponse:
    """Structured narrative from the most recent assessment."""
    assessment = await _get_latest_assessment()
    return SummaryResponse(
        summary=assessment.natural_language_summary,
        timestamp=assessment.timestamp,
        health_state=assessment.health_state,
        narrative=assessment.narrative,  # New: structured five-act output
    )
```

The `SummaryResponse` model gains an optional `narrative: NarrativeOutput | None` field.

## Migration Strategy

All changes are additive and backward compatible:

1. New fields on existing models default to None
2. Existing API responses retain all current fields
3. The `natural_language_summary` field continues to be populated
4. Existing tests pass without modification
5. The researcher agent continues to work with the old prompt format until the new prompt builder is wired in

The rollout order:

1. Add models (`ServiceHealth`, `ClusterNarrative`, `NarrativeOutput`, `TrendSummary`)
2. Add `compute_cluster_narrative()` and `compute_trend_summary()` pure functions
3. Add critical gate evaluation to `evaluate_gates()`
4. Wire `ClusterNarrative` computation into `ObserveClusterWorkflow`
5. Thread through `AssessHealthInput` to `AssessHealthWorkflow`
6. Update researcher prompt builder to consume `ClusterNarrative`
7. Update researcher system instructions with five-act structure
8. Update API endpoints to serve structured data
9. Update `assess.py` to populate `narrative` and backfill `natural_language_summary`

## Testing Strategy

### Property-Based Tests

- `ClusterNarrative` is deterministic: same inputs → same output
- `TrendSummary` is deterministic: same signal window → same trends
- `ServiceHealth` classification is consistent with gate evaluation (if a gate passed, the corresponding actor should not be BLOCKED)
- `NarrativeOutput` round-trip serialization
- Backward compatibility: `HealthAssessment` without `narrative` field deserializes correctly

### Unit Tests

- Each `_classify_*` function tested with representative signal combinations
- `compute_trend_summary` with: empty window, 1 snapshot, 4 snapshots (minimum), 10 snapshots, improving/stable/worsening scenarios
- Critical gate evaluation: all four critical gates tested individually
- `_build_setting` with: no profile, profile only, profile + context
- Minimal narrative generation for non-deep assessments

### Integration Tests

- Full flow: signals → ClusterNarrative → prompt → (mock) researcher → HealthAssessment with NarrativeOutput
- API endpoints return structured ServiceHealth and NarrativeOutput
