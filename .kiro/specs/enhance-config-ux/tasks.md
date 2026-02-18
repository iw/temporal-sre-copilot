# Implementation Plan: Enhanced Configuration UX

## Overview

Incremental implementation of the Config Compiler and Behaviour Profile API in `temporal-sre-copilot` as a uv workspace monorepo. Four packages under `packages/`: `copilot_core` (shared types), `dsql_config` (compiler + CLI), `behaviour_profiles` (profile store + API), and `copilot` (orchestrator). Each task builds on the previous, with property tests close to implementation to catch errors early.

## Tasks

- [x] 1. Set up workspace structure and copilot_core package
  - [x] 1.1 Scaffold uv workspace monorepo
    - Create workspace root `pyproject.toml` with `[tool.uv] workspace = { members = ["packages/*"] }`
    - Create `packages/copilot_core/pyproject.toml` with dependencies on `pydantic` and `packaging`
    - Create `packages/dsql_config/pyproject.toml` with dependency on `copilot-core` (workspace = true), `pydantic`, `typer`, `rich`, `pyyaml`
    - Create `packages/behaviour_profiles/pyproject.toml` with dependency on `copilot-core` (workspace = true), `pydantic`, `fastapi`, `asyncpg`, `aiobotocore`
    - Create `packages/copilot/pyproject.toml` with dependencies on all three workspace packages
    - Create `packages/copilot_core/src/copilot_core/__init__.py`
    - Create `packages/dsql_config/src/dsql_config/__init__.py`
    - Create `packages/behaviour_profiles/src/behaviour_profiles/__init__.py`
    - _Requirements: N/A (infrastructure)_

  - [x] 1.2 Implement copilot_core types and enums
    - Create `packages/copilot_core/src/copilot_core/types.py`
    - Implement `ParameterClassification`, `ParameterValueType`, `ParameterUnit`, `OutputTarget` StrEnums
    - Implement `ParameterConstraints`, `ParameterEntry`, `ResolvedParameter`, `ParameterOverrides` models
    - _Requirements: 1.1_

  - [x] 1.3 Implement copilot_core versions and shared models
    - Create `packages/copilot_core/src/copilot_core/versions.py` with `VersionType` annotated type (`packaging.version.Version` with Pydantic serializer/validator)
    - Create `packages/copilot_core/src/copilot_core/models.py` with `TelemetryBound`, `MetricAggregate`, `ServiceMetrics` models
    - _Requirements: 6.1, 10.7_

  - [x] 1.4 Implement Parameter Registry
    - Create `packages/dsql_config/src/dsql_config/registry.py`
    - Implement `ParameterRegistry` class with methods: `register()`, `get()`, `list_by_classification()`, `all_keys()`
    - Populate registry with all known Temporal dynamic config keys, DSQL plugin env vars, and worker options from the existing `development-dsql.yaml` and `.env.example`
    - Each entry must have classification, description, rationale, default_value, value_type, unit, constraints, and output_targets
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x]* 1.5 Write property test for parameter classification uniqueness
    - **Property 1: Parameter classification uniqueness**
    - **Validates: Requirements 1.1**

  - [x] 1.6 Implement ConfigProfile and compilation models
    - Create `packages/dsql_config/src/dsql_config/models.py`
    - Implement `ConfigProfile`, `CompilationTrace`, `DSQLPluginConfig`, `CompilationResult` models
    - Implement `ThroughputRange`, `PresetDefault`, `DerivationRule`, `ScalePreset` models
    - Import shared types from `copilot_core.types` and `copilot_core.versions`
    - _Requirements: 1.1, 4.1, 4.4_

  - [x]* 1.7 Write property test for Config_Profile serialization round-trip
    - **Property 10: Config_Profile serialization round-trip**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**

