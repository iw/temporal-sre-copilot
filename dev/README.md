# Standalone Dev Environment

Self-contained Docker Compose stack for Copilot development. Runs a monitored Temporal cluster, observability stack, and Copilot cluster — 15 services on a single Docker network.

The only external dependency is the [`temporal-dsql`](https://github.com/iw/temporal) repository for building the Temporal runtime image.

## Architecture

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

## Prerequisites

- **Docker Desktop** — 6 GB+ memory allocated (15 containers)
- **AWS CLI** — configured with credentials that have DSQL and Bedrock access
- **temporal-dsql repo** — cloned at `../temporal-dsql` (or set `TEMPORAL_DSQL_PATH`)
- **Python 3.14+** and [uv](https://docs.astral.sh/uv/)
- **Terraform** >= 1.0

## Quick Start

```bash
# 1. Install the CLI
uv sync

# 2. Provision DSQL clusters + Bedrock KB
uv run copilot dev infra apply

# 3. Configure environment
cp dev/.env.example dev/.env
# Edit dev/.env — set TEMPORAL_SQL_HOST and COPILOT_DSQL_HOST from terraform output

# 4. Build Docker images
uv run copilot dev build

# 5. Start all services
uv run copilot dev up

# 6. Set up schemas (once services are healthy)
uv run copilot dev schema setup

# 7. Verify
open http://localhost:8080    # Temporal UI (monitored cluster)
open http://localhost:3000    # Grafana (admin/admin)
open http://localhost:8081    # Copilot API
open http://localhost:8082    # Temporal UI (copilot cluster)
```

## Service Port Mapping

| Service | Host Port | Purpose |
|---------|-----------|---------|
| elasticsearch | 9200 | Visibility store |
| temporal-frontend | 7233 | Temporal gRPC API |
| temporal-frontend | 8233 | Temporal HTTP API |
| temporal-history | 7234 | History service |
| temporal-matching | 7235 | Matching service |
| temporal-worker | 7239 | Worker service |
| temporal-ui | 8080 | Monitored cluster UI |
| mimir | 9009 | Prometheus-compatible metrics |
| loki | 3100 | Log aggregation |
| alloy | 12345 | Metrics/log collection |
| grafana | 3000 | Dashboards (admin/admin) |
| copilot-temporal | 7243 | Copilot Temporal gRPC |
| copilot-ui | 8082 | Copilot cluster UI |
| copilot-api | 8081 | Copilot JSON API |

## Dev CLI Commands

All commands run from the repo root:

```bash
uv run copilot dev up              # Start services (detached)
uv run copilot dev down            # Stop services
uv run copilot dev down -v         # Stop and remove volumes
uv run copilot dev ps              # Show service status
uv run copilot dev logs            # Tail all logs
uv run copilot dev logs <service>  # Tail specific service logs
uv run copilot dev build           # Build runtime + copilot images
uv run copilot dev schema setup    # Apply all schemas
uv run copilot dev infra apply     # Provision DSQL + Bedrock KB
uv run copilot dev infra destroy   # Tear down AWS resources
```

Or use Just shortcuts:

```bash
just dev-up       # Start services
just dev-down     # Stop services
just dev-build    # Build images
just dev-ps       # Service status
just dev-logs     # Tail logs
```

## Environment Variables

Copy `dev/.env.example` to `dev/.env` and set the required values.

### Monitored Cluster (required)

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPORAL_SQL_HOST` | — | DSQL endpoint for monitored cluster |
| `TEMPORAL_SQL_PORT` | `5432` | DSQL port |
| `TEMPORAL_SQL_USER` | `admin` | DSQL user |
| `TEMPORAL_SQL_DATABASE` | `postgres` | DSQL database |
| `TEMPORAL_SQL_MAX_CONNS` | `50` | Max pool connections |
| `TEMPORAL_SQL_MAX_IDLE_CONNS` | `50` | Must equal MAX_CONNS |
| `TEMPORAL_SQL_MAX_CONN_LIFETIME` | `55m` | Under DSQL's 60m limit |
| `TEMPORAL_ELASTICSEARCH_HOST` | `elasticsearch` | ES hostname |
| `TEMPORAL_ELASTICSEARCH_PORT` | `9200` | ES port |
| `AWS_REGION` | `eu-west-1` | AWS region |
| `TEMPORAL_HISTORY_SHARDS` | `4` | History shard count |

### Copilot Cluster (required)

| Variable | Default | Description |
|----------|---------|-------------|
| `COPILOT_DSQL_HOST` | — | DSQL endpoint for copilot cluster |
| `COPILOT_DSQL_DATABASE` | `postgres` | DSQL database |
| `COPILOT_KNOWLEDGE_BASE_ID` | — | Bedrock KB ID (optional) |

## Troubleshooting

### Services won't start

1. Check Docker Desktop has 6 GB+ memory allocated
2. Verify `dev/.env` exists and has valid DSQL endpoints
3. Check `uv run copilot dev logs temporal-history` for connection errors

### DSQL connection failures

1. Verify AWS credentials: `aws sts get-caller-identity`
2. Check the DSQL cluster is active: `aws dsql get-cluster --identifier <id>`
3. Ensure `~/.aws` is mounted (automatic via docker-compose)

### Elasticsearch issues

```bash
curl http://localhost:9200/_cluster/health
uv run copilot dev logs elasticsearch
```

### Schema setup fails

- Ensure services are healthy first: `uv run copilot dev ps`
- Run individual steps manually if needed — the schema command continues past failures

### Grafana shows no data

1. Check Alloy is scraping: `uv run copilot dev logs alloy`
2. Verify Mimir is receiving data: `curl http://localhost:9009/api/v1/query?query=up`
3. Confirm datasources are provisioned in Grafana → Settings → Data Sources

### Cleaning up

```bash
uv run copilot dev down -v         # Remove containers + volumes
uv run copilot dev infra destroy   # Destroy AWS resources
```
