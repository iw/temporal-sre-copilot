# Requirements Document

## Introduction

### Vision

Copilot is not an alerting system. It is a chronicler of a distributed organism.

Dashboards fail because they show facts without causality. A wall of numbers — latency, throughput, error rates — tells you *what* but never *why*. A junior SRE staring at 40 metrics cannot distinguish symptoms from causes, artifacts from failures, or innocent bystanders from culprits.

Copilot must tell:
- **What happened** — which phase transition occurred
- **Why it happened** — which actor's behaviour explains the trigger
- **Who was involved** — which services contributed, which were unaffected
- **What changed** — how signals evolved over the recent window
- **What it means** — whether forward progress was impaired or this was an artifact

That is story structure. And it requires treating Temporal as a dramatic ensemble.

### The Cast

Each service is an actor with a role, motivations, dependencies, failure modes, and signals of distress:

- 🧠 **History — The Archivist**: Owns truth. Commits state transitions. Talks to DSQL. Feels pressure from write amplification. Signals stress via persistence path latency and backlog age. History does not fail loudly. It slows.
- 🧵 **Matching — The Dispatcher**: Connects supply (tasks) to demand (pollers). Lives on partitions. Can become imbalanced. Signals distress via backlog age and async dispatch latency. Matching is rhythmic. It stutters when stressed.
- 🌉 **Frontend — The Gatekeeper**: Speaks to clients. Reflects cluster pain outward. Latency is contagious here. Frontend doesn't create problems. It reveals them.
- 🛠 **Workers — The Laborers**: Execute tasks. Can starve or saturate. Signal health via schedule-to-start and poll success. Workers show imbalance first. They feel matching's mistakes.
- 🗄 **DSQL — The Substrate**: Stateless compute for state. Responds to commits. Signals stress via transaction latency and connection churn. DSQL is rarely dramatic. It just responds.

### Narrative Structure

Every health explanation should follow a dramatic arc:

1. **Setting** (Scale & Context) — Where are we? Scale band, replica count, environment type, shard stability. Establish baseline.
2. **Inciting Signal** (The Trigger) — Which gate fired? This is the inciting incident. Not a list of metrics — the specific signal that caused the phase transition.
3. **Character Reactions** (Service-by-Service) — How did each actor behave? History continued steady progress. Matching maintained zero backlog. Workers were not saturated. This builds causal isolation.
4. **Tension Analysis** (Why) — Why did the trigger fire? Visibility long-running calls? Long-poll variants not filtered? Not forward-progress degradation? Explain causality.
5. **Resolution & Meaning** — Forward progress remained intact. Completion rate 100%. No cascading signals. System remained functionally healthy despite latency artifact. That's clarity.

### The Deep Insight

Copilot should not think in "metrics." It should think in actors, interactions, signals, and phase transitions. The deterministic layer already identifies phase changes (STARTER → STRESSED). The LLM's job is to narrate the phase shift.

### Current State Assessment

The researcher prompt redesign (services-as-actors, gate evaluation, qualitative classification) established the foundation. But five gaps remain between the current implementation and the vision:

1. **No `ServiceHealth` model** — Qualitative classification happens inside string-building helpers and evaporates into prompt text. It's not a first-class Pydantic model. The LLM gets prose, not structured actor states. Grafana never sees per-service health.
2. **No deployment context in the narrative** — The "Setting" act needs replica counts, environment type, preset name. The deployment profile doesn't reach the researcher prompt.
3. **No dramatic arc in the output** — `HealthAssessment.natural_language_summary` is a single unstructured string. The five-act arc is not enforced.
4. **Critical gates not evaluated** — `GateEvaluation.critical_gates` is always empty. CRITICAL transitions lack structured gate context.
5. **Trend section is a stub** — `_build_trend_section` says "Comparing N snapshots" but doesn't classify whether signals are improving, worsening, or stable.

### Litmus Test

