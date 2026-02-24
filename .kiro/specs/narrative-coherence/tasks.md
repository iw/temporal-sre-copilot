# Implementation Tasks

## Component 1: ServiceHealth Model and ClusterNarrative

### Task 1: Core narrative models
- [ ] Create `packages/copilot/src/copilot/models/narrative.py`
- [ ] Add `ForwardProgress` StrEnum (OK, DEGRADED, BLOCKED)
- [ ] Add `PressureLevel` StrEnum (LOW, MODERATE, HIGH)
- [ ] Add `ServiceHealth` model (service, forward_progress, pressure, artifact_signals, dominant_signal, summary)
- [ ] Add `NarrativeSetting` model (scale_band, preset_name, platform_type, environment_summary, per-service replica counts)
- [ ] Add `ClusterNarrative` model (setting, gate_evaluation, actors, trends, forward_progress_intact, unaffected_actors)
- [ ] Export all from `copilot.models.__init__.py`

**Requirements:** R1.1, R1.2, R1.7, R7.4, R8.1

### Task 2: Actor classification functions
- [ ] Implement `_classify_history(primary, amplifiers, gate_eval) -> ServiceHealth` — extract logic from `_build_history_section` in researcher.py
- [ ] Implement `_classify_matching(primary, gate_eval) -> ServiceHealth` — extract logic from `_build_matching_section`
- [ ] Implement `_classify_frontend(primary, gate_eval) -> ServiceHealth` — extract logic from `_build_frontend_section`
- [ ] Implement `_classify_workers(primary, amplifiers) -> ServiceHealth` — extract logic from `_build_workers_section`
- [ ] Implement `_classify_dsql(amplifiers) -> ServiceHealth` — extract logic from `_build_foundation_section`
- [ ] All classification functions are pure (no I/O, no async, no LLM) — R7.1, R7.3

**Requirements:** R1.3, R7.1, R7.2, R7.3

### Task 3: compute_cluster_narrative() function
- [ ] Implement `compute_cluster_narrative(primary, amplifiers, gate_eval, *, deployment_profile, deployment_context, trend_summary) -> ClusterNarrative`
- [ ] Implement `_build_setting(gate_eval, profile, context) -> NarrativeSetting`
- [ ] Compute `forward_progress_intact` from History actor's forward_progress
- [ ] Compute `unaffected_actors` list (OK progress + LOW pressure)
- [ ] Verify function is pure: no I/O, no async, deterministic

**Requirements:** R1.3, R1.4, R2.1, R2.2, R2.3, R2.4, R7.1, R7.3

## Component 2: Deployment Context in the Narrative

### Task 4: Thread deployment context to AssessHealthInput
- [ ] Add `cluster_narrative: ClusterNarrative | None = None` field to `AssessHealthInput` in `workflow_inputs.py`
- [ ] Add `deployment_profile: DeploymentProfile | None = None` field to `AssessHealthInput`
- [ ] Add `deployment_context: DeploymentContext | None = None` field to `AssessHealthInput`
- [ ] All new fields default to None for backward compatibility — R6.4
- [ ] Update `ObserveClusterWorkflow` to compute `ClusterNarrative` and pass it to `AssessHealthInput` on state change

**Requirements:** R2.5, R6.4

### Task 5: Update ObserveClusterWorkflow to compute narrative
- [ ] Import `compute_cluster_narrative` and `compute_trend_summary` in observe.py
- [ ] After `evaluate_health_state()`, compute `trend_summary = compute_trend_summary(self._signal_window)`
- [ ] Compute `cluster_narrative = compute_cluster_narrative(signals.primary, signals.amplifiers, gate_eval, deployment_profile=..., deployment_context=..., trend_summary=...)`
- [ ] Pass `cluster_narrative`, `deployment_profile`, and `deployment_context` to `AssessHealthInput`
- [ ] Ensure narrative computation happens only on state change (not every 30s cycle) to avoid unnecessary work

**Requirements:** R1.4, R2.5, R5.3

## Component 3: Structured Narrative Output

