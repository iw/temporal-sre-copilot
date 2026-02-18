# Temporal SRE Copilot - Implementation Guide

## Project Overview

AI-powered observability agent for Temporal deployments on Aurora DSQL. Uses Pydantic AI workflows on a separate Temporal cluster to observe signals, derive health state, and expose assessments via JSON API for Grafana.

The repo is a uv workspace monorepo with four packages: `copilot_core` (shared types), `dsql_config` (config compiler + CLI), `behaviour_profiles` (profile store + API), and `copilot` (orchestrator). The Copilot is the principal product; Config Compiler and Behaviour Profiles are supporting capabilities that form a feedback loop with it.

## Spec Reference

- `.kiro/specs/temporal-sre-copilot/` — Copilot spec (requirements, design, tasks)
- `.kiro/specs/enhance-config-ux/` — Config Compiler + Behaviour Profiles spec (requirements, design, tasks)

## Workspace Architecture

```
copilot_core (shared types, no internal deps)
    ▲           ▲           ▲
    │           │           │
dsql_config  behaviour_profiles  │
    ▲           ▲           │
    └───────────┴───── copilot (orchestrator)
```

- `dsql_config` does NOT depend on `behaviour_profiles` — they only share types through `copilot_core`
- Shared types (`ParameterClassification`, `MetricAggregate`, `TelemetryBound`, `VersionType`) live in `copilot_core`
- Tests live at workspace root in `tests/` and import from all packages

## Core Architectural Principles

### 1. "Rules Decide, AI Explains"

The Health State Machine uses **deterministic rules** to evaluate signals and set health state. The LLM receives the state and explains/ranks issues—it **never decides state transitions or applies thresholds**.

```python
# CORRECT: Rules decide
health_state = evaluate_health_state(signals)  # Deterministic
explanation = await llm.explain(health_state, signals)  # AI explains

# WRONG: AI decides
health_state = await llm.determine_health(signals)  # Never do this
```

### 2. Forward Progress Invariant

Health is derived from one question: **"Is the cluster making forward progress on workflows?"**

- Primary signals (state transitions, completions) answer this question
- Amplifiers explain WHY progress may be impaired
- High latency alone ≠ Critical; high latency WITH impaired progress = Critical

### 3. Signal Taxonomy

| Category | Purpose | Examples |
|----------|---------|----------|
| **Primary** | Decide health state | State transitions/sec, backlog age, completion rate |
| **Amplifiers** | Explain why | DSQL latency, OCC conflicts, pool utilization |
| **Narrative** | Logs explain transitions | "reservoir discard", "SQLSTATE 40001" |

### 4. Health State Machine

```
Happy → Stressed → Critical
  ↑         ↓         ↓
  └─────────┴─────────┘
```

- **Happy**: Forward progress healthy, no concerning amplifiers
- **Stressed**: Progress continues but amplifiers indicate pressure
- **Critical**: Forward progress is impaired or stopped
- **Invariant**: Never transition directly Happy → Critical

### 5. "Grafana Consumes, Not Computes"

All computation happens in the Copilot. Grafana only displays pre-computed values from the JSON API.

### 6. Parameter Registry is the Single Source of Truth

Every configuration parameter is registered in `dsql_config/registry.py` with classification, default derivation logic, rationale string, and guard rail constraints. Presets compose over the registry; they don't duplicate parameter definitions.

### 7. Explain is Deterministic

All three explain levels (key, preset, profile) use template-based rendering from structured metadata. No LLM involvement. The parameter registry's rationale strings and the compilation trace provide all the data needed.

## Workflow Names

- `ObserveClusterWorkflow` - Continuous signal observation, evaluates health state
- `AssessHealthWorkflow` - LLM-powered explanation of health state
- `LogWatcherWorkflow` - Collects narrative signals from Loki
- `ScheduledAssessmentWorkflow` - Periodic assessments

## Project Structure

```
temporal-sre-copilot/
├── pyproject.toml                  # workspace root (NOT a package)
├── packages/
│   ├── copilot_core/src/copilot_core/   # shared types
│   ├── dsql_config/src/dsql_config/     # config compiler + CLI
│   ├── behaviour_profiles/src/behaviour_profiles/  # profile store + API
│   └── copilot/src/copilot/            # orchestrator
├── tests/                          # shared test directory
│   └── properties/                 # Hypothesis property-based tests
├── terraform/                      # Copilot infrastructure
├── grafana/                        # Dashboards
└── docs/rag/                       # RAG corpus
```

## Tech Stack

- Python 3.14+, uv, ruff, ty
- Pydantic AI + Temporal
- FastAPI for JSON API + Profile API
- Claude Sonnet 4.5 (dispatcher), Claude Opus 4.6 (researcher)
- Aurora DSQL for state store
- Bedrock Knowledge Base for RAG
- `whenever` for all date/time handling (UTC-first, Rust-backed)

## Date/Time Handling

All date and time operations use the `whenever` library (https://github.com/ariebovenberg/whenever):

```python
# CORRECT: Use whenever
from whenever import Instant, TimeDelta

now = Instant.now()
one_hour_ago = now - TimeDelta(hours=1)

# WRONG: Don't use datetime directly
from datetime import datetime, timedelta  # Never do this
```

- Use `Instant` for points in time
- Use `TimeDelta` for durations
- All timestamps are UTC
- Serialize to ISO 8601 for JSON

## Implementation Notes

- CLI uses Typer + Rich for elegant terminal output
- Terraform references dependent resources from `temporal-dsql-deploy-ecs` via `terraform.tfvars`
- Property tests use Hypothesis (156 tests, ~10s)
- RAG corpus excludes raw metrics/PromQL (those belong in code)
- Adapters are protocol-based with `importlib.metadata.entry_points()` discovery
- Guard rails collect all errors/warnings before halting on errors
- Profile JSON stored in S3, metadata indexed in DSQL
