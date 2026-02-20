# Requirements Document

## Introduction

The Health State Machine evaluates cluster health using deterministic rules with fixed thresholds. These thresholds were calibrated for production-scale deployments (~150 wf/s) and produce false positives on low-throughput clusters. At 2 wf/s on a dev cluster, the Copilot incorrectly reports STRESSED because: (1) DSQL baseline persistence latency (300-400ms p99) exceeds the 100ms stressed gate, (2) throughput falls in a dead zone between idle (<1 st/sec) and healthy (≥10 st/sec), (3) poller timeouts are expected behavior when there's little work to poll, and (4) state transition latency p99 is dominated by individual slow transactions at low throughput.

This feature introduces a three-layer calibration system that progressively refines the Health State Machine's expectations to match reality:

- **Layer 1 — Scale-Aware Thresholds**: The Health State Machine adapts thresholds based on observed throughput, aligned with Config Compiler presets (starter, mid-scale, high-throughput). This is the immediate fix for the "2 wf/s dev cluster stuck in Stressed" problem.
- **Layer 2 — Deployment Profiles**: The Config Compiler gains a DeploymentProfile that captures scaling topology (min/max replicas, autoscaler type, resource limits) and provisioned resource identities (DSQL endpoint, ECS cluster ARN, AMP workspace ID). This bridges "what we compiled" to "what we deployed."
- **Layer 3 — Dynamic Inspection**: The Copilot dynamically inspects the monitored cluster's deployment (replica counts, resource utilization, autoscaler state, DSQL connection limits) and feeds a DeploymentContext into health evaluation, allowing thresholds to be refined beyond what throughput alone can determine.

Together these form a feedback loop:

```
Config Compiler (what we intended)
        ↓
Deployment Profile (what we deployed + scaling bounds)
        ↓
Copilot Dynamic Inspection (what's actually running)
        ↓
Scale-Aware Thresholds (expectations calibrated to reality)
        ↓
Behaviour Profiles (what we observed → feeds back to Config Compiler)
```

All thresholds remain fully deterministic — no LLM involvement in state transitions. The "Rules Decide, AI Explains" principle is preserved across all three layers.

## Glossary

- **Health_State_Machine**: The deterministic rules engine in `copilot/models/state_machine.py` that evaluates primary signals and produces a HealthState (HAPPY, STRESSED, CRITICAL). Follows the "Rules Decide, AI Explains" principle.
- **Scale_Band**: A throughput range (measured in state transitions per second) that determines which set of thresholds to apply. Aligned with Config Compiler presets: starter (0-50 st/sec), mid-scale (50-500 st/sec), high-throughput (500+ st/sec).
- **Threshold_Profile**: A complete set of CriticalThresholds, StressedThresholds, and HealthyThresholds calibrated for a specific Scale_Band.
- **Operating_Point**: The cluster's current observed throughput level, derived from the state_transitions.throughput_per_sec primary signal.
- **Dead_Zone**: A throughput range where the cluster is too active to be classified as idle but too quiet to meet the healthy gate, causing a default to STRESSED even when forward progress is unimpaired.
- **Idle_Detector**: The `_is_idle()` function that classifies clusters with near-zero throughput and no errors as HAPPY. Current threshold: <1 st/sec.
- **Forward_Progress_Invariant**: The principle that health is derived from one question: "Is the cluster making forward progress on workflows?" A cluster completing all submitted work is healthy regardless of absolute throughput.
- **Scale_Preset**: A Config Compiler construct (starter, mid-scale, high-throughput) that defines expected throughput ranges and topology defaults. Defined in `dsql_config/presets.py`.
- **Hysteresis_Band**: A margin around threshold boundaries that prevents rapid oscillation (flapping) between states when signals hover near a threshold.
- **Primary_Signals**: The 12 forward-progress indicators collected from AMP every 30 seconds that are the sole inputs to health state evaluation.
- **Amplifier_Signals**: The 14 resource-pressure indicators that explain why a state change occurred. Amplifiers do not decide state.
- **Deployment_Profile**: A model that extends ConfigProfile with scaling topology (min/max replicas per service, autoscaler type, resource limits) and provisioned resource identities (DSQL endpoint, ECS cluster ARN, AMP workspace ID). Lives in `copilot_core` since both `dsql_config` and `copilot` need it.
- **Deployment_Adapter**: A protocol (extending or parallel to PlatformAdapter) that renders a ConfigProfile into a DeploymentProfile by annotating it with infrastructure identifiers and scaling bounds. Discovered via `importlib.metadata.entry_points()`.
- **Deployment_Context**: A runtime snapshot of the monitored cluster's actual deployment state: current replica counts per service, resource utilization vs limits, autoscaler state, and DSQL connection limits. Fetched by the Copilot and passed to `evaluate_health_state()`.
- **Platform_Inspector**: A protocol-based adapter that queries a specific deployment platform (ECS, EKS) for current deployment state. Discovered via entry points, same pattern as Config Compiler adapters.
- **Scaling_Topology**: The min/max replica counts per Temporal service, autoscaler type (Karpenter, HPA, fixed), and resource limits (CPU, memory) per service.
- **Resource_Identity**: A provisioned infrastructure identifier: DSQL cluster endpoint, ECS cluster ARN or EKS namespace, AMP workspace ID.


