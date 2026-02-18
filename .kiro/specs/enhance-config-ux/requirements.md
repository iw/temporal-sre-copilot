# Requirements Document

## Introduction

The Temporal DSQL offering presents adopters with an overwhelming configuration surface: Temporal's own dynamic config (hundreds of keys), per-service static config, Go SDK worker options, and 30+ DSQL plugin-specific environment variables (reservoir, rate limiter, token cache, slot blocks, connection pool). This spec addresses two interconnected projects:

1. **Simplified Configuration Product** — Collapse the configuration surface into ~10–15 surfaced parameters organized by a parameter classification system (SLO, Topology, Safety, Tuning). A "compiler" takes a named scale preset plus optional overrides, applies guard rails, and produces validated configuration artifacts (dynamic config YAML, per-service environment variables, worker option snippets, DSQL plugin defaults). Everything the adopter doesn't explicitly choose is derived.

2. **Behaviour Profiles** — Snapshot a time window of a running Temporal DSQL deployment (configuration + curated telemetry + version metadata) and label it as a named "behaviour profile". These profiles enable comparison ("healthy @ 150 WPS" vs "failed @ 400 WPS"), drift detection, and config validation through the SRE Copilot.

The two projects form a feedback loop: behaviour profiles validate that simplified presets produce the expected telemetry bounds, and the Copilot can recommend preset changes when observed behaviour drifts from the profile baseline.

### Tooling and Technology Constraints

The configuration product (Config_Compiler, CLI, SDK and Platform adapters) is built with Python 3.14+ and uses `uv` as the package manager. This aligns with the existing temporal-sre-copilot and tdeploy CLI tech stack, enabling shared libraries and a consistent developer experience across the tooling surface.

## Glossary

- **Config_Compiler**: The component that takes a Scale_Preset selection plus optional overrides, applies Guard_Rails, and produces output artifacts via pluggable adapters (dynamic config YAML, environment variable map, worker option snippet, DSQL plugin config)
- **SDK_Adapter**: A pluggable output generator that produces worker option configuration for a specific Temporal client SDK language (e.g., Go SDK, Python SDK); the Config_Compiler delegates worker option generation to the registered SDK_Adapter
- **Platform_Adapter**: A pluggable output generator that produces deployment-specific configuration artifacts for a target platform (e.g., AWS ECS task definitions, AWS EKS Helm values, Docker Compose service definitions); the Config_Compiler delegates deployment artifact generation to the registered Platform_Adapter
- **Scale_Preset**: A named configuration bundle reflecting the scale of the deployment (e.g., "starter", "mid-scale", "high-throughput"); the primary dimensions for composing presets are state transitions per second and workflow completion rates
- **Parameter_Classification**: The categorization of every configuration parameter into one of four buckets: SLO, Topology, Safety, or Tuning
- **SLO_Parameter**: A configuration parameter that adopters choose because it reflects service-level objectives (e.g., target WPS, max schedule-to-start latency, max end-to-end workflow latency)
- **Topology_Parameter**: A configuration parameter that adopters sometimes choose based on deployment shape (e.g., shard count, history replicas, matching partitions, number of workers)
- **Safety_Parameter**: A configuration parameter that is fixed or auto-derived because incorrect values cause operational failures (e.g., DSQL rate limiting, reservoir warm-up strategy, token refresh jitter)
- **Tuning_Parameter**: A configuration parameter that is never exposed to adopters; derived from SLO and Topology parameters (e.g., internal batch sizes, sticky timeout, forwarder outstanding, reservoir refill cadence)
- **Guard_Rail**: A validation rule that prevents unsafe or contradictory configuration combinations, emitting errors or warnings with explanations
- **Config_Profile**: A fully resolved configuration produced by the Config_Compiler from a Scale_Preset plus optional overrides; represents a complete, validated set of configuration values across all parameter categories
- **Behaviour_Profile**: A time-bounded bundle containing identity metadata, a configuration snapshot, curated telemetry aggregates, and optional artifacts (trace exemplars, log samples) for a specific cluster, namespace, and task queue selection
- **Profile_API**: The FastAPI endpoints on the SRE Copilot that create, list, compare, and retrieve Behaviour_Profiles
- **Telemetry_Summary**: A curated, downsampled set of time-series aggregates for a fixed metric list, stored as part of a Behaviour_Profile
- **Profile_Comparison**: A structured diff between two Behaviour_Profiles highlighting configuration changes, telemetry regressions, and anomalies
- **Baseline_Profile**: A Behaviour_Profile designated as the reference point for drift detection and anomaly identification
- **Config_Explain**: A deterministic, template-based explanation capability operating at three levels: single parameter (registry metadata), preset (reasoning chain from SLO targets to resolved values), and compiled profile (full composition trace including overrides and guard rail activations)

