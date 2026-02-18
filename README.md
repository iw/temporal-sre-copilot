# Temporal SRE Copilot

An AI-powered observability agent for Temporal deployments on Aurora DSQL. The Copilot continuously monitors a running cluster, derives health state from forward progress signals using deterministic rules, and uses LLMs to explain what's happening — never to decide.

It runs as a separate Temporal cluster alongside the one it monitors. Pydantic AI workflows collect signals from Amazon Managed Prometheus and Loki every 30 seconds, evaluate a Health State Machine, and when state changes, dispatch Claude to explain why. Assessments are stored in DSQL and served through a JSON API that Grafana consumes directly — no computation in the dashboard.

The result: operators see a single Happy / Stressed / Critical status with a natural language explanation, ranked contributing factors, and suggested remediations with confidence scores. No alert fatigue, no dashboard archaeology.

## Also in this repo

Two supporting capabilities form a feedback loop with the Copilot:

**[Config Compiler](docs/config-compiler.md)** — Collapses hundreds of Temporal + DSQL configuration parameters into ~15 surfaced inputs. Pick a scale preset, optionally a workload modifier, and the compiler derives all safety and tuning parameters, applies guard rails, and emits validated artifacts through pluggable adapters. `uv run temporal-dsql-config compile mid-scale --name prod-v2`

**[Behaviour Profiles](docs/behaviour-profiles.md)** — Snapshot a time window of a running cluster (config + curated telemetry + version metadata) into a labelled profile. Compare profiles, detect drift against a baseline, and validate that a preset produces the expected telemetry bounds.

```
Config Compiler ──► Presets define expected telemetry bounds
        ▲                                          │
        │                                          ▼
Copilot recommends          Behaviour Profiles validate
preset changes ◄──────────── that bounds are met
```

---

## How the Copilot works

The Copilot answers one question: **"Is the cluster making forward progress on workflows?"**

Everything flows from this. A deterministic Health State Machine evaluates 26 signals and sets state. An LLM then explains what's happening — it never decides state transitions or applies thresholds. This is the "Rules decide, AI explains" principle.

```
Signals → Health State Machine (deterministic) → State + Signals → LLM → Explanation
```

### Health states

```
Happy → Stressed → Critical
  ↑         ↓         ↓
  └─────────┴─────────┘
```

| State | Meaning |
|-------|---------|
| Happy | Forward progress healthy, no concerning amplifiers |
| Stressed | Progress continues but amplifiers indicate pressure |
| Critical | Forward progress is impaired or stopped |

The machine enforces an invariant: Happy → Critical must pass through Stressed first, preventing over-eager critical alerts.

### Signal taxonomy

Health is derived from a structured signal taxonomy, not arbitrary thresholds:

| Category | Count | Role | Examples |
|----------|-------|------|----------|
| Primary | 12 | Decide health state | State transitions/sec, backlog age, completion rate, persistence latency |
| Amplifiers | 14 | Explain why | DSQL latency, OCC conflicts, pool utilization, shard churn |
| Narrative | — | Logs explain transitions | "reservoir discard", "SQLSTATE 40001", membership changes |
| Worker | 6 | Worker-side health | Schedule-to-start latency, task slots, pollers, sticky cache |

Only primary signals decide state. Amplifiers provide context for the LLM's explanation. High latency alone ≠ Critical; high latency WITH impaired progress = Critical.

### Multi-agent architecture

Two Pydantic AI agents handle explanation:

| Agent | Model | Latency | Role |
|-------|-------|---------|------|
| Dispatcher | Claude Sonnet 4.5 | ~1-2s | Fast triage. Decides explanation depth, not health state. |
| Researcher | Claude Opus 4.6 | ~10-20s | Deep explanation. Ranked contributing factors, suggested remediations with confidence scores, natural language summaries. |

The dispatcher runs on every state change. It decides whether the situation needs a quick one-liner or a deep dive from the researcher. Most Happy → Happy transitions get a quick explanation; state changes and anomalies get the full treatment.

### Bottleneck classification