## Requirements

### Layer 1: Scale-Aware Thresholds (Health State Machine)

### Requirement 1: Scale Band Classification

**User Story:** As an SRE, I want the Copilot to classify the cluster's current throughput into a scale band, so that appropriate thresholds are applied for the cluster's operating point.

#### Acceptance Criteria

1. WHEN the Health_State_Machine evaluates Primary_Signals, THE Health_State_Machine SHALL classify the Operating_Point into exactly one Scale_Band based on the observed state_transitions.throughput_per_sec value.
2. THE Health_State_Machine SHALL support three Scale_Bands aligned with Scale_Preset throughput ranges: starter (0-50 st/sec), mid-scale (50-500 st/sec), and high-throughput (500+ st/sec).
3. WHEN the Operating_Point crosses a Scale_Band boundary, THE Health_State_Machine SHALL apply a Hysteresis_Band of 10% of the boundary value to prevent rapid oscillation between Threshold_Profiles.
4. THE Health_State_Machine SHALL use the Scale_Band classification as a pure function of the current throughput value, requiring no external configuration or LLM involvement.

### Requirement 2: Threshold Profiles per Scale Band

**User Story:** As an SRE, I want each scale band to have its own calibrated threshold profile, so that a 2 wf/s dev cluster and a 150 wf/s production cluster are evaluated with appropriate expectations.

#### Acceptance Criteria

1. THE Health_State_Machine SHALL define a distinct Threshold_Profile (CriticalThresholds, StressedThresholds, HealthyThresholds) for each Scale_Band.
2. THE starter Threshold_Profile SHALL set persistence_latency_p99_max_ms to a value that accommodates DSQL baseline latency at low throughput (at least 500ms for the stressed gate).
3. THE starter Threshold_Profile SHALL set state_transition_latency_p99_max_ms to a value that accommodates individual slow transactions dominating p99 at low throughput (at least 2000ms for the stressed gate).
4. THE starter Threshold_Profile SHALL set poller_timeout_rate_max to a value that accommodates expected poll timeouts when there is little work to poll (at least 0.5 for the stressed gate).
5. THE high-throughput Threshold_Profile SHALL retain the current production-calibrated thresholds (persistence_latency_p99_max_ms of 100ms, state_transition_latency_p99_max_ms of 500ms, poller_timeout_rate_max of 0.1).
6. THE mid-scale Threshold_Profile SHALL define thresholds between the starter and high-throughput values, proportional to the throughput range.
7. WHEN a Threshold_Profile is applied, THE Health_State_Machine SHALL use all thresholds from that profile consistently within a single evaluation cycle.