## Requirements

### Requirement 1: Parameter Classification

**User Story:** As a Temporal DSQL platform engineer, I want every configuration parameter classified into a clear bucket so that adopters only see the parameters they should actually touch.

#### Acceptance Criteria

1. THE Config_Compiler SHALL classify every configuration parameter (Temporal dynamic config, worker options, DSQL plugin environment variables) into exactly one Parameter_Classification: SLO, Topology, Safety, or Tuning
2. THE Config_Compiler SHALL expose SLO_Parameters as required adopter inputs (target WPS, max schedule-to-start latency, max end-to-end workflow latency)
3. THE Config_Compiler SHALL expose Topology_Parameters as optional adopter inputs with preset-provided defaults (shard count, history replicas, matching partitions, worker count)
4. THE Config_Compiler SHALL derive Safety_Parameters automatically from the chosen Scale_Preset and Topology_Parameter values (DSQL connection rate limiting, reservoir warm-up strategy, token refresh jitter, MaxIdleConns equal to MaxConns)
5. THE Config_Compiler SHALL derive Tuning_Parameters from SLO_Parameter and Topology_Parameter inputs without exposing the Tuning_Parameters to adopters (internal batch sizes, sticky timeout, forwarder outstanding, reservoir refill cadence)
6. THE Config_Compiler SHALL surface no more than 15 total parameters (SLO_Parameters plus Topology_Parameters combined) to adopters

### Requirement 2: Scale-Based Presets

**User Story:** As a Temporal DSQL adopter, I want to choose a named scale preset that matches my deployment's throughput requirements so that I get a complete, validated configuration without researching every parameter.

#### Acceptance Criteria

1. THE Config_Compiler SHALL provide named Scale_Presets that reflect server scale requirements, with the primary dimensions being state transitions per second and workflow completion rates
2. THE Config_Compiler SHALL provide a "starter" Scale_Preset targeting low-throughput deployments (under 50 state transitions per second) with conservative resource allocation
3. THE Config_Compiler SHALL provide a "mid-scale" Scale_Preset targeting moderate-throughput deployments (50 to 500 state transitions per second) with balanced resource allocation
4. THE Config_Compiler SHALL provide a "high-throughput" Scale_Preset targeting high-throughput deployments (over 500 state transitions per second) with aggressive resource allocation and full DSQL plugin features enabled
5. WHEN the "starter" Scale_Preset is selected, THE Config_Compiler SHALL produce defaults with reservoir disabled, pool size of 10, no distributed rate limiting, no slot blocks, and low persistence QPS limits
6. WHEN the "mid-scale" Scale_Preset is selected, THE Config_Compiler SHALL produce defaults with reservoir enabled, pool size of 50, per-instance rate limiting enabled, and moderate persistence QPS limits
7. WHEN the "high-throughput" Scale_Preset is selected, THE Config_Compiler SHALL produce defaults with reservoir enabled with target matching pool size, distributed rate limiting enabled, connection lifetime under 55 minutes, high matching partition counts, and aggressive persistence QPS limits

### Requirement 3: Workload Shape Modifiers

**User Story:** As a Temporal DSQL adopter, I want to describe the shape of my workloads so that the configuration is tuned for my specific workflow patterns on top of the scale preset.

#### Acceptance Criteria