A Copilot output succeeds when:
- A junior SRE can read it and understand what happened
- It clearly separates symptoms, causes, artifacts, and unaffected subsystems
- It avoids blaming innocent services
- It follows the dramatic arc: setting → trigger → reactions → tension → resolution

### The Vision

Imagine running a HIGH_THROUGHPUT test at 10k st/s and Copilot says:

> "Matching began to fall behind as async dispatch latency stretched beyond threshold. Workers remained underutilized, suggesting partition imbalance rather than capacity exhaustion. History continued committing steadily, but queue depth grew in partition 3, indicating localized pressure."

That's story. Not stats.

## Glossary

- **Service_Health**: A deterministic, per-actor health classification computed before the LLM runs. Contains forward progress state, pressure level, artifact signals, and dominant signal. Computed by rules, not by the LLM.
- **Dramatic_Arc**: The five-act narrative structure for health explanations: Setting, Inciting Signal, Character Reactions, Tension Analysis, Resolution & Meaning.
- **Actor**: A Temporal service (History, Matching, Frontend, Worker) or infrastructure component (DSQL) treated as a character in the cluster narrative with role, motivations, and failure modes.
- **Forward_Progress_State**: Per-service classification of whether the actor is making forward progress: OK, DEGRADED, or BLOCKED.
- **Pressure_Level**: Per-service classification of resource pressure: LOW, MODERATE, or HIGH.
- **Artifact_Signal**: A signal that appears anomalous but is expected behaviour for the current context (e.g., high poller timeout rate on an idle cluster, elevated frontend latency from long-running visibility queries).
- **Dominant_Signal**: The single most important signal for a given actor in the current evaluation — the one that best explains the actor's behaviour.
- **Signal_Trend**: Classification of how a signal has changed over the recent window: IMPROVING, STABLE, or WORSENING.
- **Causal_Isolation**: The narrative technique of describing each actor's behaviour independently so that the reader can identify which actor is the source of a problem and which are unaffected bystanders.
- **Phase_Transition**: A health state change (HAPPY → STRESSED, STRESSED → CRITICAL, etc.) as determined by the deterministic state machine.
- **Gate_Evaluation**: The existing module that captures which state machine gates fired and which passed, providing the bridge between "Rules Decide" and "AI Explains."
- **Narrative_Section**: A structured section of the health assessment output corresponding to one act of the Dramatic_Arc.

## Requirements

### Requirement 1: ServiceHealth Model

**User Story:** As an SRE, I want each Temporal service to have a deterministic health classification computed before the LLM runs, so that both the researcher prompt and the Grafana API receive structured per-actor state rather than unstructured prose.

#### Acceptance Criteria

1. THE system SHALL define a `ServiceHealth` Pydantic model with the following fields: `service` (actor name), `forward_progress` (OK | DEGRADED | BLOCKED), `pressure` (LOW | MODERATE | HIGH), `artifact_signals` (list of signal names that are expected behaviour for the current context), `dominant_signal` (the single most explanatory signal, or None).
2. THE system SHALL define a `ClusterNarrative` Pydantic model that contains a `ServiceHealth` for each actor (history, matching, frontend, workers, dsql) plus the `GateEvaluation` and deployment context summary.
3. THE system SHALL compute `ClusterNarrative` deterministically from `PrimarySignals`, `AmplifierSignals`, and `GateEvaluation` using the same qualitative classification logic currently embedded in the researcher prompt builder helpers (`_build_history_section`, etc.), extracted into a reusable function.
4. THE `ClusterNarrative` SHALL be computed in `ObserveClusterWorkflow` (or a shared function called from there) and passed to `AssessHealthInput`, so that both the researcher prompt and the API can consume it.
5. THE `/status/services` API endpoint SHALL return `ServiceHealth` objects for each actor, populated from the most recent `ClusterNarrative`. Grafana SHALL be able to render per-service health panels from this endpoint without any computation.
6. THE researcher prompt builder SHALL consume `ClusterNarrative` instead of raw signals, presenting pre-classified actor states to the LLM.
7. THE `ServiceHealth` model SHALL live in `copilot.models` (not `copilot_core`) since it is an orchestrator concern that depends on gate evaluation and threshold profiles.