### Requirement 3: Dead Zone Elimination

**User Story:** As an SRE, I want the Copilot to correctly classify a cluster doing 2-9 st/sec with no errors as HAPPY, so that low-throughput clusters are not perpetually stuck in STRESSED.

#### Acceptance Criteria

1. THE Health_State_Machine SHALL eliminate the Dead_Zone between the Idle_Detector upper bound and the HealthyThresholds lower bound.
2. WHEN the Operating_Point is between 1 and 10 st/sec AND the cluster has zero persistence errors AND the cluster has zero frontend errors AND the workflow completion rate is above 0.85, THE Health_State_Machine SHALL evaluate the cluster as HAPPY.
3. THE starter Threshold_Profile SHALL set state_transitions_healthy_per_sec to a value at or below the Idle_Detector upper bound (at most 1.0 st/sec), ensuring continuous coverage from idle through low-throughput operation.
4. THE Health_State_Machine SHALL preserve the Forward_Progress_Invariant: a cluster completing all submitted work is healthy regardless of absolute throughput level.

### Requirement 4: Frontend Latency Scaling

**User Story:** As an SRE, I want frontend latency thresholds to scale with load, so that the Copilot does not flag normal low-traffic frontend latency as stress.

#### Acceptance Criteria

1. THE starter Threshold_Profile SHALL set frontend_latency_p99_max_ms to a value that accommodates sparse request patterns at low throughput (at least 3000ms for the stressed gate).
2. THE high-throughput Threshold_Profile SHALL retain the current frontend_latency_p99_max_ms of 1000ms for the stressed gate.
3. WHILE the Operating_Point is in the starter Scale_Band, THE Health_State_Machine SHALL apply the relaxed frontend latency threshold from the starter Threshold_Profile.

### Requirement 5: Critical Threshold Scaling

**User Story:** As an SRE, I want critical thresholds to scale with the cluster's operating point, so that a low-throughput cluster is not flagged as critical for having throughput below a production-calibrated floor.

#### Acceptance Criteria

1. THE starter Threshold_Profile SHALL set state_transitions_min_per_sec (critical gate) to a value proportional to the starter Scale_Band (at most 1.0 st/sec).
2. THE starter Threshold_Profile SHALL set history_processing_rate_min_per_sec (critical gate) to a value proportional to the starter Scale_Band (at most 1.0 st/sec).
3. THE starter Threshold_Profile SHALL set completion_rate_demand_floor_per_sec to a value proportional to the starter Scale_Band (at most 1.0 st/sec).
4. THE high-throughput Threshold_Profile SHALL retain the current critical thresholds (state_transitions_min_per_sec of 5.0, history_processing_rate_min_per_sec of 5.0, completion_rate_demand_floor_per_sec of 5.0).
5. FOR ALL Scale_Bands, THE critical state_transitions_min_per_sec threshold SHALL be strictly less than the healthy state_transitions_healthy_per_sec threshold, ensuring a cluster cannot be simultaneously critical and healthy.

### Requirement 6: Threshold Profile Override

**User Story:** As an operator, I want to override individual thresholds within a scale-band profile, so that I can tune the Copilot for cluster-specific characteristics without replacing the entire profile.

#### Acceptance Criteria

1. THE CopilotConfig SHALL accept optional per-threshold overrides that take precedence over the Scale_Band Threshold_Profile defaults.
2. WHEN an operator provides a threshold override, THE Health_State_Machine SHALL use the override value instead of the Scale_Band default for that specific threshold.
3. WHEN an operator does not provide any overrides, THE Health_State_Machine SHALL use the Scale_Band Threshold_Profile defaults determined by the Operating_Point.
4. IF an operator provides a threshold override that violates the ordering invariant (critical < stressed < healthy for throughput thresholds), THEN THE CopilotConfig SHALL reject the configuration with a descriptive error message.

