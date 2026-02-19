# Behaviour Profiles

The Behaviour Profile API (`behaviour-profiles` package) snapshots a time window of a running Temporal DSQL deployment into a labelled profile. Each profile captures:

- **Identity metadata** — cluster, namespace, task queue, Temporal server version, DSQL plugin version, worker code SHA
- **Configuration snapshot** — dynamic config, server env vars (secrets redacted), worker options, DSQL plugin config
- **Curated telemetry summary** — throughput, latency, matching, DSQL pool, errors, resources

Profiles enable comparison ("healthy @ 150 WPS" vs "failed @ 400 WPS"), drift detection against a baseline, and preset conformance validation through the Copilot.

## Configuration

The profile API is mounted by the Copilot's FastAPI app and configured automatically during startup. It requires three things:

| Requirement | Environment variable | Source |
|-------------|---------------------|--------|
| DSQL pool (metadata index) | `COPILOT_DSQL_ENDPOINT` | `copilot dev infra apply` → `copilot_dsql_endpoint` |
| S3 bucket (full profile JSON) | `COPILOT_PROFILE_S3_BUCKET` | `copilot dev infra apply` → `profile_bucket` |
| Prometheus-compatible endpoint (telemetry collection) | `PROMETHEUS_ENDPOINT` | Auto-configured in docker-compose to point at Mimir (`http://mimir:9009/prometheus`) |

If `COPILOT_PROFILE_S3_BUCKET` or `PROMETHEUS_ENDPOINT` is missing, the profile router stays unconfigured and all `/profiles` endpoints return HTTP 503 with "Profile storage not configured".

The DSQL `behaviour_profiles` table is created by `copilot dev schema setup` as part of the Copilot schema — no additional migration needed.

### Local dev setup

```bash
# 1. Provision infrastructure (creates the profile S3 bucket)
just copilot dev infra apply

# 2. Add to dev/.env
COPILOT_PROFILE_S3_BUCKET=<profile_bucket output from terraform>

# 3. Restart copilot-api to pick up the new env var
just copilot dev down
just copilot dev up
```

Verify with `curl http://localhost:8081/profiles/` — you should get `[]` instead of a 503.

## Profile API

The API is mounted by the Copilot at `/profiles/*`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/profiles` | POST | Create a profile from a time range (max 24 hours) |
| `/profiles` | GET | List profiles with filtering by cluster, label, namespace |
| `/profiles/{id}` | GET | Retrieve full profile |
| `/profiles/{id}/baseline` | POST | Designate as baseline for drift detection |
| `/profiles/compare` | POST | Compare two profiles |

### Creating a profile

Provide a time range, cluster identifier, and optional label. The API queries Amazon Managed Prometheus for telemetry aggregates and captures the current configuration snapshot.

```json
POST /profiles
{
    "name": "pre-scale-test",
    "cluster_id": "temporal-prod",
    "time_window_start": "2026-02-18T10:00:00Z",
    "time_window_end": "2026-02-18T11:00:00Z",
    "namespace": "default",
    "task_queue": "main-queue",
    "label": "baseline-150wps"
}
```

Time windows are capped at 24 hours.

### Comparing profiles

```json
POST /profiles/compare
{
    "profile_a_id": "abc-123",
    "profile_b_id": "def-456"
}
```

The comparison returns:

- **Config diff** — parameters that changed, with old and new values
- **Telemetry diff** — metrics that regressed or improved beyond thresholds (default: 20% for latency, 50% for error rates), ordered by severity
- **Version diff** — changes in Temporal server, DSQL plugin, or worker code versions

## Telemetry summary

Each profile stores curated metric aggregates (min, max, mean, p50, p95, p99) for a fixed metric list:

| Category | Metrics |
|----------|---------|
| Throughput | Workflows started/sec, completed/sec, state transitions/sec |
| Latency | Workflow schedule-to-start p95/p99, activity schedule-to-start p95/p99, persistence latency p95/p99 |
| Matching | Sync match rate, async match rate, task dispatch latency, backlog count, backlog age |
| DSQL pool | Pool open/in-use/idle count, reservoir size, reservoir empty events, open failures, reconnect count |
| Errors | OCC conflicts/sec, exhausted retries/sec, DSQL auth failures |
| Resources | CPU and memory utilization per service, worker task slot utilization |

## Storage

Profiles use a split storage model:

- **S3** — Full profile JSON document (keeps DSQL row sizes small)
- **DSQL** — Metadata index for listing, filtering, and baseline designation

## Copilot integration

The Copilot uses behaviour profiles for three purposes:

### Drift detection

During health assessments, the Copilot compares current telemetry against the active baseline profile for the cluster and namespace. Deviations beyond configured thresholds are flagged as drift in the assessment.

### Drift correlation

When a profile comparison reveals config changes correlated with telemetry regressions, the Copilot includes the correlation in the assessment explanation. This helps operators connect "we changed X" with "Y got worse".

### Preset conformance

When a profile is associated with a scale preset, the Copilot compares the profile's telemetry against the expected bounds defined by the preset. The profile is labelled "conforming" or "drifted" with per-metric pass/fail detail.

## Grafana integration

The Copilot dashboard includes a Behaviour Profiles section:

- **Create Profile** — Snapshot the current dashboard time range as a profile. Set cluster, namespace, task queue, and label via dashboard variables.
- **Recent Profiles** — Table of profiles with ID, name, label, cluster, time window, and baseline status. Sorted by creation time.

## Package structure

```
packages/behaviour_profiles/src/behaviour_profiles/
├── models.py       # BehaviourProfile, TelemetrySummary, comparison models
├── comparison.py   # ProfileComparison logic (config diff, telemetry diff, version diff)
├── storage.py      # S3 for full JSON, DSQL for metadata queries
├── telemetry.py    # AMP query for telemetry collection
└── api.py          # FastAPI router (/profiles/*)
```

## Spec reference

Full requirements and acceptance criteria: [`.kiro/specs/enhance-config-ux/`](../.kiro/specs/enhance-config-ux/)