1. THE Config_Compiler SHALL accept optional workload shape modifiers that adjust the Scale_Preset defaults: "simple-crud", "orchestrator", "batch-processor", and "long-running"
2. WHEN the "long-running" modifier is applied, THE Config_Compiler SHALL enable sticky execution caching and configure longer sticky schedule-to-start timeouts
3. WHEN the "batch-processor" modifier is applied, THE Config_Compiler SHALL configure higher matching partition counts and increased concurrent activity execution limits
4. WHEN the "simple-crud" modifier is applied, THE Config_Compiler SHALL enable eager activity execution and configure lower matching partition counts
5. WHEN the "orchestrator" modifier is applied, THE Config_Compiler SHALL configure balanced matching partitions, moderate concurrent workflow task execution limits, and child workflow dispatch settings

### Requirement 4: Configuration Compilation

**User Story:** As a Temporal DSQL adopter, I want the system to produce all required configuration artifacts from my preset and overrides so that I do not maintain separate files by hand.

#### Acceptance Criteria

1. WHEN a Scale_Preset and optional overrides are provided, THE Config_Compiler SHALL produce a Temporal dynamic config YAML file containing all server-side settings
2. WHEN a Scale_Preset and optional overrides are provided, THE Config_Compiler SHALL delegate deployment artifact generation to the registered Platform_Adapter (e.g., ECS task definition environment variables, EKS Helm values, Docker Compose service definitions)
3. WHEN a Scale_Preset and optional overrides are provided, THE Config_Compiler SHALL delegate worker option generation to the registered SDK_Adapter (e.g., Go SDK concurrency and poller settings, Python SDK worker configuration)
4. WHEN a Scale_Preset and optional overrides are provided, THE Config_Compiler SHALL produce a DSQL plugin configuration section covering reservoir, rate limiter, token cache, slot block, and connection pool settings
5. WHEN an adopter provides an override for a parameter, THE Config_Compiler SHALL apply the override on top of the preset-derived default for that parameter
6. THE Config_Compiler SHALL include a "why" section in the output explaining the rationale for key derived values and the reasoning chain from the Scale_Preset to final values

### Requirement 4a: SDK Adapter Extension Points

**User Story:** As a platform engineer supporting multiple Temporal client SDK languages, I want the config compiler to support pluggable SDK adapters so that I can generate worker configuration for Go, Python, and future SDK languages without modifying the core compiler.

#### Acceptance Criteria

1. THE Config_Compiler SHALL define an SDK_Adapter interface that accepts a resolved Config_Profile and produces SDK-specific worker option configuration
2. THE Config_Compiler SHALL ship with a Go SDK_Adapter that produces Go SDK worker option snippets (concurrency limits, poller counts, cache settings, eager activity settings)
3. THE Config_Compiler SHALL ship with a Python SDK_Adapter that produces Python SDK worker configuration (max concurrent activities, max concurrent workflow tasks, poller settings)
4. WHEN a new SDK_Adapter is registered, THE Config_Compiler SHALL use the registered adapter without requiring changes to the core compilation logic
5. THE SDK_Adapter interface SHALL accept the resolved Config_Profile and return a structured output containing the SDK-specific configuration and a human-readable snippet

### Requirement 4b: Platform Adapter Extension Points

**User Story:** As a platform engineer deploying Temporal on different infrastructure targets, I want the config compiler to support pluggable platform adapters so that I can generate deployment artifacts for ECS, EKS, and future platforms without modifying the core compiler.

#### Acceptance Criteria

1. THE Config_Compiler SHALL define a Platform_Adapter interface that accepts a resolved Config_Profile and produces platform-specific deployment artifacts
2. THE Config_Compiler SHALL ship with an AWS ECS Platform_Adapter that produces per-service environment variable maps suitable for ECS task definitions
3. THE Config_Compiler SHALL ship with a Docker Compose Platform_Adapter that produces per-service environment variable maps suitable for Docker Compose service definitions
4. WHEN a new Platform_Adapter is registered, THE Config_Compiler SHALL use the registered adapter without requiring changes to the core compilation logic
5. THE Platform_Adapter interface SHALL accept the resolved Config_Profile and return a structured output containing per-service deployment configuration