### Requirement 7: Transition Invariant Preservation

**User Story:** As an SRE, I want the scale-aware thresholds to preserve all existing Health State Machine invariants, so that the change does not introduce new failure modes.

#### Acceptance Criteria

1. FOR ALL Scale_Bands, THE Health_State_Machine SHALL preserve the transition invariant: HAPPY to CRITICAL transitions go through STRESSED.
2. FOR ALL Scale_Bands, THE Health_State_Machine SHALL preserve the anti-flap design: CRITICAL requires CONSECUTIVE_CRITICAL_THRESHOLD (3) consecutive evaluations.
3. FOR ALL Scale_Bands, THE Health_State_Machine SHALL preserve the recovery hysteresis: recovering from CRITICAL requires signals to clear a margin above critical thresholds before downgrading to STRESSED.
4. WHEN the Scale_Band changes between consecutive evaluations, THE Health_State_Machine SHALL preserve the consecutive_critical_count to prevent the scale band change from resetting the debounce counter.
5. FOR ALL valid Primary_Signals inputs, THE Health_State_Machine SHALL produce a deterministic output: the same inputs with the same current state and consecutive count produce the same new state and new count.

### Requirement 8: Bottleneck Classifier Scale Awareness

**User Story:** As an SRE, I want the bottleneck classifier to use scale-appropriate thresholds, so that server-side stress detection does not false-positive on low-throughput clusters.

#### Acceptance Criteria

1. THE `_is_server_stressed` function SHALL use the current Scale_Band Threshold_Profile for persistence_latency_p95 and history_backlog_age thresholds instead of hardcoded values.
2. WHILE the Operating_Point is in the starter Scale_Band, THE bottleneck classifier SHALL use relaxed persistence latency thresholds consistent with the starter Threshold_Profile.
3. THE bottleneck classifier SHALL remain deterministic with no LLM involvement.


### Layer 2: Deployment Profiles (Config Compiler)

### Requirement 9: Deployment Profile Model

**User Story:** As an operator, I want to capture my cluster's scaling topology and infrastructure identifiers alongside the compiled configuration, so that the Copilot knows what was deployed and can set expectations accordingly.

#### Acceptance Criteria

1. THE Deployment_Profile model SHALL extend ConfigProfile with a Scaling_Topology section containing: min and max replica counts per Temporal service (history, matching, frontend, worker), autoscaler type (karpenter, hpa, fixed), and resource limits (CPU millicores, memory MiB) per service.
2. THE Deployment_Profile model SHALL include a Resource_Identity section containing: DSQL cluster endpoint, deployment platform identifier (ECS cluster ARN or EKS namespace), and AMP workspace ID.
3. THE Deployment_Profile model SHALL live in `copilot_core` as a shared type, since both `dsql_config` (produces it) and `copilot` (consumes it) need access.
4. THE Deployment_Profile model SHALL be a Pydantic BaseModel with all fields typed and validated.
5. THE Deployment_Profile model SHALL include the source ConfigProfile's preset_name and throughput_range, preserving the link between compiled configuration and deployment.

### Requirement 10: Deployment Profile Creation

**User Story:** As an operator, I want to clone a compiled ConfigProfile into a DeploymentProfile by annotating it with my infrastructure details, so that I have a single artifact describing both configuration and deployment topology.

#### Acceptance Criteria

1. WHEN an operator provides a ConfigProfile and infrastructure annotations, THE Config_Compiler SHALL produce a Deployment_Profile that combines the compiled parameters with the Scaling_Topology and Resource_Identity.
2. THE Config_Compiler SHALL validate that replica counts in the Scaling_Topology are consistent with the ConfigProfile's topology parameters (min_replicas ≤ topology default ≤ max_replicas).
3. IF the Scaling_Topology specifies max_replicas less than the ConfigProfile's topology default for any service, THEN THE Config_Compiler SHALL emit a warning that the deployment cannot reach the compiled topology.
4. THE Config_Compiler SHALL accept Scaling_Topology and Resource_Identity as optional inputs; WHEN not provided, THE Config_Compiler SHALL produce a ConfigProfile without deployment annotations (backward compatible).