The Copilot distinguishes "server can't keep up" from "workers can't keep up":

| Classification | Condition |
|----------------|-----------|
| Server-limited | High backlog age, persistence latency; workers idle |
| Worker-limited | Slots exhausted, high schedule-to-start; server backlog low |
| Mixed | Both server and workers under pressure |
| Healthy | Neither constrained |

Worker evaluation only runs when the server is Happy or Stressed — if the server is Critical, worker advice is irrelevant.

### Workflows

Four Temporal workflows run continuously:

| Workflow | Purpose | Cadence |
|----------|---------|---------|
| `ObserveClusterWorkflow` | Fetches signals from AMP, evaluates health state, triggers assessment on state change | Every 30s |
| `LogWatcherWorkflow` | Queries Loki for error patterns (narrative signals), stores detected patterns | Every 30s |
| `AssessHealthWorkflow` | Dispatches to Sonnet for triage, optionally to Opus for deep explanation. Stores assessment in DSQL. | On state change |
| `ScheduledAssessmentWorkflow` | Periodic assessment even when healthy, deduplicates against recent assessments | Every 5 min |

All workflow and activity inputs are single Pydantic models — no bare positional args. This ensures Temporal's PydanticAIPlugin handles serialization correctly.

### JSON API

The API follows the "Grafana consumes, not computes" principle. All computation happens in the Copilot; Grafana only displays pre-computed values.

| Endpoint | Description |
|----------|-------------|
| `GET /status` | Current health state with full signal taxonomy |
| `GET /status/services` | Per-service health status (derived from primary signals) |
| `GET /status/issues` | Active issues with contributing factors and severity |
| `GET /status/summary` | Natural language summary |
| `GET /status/timeline` | Health state changes over time (supports time range params) |
| `POST /actions` | Future remediation hook (501 Not Implemented) |
| `POST /profiles` | Create a behaviour profile from a time range |
| `GET /profiles` | List profiles with filtering |
| `POST /profiles/compare` | Compare two profiles |

### Grafana dashboard

The Copilot dashboard provides:

- **Advisor panel** — Status badge (Happy/Stressed/Critical), confidence score, natural language summary
- **Status filter** — Toggle by health state to filter the entire dashboard
- **Copilot Insights** — Two-column layout: analysis bullet points + suggested remediations with confidence %
- **Signal Metrics** — Key metrics with sparklines
- **Log Pattern Alerts** — Occurrence count, pattern description, affected service
- **Behaviour Profiles** — Create profiles from the dashboard time range, view recent profiles

Auto-refreshes every 30 seconds. Links to Server Health, DSQL Persistence, and Workers dashboards.

### RAG knowledge base

The Copilot uses a Bedrock Knowledge Base (Titan Embeddings V2, S3 Vectors) to ground LLM explanations in deployment-specific context:

- DSQL implementation details, reservoir design, connection management
- Worker scaling best practices, sticky cache tuning, poller configuration
- Failure mode heuristics and remediation patterns
- Grafana dashboard interpretation guides

The corpus excludes raw metrics/PromQL (those belong in code) and dated benchmark results. Refreshable without restarting the Copilot via `copilot kb sync` + `copilot kb start-ingestion`.

---

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
│  │  profile_metadata                                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                 BEDROCK KNOWLEDGE BASE                     │  │
│  │  S3 source bucket · Titan Embeddings V2 · S3 Vectors     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   Amazon Managed       Amazon Bedrock        Loki / S3
   Prometheus           (Claude)              (Logs / Profiles)
         │
         ▼
      Grafana
