# Config Compiler

The Config Compiler (`dsql-config` package) addresses the overwhelming configuration surface of Temporal + DSQL deployments. Temporal's dynamic config has hundreds of keys. The DSQL plugin adds 30+ environment variables for reservoir, rate limiter, token cache, slot blocks, and connection pool. Worker SDKs add more. Nobody should have to reason about all of this.

The compiler classifies every parameter into one of four buckets, so adopters only touch what matters:

| Classification | Who touches it | Examples |
|----------------|---------------|----------|
| SLO | Adopter (required) | Target WPS, max schedule-to-start latency |
| Topology | Adopter (optional, preset defaults) | Shard count, matching partitions, worker count |
| Safety | Auto-derived, never exposed | DSQL rate limiting, reservoir warm-up, MaxIdleConns == MaxConns |
| Tuning | Auto-derived, never exposed | Sticky timeout, batch sizes, reservoir refill cadence |

The total surface exposed to adopters is ≤15 parameters. Everything else is derived.

## Scale presets

Pick a preset that matches your throughput:

| Preset | Target | Key defaults |
|--------|--------|-------------|
| `starter` | < 50 st/s | Reservoir disabled, pool size 10, no distributed rate limiting |
| `mid-scale` | 50–500 st/s | Reservoir enabled, pool size 50, per-instance rate limiting |
| `high-throughput` | > 500 st/s | Reservoir enabled, distributed rate limiting, aggressive QPS limits |

## Workload modifiers

Modifiers adjust preset defaults for specific workflow patterns:

| Modifier | Effect |
|----------|--------|
| `simple-crud` | Eager activity execution, lower matching partitions |
| `orchestrator` | Balanced matching partitions, moderate concurrent workflow tasks, child workflow dispatch |
| `batch-processor` | Higher matching partitions, increased concurrent activity limits |
| `long-running` | Sticky execution caching, longer sticky schedule-to-start timeouts |

## Guard rails

The compiler catches unsafe configurations before deployment:

- Connection limit violations (reservoir_target × replicas > 10,000)
- Matching partition over-provisioning
- MaxIdleConns ≠ MaxConns (causes pool decay under load)
- Missing DynamoDB table for distributed rate limiting
- Reservoir enabled with target of zero
- Thundering herd at connection rotation time

All errors and warnings are reported before halting. No silent failures.

## Adapters

Output generation is pluggable via entry points:

| Type | Adapters | Output |
|------|----------|--------|
| SDK | Go, Python | Worker option snippets |
| Platform | ECS, Docker Compose | Task definition env vars, dotenv files |

New adapters register under `temporal_dsql.sdk_adapters` or `temporal_dsql.platform_adapters` entry point groups. Adding `uv add temporal-dsql-gen-rust` would make Rust output appear automatically.

## CLI

All commands run via `uv run` from the workspace root:

```bash
# List available presets
uv run temporal-dsql-config list-presets

# Compile a named config
uv run temporal-dsql-config compile mid-scale --name prod-v2

# Compile with a deployment profile from an existing compose file
uv run temporal-dsql-config compile starter --name dev \
    --deployment compose --from dev/docker-compose.yml

# Compile with a deployment profile for ECS
uv run temporal-dsql-config compile mid-scale --name prod-v2 \
    --deployment ecs \
    -a dsql_endpoint=xxx.dsql.region.on.aws \
    -a ecs_cluster_arn=arn:aws:ecs:region:account:cluster/name

# Compile with modifier and overrides
uv run temporal-dsql-config compile mid-scale \
    --name staging \
    --modifier batch-processor \
    -o target_state_transitions_per_sec=300

# Describe what a preset resolves to
uv run temporal-dsql-config describe-preset high-throughput --modifier long-running

# Explain a specific parameter
uv run temporal-dsql-config explain --key history.transferActiveTaskQueueTimeout

# Explain a preset's reasoning chain
uv run temporal-dsql-config explain --preset mid-scale --modifier orchestrator

# Explain the latest compiled config
uv run temporal-dsql-config explain
```

Compiled artifacts are written to `.temporal-dsql/<name>/<config-profile-id>/`:

```
.temporal-dsql/
├── .active_context          # contains "prod-v2/<uuid>"
├── prod-v2/
│   ├── current -> <uuid>/   # symlink set by `dev up`
│   └── <uuid>/
│       ├── profile.json     # full ConfigProfile (used by explain --profile)
│       ├── dynamic_config.yaml
│       ├── dsql_plugin.json
│       ├── deployment_profile.json  # DeploymentProfile (when --deployment used)
│       ├── ...              # SDK + platform adapter outputs
│       └── behaviour/       # behaviour profile snapshots
│           └── <epoch>/
│               └── behaviour_profile.json
└── staging/
    └── <uuid>/
        └── ...
```

Each `compile` invocation creates a new instantiation (UUID) of the preset.
The `.active_context` file tracks the most recently compiled profile so
subsequent CLI commands (e.g., `explain`, `dev up`) resolve it automatically.
Use `--context <uuid>` to target a specific instantiation.

## Explain capability

Three levels of deterministic, template-based explanation. No LLM involvement — all output is derived from structured metadata in the parameter registry and preset definitions.

| Level | Input | Output |
|-------|-------|--------|
| Key | A parameter key | Purpose, classification, resolved value, rationale |
| Preset | Preset name + optional modifier | SLO targets, topology derivation, locked safety params, reasoning chain |
| Profile | A compiled ConfigProfile | Full composition: base preset, overrides, guard rails fired, derivation chains |

All output available in both human-readable text and structured JSON.

## Backward compatibility

Existing DSQL environment variables continue to work. When no preset is explicitly provided, the compiler treats existing env vars as overrides on the `starter` preset. The `compile` command reports which existing variables are redundant with preset defaults, enabling incremental migration.

## Package structure

```
packages/dsql_config/src/dsql_config/
├── registry.py         # ParameterRegistry (single source of truth)
├── compiler.py         # ConfigCompiler
├── guard_rails.py      # GuardRailEngine
├── presets.py          # Scale presets (starter, mid-scale, high-throughput)
├── modifiers.py        # Workload modifiers
├── explain.py          # 3-level explain capability
├── models.py           # ConfigProfile, CompilationResult, ScalePreset
├── compat.py           # Backward compatibility (env var mapping)
├── cli.py              # Typer CLI (temporal-dsql-config)
└── adapters/
    ├── __init__.py     # Protocols, discovery via entry points
    ├── go_sdk.py       # Go SDK adapter
    ├── python_sdk.py   # Python SDK adapter
    ├── ecs.py          # ECS platform adapter
    └── compose.py      # Docker Compose platform adapter
```

## Spec reference

Full requirements and acceptance criteria: [`.kiro/specs/enhance-config-ux/`](../.kiro/specs/enhance-config-ux/)