### Requirement 11: Deployment Adapter Protocol

**User Story:** As a platform engineer, I want to implement a DeploymentAdapter for my platform (ECS, EKS, Compose), so that deployment profiles can be generated for different infrastructure targets.

#### Acceptance Criteria

1. THE Deployment_Adapter protocol SHALL define a `render_deployment` method that accepts a ConfigProfile and platform-specific annotations and returns a Deployment_Profile.
2. THE Deployment_Adapter protocol SHALL be discoverable via `importlib.metadata.entry_points()` under a well-known group name, following the same pattern as SDKAdapter and PlatformAdapter.
3. THE Deployment_Adapter protocol SHALL be a `typing.Protocol` with `runtime_checkable` decorator, consistent with the existing adapter protocols in `dsql_config/adapters/__init__.py`.
4. WHEN a Deployment_Adapter is loaded, THE adapter discovery function SHALL verify that the loaded object implements the Deployment_Adapter protocol and raise TypeError if not.

### Requirement 12: ECS Deployment Adapter

**User Story:** As an operator deploying on ECS, I want the ECS adapter to produce a DeploymentProfile with ECS-specific resource identities and scaling bounds, so that the Copilot understands my ECS deployment topology.

#### Acceptance Criteria

1. THE ECS Deployment_Adapter SHALL populate Resource_Identity with the ECS cluster ARN and DSQL cluster endpoint from the provided annotations.
2. THE ECS Deployment_Adapter SHALL populate Scaling_Topology with per-service replica bounds derived from ECS service configuration (desired count as default, min/max from autoscaling policies if present).
3. THE ECS Deployment_Adapter SHALL populate per-service resource limits from ECS task definition CPU and memory values.
4. THE ECS Deployment_Adapter SHALL extend the existing ECSAdapter class or coexist alongside it, reusing the existing entry point registration pattern.

### Requirement 13: Compose Deployment Adapter

**User Story:** As a developer running the standalone dev environment on Docker Compose, I want the Compose adapter to produce a DeploymentProfile with Compose-specific topology, so that the Copilot understands the dev stack's single-replica, no-autoscaler nature and sets expectations accordingly.

#### Acceptance Criteria

1. THE Compose Deployment_Adapter SHALL populate Scaling_Topology with fixed replica counts (min = max = 1 per service) and autoscaler type set to "fixed", reflecting that Compose services do not autoscale.
2. THE Compose Deployment_Adapter SHALL populate per-service resource limits from the Compose service's `deploy.resources.limits` if present, or mark them as unbounded (None) when no resource limits are configured.
3. THE Compose Deployment_Adapter SHALL populate Resource_Identity with the DSQL cluster endpoint extracted from the Compose environment variables (TEMPORAL_SQL_HOST) and the Compose project name as the deployment platform identifier.
4. THE Compose Deployment_Adapter SHALL extend the existing ComposeAdapter class or coexist alongside it, reusing the existing entry point registration pattern.

### Requirement 14: Deployment Profile Serialization

**User Story:** As a developer, I want Deployment Profiles to round-trip through JSON serialization without data loss, so that profiles can be stored, transmitted, and compared reliably.

#### Acceptance Criteria

1. THE Deployment_Profile model SHALL serialize to JSON via Pydantic's `.model_dump_json()` method.
2. THE Deployment_Profile model SHALL deserialize from JSON via Pydantic's `.model_validate_json()` method.
3. FOR ALL valid Deployment_Profile instances, serializing to JSON then deserializing SHALL produce an equivalent Deployment_Profile (round-trip property).
4. THE Deployment_Profile JSON schema SHALL be backward compatible: a Deployment_Profile without Scaling_Topology or Resource_Identity SHALL deserialize as a valid model with those fields set to None.


