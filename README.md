# Temporal SRE Copilot

An AI-powered observability agent for Temporal deployments on Aurora DSQL. The Copilot continuously monitors a running cluster, derives health state from forward progress signals using deterministic rules, and uses LLMs to explain what's happening — never to decide.

It runs as a separate Temporal cluster alongside the one it monitors. Pydantic AI workflows collect signals from Amazon Managed Prometheus and Loki every 30 seconds, evaluate a Health State Machine, and when state changes, dispatch Claude to explain why. Assessments are stored in DSQL and served through a JSON API that Grafana consumes directly — no computation in the dashboard.

The result: operators see a single Happy / Stressed / Critical status with a natural language explanation, ranked contributing factors, and suggested remediations with confidence scores. No alert fatigue, no dashboard archaeology.

## Also in this repo

Two supporting capabilities form a feedback loop with the Copilot:

**[Config Compiler](docs/config-compiler.md)** — Collapses hundreds of Temporal + DSQL configuration parameters into ~15 surfaced inputs. Pick a scale preset, optionally a workload modifier, and the compiler derives all safety and tuning parameters, applies guard rails, and emits validated artifacts through pluggable adapters. `just config compile mid-scale --name prod-v2`

**[Behaviour Profiles](docs/behaviour-profiles.md)** — Snapshot a time window of a running cluster (config + curated telemetry + version metadata) into a labelled profile. Compare profiles, detect drift against a baseline, and validate that a preset produces the expected telemetry bounds.

```
Config Compiler ──► Presets define expected telemetry bounds
        ▲                                          │
        │                                          ▼
Copilot recommends          Behaviour Profiles validate
preset changes ◄──────────── that bounds are met
```

---

## Quick start

