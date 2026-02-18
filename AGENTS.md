# Temporal SRE Copilot

AI-powered observability agent for Temporal deployments on Aurora DSQL. Uses Pydantic AI workflows on a separate Temporal cluster to observe signals, derive health state, and expose assessments via JSON API for Grafana.

The repo also ships a Config Compiler (`dsql-config`) that collapses hundreds of Temporal + DSQL configuration parameters into ~15 surfaced inputs, and a Behaviour Profile API (`behaviour-profiles`) that snapshots running clusters for comparison and drift detection. These form a feedback loop with the Copilot.

## Workspace Architecture

The repo is a uv workspace monorepo with four packages under `packages/`. The workspace root `pyproject.toml` is NOT a package — it only declares `[tool.uv] workspace = { members = ["packages/*"] }`.

### Dependency Graph (strict DAG, no cycles)

```
copilot_core (shared types, no internal deps)
    ▲           ▲           ▲
    │           │           │
dsql_config  behaviour_profiles  │
    ▲           ▲           │
    │           │           │
    └───────────┴───── copilot (orchestrator)
```

- `copilot_core` — Shared foundation: `ParameterClassification`, `MetricAggregate`, `TelemetryBound`, `VersionType`, signal taxonomy
- `dsql_config` — Config compiler, parameter registry, presets, guard rails, adapters, CLI
- `behaviour_profiles` — Profile models, storage (S3 + DSQL), telemetry collection (AMP), comparison, FastAPI router
- `copilot` — Orchestrator: Temporal workflows, Pydantic AI agents, FastAPI app (mounts profile router), drift detection, conformance assessment

**Critical constraint:** `dsql_config` does NOT depend on `behaviour_profiles`. They only share types through `copilot_core`.

## Copilot Architecture

The Copilot runs as a Temporal worker on its own cluster, observing a monitored Temporal+DSQL cluster via AMP (Amazon Managed Prometheus) and Loki. It follows the "Rules Decide, AI Explains" principle: health state is determined by deterministic rules, the LLM only explains.

```
Monitored Cluster (Temporal + DSQL)
        │
        ├── AMP ──► ObserveClusterWorkflow (30s cycle)
        │               ├── evaluate_health_state() [deterministic]
        │               └── AssessHealthWorkflow [LLM explains]
        │
        ├── Loki ──► LogWatcherWorkflow (30s cycle)
        │
        └── ScheduledAssessmentWorkflow (5min cycle)
                        │
                        ▼
                   FastAPI JSON API ──► Grafana
```

### Key Principles

1. **"Rules Decide, AI Explains"** — The Health State Machine uses deterministic rules to evaluate primary signals and set health state. The LLM receives the state and explains/ranks issues — it never decides state transitions or applies thresholds.

2. **Forward Progress Invariant** — Health is derived from one question: "Is the cluster making forward progress on workflows?"

3. **Signal Taxonomy** — Primary signals (12) decide state, amplifier signals (14) explain why, narrative signals (logs) explain transitions.

4. **"Grafana Consumes, Not Computes"** — All computation happens in the Copilot. Grafana only displays pre-computed values from the JSON API.

5. **Pydantic Models Everywhere** — Every workflow input and every activity input is a single Pydantic model. No bare positional args. This ensures Temporal's PydanticAIPlugin handles serialization correctly.

## Config Compiler Architecture

The Config Compiler classifies every Temporal + DSQL parameter into SLO, Topology, Safety, or Tuning. Adopters only see SLO (required) and Topology (optional with defaults) — Safety and Tuning are auto-derived.

- **Parameter Registry** (`dsql_config/registry.py`) is the single source of truth. Every parameter is registered with classification, default derivation logic, rationale string, and guard rail constraints. Presets compose over the registry; they don't duplicate parameter definitions.
- **Scale Presets** (`dsql_config/presets.py`) — starter, mid-scale, high-throughput. Primary dimensions: state transitions/sec and workflow completion rates.
- **Workload Modifiers** (`dsql_config/modifiers.py`) — simple-crud, orchestrator, batch-processor, long-running. Adjust preset defaults for specific workflow patterns.
- **Guard Rails** (`dsql_config/guard_rails.py`) — Validation rules that prevent unsafe configurations. All errors/warnings reported before halting.
- **Adapters** (`dsql_config/adapters/`) — Protocol-based with `importlib.metadata.entry_points()` discovery. SDK adapters (Go, Python) and platform adapters (ECS, Compose) are registered in `dsql_config`'s `pyproject.toml`.
- **Explain** (`dsql_config/explain.py`) — Three levels of deterministic, template-based explanation. No LLM involvement. Uses registry metadata and compilation trace data.
- **CLI** (`dsql_config/cli.py`) — Typer entry point: `temporal-dsql-config compile|list-presets|describe-preset|explain`

## Behaviour Profile Architecture

Profiles are stored in S3 (full JSON document) with metadata indexed in DSQL (for listing, filtering, baseline designation). This keeps DSQL row sizes small.