### Requirement 5: Configuration Guard Rails

**User Story:** As a Temporal DSQL adopter, I want the system to catch unsafe or contradictory configuration before I deploy so that I avoid runtime failures.

#### Acceptance Criteria

1. WHEN the total reservoir_target across all expected replicas implies more than 10,000 cluster connections, THE Config_Compiler SHALL fail compilation with an error explaining the DSQL connection limit
2. WHEN matching partitions are configured higher than the expected task throughput can utilize, THE Config_Compiler SHALL emit a warning suggesting a smaller partition count
3. WHEN sticky execution is enabled but the typical workflow runtime is under 2 seconds, THE Config_Compiler SHALL emit a warning that sticky caching provides minimal benefit
4. WHEN the DSQL connection rate configuration combined with MaxConnLifetime of 55 minutes would cause a thundering herd at rotation time, THE Config_Compiler SHALL enforce jittered rotation and emit an explanation
5. WHEN MaxIdleConns does not equal MaxConns in the resolved configuration, THE Config_Compiler SHALL fail compilation with an error explaining that pool decay causes rate limit pressure under load
6. WHEN reservoir is enabled but reservoir target is set to zero, THE Config_Compiler SHALL fail compilation with an error explaining that reservoir target must be positive when reservoir is enabled
7. WHEN distributed rate limiting is enabled but no DynamoDB table name is configured, THE Config_Compiler SHALL fail compilation with an error identifying the missing table name
8. IF any Guard_Rail produces an error, THEN THE Config_Compiler SHALL report all Guard_Rail errors and warnings before halting compilation

### Requirement 6: Configuration Serialization

**User Story:** As a developer, I want to serialize and deserialize profile configurations so that I can store, compare, and test them programmatically.

#### Acceptance Criteria

1. THE Config_Compiler SHALL serialize a complete resolved Config_Profile (all parameter values across all categories plus the input Scale_Preset and overrides) to JSON
2. THE Config_Compiler SHALL deserialize a JSON representation back into a resolved Config_Profile
3. FOR ALL valid resolved Config_Profiles, serializing to JSON then deserializing SHALL produce an equivalent Config_Profile (round-trip property)
4. THE Config_Compiler SHALL serialize a complete resolved Config_Profile to YAML for human-readable inspection

### Requirement 7: Preset Discoverability

**User Story:** As a Temporal DSQL adopter, I want to explore available presets and inspect what each one configures so that I can make an informed choice.

#### Acceptance Criteria

1. THE Config_Compiler SHALL support a list-presets command that prints all available Scale_Presets with a one-line summary and the target throughput range for each
2. THE Config_Compiler SHALL support a describe-preset command that, given a Scale_Preset name and optional workload modifier, prints the complete set of resolved settings with the Parameter_Classification, resolved value, and a one-line rationale for each parameter
3. WHEN describe-preset is invoked, THE Config_Compiler SHALL group parameters by Parameter_Classification (SLO, Topology, Safety, Tuning)

### Requirement 8: Backward Compatibility

**User Story:** As an existing Temporal DSQL adopter, I want the new preset system to work alongside my current environment variable configuration so that I can migrate incrementally.

#### Acceptance Criteria

1. WHEN no Scale_Preset is explicitly provided and existing DSQL environment variables are present, THE Config_Compiler SHALL treat the existing environment variables as overrides on top of the "starter" Scale_Preset defaults
2. THE Config_Compiler SHALL accept all existing DSQL environment variable names without renaming or deprecation
3. WHEN an adopter migrates to preset-based configuration, THE Config_Compiler SHALL report which existing environment variables are redundant with the preset-derived defaults

### Requirement 9: Behaviour Profile Creation

**User Story:** As a Temporal DSQL operator, I want to snapshot a time window of my running cluster into a labelled behaviour profile so that I can reference it later for comparison and analysis.

#### Acceptance Criteria

