# Implementation Tasks

## Layer 1: Scale-Aware Thresholds

### Task 1: ScaleBand enum and classify_scale_band()
- [x] Add `ScaleBand` StrEnum to `packages/copilot/src/copilot/models/config.py` with STARTER, MID_SCALE, HIGH_THROUGHPUT values
- [x] Add `classify_scale_band(throughput_per_sec, current_band)` pure function to `packages/copilot/src/copilot/models/state_machine.py`
- [x] Implement 10% hysteresis at the 50 st/sec and 500 st/sec boundaries
- [x] Handle NaN/negative throughput defensively (treat as 0.0 → STARTER)
- [x] Export `ScaleBand` from `copilot.models` `__init__.py`

**Requirements:** R1 (Scale Band Classification)

### Task 2: ThresholdProfile and per-band defaults
- [x] Add `ThresholdProfile` model (scale_band, critical, stressed, healthy) to `packages/copilot/src/copilot/models/config.py`
- [x] Define `THRESHOLD_PROFILES` dict with starter, mid-scale, and high-throughput profiles using the values from the design threshold table
- [x] Starter: persistence_latency_p99=500ms, state_transition_latency_p99=2000ms, poller_timeout_rate=0.5, frontend_latency_p99=3000ms, state_transitions_healthy=0.5
- [x] High-throughput: identical to current production defaults (persistence_latency_p99=100ms, etc.)
- [x] Mid-scale: intermediate values (persistence_latency_p99=200ms, etc.)
- [x] Add `get_threshold_profile(scale_band, *, overrides)` function
- [x] Add `_validate_threshold_ordering(profile)` helper that checks critical < healthy for throughput thresholds

**Requirements:** R2 (Threshold Profiles), R3 (Dead Zone Elimination), R4 (Frontend Latency Scaling), R5 (Critical Threshold Scaling)

### Task 3: ThresholdOverrides model
- [x] Add `ThresholdOverrides` model to `packages/copilot/src/copilot/models/config.py` with all threshold fields as `float | None = None`
- [x] Add `_apply_overrides(profile, overrides)` helper that applies non-None fields to the profile
- [x] Validate ordering invariant after applying overrides; raise `ValueError` with descriptive message if violated
- [x] Add `threshold_overrides: ThresholdOverrides | None = None` field to `CopilotConfig`

**Requirements:** R6 (Threshold Profile Override)

### Task 4: Update evaluate_health_state() signature
- [x] Extend `evaluate_health_state()` in `packages/copilot/src/copilot/models/state_machine.py` with keyword-only params: `current_scale_band`, `deployment_context`, `overrides`
- [x] Change return type from `tuple[HealthState, int]` to `tuple[HealthState, int, ScaleBand]`
- [x] When no explicit threshold objects are provided, classify scale band and use the corresponding profile
- [x] When explicit threshold objects ARE provided (backward compat), use them and still return the classified scale band
- [x] Preserve consecutive_critical_count across scale band changes (R7.4)
- [x] Update all existing callers of `evaluate_health_state()` to handle the new 3-tuple return

**Requirements:** R7 (Transition Invariant Preservation)

### Task 5: Update bottleneck classifier for scale awareness
- [x] Add keyword params `persistence_latency_p95_threshold` and `backlog_age_threshold` to `_is_server_stressed()` in `packages/copilot/src/copilot/models/state_machine.py`
- [x] Update `classify_bottleneck()` to accept optional `scale_band` param, derive profile, and pass thresholds to `_is_server_stressed()`
- [x] Default values preserve current behavior (100.0 and 30.0)

**Requirements:** R8 (Bottleneck Classifier Scale Awareness)

## Layer 2: Deployment Profiles

### Task 6: Deployment models in copilot_core
- [x] Create `packages/copilot_core/src/copilot_core/deployment.py`
- [x] Add `AutoscalerType` StrEnum (karpenter, hpa, fixed)
- [x] Add `ServiceResourceLimits` model (cpu_millicores, memory_mib — both `int | None`)
- [x] Add `ServiceScalingBounds` model (min_replicas, max_replicas, resource_limits)
- [x] Add Pydantic validator on `ServiceScalingBounds`: min_replicas ≤ max_replicas
- [x] Add `ScalingTopology` model (history, matching, frontend, worker, autoscaler_type)
- [x] Add `ResourceIdentity` model (dsql_endpoint, platform_identifier, platform_type literal, amp_workspace_id)
- [x] Add `DeploymentProfile` model (preset_name, throughput_range_min/max, scaling_topology, resource_identity, config_profile_id — last three optional with None)
- [x] Export all from `copilot_core` package `__init__.py`