### Requirement 2: Deployment Context in the Narrative

**User Story:** As an SRE, I want the health narrative to include the cluster's deployment context (scale band, replica counts, environment type, preset name), so that the "Setting" act of the dramatic arc establishes baseline expectations.

#### Acceptance Criteria

1. WHEN a `DeploymentProfile` is available, THE `ClusterNarrative` SHALL include a `setting` section containing: scale band name, preset name, platform type (ECS/Compose), and per-service replica counts.
2. WHEN a `DeploymentContext` is available, THE `ClusterNarrative.setting` SHALL additionally include: actual vs desired replica counts per service, autoscaler state (fixed/scaling), and DSQL connection utilization.
3. THE researcher prompt builder SHALL render the setting section as the first act of the narrative, establishing the cluster's identity and baseline before describing what happened.
4. WHEN neither `DeploymentProfile` nor `DeploymentContext` is available, THE setting section SHALL contain only the scale band (derived from throughput) and note that deployment details are unavailable.
5. THE `AssessHealthInput` workflow input SHALL include `deployment_profile: DeploymentProfile | None` and `deployment_context: DeploymentContext | None` fields, threaded from `ObserveClusterWorkflow`.

### Requirement 3: Structured Narrative Output

**User Story:** As an SRE reading Copilot output in Grafana, I want the health assessment to follow the five-act dramatic arc, so that I can quickly find the setting, trigger, per-service reactions, causal analysis, and resolution.

#### Acceptance Criteria

1. THE `HealthAssessment` model SHALL include a `narrative` field containing a `NarrativeOutput` Pydantic model with five sections: `setting` (str), `inciting_signal` (str), `character_reactions` (str), `tension_analysis` (str), `resolution` (str).
2. THE `NarrativeOutput` model SHALL also include a `watch_next` field (list of str) describing what to monitor going forward.
3. THE researcher agent's output type SHALL be updated to produce `NarrativeOutput` as part of `HealthAssessment`, replacing the unstructured `natural_language_summary` as the primary narrative vehicle.
4. THE `natural_language_summary` field SHALL remain on `HealthAssessment` for backward compatibility, populated by concatenating the five narrative sections.
5. THE `/status/summary` API endpoint SHALL return the full `NarrativeOutput` structure so that Grafana can render each section in a separate panel or as a structured text block.
6. THE researcher system instructions SHALL explicitly describe the five-act structure and instruct the LLM to populate each section with the appropriate content, using the `ClusterNarrative` as input.
7. WHEN the dispatcher routes to `NoExplanationNeeded` or `QuickExplanation`, THE system SHALL generate a minimal `NarrativeOutput` deterministically (no LLM) with appropriate defaults for each section.

### Requirement 4: Critical Gate Evaluation

**User Story:** As an SRE, I want the gate evaluation to include critical gates when the cluster transitions to CRITICAL, so that the researcher has the same structured context for critical transitions as it does for stressed transitions.

#### Acceptance Criteria

1. THE `evaluate_gates()` function SHALL evaluate critical gates (Signals 1, 3, 4, 5 — state transition collapse, completion rate collapse, critical backlog age, persistence error storm) and populate `GateEvaluation.critical_gates` when the health state is CRITICAL or when any critical gate fires.
2. EACH critical gate result SHALL include the same fields as stressed gates: signal name, fired/passed, qualitative observation, threshold context, and explanatory context.
3. THE researcher prompt builder SHALL include critical gate results in the verdict section when present, clearly distinguishing them from stressed gates.
4. THE critical gate evaluation SHALL use the same `ThresholdProfile` (scale-band-aware) as the stressed gate evaluation, ensuring consistency.
5. THE `evaluate_gates()` function SHALL remain deterministic with no LLM involvement.

### Requirement 5: Signal Trend Computation