- [x] 2. Scale presets and workload modifiers
  - [x] 2.1 Implement scale presets
    - Create `packages/dsql_config/src/dsql_config/presets.py`
    - Define "starter", "mid-scale", and "high-throughput" ScalePreset instances with all SLO defaults, topology defaults, safety derivations, and tuning derivations
    - Starter: reservoir disabled, pool size 10, no distributed rate limiting
    - Mid-scale: reservoir enabled, pool size 50, per-instance rate limiting
    - High-throughput: reservoir enabled, distributed rate limiting, aggressive QPS limits
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 2.2 Implement workload modifiers
    - Create `packages/dsql_config/src/dsql_config/modifiers.py`
    - Define "simple-crud", "orchestrator", "batch-processor", "long-running" modifiers
    - Each modifier adjusts specific preset defaults (sticky caching, matching partitions, eager activities, etc.)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x]* 2.3 Write unit tests for preset and modifier outputs
    - Create `tests/test_presets.py`
    - Test each preset produces expected specific values (reservoir, pool size, rate limiting)
    - Test each modifier adjusts the correct parameters
    - _Requirements: 2.5, 2.6, 2.7, 3.2, 3.3, 3.4, 3.5_

  - [x]* 2.4 Write property test for exposed parameter count invariant
    - **Property 3: Exposed parameter count invariant**
    - **Validates: Requirements 1.6**

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Config Compiler core
  - [x] 4.1 Implement the compilation pipeline
    - Create `packages/dsql_config/src/dsql_config/compiler.py`
    - Implement `ConfigCompiler` class with `compile()` method
    - Pipeline: resolve preset defaults → apply modifier → apply overrides → derive safety params → derive tuning params → build ConfigProfile
    - Generate `CompilationTrace` for each parameter recording source and derivation chain
    - _Requirements: 4.1, 4.4, 4.5_

  - [x] 4.2 Implement guard rail engine
    - Create `packages/dsql_config/src/dsql_config/guard_rails.py`
    - Implement `GuardRailEngine` with `evaluate()` method
    - Implement all guard rails: connection limit (10k), matching partition warning, sticky warning, thundering herd, MaxIdleConns==MaxConns, reservoir target, DynamoDB table name
    - Compiler collects all errors/warnings before halting on errors
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [x] 4.3 Implement dynamic config YAML generation
    - Add `_emit_dynamic_config_yaml()` to compiler
    - Produce valid YAML from resolved dynamic config parameters in the registry
    - _Requirements: 4.1_

  - [x] 4.4 Implement "why" section generation
    - Add `_generate_why_section()` to compiler
    - Template-based rendering of rationale for key derived values
    - _Requirements: 4.6_

  - [x]* 4.5 Write property tests for compiler core
    - Create `tests/properties/test_config_compiler.py`
    - **Property 2: Derived parameter completeness**
    - **Property 4: Dynamic config YAML validity**
    - **Property 5: Override application**
    - **Property 6: Why section presence**
    - **Validates: Requirements 1.4, 1.5, 4.1, 4.5, 4.6**

  - [x]* 4.6 Write property tests for guard rails
    - **Property 8: MaxIdleConns equals MaxConns guard rail**
    - **Property 9: All guard rail errors reported**
    - **Validates: Requirements 5.5, 5.8**

  - [x]* 4.7 Write unit tests for guard rail edge cases
    - Create `tests/test_guard_rails.py`
    - Test each specific guard rail trigger condition (Requirements 5.1-5.7)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 5. Adapter plugin system
  - [x] 5.1 Implement adapter protocols and discovery
    - Create `packages/dsql_config/src/dsql_config/adapters/__init__.py`
    - Implement `SDKAdapter` and `PlatformAdapter` protocols with `@runtime_checkable`
    - Implement `RenderedSnippet` dataclass
    - Implement `discover_sdk_adapters()` and `discover_platform_adapters()` using `importlib.metadata.entry_points()`
    - _Requirements: 4a.1, 4a.4, 4b.1, 4b.4_

  - [x] 5.2 Implement Go SDK adapter
    - Create `packages/dsql_config/src/dsql_config/adapters/go_sdk.py`
    - Render Go SDK worker option snippets from ConfigProfile (concurrency limits, poller counts, cache settings, eager activity settings)
    - _Requirements: 4a.2_

  - [x] 5.3 Implement Python SDK adapter
    - Create `packages/dsql_config/src/dsql_config/adapters/python_sdk.py`
    - Render Python SDK worker configuration from ConfigProfile
    - _Requirements: 4a.3_

  - [x] 5.4 Implement ECS platform adapter
    - Create `packages/dsql_config/src/dsql_config/adapters/ecs.py`
    - Render per-service environment variable maps for ECS task definitions
    - _Requirements: 4b.2_

  - [x] 5.5 Implement Docker Compose platform adapter
    - Create `packages/dsql_config/src/dsql_config/adapters/compose.py`
    - Render per-service environment variable maps for Docker Compose service definitions
    - _Requirements: 4b.3_

  - [x] 5.6 Register built-in adapters in dsql_config pyproject.toml
    - Add `[project.entry-points."temporal_dsql.sdk_adapters"]` for Go and Python adapters
    - Add `[project.entry-points."temporal_dsql.platform_adapters"]` for ECS and Compose adapters
    - Wire adapter discovery into ConfigCompiler
    - _Requirements: 4a.4, 4b.4_

  - [x]* 5.7 Write property test for adapter output completeness
    - **Property 7: Adapter output completeness**
    - **Validates: Requirements 4a.5, 4b.5**

  - [x]* 5.8 Write unit tests for adapter outputs
    - Create `tests/test_adapters.py`
    - Snapshot tests for each adapter's rendered output
    - Test adapter discovery with mock entry points
    - _Requirements: 4a.2, 4a.3, 4b.2, 4b.3_