Get the full Copilot running locally — a monitored Temporal cluster, observability stack, and the Copilot itself — all in Docker Compose. The only external dependency is the [`temporal-dsql`](https://github.com/iw/temporal) repo for building the Temporal server image.

### Prerequisites

- Docker Desktop (6 GB+ memory)
- AWS CLI configured with DSQL and Bedrock permissions
- Python 3.14+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [just](https://just.systems/) task runner
- Terraform 1.0+
- [`temporal-dsql`](https://github.com/iw/temporal) repo cloned at `../temporal-dsql`

### Install

```bash
uv sync
```

The repo uses [just](https://just.systems/) as a task runner. The `just copilot` recipe invokes the Copilot CLI via `uv run --package temporal-sre-copilot copilot` — the `--package` flag is required in a uv workspace monorepo where the root `pyproject.toml` is not itself a package.

### Provision infrastructure

Two ephemeral DSQL clusters (monitored + copilot) and a Bedrock Knowledge Base:

```bash
just copilot dev infra apply
```

### Configure

```bash
cp dev/.env.example dev/.env
# Set values from `copilot dev infra apply` terraform output:
#   TEMPORAL_SQL_HOST          — monitored cluster DSQL endpoint
#   COPILOT_DSQL_HOST          — copilot cluster DSQL endpoint
#   COPILOT_PROFILE_S3_BUCKET  — S3 bucket for behaviour profiles (optional)
#   COPILOT_KNOWLEDGE_BASE_ID  — Bedrock KB ID (optional)
```

### Compile config profile

```bash
just config compile starter --name dev --deployment compose --from dev/docker-compose.yml
```

Compiles the starter preset and generates a deployment profile from the dev compose file. Artifacts are written to `.temporal-dsql/dev/<uuid>/` and the active context is set automatically.

### Build and start

```bash
just copilot dev build           # Build runtime + copilot images
just copilot dev up              # Start all 15 services
just copilot dev schema setup    # Apply schemas to both clusters + ES
```

### Verify

- Temporal UI (monitored): http://localhost:8080
- Grafana (admin/admin): http://localhost:3000
- Copilot API: http://localhost:8081
- Copilot Temporal UI: http://localhost:8082

### Manage

```bash
just copilot dev ps              # Service status
just copilot dev logs            # Tail all logs
just copilot dev logs <service>  # Tail specific service
just copilot dev down            # Stop services
just copilot dev down -v         # Stop + remove volumes
just copilot dev infra destroy   # Tear down AWS resources
```

See [dev/README.md](dev/README.md) for the full setup guide, port mapping, environment variable reference, and troubleshooting.

### Set up the knowledge base

Optionally populate the RAG knowledge base for richer health explanations:

```bash
just copilot kb sync --bucket <s3-bucket> --source docs/rag
just copilot kb start-ingestion --kb-id <kb-id> --ds-id <data-source-id>
just copilot kb status --kb-id <kb-id>
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

### Scale-aware thresholds

A 2 wf/s dev cluster and a 500 wf/s production cluster have very different "normal". The Copilot classifies observed throughput into scale bands and selects a matching threshold profile — no manual tuning required.

| Scale Band | Throughput | Persistence p99 gate | State transitions healthy | Poller timeout rate |
|------------|-----------|----------------------|--------------------------|---------------------|
| Starter | < 50 st/s | 500 ms | 0.5 st/s | 0.50 |
| Mid-scale | 50–500 st/s | 200 ms | 10 st/s | 0.20 |
| High-throughput | > 500 st/s | 100 ms | 50 st/s | 0.10 |

Band transitions use 10% hysteresis to prevent flapping at boundaries (e.g. oscillating around 50 st/s won't flip between Starter and Mid-scale).

Four layers build on each other:

1. **Scale-aware thresholds** — `ScaleBand` classification + `ThresholdProfile` per band. Eliminates the dead zone where low-throughput clusters were incorrectly flagged as Stressed.
2. **Deployment profiles** — `DeploymentProfile` captures what was deployed (scaling topology, resource identity). Deployment adapters (ECS, Compose) render profiles from config compiler output.
3. **Dynamic inspection** — `PlatformInspector` queries the live cluster (ECS DescribeServices, CloudWatch, Docker API) for runtime state. `refine_thresholds()` adjusts thresholds based on actual vs expected capacity — more History replicas tightens latency gates, fewer loosens them.
4. **Deployment profile loading** — A single `DEPLOYMENT_PROFILE` env var (file path or `s3://` URI) loads the profile at worker boot. The config compiler's `--deployment compose --from <compose-file>` flag generates the profile from an existing compose file. For ECS, `--deployment ecs` with annotations does the same.

Operators can override any threshold via `ThresholdOverrides` in `CopilotConfig` without touching the profile system.

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

The corpus excludes raw metrics/PromQL (those belong in code) and dated benchmark results. Refreshable without restarting the Copilot via `just copilot kb sync` + `just copilot kb start-ingestion`.

---

## Architecture

### Local development

The `dev/` directory runs 15 services on a single Docker network — three groups connected to ephemeral AWS resources:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DOCKER COMPOSE NETWORK                          │
│                                                                     │
│  MONITORED CLUSTER              OBSERVABILITY        COPILOT        │
│  ┌──────────────────┐          ┌────────────┐       ┌────────────┐ │
│  │ temporal-frontend │──┐      │ mimir      │       │ copilot-   │ │
│  │ temporal-history  │  │      │ (metrics)  │◄──────│ temporal   │ │
│  │ temporal-matching │  ├─────▶│            │       │            │ │
│  │ temporal-worker   │  │      ├────────────┤       ├────────────┤ │
│  └──────────────────┘  │      │ loki       │       │ copilot-   │ │
│  ┌──────────────────┐  │      │ (logs)     │◄──────│ worker     │ │
│  │ elasticsearch    │  │      ├────────────┤       │ (Pydantic  │ │
│  │ temporal-ui      │  │      │ alloy      │       │  AI)       │ │
│  └──────────────────┘  │      │ (collector)│       ├────────────┤ │
│                        │      ├────────────┤       │ copilot-   │ │
│                        └─────▶│ grafana    │◄──────│ api        │ │
│                               │ :3000      │       │ :8081      │ │
│                               └────────────┘       └────────────┘ │
│                                                                     │
│  ┌──────────────────┐                          ┌────────────────┐  │
│  │ Aurora DSQL      │                          │ Aurora DSQL    │  │
│  │ (monitored)      │                          │ (copilot)      │  │
│  └──────────────────┘                          └────────────────┘  │
│                                                          │         │
│                                                ┌─────────▼──────┐  │
│                                                │ Amazon Bedrock │  │
│                                                │ (Claude, KB)   │  │
│                                                └────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Production (ECS)

In production, the Copilot runs on its own ECS cluster in the same VPC as the monitored deployment. A failure in the Copilot cannot impact production.

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

---

## Production deployment

To run the Copilot against a real production cluster, you need a [`temporal-dsql-deploy-ecs`](../temporal-dsql-deploy-ecs/) deployment. This provides the monitored Temporal cluster, AMP, Loki, DSQL, and VPC that the Copilot observes.

### Set up the database

```bash
just copilot db check-connection -e <dsql-endpoint>
just copilot db setup-schema -e <dsql-endpoint>
just copilot db list-tables -e <dsql-endpoint>
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
├── dev/                            # standalone dev environment (Docker Compose)
├── tests/                          # shared test directory (214 tests, ~10s)
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
just test              # 214 tests, ~10s
just lint              # ruff check + format
just typing            # ty check
just check-all         # all three
```

Property-based tests (Hypothesis) validate state machine invariants, scale band classification purity, threshold ordering across all bands, dead zone elimination, config compiler derivation completeness, serialization round-trips, guard rail coverage, adapter output completeness, profile comparison ordering, drift detection, preset conformance, and deployment model backward compatibility.

## Related

- [`temporal-dsql-deploy-ecs`](../temporal-dsql-deploy-ecs/) — Production ECS deployment (provides AMP, Loki, DSQL, VPC)
- [Config Compiler docs](docs/config-compiler.md)
- [Behaviour Profiles docs](docs/behaviour-profiles.md)
- [Spec: Copilot](.kiro/specs/temporal-sre-copilot/) — Requirements, design, tasks
- [Spec: Enhanced Config UX](.kiro/specs/enhance-config-ux/) — Requirements, design, tasks
- [Spec: Scale-Aware Thresholds](.kiro/specs/scale-aware-thresholds/) — Requirements, design, tasks

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

This project was developed with significant assistance from [Kiro](https://kiro.dev), an AI-powered IDE. The `.kiro/specs/` directory contains the structured specifications that guided the implementation.