### Layer 3: Dynamic Inspection (Copilot Runtime Discovery)

### Requirement 15: Deployment Context Model

**User Story:** As an SRE, I want the Copilot to have a runtime snapshot of the monitored cluster's actual deployment state, so that health evaluation can account for what is actually running rather than relying solely on throughput.

#### Acceptance Criteria

1. THE Deployment_Context model SHALL capture current replica counts per Temporal service (history, matching, frontend, worker) as observed from the deployment platform.
2. THE Deployment_Context model SHALL capture resource utilization vs limits per service (CPU percentage, memory percentage) as observed from the deployment platform.
3. THE Deployment_Context model SHALL capture autoscaler state: current desired replicas, min/max bounds, and whether the autoscaler is actively scaling.
4. THE Deployment_Context model SHALL capture DSQL cluster connection limits and current connection count.
5. THE Deployment_Context model SHALL be a Pydantic BaseModel with a timestamp field using the `whenever` library (ISO 8601 UTC string).
6. THE Deployment_Context model SHALL live in `copilot_core` as a shared type.

### Requirement 16: Platform Inspector Protocol

**User Story:** As a platform engineer, I want to implement a PlatformInspector for my deployment platform (ECS, EKS, Compose), so that the Copilot can discover the actual deployment state at runtime.

#### Acceptance Criteria

1. THE Platform_Inspector protocol SHALL define an async `inspect` method that accepts a Resource_Identity and returns a Deployment_Context.
2. THE Platform_Inspector protocol SHALL be discoverable via `importlib.metadata.entry_points()` under a well-known group name, following the same pattern as Config Compiler adapters.
3. THE Platform_Inspector protocol SHALL be a `typing.Protocol` with `runtime_checkable` decorator.
4. WHEN a Platform_Inspector is loaded, THE inspector discovery function SHALL verify that the loaded object implements the Platform_Inspector protocol and raise TypeError if not.
5. IF the Platform_Inspector fails to query the deployment platform, THEN THE Platform_Inspector SHALL return None rather than raising an exception, allowing the Copilot to fall back to throughput-only scale band classification.

### Requirement 17: ECS Platform Inspector

**User Story:** As an operator running on ECS, I want the Copilot to discover my ECS deployment state (replica counts, resource utilization, autoscaler configuration), so that health evaluation accounts for my actual infrastructure.

#### Acceptance Criteria

1. THE ECS Platform_Inspector SHALL query ECS DescribeServices to obtain current running count, desired count, and pending count per Temporal service.
2. THE ECS Platform_Inspector SHALL query CloudWatch Container Insights for per-service CPU and memory utilization percentages.
3. THE ECS Platform_Inspector SHALL query Application Auto Scaling to obtain min/max capacity and scaling policy state for each ECS service.
4. THE ECS Platform_Inspector SHALL query DSQL cluster metrics from CloudWatch to obtain current connection count and connection limit.
5. THE ECS Platform_Inspector SHALL use IAM credentials from the Copilot's task role, requiring no additional credential configuration.

### Requirement 18: Compose Platform Inspector

**User Story:** As a developer running the standalone dev environment on Docker Compose, I want the Copilot to discover the Compose deployment state (running containers, resource usage), so that health evaluation accounts for the dev stack's single-replica topology.

#### Acceptance Criteria