- [x] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Preset discoverability and backward compatibility
  - [x] 7.1 Implement list-presets and describe-preset
    - Add `list_presets()` and `describe_preset()` methods to `ConfigCompiler` in `packages/dsql_config/src/dsql_config/compiler.py`
    - `list_presets` returns PresetSummary with name, description, throughput range
    - `describe_preset` returns all resolved settings grouped by ParameterClassification
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 7.2 Implement backward compatibility with existing env vars
    - Add env var migration logic to ConfigCompiler
    - When no preset is provided, treat existing env vars as overrides on "starter"
    - Accept all existing DSQL env var names
    - Report which env vars are redundant with preset defaults
    - _Requirements: 8.1, 8.2, 8.3_

  - [x]* 7.3 Write property tests for discoverability and backward compat
    - **Property 11: Describe-preset completeness and grouping**
    - **Property 12: Redundant environment variable detection**
    - **Validates: Requirements 7.2, 7.3, 8.3**

  - [x]* 7.4 Write unit tests for backward compatibility
    - Create `tests/test_backward_compat.py`
    - Test env var fallback to starter preset
    - Test all known DSQL env var names are accepted
    - _Requirements: 8.1, 8.2_

- [x] 8. Configuration explain capability
  - [x] 8.1 Implement explain-key (Level 1)
    - Create `packages/dsql_config/src/dsql_config/explain.py`
    - Implement `explain_key()` returning KeyExplanation with purpose, classification, value, rationale from registry
    - Wire into ConfigCompiler
    - _Requirements: 17.1_

  - [x] 8.2 Implement explain-preset (Level 2)
    - Add `explain_preset()` to explain module
    - Template-based narrative covering SLO targets, topology derivation, locked safety params, reasoning chain
    - _Requirements: 17.2_

  - [x] 8.3 Implement explain-profile (Level 3)
    - Add `explain_profile()` to explain module
    - Uses CompilationTrace to explain full composition: base preset, overrides, guard rails, derivation chains
    - _Requirements: 17.3_

  - [x] 8.4 Implement dual output format (text + JSON)
    - All explain methods support both human-readable text and structured JSON output
    - _Requirements: 17.6_

  - [x]* 8.5 Write property tests for explain capability
    - **Property 22: Explain key completeness**
    - **Property 23: Explain preset completeness**
    - **Property 24: Explain profile completeness**
    - **Property 25: Explain determinism**
    - **Property 26: Explain dual format**
    - **Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.6**

- [x] 9. CLI integration
  - [x] 9.1 Wire Config Compiler into dsql_config CLI
    - Create `packages/dsql_config/src/dsql_config/cli.py` with Typer subcommands
    - Implement `temporal-dsql-config compile`, `temporal-dsql-config list-presets`, `temporal-dsql-config describe-preset`
    - Implement `temporal-dsql-config explain --key`, `temporal-dsql-config explain --preset`, `temporal-dsql-config explain --profile`
    - Support `--sdk`, `--platform`, `--modifier`, `--override` flags
    - Rich terminal output for all commands
    - Register CLI entry point in `packages/dsql_config/pyproject.toml` under `[project.scripts]`
    - _Requirements: 4.1, 7.1, 7.2, 17.1, 17.2, 17.3_

- [x] 10. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Behaviour Profile data models
  - [x] 11.1 Create profile data models
    - Create `packages/behaviour_profiles/src/behaviour_profiles/models.py`
    - Implement `BehaviourProfile`, `ConfigSnapshot`, `DynamicConfigEntry`, `EnvVarEntry`, `WorkerOptionsSnapshot`, `DSQLPluginSnapshot`
    - Implement `ProfileMetadata`, `CreateProfileRequest`, `CompareRequest`
    - Import `VersionType` from `copilot_core.versions`, `MetricAggregate` and `ServiceMetrics` from `copilot_core.models`
    - _Requirements: 9.2, 9.3_

  - [x] 11.2 Create telemetry summary models
    - Add to `packages/behaviour_profiles/src/behaviour_profiles/models.py`
    - Implement `TelemetrySummary`, `ThroughputMetrics`, `LatencyMetrics`, `MatchingMetrics`, `DSQLPoolMetrics`, `ErrorMetrics`, `ResourceMetrics`
    - Use `MetricAggregate` and `ServiceMetrics` from `copilot_core.models`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 11.3 Create profile comparison models
    - Add `ProfileComparison`, `ConfigDiff`, `TelemetryDiff`, `VersionDiff` to `packages/behaviour_profiles/src/behaviour_profiles/models.py`
    - Or create `packages/behaviour_profiles/src/behaviour_profiles/comparison.py` for comparison logic
    - _Requirements: 12.2, 12.3, 12.4_

  - [x]* 11.4 Write property test for Behaviour_Profile serialization round-trip
    - Create `tests/properties/test_behaviour_profiles.py`
    - **Property 18: Behaviour_Profile serialization round-trip**
    - **Validates: Requirements 13.1, 13.2, 13.3**

  - [x]* 11.5 Write property test for Telemetry_Summary completeness
    - **Property 14: Telemetry_Summary completeness**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7**