```

The Copilot cluster runs in the same VPC as the monitored Temporal deployment but on separate ECS infrastructure. A failure in the Copilot cannot impact production.

---

## Quick start

### Prerequisites

- Python 3.14+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- AWS CLI configured with appropriate permissions
- Terraform 1.0+
- A running [`temporal-dsql-deploy-ecs`](../temporal-dsql-deploy-ecs/) deployment (provides AMP, Loki, DSQL, VPC)

### Install

```bash
uv sync
```

### Set up the database

```bash
uv run copilot db check-connection    # verify DSQL connectivity
uv run copilot db setup-schema        # apply schema
uv run copilot db list-tables         # confirm tables exist
```

### Set up the knowledge base

```bash
uv run copilot kb sync --bucket <s3-bucket> --source docs/rag
uv run copilot kb start-ingestion --kb-id <kb-id> --ds-id <data-source-id>
uv run copilot kb status --kb-id <kb-id>
```

### Run locally

```bash
# Start the worker (processes all four workflows)
python -m copilot.worker

# Start the API (Copilot status + Profile endpoints)
uvicorn copilot.api:app --host 0.0.0.0 --port 8080

# Start workflows (ObserveCluster, LogWatcher, ScheduledAssessment)
python -m copilot.starter
```

### Deploy to ECS

```bash
cd terraform/envs/bench
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with values from temporal-dsql-deploy-ecs outputs

terraform init
terraform plan
terraform apply
```

For local development with Docker Compose, the Copilot's DSQL cluster and Bedrock KB are provisioned from `temporal-dsql-deploy/terraform/copilot/`. See the [copilot profile README](../temporal-dsql-deploy/profiles/copilot/README.md).

---

## Project structure

The repo is a uv workspace monorepo with four packages:

```
temporal-sre-copilot/
├── pyproject.toml                  # workspace root (NOT a package)
├── uv.lock                         # single lockfile
├── packages/
│   ├── copilot_core/               # shared types, no internal deps
│   ├── dsql_config/                # config compiler + CLI
│   ├── behaviour_profiles/         # profile store + API
│   └── copilot/                    # orchestrator (depends on all three)
├── tests/                          # shared test directory (156 tests, ~10s)
│   └── properties/                 # Hypothesis property-based tests
├── terraform/                      # modular infrastructure
├── grafana/                        # dashboards
├── docs/                           # config compiler + behaviour profiles docs
└── Dockerfile                      # multi-stage build (Python 3.14)
```

### Dependency graph

```
copilot_core (shared types, no internal deps)
    ▲           ▲           ▲
    │           │           │
dsql_config  behaviour_profiles  │
    ▲           ▲           │
    └───────────┴───── copilot (orchestrator)
```

`dsql_config` does NOT depend on `behaviour_profiles` — they only share types through `copilot_core`.

## Tech stack

- Python 3.14+, [uv](https://docs.astral.sh/uv/), ruff, ty
- [Pydantic AI](https://ai.pydantic.dev/) + [Temporal Python SDK](https://docs.temporal.io/develop/python)
- FastAPI for JSON API + Profile API
- Claude Sonnet 4.5 / Claude Opus 4.6 via Amazon Bedrock
- Aurora DSQL for state store (asyncpg + IAM auth)
- Bedrock Knowledge Base for RAG (Titan Embeddings V2, S3 Vectors)
- [whenever](https://github.com/ariebovenberg/whenever) for UTC-first date/time handling
- Typer + Rich for CLI
- Hypothesis for property-based tests

## Tests

```bash
just test              # 156 tests, ~10s
just lint              # ruff check + format
just typing            # ty check
just check-all         # all three
```

Property-based tests (Hypothesis) validate state machine invariants, config compiler derivation completeness, serialization round-trips, guard rail coverage, adapter output completeness, profile comparison ordering, drift detection, and preset conformance.

## Related

- [`temporal-dsql-deploy-ecs`](../temporal-dsql-deploy-ecs/) — Production ECS deployment (provides AMP, Loki, DSQL, VPC)
- [Config Compiler docs](docs/config-compiler.md)
- [Behaviour Profiles docs](docs/behaviour-profiles.md)
- [Spec: Copilot](.kiro/specs/temporal-sre-copilot/) — Requirements, design, tasks
- [Spec: Enhanced Config UX](.kiro/specs/enhance-config-ux/) — Requirements, design, tasks

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

This project was developed with significant assistance from [Kiro](https://kiro.dev), an AI-powered IDE. The `.kiro/specs/` directory contains the structured specifications that guided the implementation.