1. WHEN a create-profile request is received with a time range, cluster identifier, and optional label, THE Profile_API SHALL create a Behaviour_Profile
2. THE Behaviour_Profile SHALL contain identity metadata: profile name, time window, cluster identifier, namespace and task queue selection, and version information (Temporal server version, DSQL plugin version, worker code git SHA)
3. THE Behaviour_Profile SHALL contain a configuration snapshot: effective Temporal dynamic config values, server environment variables (with secrets redacted), worker options, and DSQL plugin configuration
4. THE Behaviour_Profile SHALL contain a Telemetry_Summary with curated time-series aggregates for a fixed metric list covering throughput, latency, matching, DSQL pool health, errors, and resource utilization
5. THE Profile_API SHALL store the Behaviour_Profile JSON document in S3 with metadata indexed in DSQL
6. IF the requested time range exceeds 24 hours, THEN THE Profile_API SHALL reject the request with an error explaining the maximum window

### Requirement 10: Telemetry Summary Curation

**User Story:** As a Temporal DSQL operator, I want the behaviour profile to capture a curated set of telemetry aggregates so that I get meaningful signal without storing raw high-cardinality data.

#### Acceptance Criteria

1. THE Telemetry_Summary SHALL include throughput metrics: workflows started per second, workflows completed per second, state transitions per second
2. THE Telemetry_Summary SHALL include latency metrics: workflow schedule-to-start p95 and p99, activity schedule-to-start p95 and p99, persistence operation latency p95 and p99
3. THE Telemetry_Summary SHALL include matching metrics: sync match rate, async match rate, task dispatch latency, backlog count, backlog age
4. THE Telemetry_Summary SHALL include DSQL pool metrics: pool open count, pool in-use count, pool idle count, reservoir size, reservoir empty events, open failures, reconnect count
5. THE Telemetry_Summary SHALL include error metrics: OCC serialization conflicts per second, exhausted retries per second, DSQL auth failures
6. THE Telemetry_Summary SHALL include resource metrics: CPU and memory utilization per service, worker task slot utilization
7. THE Telemetry_Summary SHALL store each metric as min, max, mean, p50, p95, and p99 aggregates over the profile time window
8. THE Profile_API SHALL query Amazon Managed Prometheus to collect the Telemetry_Summary metrics for the specified time range

### Requirement 11: Behaviour Profile Retrieval and Listing

**User Story:** As a Temporal DSQL operator, I want to list and retrieve behaviour profiles so that I can find and inspect past snapshots.

#### Acceptance Criteria

1. THE Profile_API SHALL support listing all Behaviour_Profiles with filtering by cluster identifier, label, time range, and namespace
2. THE Profile_API SHALL support retrieving a single Behaviour_Profile by identifier, returning the complete JSON document
3. WHEN listing profiles, THE Profile_API SHALL return profile metadata (name, time window, cluster, label, creation timestamp) without the full telemetry data
4. THE Profile_API SHALL support designating a Behaviour_Profile as a Baseline_Profile for a given cluster and namespace combination

### Requirement 12: Behaviour Profile Comparison

**User Story:** As a Temporal DSQL operator, I want to compare two behaviour profiles so that I can understand what changed between a healthy baseline and a problematic period.

#### Acceptance Criteria

1. WHEN two Behaviour_Profile identifiers are provided, THE Profile_API SHALL produce a Profile_Comparison
2. THE Profile_Comparison SHALL include a configuration diff showing parameters that changed between the two profiles, with old and new values
3. THE Profile_Comparison SHALL include a telemetry diff showing metrics that regressed or improved beyond configurable thresholds (default: 20 percent change for latency, 50 percent change for error rates)
4. THE Profile_Comparison SHALL include a version diff showing changes in Temporal server version, DSQL plugin version, or worker code SHA
5. WHEN a Profile_Comparison is produced, THE Profile_API SHALL order the diffs by severity with the largest regressions first

### Requirement 13: Behaviour Profile Serialization

**User Story:** As a developer, I want to serialize and deserialize behaviour profiles so that I can store, transfer, and test them programmatically.

#### Acceptance Criteria