- **Models** (`behaviour_profiles/models.py`) — BehaviourProfile, ConfigSnapshot, TelemetrySummary (throughput, latency, matching, DSQL pool, errors, resources), ProfileComparison, ConfigDiff, TelemetryDiff, VersionDiff
- **Storage** (`behaviour_profiles/storage.py`) — S3 for full profile JSON, DSQL for metadata queries
- **Telemetry** (`behaviour_profiles/telemetry.py`) — Queries Amazon Managed Prometheus for curated metric aggregates (min, max, mean, p50, p95, p99)
- **Comparison** (`behaviour_profiles/comparison.py`) — Config diff, telemetry diff (with configurable regression thresholds), version diff. Ordered by severity.
- **API** (`behaviour_profiles/api.py`) — FastAPI router mounted by the copilot at `/profiles/*`

The Copilot uses profiles for drift detection (compare current telemetry against baseline), drift correlation (config changes correlated with telemetry regressions), and preset conformance assessment (telemetry within expected bounds).

## Project Structure

```
temporal-sre-copilot/
├── pyproject.toml                  # workspace root (NOT a package)
├── uv.lock                         # single lockfile
├── packages/
│   ├── copilot_core/               # shared types, no internal deps
│   │   └── src/copilot_core/
│   │       ├── types.py            # ParameterClassification, enums, models
│   │       ├── versions.py         # VersionType (packaging.version + Pydantic)
│   │       ├── signals.py          # Signal taxonomy
│   │       └── models.py           # TelemetryBound, MetricAggregate, ServiceMetrics
│   │
│   ├── dsql_config/                # config compiler + CLI
│   │   └── src/dsql_config/
│   │       ├── registry.py         # ParameterRegistry
│   │       ├── compiler.py         # ConfigCompiler
│   │       ├── guard_rails.py      # GuardRailEngine
│   │       ├── presets.py          # Scale presets
│   │       ├── modifiers.py        # Workload modifiers
│   │       ├── explain.py          # 3-level explain
│   │       ├── models.py           # ConfigProfile, CompilationResult, ScalePreset
│   │       ├── cli.py              # Typer CLI
│   │       └── adapters/           # Protocols, discovery, Go, Python, ECS, Compose
│   │
│   ├── behaviour_profiles/         # profile store + API
│   │   └── src/behaviour_profiles/
│   │       ├── models.py           # BehaviourProfile, TelemetrySummary, comparison models
│   │       ├── comparison.py       # ProfileComparison logic
│   │       ├── storage.py          # S3 + DSQL storage
│   │       ├── telemetry.py        # AMP query
│   │       └── api.py              # FastAPI router (/profiles/*)
│   │
│   └── copilot/                    # orchestrator
│       └── src/copilot/
│           ├── workflows/          # Temporal workflows (4)
│           ├── activities/         # I/O: AMP, Loki, RAG, state store
│           ├── agents/             # Pydantic AI: dispatcher + researcher
│           ├── models/             # Signal taxonomy, state machine, config
│           ├── db/                 # DSQL schema (includes profile_metadata table)
│           ├── cli/                # Typer CLI (copilot db, copilot kb)
│           ├── api.py              # FastAPI app (mounts profile router)
│           └── worker.py           # Worker entry point
│
├── tests/                          # shared test directory
│   ├── properties/                 # Hypothesis property-based tests
│   │   ├── test_config_compiler.py
│   │   ├── test_behaviour_profiles.py
│   │   ├── test_state_machine.py
│   │   └── test_bottleneck.py
│   ├── test_presets.py
│   ├── test_guard_rails.py
│   ├── test_adapters.py
│   ├── test_backward_compat.py
│   ├── test_profile_api.py
│   ├── test_serialization.py
│   └── test_workflow_sandbox.py
│
├── terraform/                      # Modular infrastructure
├── grafana/                        # Dashboards
├── docs/rag/                       # RAG corpus
└── Dockerfile                      # Multi-stage build (Python 3.14)
```

## Tech Stack

- Python 3.14, uv, ruff, ty
- Pydantic AI + Temporal (PydanticAIPlugin for durable execution)
- FastAPI for JSON API + Profile API
- Claude Sonnet 4.5 (dispatcher), Claude Opus 4.6 (researcher)
- Aurora DSQL for state store (asyncpg + IAM auth)
- Bedrock Knowledge Base for RAG
- `whenever` for all date/time handling (UTC-first, Rust-backed)
- Hypothesis for property-based tests

## Development Workflow

The project uses:

