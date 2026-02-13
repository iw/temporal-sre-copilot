# Temporal SRE Copilot - Implementation Guide

## Project Overview

AI-powered observability agent for Temporal deployments on Aurora DSQL. Uses Pydantic AI workflows on a separate Temporal cluster to observe signals, derive health state, and expose assessments via JSON API for Grafana.

## Spec Reference

Full requirements, design, and tasks are in:
- `.kiro/specs/temporal-sre-copilot/requirements.md`
- `.kiro/specs/temporal-sre-copilot/design.md`
- `.kiro/specs/temporal-sre-copilot/tasks.md`

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

## Workflow Names

- `ObserveClusterWorkflow` - Continuous signal observation, evaluates health state
- `AssessHealthWorkflow` - LLM-powered explanation of health state
- `LogWatcherWorkflow` - Collects narrative signals from Loki
- `ScheduledAssessmentWorkflow` - Periodic assessments

## Project Structure

```
temporal-sre-copilot/
├── src/copilot/
│   ├── cli/           # Typer CLI (db, kb commands)
│   ├── workflows/     # Temporal workflows
│   ├── activities/    # I/O operations
│   ├── agents/        # Pydantic AI agents
│   ├── models/        # Pydantic models
│   └── db/            # DSQL schema
├── terraform/         # Copilot infrastructure
└── tests/             # Property and unit tests
```

## Tech Stack

- Python 3.14+, uv, ruff, ty
- Pydantic AI + Temporal
- FastAPI for JSON API
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
- Property tests use Hypothesis
- RAG corpus excludes raw metrics/PromQL (those belong in code)
