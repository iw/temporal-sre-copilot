# Temporal SRE Copilot

AI-powered observability agent for Temporal deployments on Aurora DSQL. Runs as a separate Temporal cluster using Pydantic AI workflows to continuously observe signals, derive health state from forward progress, and expose assessments via a JSON API for Grafana.

## How It Works

The Copilot answers one question: **"Is the cluster making forward progress on workflows?"**

A deterministic Health State Machine evaluates 26 signals and sets health state. An LLM then explains what's happening and suggests remediations — it never decides state.

```
Signals → Health State Machine (deterministic) → State + Signals → LLM → Explanation
```

### Health States

```
Happy → Stressed → Critical
  ↑         ↓         ↓
  └─────────┴─────────┘
```

- **Happy** — Forward progress healthy, no concerning amplifiers
- **Stressed** — Progress continues but amplifiers indicate pressure
- **Critical** — Forward progress is impaired or stopped

The machine enforces an invariant: Happy → Critical must pass through Stressed first, preventing over-eager critical alerts.

### Signal Taxonomy

| Category | Count | Purpose | Examples |
|----------|-------|---------|----------|
| Primary | 12 | Decide health state | State transitions/sec, backlog age, completion rate |
| Amplifiers | 14 | Explain why | DSQL latency, OCC conflicts, pool utilization |
| Narrative | — | Logs explain transitions | "reservoir discard", "SQLSTATE 40001" |
| Worker | 6 | Worker-side health | Schedule-to-start latency, task slots, pollers |

### Multi-Agent Architecture

Two Pydantic AI agents follow the "Rules decide, AI explains" principle:

- **Dispatcher** (Claude Sonnet 4.5) — Fast triage (~1-2s). Decides explanation depth, not health state.
- **Researcher** (Claude Opus 4.6) — Deep explanation (~10-20s). Produces ranked contributing factors, suggested remediations with confidence scores, and natural language summaries.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  COPILOT ECS CLUSTER (Same VPC)                 │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ Temporal Server   │  │ Copilot Worker   │  │ API Service  │  │
│  │ (single-binary)   │  │ (Pydantic AI)    │  │ (FastAPI)    │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘  │
│           └─────────────────────┼────────────────────┘          │
│                                 │                               │
│  ┌──────────────────────────────▼────────────────────────────┐  │
│  │                    DSQL STATE STORE                        │  │
│  │  health_assessments · issues · metrics_snapshots           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 BEDROCK KNOWLEDGE BASE                     │  │
│  │  S3 source bucket · Titan Embeddings V2 · S3 Vectors     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   Amazon Managed       Amazon Bedrock           Loki
   Prometheus           (Claude)                 (Logs)
         │
         ▼
      Grafana
```

The Copilot cluster runs in the same VPC as the monitored Temporal deployment but on separate ECS infrastructure. A failure in the Copilot cannot impact production.

## Workflows

| Workflow | Purpose | Cadence |
|----------|---------|---------|
| `ObserveClusterWorkflow` | Continuous signal observation, evaluates health state | Every 30s |
| `LogWatcherWorkflow` | Collects narrative signals from Loki | Every 30s |
| `AssessHealthWorkflow` | LLM-powered explanation of health state | On state change |
| `ScheduledAssessmentWorkflow` | Periodic assessments even when healthy | Every 5 min |

## Project Structure

```
temporal-sre-copilot/
├── src/copilot/
│   ├── cli/               # Typer CLI (db, kb commands)
│   ├── workflows/         # Temporal workflows (4)
│   ├── activities/        # I/O: AMP, Loki, RAG, state store
│   ├── agents/            # Pydantic AI: dispatcher + researcher
│   ├── models/            # Signal taxonomy, state machine, config
│   │   ├── signals.py     # Primary + amplifier + worker signals
│   │   ├── assessment.py  # HealthAssessment, Issue, SuggestedAction
│   │   ├── state_machine.py # Deterministic health evaluation
│   │   ├── config.py      # Threshold configuration
│   │   ├── api_responses.py # FastAPI response models
│   │   ├── workflow_inputs.py  # Workflow input models
│   │   └── activity_inputs.py # Activity input models
│   ├── db/                # DSQL schema
│   ├── api.py             # FastAPI JSON API for Grafana
│   ├── worker.py          # Worker entry point
│   ├── starter.py         # Workflow starter
│   └── temporal.py        # Client + worker setup
├── terraform/             # Modular infrastructure
│   ├── modules/           # Reusable modules
│   │   ├── ecs-cluster/   # Cluster, namespace, log groups
│   │   ├── ec2-capacity/  # Launch template, ASG, capacity provider
│   │   ├── iam/           # Execution, task, and Bedrock KB roles
│   │   ├── networking/    # Security group and rules
│   │   ├── knowledge-base/# S3 Vectors, Bedrock KB, data source
│   │   └── copilot-service/ # Generic ECS service (worker, API, temporal)
│   └── envs/
│       ├── bench/         # Bench environment config
│       └── dev/           # Dev environment config (cost-optimized)
├── grafana/               # Copilot dashboard + provisioning
├── docs/rag/              # RAG corpus (worker scaling, cache tuning)
├── tests/                 # Serialization, sandbox, property tests (Hypothesis)
├── Dockerfile             # Multi-stage build (Python 3.14)
└── pyproject.toml
```

## Tech Stack

- Python 3.14+, [uv](https://docs.astral.sh/uv/), ruff
- [Pydantic AI](https://ai.pydantic.dev/) + [Temporal Python SDK](https://docs.temporal.io/develop/python)
- FastAPI for JSON API
- Claude Sonnet 4.5 (dispatcher) / Claude Opus 4.6 (researcher) via Amazon Bedrock
- Aurora DSQL for state store (asyncpg)
- Bedrock Knowledge Base for RAG (Titan Embeddings V2, S3 Vectors)
- [whenever](https://github.com/ariebovenberg/whenever) for UTC-first date/time handling
- Typer + Rich for CLI

## Quick Start

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- AWS CLI configured with appropriate permissions
- Terraform 1.0+
- A running `temporal-dsql-deploy-ecs` deployment (provides AMP, Loki, DSQL, VPC)

### Install

```bash
cd temporal-sre-copilot
uv sync
```

### CLI

```bash
# Database operations
copilot db check-connection    # Test DSQL connectivity
copilot db setup-schema        # Apply DSQL schema
copilot db list-tables         # Show tables and row counts