- [`uv`](https://docs.astral.sh/uv/) as the package manager (Python 3.14)
- [`ruff`](https://docs.astral.sh/ruff/) for linting and formatting
- [`ty`](https://docs.astral.sh/ty/) for type checking
- [`pytest`](https://docs.pytest.org/) with `hypothesis` for property-based tests
- [`just`](https://just.systems/) as the task runner

All QA checks should pass before committing:

```bash
just check-all    # lint + test + type check
```

Individual commands:

```bash
just install      # sync virtualenv
just lint         # ruff check + ruff format
just test         # pytest (156 tests, ~10s)
just typing       # ty check
```

## Working Agreements

### Code Style

- Modern, idiomatic Python 3.14 — use `X | None` not `Optional[X]`, f-strings, walrus operator where it helps
- Extract helpers at 2+ call sites, inline single-use helpers unless they reduce significant complexity
- Comments explain WHY, not WHAT — code should be self-documenting through naming
- Simplify nested conditionals: use `and`/`or` for compound conditions, `elif` for mutual exclusion
- Use `set` for unique collections; convert to `list` only for API boundaries
- Prefix internal helpers with `_`
- Use `*` to make optional params keyword-only after 1-2 essential positional args

### Package Boundaries

- Shared types (`ParameterClassification`, `MetricAggregate`, `TelemetryBound`, `VersionType`) live in `copilot_core`
- `dsql_config` does NOT depend on `behaviour_profiles` — they only share types through `copilot_core`
- New shared models go in `copilot_core.types` or `copilot_core.models`
- Version fields use `packaging.version.Version` via `copilot_core.versions.VersionType`
- Tests live at workspace root in `tests/` and import from all packages

### Date/Time

All date and time operations use the `whenever` library:

```python
from whenever import Instant, TimeDelta

now = Instant.now()
one_hour_ago = now - TimeDelta(hours=1)
```

Never use `datetime` directly. Use `Instant` for points in time, `TimeDelta` for durations. All timestamps are UTC. Serialize to ISO 8601 for JSON.

### Pydantic Models for Temporal

Every workflow takes a single Pydantic `BaseModel` as input. Every activity takes a single Pydantic `BaseModel` as input. No bare positional args — this ensures PydanticAIPlugin handles serialization correctly through Temporal's data converter.

```python
# CORRECT: Single Pydantic model input
class FetchSignalsInput(BaseModel):
    amp_endpoint: str

@activity.defn
async def fetch_signals(input: FetchSignalsInput) -> Signals: ...

# WRONG: Bare positional args
@activity.defn
async def fetch_signals(amp_endpoint: str) -> Signals: ...
```

### Health State Machine

The state machine is deterministic. Only primary signals decide state — amplifiers explain WHY later. The LLM never decides state transitions.

```python
# CORRECT
health_state = evaluate_health_state(signals.primary, current_state)
explanation = await llm.explain(health_state, signals)

# WRONG
health_state = await llm.determine_health(signals)
```

State transitions: `Happy → Stressed → Critical`. No direct `Happy → Critical`.

### Config Compiler Conventions

- The Parameter Registry is the single source of truth — presets compose over it, never duplicate definitions
- Guard rails collect all errors/warnings before halting on errors
- Adapters implement `SDKAdapter` or `PlatformAdapter` protocols and are discovered via entry points
- Explain output is deterministic and template-based — no LLM involvement
- All explain methods support both text and JSON output via `.to_text()` / `.to_json()`

### Behaviour Profile Conventions

- Full profile JSON stored in S3, metadata indexed in DSQL
- Telemetry metrics stored as `MetricAggregate` (min, max, mean, p50, p95, p99)
- Profile comparison diffs ordered by severity (largest regressions first)
- Time range validation: max 24 hours per profile
- Baseline designation replaces previous baseline for the same cluster + namespace

### Type Safety

- Use `ty check` (not pyright or mypy) for type checking
- No unnecessary `cast`s or `Any`s
- Use `assert_never()` for exhaustive union handling
- Use `TYPE_CHECKING` imports only for circular dependencies — Pydantic models need runtime imports

### Testing

- Property-based tests with Hypothesis for invariants (state machine, bottleneck, config compiler, profiles)
- Serialization round-trip tests for all Pydantic models
- Workflow sandbox tests for Temporal data converter compatibility
- Property tests live in `tests/properties/`
- Run with `just test` or `uv run -m pytest`
- Cover success and failure cases
- Use `require`-style assertions (pytest `assert`)

### Linting and Formatting

- `ruff check` for linting (rules: E, F, I, UP, B, SIM, TCH)
- `ruff format` for formatting (double quotes, 100 char line length)
- `ty check` for type checking
- All three must pass before committing

### Infrastructure

- Terraform in `terraform/` references dependent resources from `temporal-dsql-deploy-ecs` via `terraform.tfvars`
- CLI uses Typer + Rich for terminal output
- RAG corpus in `docs/rag/` excludes raw metrics/PromQL (those belong in code)

## Spec Reference

Full requirements, design, and tasks:

- `.kiro/specs/temporal-sre-copilot/` — Copilot spec (requirements, design, tasks)
- `.kiro/specs/enhance-config-ux/` — Config Compiler + Behaviour Profiles spec (requirements, design, tasks)