1. THE Compose Platform_Inspector SHALL query the Docker Engine API to obtain running container state per Temporal service (running, restarting, exited), matching containers by Compose service name or container name convention (temporal-dsql-history, temporal-dsql-matching, temporal-dsql-frontend, temporal-dsql-worker).
2. THE Compose Platform_Inspector SHALL query Docker container stats for per-service CPU and memory utilization percentages relative to the host or configured resource limits.
3. THE Compose Platform_Inspector SHALL set autoscaler state to fixed (min = max = current replica count, actively_scaling = false), reflecting that Compose services do not autoscale.
4. THE Compose Platform_Inspector SHALL obtain the DSQL cluster endpoint from the container's environment variables (TEMPORAL_SQL_HOST) and set DSQL connection limits to the configured TEMPORAL_SQL_MAX_CONNS value per service.
5. THE Compose Platform_Inspector SHALL connect to the Docker Engine API via the Unix socket (/var/run/docker.sock) or the DOCKER_HOST environment variable, requiring no additional credential configuration.
6. IF the Docker Engine API is not accessible, THEN THE Compose Platform_Inspector SHALL return None, allowing the Copilot to fall back to throughput-only scale band classification.

### Requirement 19: Fetch Deployment Context Activity

**User Story:** As a developer, I want a Temporal activity that fetches the deployment context, so that the ObserveClusterWorkflow can incorporate deployment state into health evaluation.

#### Acceptance Criteria

1. THE `fetch_deployment_context` activity SHALL accept a single Pydantic BaseModel input containing the Resource_Identity and the platform type.
2. THE `fetch_deployment_context` activity SHALL use the Platform_Inspector protocol to query the deployment platform and return a Deployment_Context.
3. IF no Platform_Inspector is available for the configured platform type, THEN THE `fetch_deployment_context` activity SHALL return None.
4. IF the Platform_Inspector returns None (query failure), THEN THE `fetch_deployment_context` activity SHALL log a warning and return None, allowing the workflow to continue with throughput-only evaluation.
5. THE `fetch_deployment_context` activity SHALL have a start-to-close timeout of 30 seconds.

### Requirement 20: Deployment Context Integration in ObserveClusterWorkflow

**User Story:** As an SRE, I want the ObserveClusterWorkflow to periodically fetch deployment context and pass it to health evaluation, so that thresholds can be refined based on actual infrastructure state.

#### Acceptance Criteria

1. THE ObserveClusterWorkflow SHALL fetch Deployment_Context every 5 minutes (10 observation cycles), independent of the 30-second signal fetch interval.
2. THE ObserveClusterWorkflow SHALL cache the most recent Deployment_Context and reuse it across signal evaluation cycles until the next fetch.
3. WHEN Deployment_Context is available, THE ObserveClusterWorkflow SHALL pass the Deployment_Context to `evaluate_health_state()` alongside Primary_Signals.
4. WHEN Deployment_Context is not available (None), THE ObserveClusterWorkflow SHALL fall back to throughput-only Scale_Band classification with no change in behavior.
5. THE ObserveClusterWorkflow SHALL expose the current Deployment_Context via a Temporal query for observability.

### Requirement 21: Deployment Context Threshold Refinement

**User Story:** As an SRE, I want the Health State Machine to refine scale-band thresholds using deployment context when available, so that a cluster with 8 History replicas at 4 vCPU each is evaluated differently from a cluster with 2 History replicas at 1 vCPU each, even at the same throughput.

#### Acceptance Criteria

1. WHEN Deployment_Context is provided, THE Health_State_Machine SHALL use the deployment context to refine the Threshold_Profile selected by the throughput-derived Scale_Band.
2. WHEN the Deployment_Context shows History replicas above the Scale_Band's topology default, THE Health_State_Machine SHALL tighten persistence and backlog thresholds proportionally (more capacity means tighter expectations).
3. WHEN the Deployment_Context shows History replicas below the Scale_Band's topology default, THE Health_State_Machine SHALL relax persistence and backlog thresholds proportionally (less capacity means looser expectations).
4. WHEN the Deployment_Context shows an autoscaler actively scaling up, THE Health_State_Machine SHALL apply a grace period (at least 2 evaluation cycles / 60 seconds) before tightening thresholds to the new capacity level.
5. THE threshold refinement SHALL remain deterministic: the same Deployment_Context and Primary_Signals produce the same refined Threshold_Profile.
6. THE threshold refinement SHALL preserve all invariants from Requirement 7 (transition invariant, anti-flap, recovery hysteresis, consecutive count preservation, determinism).