1. THE Profile_API SHALL serialize Behaviour_Profiles to JSON for storage in S3
2. THE Profile_API SHALL deserialize JSON documents from S3 back into Behaviour_Profile structures
3. FOR ALL valid Behaviour_Profiles, serializing to JSON then deserializing SHALL produce an equivalent Behaviour_Profile (round-trip property)

### Requirement 14: Grafana Integration for Profile Creation

**User Story:** As a Temporal DSQL operator, I want to create behaviour profiles directly from the Grafana dashboard by selecting a time range so that profile creation is integrated into my observability workflow.

#### Acceptance Criteria

1. THE Grafana Copilot dashboard SHALL include a "Create Behaviour Profile" action that sends the current dashboard time range to the Profile_API
2. WHEN the action is triggered, THE dashboard SHALL pass the time range, selected namespace variable, selected task queue variable, and an optional user-provided label to the Profile_API
3. WHEN a profile is successfully created, THE dashboard SHALL display a confirmation with the profile identifier and a link to view the profile
4. IF profile creation fails, THEN THE dashboard SHALL display the error message returned by the Profile_API

### Requirement 15: Copilot Integration for Profile Analysis

**User Story:** As a Temporal DSQL operator, I want the SRE Copilot to use behaviour profiles for drift detection and config recommendations so that I get actionable insights grounded in historical evidence.

#### Acceptance Criteria

1. WHEN the Copilot performs a health assessment, THE Copilot SHALL compare current telemetry against the active Baseline_Profile for the cluster and namespace
2. WHEN current telemetry deviates from the Baseline_Profile beyond configured thresholds, THE Copilot SHALL flag the deviation as drift in the health assessment
3. WHEN a Profile_Comparison reveals configuration changes correlated with telemetry regressions, THE Copilot SHALL include the correlation in the assessment explanation
4. THE Copilot SHALL support a "recommend config" action that, given a Behaviour_Profile showing problems, suggests Scale_Preset or override changes with evidence from the profile telemetry

### Requirement 16: Preset-to-Profile Validation Loop

**User Story:** As a Temporal DSQL platform engineer, I want to validate that a config preset produces the expected telemetry bounds so that I can certify preset configurations with evidence.

#### Acceptance Criteria

1. WHEN a Behaviour_Profile is associated with a Config_Profile (via matching Scale_Preset), THE Copilot SHALL compare the profile telemetry against expected bounds defined by the Scale_Preset
2. WHEN the telemetry falls within expected bounds, THE Copilot SHALL label the profile as "conforming" to the Scale_Preset
3. WHEN the telemetry deviates from expected bounds, THE Copilot SHALL label the profile as "drifted" and identify which metrics are out of range
4. THE Copilot SHALL support a query "does this profile match preset X" that returns a conformance assessment with per-metric pass or fail detail


### Requirement 17: Configuration Explain Capability

**User Story:** As a Temporal DSQL adopter, I want to ask "why is this value what it is" at multiple levels of detail so that I understand the reasoning behind my configuration without reading source code.

#### Acceptance Criteria

1. WHEN an adopter provides a specific configuration key (e.g., "history.transferActiveTaskQueueTimeout"), THE Config_Compiler SHALL emit the parameter purpose, its Parameter_Classification, the preset-derived value, and the rationale from the parameter registry
2. WHEN an adopter provides a Scale_Preset name and optional workload modifier, THE Config_Compiler SHALL emit a narrative explanation covering the assumed SLO targets, how Topology_Parameters are derived, which Safety_Parameters are locked and why, and the reasoning chain from preset inputs to resolved values
3. WHEN an adopter provides a compiled Config_Profile, THE Config_Compiler SHALL emit a full composition explanation covering the base Scale_Preset, all applied overrides, which Guard_Rails fired, and the derivation chain for each non-default value
4. THE Config_Compiler SHALL produce all explain output deterministically using template-based rendering from parameter registry metadata, preset metadata, and compilation trace data
5. THE Config_Compiler SHALL NOT use LLM generation for any explain output; all explanations SHALL be derived from structured metadata authored in the parameter registry and preset definitions
6. THE Config_Compiler SHALL support explain output in both human-readable text and structured JSON formats