**Requirements:** R9 (Deployment Profile Model)

### Task 7: DeploymentAdapter protocol and discovery
- [x] Add `DEPLOYMENT_ADAPTER_GROUP = "temporal_dsql.deployment_adapters"` to `packages/dsql_config/src/dsql_config/adapters/__init__.py`
- [x] Add `DeploymentAdapter` protocol with `platform`, `name`, `render_deployment(profile, annotations) -> DeploymentProfile`
- [x] Add `discover_deployment_adapters()` function following the same pattern as `discover_platform_adapters()`
- [x] Import `DeploymentProfile` from `copilot_core.deployment` (TYPE_CHECKING guard)

**Requirements:** R11 (Deployment Adapter Protocol)

### Task 8: ECS Deployment Adapter
- [x] Add `ECSDeploymentAdapter` class to `packages/dsql_config/src/dsql_config/adapters/ecs.py`
- [x] Implement `render_deployment()` that builds `ScalingTopology` from annotations (per-service desired/min/max counts, cpu, memory)
- [x] Implement `render_deployment()` that builds `ResourceIdentity` from annotations (ecs_cluster_arn, dsql_endpoint, amp_workspace_id)
- [x] Add `_build_service_bounds(annotations, service, topology_defaults)` helper
- [x] Log warning when max_replicas < topology default for any service (R10.3)
- [x] Register entry point in `packages/dsql_config/pyproject.toml` under `temporal_dsql.deployment_adapters`

**Requirements:** R10 (Deployment Profile Creation), R12 (ECS Deployment Adapter)

### Task 9: Compose Deployment Adapter
- [x] Add `ComposeDeploymentAdapter` class to `packages/dsql_config/src/dsql_config/adapters/compose.py`
- [x] Implement `render_deployment()` with fixed replicas (min=max=1), autoscaler_type=FIXED
- [x] Extract resource limits from annotations when present, None when absent
- [x] Build `ResourceIdentity` with platform_type="compose", platform_identifier from compose_project_name
- [x] Register entry point in `packages/dsql_config/pyproject.toml` under `temporal_dsql.deployment_adapters`

**Requirements:** R13 (Compose Deployment Adapter)

## Layer 3: Dynamic Inspection

### Task 10: DeploymentContext models in copilot_core
- [x] Add `ServiceReplicaState` model to `packages/copilot_core/src/copilot_core/deployment.py` (running, desired, pending, cpu_utilization_pct, memory_utilization_pct)
- [x] Add `AutoscalerState` model (min_capacity, max_capacity, desired_capacity, actively_scaling)
- [x] Add `DSQLConnectionState` model (current_connections, max_connections, connections_per_service)
- [x] Add `DeploymentContext` model (history, matching, frontend, worker as ServiceReplicaState; autoscaler, dsql optional; timestamp as ISO 8601 str)
- [x] Export all from `copilot_core` package `__init__.py`

**Requirements:** R15 (Deployment Context Model)

### Task 11: PlatformInspector protocol and discovery
- [x] Create `packages/copilot/src/copilot/inspectors/__init__.py`
- [x] Add `PLATFORM_INSPECTOR_GROUP = "temporal_copilot.platform_inspectors"` constant
- [x] Add `PlatformInspector` protocol with `platform`, `name`, `async inspect(identity) -> DeploymentContext | None`
- [x] Add `discover_platform_inspectors()` function following the adapter discovery pattern
- [x] Import types from `copilot_core.deployment` under TYPE_CHECKING guard

**Requirements:** R16 (Platform Inspector Protocol)

