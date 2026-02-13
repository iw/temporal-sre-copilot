# Temporal SRE Copilot

AI-powered observability agent for Temporal deployments on Aurora DSQL. Uses Pydantic AI workflows on a separate Temporal cluster to observe signals, derive health state, and expose assessments via JSON API for Grafana.

## Architecture

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

## Project Structure

```
temporal-sre-copilot/
├── src/copilot/
│   ├── activities/         # I/O operations (AMP, Loki, RAG, DSQL)
│   ├── agents/             # Pydantic AI agents (dispatcher, researcher)
│   ├── cli/                # Typer CLI (db, kb commands)
│   ├── db/                 # DSQL schema
│   ├── models/             # Pydantic models
│   │   ├── signals.py      # Primary + amplifier + worker signals
│   │   ├── assessment.py   # HealthAssessment, Issue, SuggestedAction
│   │   ├── state_machine.py # Deterministic health evaluation
│   │   ├── config.py       # Threshold configuration
│   │   ├── api_responses.py # FastAPI response models
│   │   ├── workflow_inputs.py  # Workflow input models
│   │   └── activity_inputs.py # Activity input models
│   ├── workflows/          # Temporal workflows
│   │   ├── observe.py      # ObserveClusterWorkflow
│   │   ├── log_watcher.py  # LogWatcherWorkflow
│   │   ├── assess.py       # AssessHealthWorkflow
│   │   └── scheduled.py    # ScheduledAssessmentWorkflow
│   ├── api.py              # FastAPI JSON API for Grafana
│   ├── worker.py           # Worker entrypoint (starts workflows on boot)
│   ├── starter.py          # Standalone workflow starter
│   └── temporal.py         # Client/worker factory with PydanticAIPlugin
├── tests/
│   └── properties/         # Hypothesis property-based tests
├── docs/rag/               # RAG corpus for Bedrock Knowledge Base
├── grafana/                # Grafana dashboard JSON
├── terraform/              # Copilot infrastructure (ECS, IAM, KB)
├── Dockerfile              # Multi-stage build with uv
├── Justfile                # Development task runner
└── pyproject.toml          # Project config
```

## Tech Stack

- Python 3.14, uv, ruff, ty
- Pydantic AI + Temporal (PydanticAIPlugin for durable execution)
- FastAPI for JSON API
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
just test         # pytest
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

# In workflow:
signals = await workflow.execute_activity(
    fetch_signals,
    FetchSignalsInput(amp_endpoint=endpoint),
    start_to_close_timeout=...,
)

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

### Type Safety

- Use `ty check` (not pyright or mypy) for type checking
- No unnecessary `cast`s or `Any`s
- Use `assert_never()` for exhaustive union handling
- Use `TYPE_CHECKING` imports only for circular dependencies — Pydantic models need runtime imports

### Testing

- Property-based tests with Hypothesis for invariants (state machine, bottleneck classification)
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

- `.kiro/specs/temporal-sre-copilot/requirements.md`
- `.kiro/specs/temporal-sre-copilot/design.md`
- `.kiro/specs/temporal-sre-copilot/tasks.md`