# Knowledge base operations
copilot kb sync                # Upload docs to S3
copilot kb start-ingestion     # Trigger KB ingestion job
copilot kb status              # Check KB or job status
copilot kb list-jobs           # List recent ingestion jobs
```

### Run Locally

```bash
# Start the worker (processes workflows)
python -m copilot.worker

# Start the API (JSON API for Grafana)
uvicorn copilot.api:app --host 0.0.0.0 --port 8080

# Start workflows
python -m copilot.starter
```

### Deploy

For ECS deployment (bench/prod):

```bash
cd terraform/envs/bench
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with values from temporal-dsql-deploy-ecs

terraform init
terraform plan
terraform apply
```

For local development with Docker Compose, the Copilot's DSQL cluster and Bedrock KB are provisioned from `temporal-dsql-deploy/terraform/copilot/` instead. See the [copilot profile README](../temporal-dsql-deploy/profiles/copilot/README.md) for the full local setup workflow.

### Docker

```bash
docker build -t temporal-sre-copilot .

# Worker
docker run temporal-sre-copilot

# API
docker run -p 8080:8080 temporal-sre-copilot uvicorn copilot.api:app --host 0.0.0.0 --port 8080
```

## JSON API

The API follows the "Grafana consumes, not computes" principle — all computation happens in the Copilot, Grafana only displays pre-computed values.

| Endpoint | Description |
|----------|-------------|
| `GET /status` | Current health state with full signal taxonomy |
| `GET /status/services` | Per-service health status |
| `GET /status/issues` | Active issues with contributing factors |
| `GET /status/summary` | Natural language summary |
| `GET /status/timeline` | Health state changes over time |
| `POST /actions` | Future remediation (501 Not Implemented) |

Example response from `/status`:

```json
{
  "health_state": "stressed",
  "primary_signals": {
    "state_transitions": { "throughput_per_sec": 182 },
    "history": { "backlog_age_sec": 47 }
  },
  "amplifiers": {
    "persistence": { "dsql_latency_p99_ms": 92, "occ_conflicts_per_sec": 38 }
  },
  "log_patterns": [
    { "count": 128, "pattern": "reservoir discard", "service": "history" }
  ],
  "recommended_actions": [
    { "action": "scale history", "confidence": 0.71 }
  ]
}
```

## Grafana Dashboard

The Copilot dashboard includes:

- **Advisor panel** — Status badge (Happy/Stressed/Critical), confidence score, natural language summary
- **Status filter** — Toggle by health state to filter the entire dashboard
- **Copilot Insights** — Two-column layout: analysis bullet points + suggested remediations with confidence %
- **Signal Metrics** — Key metrics with sparklines
- **Log Pattern Alerts** — Occurrence count, pattern description, affected service

Auto-refreshes every 30 seconds. Links to Server Health, DSQL Persistence, and Workers dashboards.

## Bottleneck Classification

The Copilot classifies bottlenecks to distinguish "server can't keep up" from "workers can't keep up":

| Classification | Condition |
|----------------|-----------|
| Server-limited | High backlog age, persistence latency; workers idle |
| Worker-limited | Slots exhausted, high schedule-to-start; server backlog low |
| Mixed | Both server and workers under pressure |
| Healthy | Neither constrained |

Worker evaluation only runs when the server is Happy or Stressed — if the server is Critical, worker advice is irrelevant.

## Related

- [`temporal-dsql-deploy-ecs`](../temporal-dsql-deploy-ecs/) — Production ECS deployment (provides AMP, Loki, DSQL, VPC)
- [Spec: requirements](.kiro/specs/temporal-sre-copilot/requirements.md)
- [Spec: design](.kiro/specs/temporal-sre-copilot/design.md)
- [Spec: tasks](.kiro/specs/temporal-sre-copilot/tasks.md)

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

This project was developed with significant assistance from [Kiro](https://kiro.dev), an AI-powered IDE. The `.kiro/specs/` directory contains the structured specifications that guided the implementation, including requirements, design documents, and task tracking.