### Task 12: ECS Platform Inspector
- [x] Create `packages/copilot/src/copilot/inspectors/ecs.py`
- [x] Implement `ECSInspector` class with `async inspect(identity) -> DeploymentContext | None`
- [x] Query ECS DescribeServices for running/desired/pending counts per Temporal service
- [x] Query CloudWatch Container Insights for CPU/memory utilization
- [x] Query Application Auto Scaling for min/max/desired capacity and scaling state
- [x] Query CloudWatch DSQL metrics for connection count/limit
- [x] Return None on any exception (graceful fallback)
- [x] Use IAM credentials from the Copilot's task role (no additional config)
- [x] Register entry point in `packages/copilot/pyproject.toml` under `temporal_copilot.platform_inspectors`

**Requirements:** R17 (ECS Platform Inspector)

### Task 13: Compose Platform Inspector
- [x] Create `packages/copilot/src/copilot/inspectors/compose.py`
- [x] Implement `ComposeInspector` class with `async inspect(identity) -> DeploymentContext | None`
- [x] Query Docker Engine API via Unix socket (`/var/run/docker.sock`) or DOCKER_HOST env var
- [x] List containers matching Temporal service name convention (temporal-dsql-history, etc.)
- [x] Get container stats for CPU/memory utilization
- [x] Set autoscaler state to fixed (min=max=current, actively_scaling=False)
- [x] Extract DSQL endpoint and max connections from container env vars
- [x] Return None if Docker Engine API is not accessible
- [x] Register entry point in `packages/copilot/pyproject.toml` under `temporal_copilot.platform_inspectors`

**Requirements:** R18 (Compose Platform Inspector)

### Task 14: refine_thresholds() function
- [x] Add `refine_thresholds(profile, context) -> ThresholdProfile` to `packages/copilot/src/copilot/models/state_machine.py`
- [x] Add `_get_default_history_replicas(scale_band) -> int` helper (starter=2, mid-scale=6, high-throughput=8)
- [x] Compute ratio of actual/default History replicas, clamp to [0.5, 2.0]
- [x] Skip tightening when autoscaler is actively scaling (grace period)
- [x] Adjust persistence_latency_p99, history_backlog_age_stress, history_backlog_age_healthy inversely to capacity ratio
- [x] Return original profile unchanged when actual or default replicas are 0
- [x] Validate threshold ordering after refinement; fall back to original profile if violated

**Requirements:** R21 (Deployment Context Threshold Refinement)

### Task 15: fetch_deployment_context activity
- [x] Create `packages/copilot/src/copilot/activities/inspect.py`
- [x] Add `FetchDeploymentContextInput` Pydantic model with `resource_identity: ResourceIdentity`
- [x] Implement `fetch_deployment_context` activity with `@activity.defn`
- [x] Discover platform inspectors, find matching platform type, call inspect()
- [x] Return None if no inspector available or if inspector returns None
- [x] Log warning on None result, log info when no inspector for platform type
- [x] Register activity in the worker's activity list

**Requirements:** R19 (Fetch Deployment Context Activity)

### Task 16: Update ObserveClusterWorkflow
- [x] Add `_current_scale_band`, `_deployment_context`, `_cycles_since_context_fetch`, `_context_fetch_interval` to `__init__` in `packages/copilot/src/copilot/workflows/observe.py`
- [x] Add deployment context fetch every 10 cycles (5 minutes) in the observation loop
- [x] Add `resource_identity` and `threshold_overrides` fields to `ObserveClusterInput` model (optional, None default)
- [x] Update `evaluate_health_state()` call to pass `current_scale_band`, `deployment_context`, `overrides` and unpack 3-tuple return
- [x] Add `@workflow.query` for `deployment_context` and `current_scale_band`
- [x] Cache deployment context between fetches; use None gracefully when unavailable

**Requirements:** R20 (Deployment Context Integration in ObserveClusterWorkflow)

## Cross-Cutting

### Task 17: Behaviour Profile integration
- [x] Add `deployment_context: DeploymentContext | None = None` field to `BehaviourProfile` in `packages/behaviour_profiles/src/behaviour_profiles/models.py`
- [x] Add `deployment_profile: DeploymentProfile | None = None` field to `ConfigSnapshot`
- [x] Add `DeploymentDiff` model (service, field, old_value, new_value)
- [x] Add `deployment_diffs: list[DeploymentDiff] = []` field to `ProfileComparison`
- [x] Update comparison logic in `packages/behaviour_profiles/src/behaviour_profiles/comparison.py` to include deployment topology diffs
- [x] Import `DeploymentProfile` and `DeploymentContext` from `copilot_core.deployment`