**User Story:** As an SRE, I want the health narrative to describe whether key signals are improving, stable, or worsening over the recent observation window, so that I understand the trajectory of the cluster's health, not just its current snapshot.

#### Acceptance Criteria

1. THE system SHALL define a `SignalTrend` enum with values: IMPROVING, STABLE, WORSENING.
2. THE system SHALL define a `TrendSummary` Pydantic model containing trends for key signals: `throughput` (SignalTrend), `persistence_latency` (SignalTrend), `backlog_age` (SignalTrend), `frontend_latency` (SignalTrend), `error_rate` (SignalTrend).
3. THE system SHALL compute `TrendSummary` from the signal window (last 10 snapshots / 5 minutes) maintained by `ObserveClusterWorkflow`, using a simple comparison of the first-half average vs second-half average of the window.
4. WHEN the signal window contains fewer than 4 snapshots, THE system SHALL return a `TrendSummary` with all trends set to STABLE (insufficient data).
5. THE `ClusterNarrative` SHALL include the `TrendSummary`.
6. THE researcher prompt builder SHALL render trends in a dedicated section, describing the trajectory of key signals in qualitative terms (e.g., "persistence latency is improving" or "backlog age is worsening").
7. THE trend computation SHALL be deterministic: the same signal window produces the same `TrendSummary`.
8. A signal SHALL be classified as IMPROVING when the second-half average is at least 10% lower than the first-half average (for latency/errors/backlog) or 10% higher (for throughput). WORSENING is the inverse. STABLE is within the 10% band.

### Cross-Cutting Requirements

### Requirement 6: Backward Compatibility

**User Story:** As a developer, I want the narrative coherence changes to be backward compatible with existing API consumers and stored assessments, so that no existing functionality breaks.

#### Acceptance Criteria

1. THE `HealthAssessment` model SHALL retain all existing fields (`natural_language_summary`, `issues`, `recommended_actions`, `primary_signals`, `amplifiers`, `log_patterns`) with no changes to their types or semantics.
2. THE new `narrative` field on `HealthAssessment` SHALL default to None, so that existing stored assessments deserialize without error.
3. THE `/status` API response SHALL continue to include all existing fields. New fields (`narrative`, per-service health) are additive.
4. THE `AssessHealthInput` workflow input SHALL retain all existing fields. New fields (`cluster_narrative`, `deployment_profile`, `deployment_context`) SHALL have None defaults.
5. EXISTING tests SHALL continue to pass without modification (new tests are additive).

### Requirement 7: Determinism Invariant

**User Story:** As a developer, I want all new computation (ServiceHealth, ClusterNarrative, TrendSummary, critical gates) to be fully deterministic, so that the "Rules Decide, AI Explains" principle is preserved.

#### Acceptance Criteria

1. FOR ALL new models and functions introduced by this spec, THE computation SHALL be deterministic: the same inputs produce the same outputs.
2. NO new computation SHALL involve LLM calls. The LLM's role is unchanged: it receives pre-computed structured context and produces a narrative explanation.
3. THE `ClusterNarrative` SHALL be computable without any async I/O — it is a pure function of signals, gate evaluation, and deployment context.
4. ALL new models SHALL be Pydantic BaseModels with typed fields and validation.

### Requirement 8: Package Boundary Compliance

**User Story:** As a developer, I want the new models to respect the existing package dependency graph, so that no circular dependencies are introduced.

#### Acceptance Criteria

1. `ServiceHealth`, `ClusterNarrative`, `NarrativeOutput`, `SignalTrend`, and `TrendSummary` SHALL live in `copilot.models` (orchestrator package), since they depend on gate evaluation and threshold profiles which are copilot concerns.
2. NO new dependencies SHALL be added from `copilot_core` to `copilot`, from `dsql_config` to `copilot`, or from `dsql_config` to `behaviour_profiles`.
3. IF any new shared type is needed by multiple packages, it SHALL be placed in `copilot_core`.