### Cross-Cutting Requirements

### Requirement 22: Package Boundary Compliance

**User Story:** As a developer, I want the three-layer system to respect the existing package dependency graph, so that no circular dependencies are introduced.

#### Acceptance Criteria

1. THE Deployment_Profile and Deployment_Context models SHALL live in `copilot_core`, preserving the DAG: copilot_core ← dsql_config, copilot_core ← behaviour_profiles, copilot_core ← copilot.
2. THE Deployment_Adapter protocol and implementations SHALL live in `dsql_config/adapters/`, consistent with the existing SDKAdapter and PlatformAdapter.
3. THE Platform_Inspector protocol and implementations SHALL live in `copilot`, since runtime inspection is an orchestrator concern.
4. THE `dsql_config` package SHALL NOT depend on `behaviour_profiles` or `copilot`.
5. THE `behaviour_profiles` package SHALL NOT depend on `dsql_config` for any new types introduced by this feature (shared types go through `copilot_core`).

### Requirement 23: Behaviour Profile Integration

**User Story:** As an SRE, I want Behaviour Profiles to capture the Deployment_Profile and Deployment_Context that were active when the profile was taken, so that profile comparisons can correlate telemetry changes with deployment changes.

#### Acceptance Criteria

1. WHEN a BehaviourProfile is created, THE profile creation process SHALL include the active Deployment_Profile (if available) in the ConfigSnapshot.
2. WHEN a BehaviourProfile is created, THE profile creation process SHALL include the most recent Deployment_Context (if available) as a new field on BehaviourProfile.
3. WHEN comparing two BehaviourProfiles, THE comparison SHALL include deployment topology diffs (replica count changes, resource limit changes) alongside config and telemetry diffs.
4. THE BehaviourProfile model changes SHALL be backward compatible: profiles created before this feature SHALL deserialize with Deployment_Profile and Deployment_Context fields set to None.

### Requirement 24: Property Test Coverage

**User Story:** As a developer, I want property-based tests that verify scale-aware threshold invariants, deployment profile serialization, and deployment context integration, so that changes do not silently break correctness.

#### Acceptance Criteria

1. THE property test suite SHALL verify that for all generated Primary_Signals and all Scale_Bands, the transition invariant (no direct HAPPY to CRITICAL) holds.
2. THE property test suite SHALL verify that for all Scale_Bands, the threshold ordering invariant (critical < healthy for throughput thresholds) holds.
3. THE property test suite SHALL verify that an idle cluster (throughput < 1 st/sec, zero errors, zero backlog) evaluates as HAPPY regardless of Scale_Band.
4. THE property test suite SHALL verify that a cluster in the Dead_Zone (1-10 st/sec, zero errors, completion rate above 0.85) evaluates as HAPPY under the starter Threshold_Profile.
5. THE property test suite SHALL verify that scale band classification is a pure function: the same throughput value always produces the same Scale_Band.
6. FOR ALL valid Deployment_Profile instances, serializing to JSON then deserializing SHALL produce an equivalent Deployment_Profile (round-trip property).
7. FOR ALL valid Deployment_Context instances, serializing to JSON then deserializing SHALL produce an equivalent Deployment_Context (round-trip property).
8. THE property test suite SHALL verify that threshold refinement with Deployment_Context preserves all Health State Machine invariants (transition invariant, threshold ordering, determinism).
9. THE property test suite SHALL verify that when Deployment_Context is None, health evaluation produces identical results to throughput-only evaluation (backward compatibility property).