**Requirements:** R22 (Package Boundary Compliance), R23 (Behaviour Profile Integration)

### Task 18: Serialization round-trip validation
- [x] Add `DeploymentProfile` and `DeploymentContext` to existing serialization tests in `tests/test_serialization.py`
- [x] Verify backward compat: JSON without new fields deserializes with None defaults
- [x] Verify `BehaviourProfile` with None deployment_context deserializes correctly
- [x] Verify `ConfigSnapshot` with None deployment_profile deserializes correctly
- [x] Verify `ProfileComparison` with empty deployment_diffs deserializes correctly

**Requirements:** R14 (Deployment Profile Serialization), R23.4 (Backward Compatibility)

### Task 19: Property-based tests
- [x] Create `tests/properties/test_scale_aware_thresholds.py`
- [x] Add Hypothesis strategies: `primary_signals_strategy`, `deployment_profile_strategy`, `deployment_context_strategy`, `service_replica_state_strategy`, `autoscaler_state_strategy`, `dsql_connection_state_strategy` (extend `tests/properties/strategies.py` if shared)
- [x] Property 1: Transition invariant across all scale bands — HAPPY never goes directly to CRITICAL
- [x] Property 2: Threshold ordering invariant — critical.state_transitions_min ≤ healthy.state_transitions_healthy for all bands
- [x] Property 3: Idle cluster is HAPPY regardless of scale band
- [x] Property 4: Dead zone elimination — 1-10 st/sec with zero errors and ≥0.85 completion rate evaluates as HAPPY under starter
- [x] Property 5: Scale band classification is pure — same inputs always produce same output
- [x] Property 6: DeploymentProfile serialization round-trip
- [x] Property 7: DeploymentContext serialization round-trip
- [x] Property 8: Threshold refinement preserves all invariants (transition, ordering, determinism)
- [x] Property 9: Backward compatibility — deployment_context=None produces identical results to omitting the parameter

**Requirements:** R24 (Property Test Coverage)

