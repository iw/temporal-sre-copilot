# Dev Scenarios

Test scripts that run against the local dev environment (`dev/docker-compose.yml`).
These are not pytest tests — they're standalone scripts that generate observable
conditions on the monitored Temporal cluster.

## Structure

```
scenarios/
├── metrics.py                  # Shared Prometheus metrics helper (port 9091)
├── copilot/                    # Generate signals for the SRE Copilot
│   ├── stress_workflows.py     # Sustained WPS for forward-progress signals
│   ├── spike_load.py           # Load spikes to trigger Happy → Stressed
│   └── error_injection.py      # Failing workflows for error-rate signals
└── dsql/                       # DSQL plugin validation
    └── load_test.py            # 45-min soak test for connection pool stability
```

## Usage

All scripts connect to `localhost:7233` (the monitored cluster) by default.
Run from the repo root:

```bash
# Copilot scenarios — generate observable conditions
uv run python dev/scenarios/copilot/stress_workflows.py
uv run python dev/scenarios/copilot/stress_workflows.py --rate 20 --duration 10
uv run python dev/scenarios/copilot/spike_load.py --base-rate 5 --spike-rate 50
uv run python dev/scenarios/copilot/error_injection.py --failure-pct 30 --rate 15

# DSQL soak test — validate connection pool stability
uv run python dev/scenarios/dsql/load_test.py
uv run python dev/scenarios/dsql/load_test.py --duration 10 --rate 5
```

## Copilot Scenarios

These scripts generate load and failure patterns on the monitored cluster
so the Copilot can observe and assess them. Run them while the Copilot is
active to validate health state transitions.

| Script | What it generates | Expected Copilot response |
|--------|-------------------|---------------------------|
| `stress_workflows.py` | Sustained WPS load | Healthy forward-progress signals |
| `spike_load.py` | Sudden 5-10× load spikes | Happy → Stressed transitions |
| `error_injection.py` | Configurable failure rate | Error-rate and completion-rate signals |

All copilot scripts expose Prometheus metrics on port 9091 for Alloy to scrape.

## DSQL Soak Test

The load test runs for 45 minutes by default to validate connection pool
stability across multiple refresh cycles. With `DSQL_CONN_REFRESH_INTERVAL=8m`,
expect ~5 refresh cycles. Watch for:

- `dsql_pool_open` stays at max in Grafana
- "DSQL connection refresh triggered" in service logs
- Zero workflow failures during refresh windows
- `dsql_db_closed_max_idle_time_total` stays at 0