- [x] 12. Behaviour Profile API
  - [x] 12.1 Implement DSQL schema for profile metadata
    - Add profile metadata table to `packages/copilot/src/copilot/db/schema.sql`
    - Columns: id, name, label, cluster_id, namespace, task_queue, time_window_start, time_window_end, s3_key, is_baseline, created_at
    - _Requirements: 9.5_

  - [x] 12.2 Implement profile storage layer
    - Create `packages/behaviour_profiles/src/behaviour_profiles/storage.py`
    - Implement S3 storage for full profile JSON documents
    - Implement DSQL metadata queries (list, get, set baseline)
    - _Requirements: 9.5_

  - [x] 12.3 Implement AMP telemetry collection
    - Create `packages/behaviour_profiles/src/behaviour_profiles/telemetry.py`
    - Query Amazon Managed Prometheus for telemetry summary metrics
    - _Requirements: 9.4, 10.8_

  - [x] 12.4 Implement profile API endpoints
    - Create `packages/behaviour_profiles/src/behaviour_profiles/api.py` with FastAPI router
    - Implement `POST /profiles` — validate time range (max 24 hours), query AMP, store in S3 + DSQL
    - Implement `GET /profiles` with filtering by cluster, label, namespace, time range
    - Implement `GET /profiles/{profile_id}` returning full profile from S3
    - Implement `POST /profiles/{profile_id}/baseline` — set baseline flag
    - Implement `POST /profiles/compare` — compute config, telemetry, and version diffs
    - _Requirements: 9.1, 9.4, 9.5, 9.6, 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 12.5 Mount profile router in copilot API
    - Update `packages/copilot/src/copilot/api.py` to import and mount `behaviour_profiles.api.router`
    - _Requirements: 9.1_

  - [x]* 12.6 Write property tests for profile API
    - **Property 13: Behaviour_Profile completeness**
    - **Property 15: Profile listing correctness**
    - **Property 16: Profile retrieval identity**
    - **Property 17: Comparison completeness and ordering**
    - **Validates: Requirements 9.2, 9.3, 9.4, 11.1, 11.2, 11.3, 12.1, 12.2, 12.3, 12.4, 12.5**

  - [x]* 12.7 Write unit tests for profile API edge cases
    - Create `tests/test_profile_api.py`
    - Test 24-hour time range rejection
    - Test comparison with same profile ID rejection
    - Test baseline designation replaces previous baseline
    - _Requirements: 9.6, 12.1_

- [x] 13. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Copilot integration
  - [x] 14.1 Implement drift detection in health assessment
    - Extend health assessment workflow in `packages/copilot/src/copilot/workflows/` to compare current telemetry against active Baseline_Profile
    - Import from `behaviour_profiles` and `dsql_config` packages
    - Flag deviations beyond configured thresholds as drift
    - _Requirements: 15.1, 15.2_

  - [x] 14.2 Implement drift correlation
    - When Profile_Comparison shows config changes correlated with telemetry regressions, include correlation in assessment explanation
    - _Requirements: 15.3_

  - [x] 14.3 Implement preset conformance assessment
    - Add conformance check: compare Behaviour_Profile telemetry against Scale_Preset expected bounds
    - Label as "conforming" or "drifted" with per-metric pass/fail detail
    - Uses `TelemetryBound` from `copilot_core.models` and `ScalePreset` from `dsql_config.models`
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [x]* 14.4 Write property tests for Copilot integration
    - **Property 19: Drift detection**
    - **Property 20: Drift correlation**
    - **Property 21: Preset conformance assessment**
    - **Validates: Requirements 15.2, 15.3, 16.1, 16.2, 16.3, 16.4**

- [x] 15. Grafana integration
  - [x] 15.1 Add Grafana dashboard action for profile creation
    - Add "Create Behaviour Profile" action to Copilot Grafana dashboard
    - Pass time range, namespace, task queue, and optional label to Profile API
    - Display confirmation or error
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 16. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- All code lives in `temporal-sre-copilot` as a uv workspace monorepo — `temporal-dsql-deploy` only consumes compiled artifacts
- Shared types (`ParameterClassification`, `MetricAggregate`, `TelemetryBound`, `VersionType`) live in `copilot_core` to keep the dependency graph acyclic
- `dsql_config` does NOT depend on `behaviour_profiles` — they only share types through `copilot_core`
- Tests live at workspace root in `tests/` and import from all packages