### Task 20: Unit tests
- [x] Create `tests/test_scale_aware_thresholds.py`
- [x] Test the motivating scenario: 2 wf/s dev cluster with 367ms persistence p99 evaluates as HAPPY
- [x] Test starter profile values match design minimums (R2.2-R2.4)
- [x] Test high-throughput profile matches current production defaults (R2.5)
- [x] Test hysteresis at 50 st/sec boundary (oscillating 45-55 doesn't flap)
- [x] Test hysteresis at 500 st/sec boundary (oscillating 450-550 doesn't flap)
- [x] Test invalid override rejected with ValueError
- [x] Test Compose adapter produces fixed replicas (min=max=1, autoscaler=fixed)
- [x] Test ECS adapter populates ResourceIdentity correctly
- [x] Test refinement: more replicas → tighter thresholds
- [x] Test refinement: fewer replicas → looser thresholds
- [x] Test refinement grace period during active scaling
- [x] Test consecutive_critical_count preserved across scale band change
- [x] Test bottleneck classifier uses relaxed thresholds under starter band

**Requirements:** R1-R8, R12, R13, R21

### Task 21: Workflow integration tests
- [x] Extend `tests/test_workflow_sandbox.py` with scale-band-aware ObserveClusterWorkflow test
- [x] Test deployment context is fetched every 10 cycles and cached between fetches
- [x] Test workflow falls back to throughput-only evaluation when no inspector available
- [x] Verify new workflow input fields (resource_identity, threshold_overrides) serialize through Temporal data converter

**Requirements:** R19, R20

### Task 22: Entry point registration
- [x] Add `temporal_dsql.deployment_adapters` entry points to `packages/dsql_config/pyproject.toml` for ecs and compose
- [x] Add `temporal_copilot.platform_inspectors` entry points to `packages/copilot/pyproject.toml` for ecs and compose
- [x] Run `uv sync` to update the lockfile
- [x] Verify adapter and inspector discovery works with `discover_deployment_adapters()` and `discover_platform_inspectors()`

**Requirements:** R11, R16


## Layer 4: Deployment Profile Loading

### Task 23: Profile loader module
- [x] Create `packages/copilot/src/copilot/profile_loader.py`
- [x] Implement `load_deployment_profile(location: str) -> DeploymentProfile` that dispatches on `s3://` prefix
- [x] Implement `_load_from_file(path)` using `Path.read_text()` + `DeploymentProfile.model_validate_json()`
- [x] Implement `_load_from_s3(uri)` using boto3 `get_object` + `DeploymentProfile.model_validate_json()`
- [x] Log preset name, platform type, and DSQL endpoint on successful load
- [x] Raise `FileNotFoundError` for missing local files, `ValueError` for invalid JSON

**Requirements:** R25 (Deployment Profile Location)

### Task 24: Update ObserveClusterInput
- [x] Replace `resource_identity_json: str | None` and `threshold_overrides_json: str | None` with `deployment_profile: DeploymentProfile | None = None` on `ObserveClusterInput`
- [x] Update `ObserveClusterWorkflow.run()` to extract `ResourceIdentity` from `deployment_profile.resource_identity`
- [x] Derive initial scale band from `deployment_profile.preset_name` when available (map preset name to ScaleBand)
- [x] Update all callers and tests that reference the old fields
- [x] Verify Temporal data converter serialization with the new field

**Requirements:** R28 (ObserveClusterInput Simplification)

### Task 25: Update worker startup
- [x] Read `DEPLOYMENT_PROFILE` env var in `worker.py`
- [x] Call `load_deployment_profile()` when set, pass result to `ObserveClusterInput`
- [x] Remove `RESOURCE_IDENTITY_JSON` and `THRESHOLD_OVERRIDES_JSON` env var handling
- [x] Update worker docstring with new env var documentation
- [x] Log loaded profile details at startup

**Requirements:** R25 (Deployment Profile Location)

### Task 26: Compose deployment adapter config resolution
- [x] Update `ComposeDeploymentAdapter.render_deployment()` to accept resolved YAML (from `docker compose config`) as an annotation or direct input
- [x] Parse the resolved YAML to extract service definitions, replica counts, resource limits, and DSQL endpoint from interpolated env vars
- [x] Add `--compose-config` flag to the Config Compiler `compile` command that pipes `docker compose config` output to the Compose adapter
- [x] Support accepting resolved YAML from stdin (for `docker compose config | temporal-dsql-config compile ...`)
- [x] Remove any compose file parsing from `ComposeInspector` — inspector only queries Docker API for runtime state
- [x] Remove `compose_file` field from `ResourceIdentity` if it was added

**Requirements:** R26 (Compose Config Resolution)

### Task 27: Config Compiler --emit-deployment-profile
- [x] Add `--emit-deployment-profile` option to the `compile` command in `dsql_config/cli.py`
- [x] Add `--adapter` option to select the deployment adapter (ecs, compose)
- [x] Add `--annotation` repeatable option for key=value pairs passed to the adapter
- [x] Invoke `DeploymentAdapter.render_deployment()` with the compiled profile and annotations
- [x] Write the resulting `DeploymentProfile` JSON to the specified path (or stdout with `-`)
- [x] Validate the emitted JSON round-trips through `DeploymentProfile.model_validate_json()`

**Requirements:** R27 (Config Compiler Profile Emit)

### Task 28: Dev Compose integration
- [x] Generate `dev/deployment-profile.json` using the config compiler with starter preset + compose adapter
- [x] Update `dev/docker-compose.yml` copilot-worker to mount and reference the profile file
- [x] Remove `RESOURCE_IDENTITY_JSON` env var from copilot-worker service
- [x] Keep Docker socket mount (needed for live container stats, not config discovery)
- [x] Update `dev/.env.example` to remove any RESOURCE_IDENTITY references
- [x] Update README Quick start to reflect the new flow

**Requirements:** R25, R26, R27

### Task 29: Tests for profile loading
- [x] Unit test: load from local file (valid JSON, invalid JSON, missing file)
- [x] Unit test: load from S3 URI (mock boto3)
- [x] Unit test: ObserveClusterInput with DeploymentProfile serializes through Temporal data converter
- [x] Unit test: worker startup with DEPLOYMENT_PROFILE env var
- [x] Unit test: Compose deployment adapter parses resolved YAML from `docker compose config`
- [x] Unit test: Compose inspector does NOT attempt to parse compose files (only Docker API)
- [x] Property test: any valid DeploymentProfile written to file and loaded back is equivalent

**Requirements:** R25, R26, R28