### Task 6: NarrativeOutput model
- [ ] Add `NarrativeOutput` model to `packages/copilot/src/copilot/models/assessment.py` with fields: setting, inciting_signal, character_reactions, tension_analysis, resolution, watch_next
- [ ] Add `narrative: NarrativeOutput | None = None` field to `HealthAssessment` — R6.1, R6.2
- [ ] Retain `natural_language_summary` field unchanged — R6.1
- [ ] Export `NarrativeOutput` from `copilot.models.__init__.py`

**Requirements:** R3.1, R3.2, R3.4, R6.1, R6.2

### Task 7: Update researcher system instructions
- [ ] Add five-act structure description to `RESEARCHER_INSTRUCTIONS` in researcher.py
- [ ] Describe each act with examples (setting, inciting_signal, character_reactions, tension_analysis, resolution)
- [ ] Instruct the LLM to populate the `narrative` field on `HealthAssessment`
- [ ] Instruct the LLM to populate `watch_next` with 2-3 forward-looking items
- [ ] Retain all existing rules (no numbers, gate consistency, persistence path understanding)

**Requirements:** R3.6

### Task 8: Update researcher prompt builder
- [ ] Update `build_researcher_prompt()` signature to accept `ClusterNarrative` instead of raw signals
- [ ] Implement `_build_setting_section(setting: NarrativeSetting) -> str` — renders the Setting act
- [ ] Implement `_build_actors_section(actors: list[ServiceHealth], unaffected: list[str]) -> str` — renders pre-classified actor states
- [ ] Update `_build_trend_section` to consume `TrendSummary` with qualitative descriptions
- [ ] Retain `_build_verdict_section`, `_build_log_section`, `_build_rag_section`, `_build_closing`
- [ ] Remove `_build_history_section`, `_build_frontend_section`, `_build_matching_section`, `_build_workers_section`, `_build_foundation_section`, `_build_cluster_stability_section` (replaced by `_build_actors_section`)
- [ ] Provide backward-compatible fallback: if `cluster_narrative` is None, fall back to raw signal prompt building (keep old helpers as `_legacy_build_*` or accept both paths)

**Requirements:** R1.6, R3.3, R3.6, R6.5

### Task 9: Update assess.py workflow
- [ ] Pass `cluster_narrative` to `build_researcher_prompt()` when available
- [ ] After researcher returns, populate `assessment.natural_language_summary` from narrative sections if `assessment.narrative` is present — R3.4
- [ ] Implement `_create_minimal_narrative(cluster_narrative, health_state) -> NarrativeOutput` for NoExplanationNeeded/QuickExplanation paths — R3.7
- [ ] Attach minimal narrative to assessments created by dispatcher fast paths

**Requirements:** R3.3, R3.4, R3.7

## Component 4: Critical Gate Evaluation

### Task 10: Evaluate critical gates
- [ ] Add `_any_critical_gate_fires(primary, critical, has_demand) -> bool` helper to gate_evaluation.py
- [ ] Evaluate Signal 1 (state transition throughput collapse) — demand-gated
- [ ] Evaluate Signal 3 (workflow completion rate collapse) — demand-gated
- [ ] Evaluate Signal 4 (critical backlog age)
- [ ] Evaluate Signal 5 (persistence error storm)
- [ ] Populate `GateEvaluation.critical_gates` when health_state is CRITICAL or any critical gate fires
- [ ] Each critical gate uses the scale-band-aware `ThresholdProfile.critical` thresholds — R4.4
- [ ] Remain deterministic — R4.5

**Requirements:** R4.1, R4.2, R4.3, R4.4, R4.5

### Task 11: Update verdict section for critical gates
- [ ] Update `_build_verdict_section` in researcher.py to include critical gates when present
- [ ] Visually distinguish critical gates from stressed gates (e.g., "CRITICAL FIRED 🔴" vs "FIRED ⚠")
- [ ] Include critical gate context strings in the prompt

**Requirements:** R4.3

## Component 5: Signal Trend Computation

### Task 12: Trend models and computation
- [ ] Add `SignalTrend` StrEnum (IMPROVING, STABLE, WORSENING) to narrative.py
- [ ] Add `TrendSummary` model (throughput, persistence_latency, backlog_age, frontend_latency, error_rate — all SignalTrend)
- [ ] Implement `compute_trend_summary(signal_window: list[Signals]) -> TrendSummary`
- [ ] Implement `_classify_trend_lower_is_better(first_avg, second_avg) -> SignalTrend` with 10% threshold
- [ ] Implement `_classify_trend_higher_is_better(first_avg, second_avg) -> SignalTrend` with 10% threshold
- [ ] Return all-STABLE when window has fewer than 4 snapshots — R5.4
- [ ] Export `SignalTrend`, `TrendSummary`, `compute_trend_summary` from `copilot.models.__init__.py`

**Requirements:** R5.1, R5.2, R5.3, R5.4, R5.7, R5.8

## API Updates

### Task 13: Update API endpoints
- [ ] Update `/status/services` to return `ServiceHealth` objects from the most recent `ClusterNarrative` — R1.5
- [ ] Add `narrative: NarrativeOutput | None` field to `SummaryResponse` in api_responses.py
- [ ] Update `/status/summary` to include `NarrativeOutput` when available — R3.5
- [ ] Store `ClusterNarrative` alongside assessment in state store (or derive from stored signals)
- [ ] All existing API fields unchanged — R6.3

**Requirements:** R1.5, R3.5, R6.3

## Testing

### Task 14: Unit tests for narrative models
- [ ] Test `_classify_history` with: idle signals, active healthy, degraded (high backlog), blocked (critical backlog), artifact (starter persistence latency)
- [ ] Test `_classify_matching` with: zero backlog, minor delay, task dispatch delayed, poller timeouts on idle
- [ ] Test `_classify_frontend` with: zero errors + low latency, elevated latency from long-running ops, high latency
- [ ] Test `_classify_workers` with: minimal system ops, retention storm, SDK slots exhausted, SDK idle
- [ ] Test `_classify_dsql` with: low utilization, moderate, near saturation, connection wait
- [ ] Test `compute_cluster_narrative` produces correct `forward_progress_intact` and `unaffected_actors`
- [ ] Test `_build_setting` with: no profile, profile only, profile + context

**Requirements:** R1.3, R7.1

### Task 15: Unit tests for trends and critical gates
- [ ] Test `compute_trend_summary` with: empty window, 1 snapshot, 3 snapshots (insufficient), 4+ snapshots
- [ ] Test improving scenario: second-half latency 20% lower than first-half
- [ ] Test worsening scenario: second-half latency 20% higher than first-half
- [ ] Test stable scenario: second-half within 10% of first-half
- [ ] Test edge case: first-half average is 0
- [ ] Test critical gate evaluation: each of the 4 critical gates individually
- [ ] Test critical gates only populated when health_state is CRITICAL or a gate fires
- [ ] Test critical gates use scale-band-aware thresholds

**Requirements:** R4.1, R5.1, R5.4, R5.7, R5.8

### Task 16: Property-based tests
- [ ] Add `test_narrative_coherence.py` to `tests/properties/`
- [ ] Property: `compute_cluster_narrative` is deterministic (same inputs → same output)
- [ ] Property: `compute_trend_summary` is deterministic (same window → same trends)
- [ ] Property: if no stressed gate fired, no actor should be BLOCKED (consistency)
- [ ] Property: `NarrativeOutput` serialization round-trip
- [ ] Property: `ClusterNarrative` serialization round-trip
- [ ] Property: `ServiceHealth` serialization round-trip
- [ ] Property: backward compat — `HealthAssessment` without `narrative` deserializes with None

**Requirements:** R6.5, R7.1, R8.1

### Task 17: Backward compatibility tests
- [ ] Existing 224 tests pass without modification — R6.5
- [ ] `HealthAssessment` without `narrative` field deserializes correctly
- [ ] `AssessHealthInput` without `cluster_narrative` field deserializes correctly
- [ ] `SummaryResponse` without `narrative` field deserializes correctly
- [ ] API responses include all existing fields unchanged

**Requirements:** R6.1, R6.2, R6.3, R6.4, R6.5

### Task 18: Lint, format, type check
- [ ] `uv run ruff check packages/ tests/` passes
- [ ] `uv run ruff format packages/ tests/` produces no changes
- [ ] `uv run ty check packages/` passes
- [ ] `uv run -m pytest tests/ -x -q --tb=short` passes (all existing + new tests)
