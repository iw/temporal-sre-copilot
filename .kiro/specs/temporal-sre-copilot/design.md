# Design Document: Temporal SRE Copilot

## Overview

The Temporal SRE Copilot is an AI-powered observability agent that provides intelligent health monitoring for Temporal deployments running on Aurora DSQL. The system runs as a separate Temporal cluster using Pydantic AI workflows to continuously observe signals, derive health state from forward progress, and produce actionable assessments with natural language explanations.

### Key Design Decisions

1. **Separate Temporal Cluster**: The Copilot runs on its own ECS cluster to ensure isolation from the monitored deployment. A failure in the Copilot cannot impact the production Temporal services.

2. **Pydantic AI + Temporal**: Using Pydantic AI's native Temporal integration provides durable execution for LLM-powered analysis. If an LLM call fails mid-analysis, Temporal automatically retries from the last checkpoint.

3. **Health State Machine**: Health is derived from forward progress using deterministic rules. The state machine has three canonical states (Happy, Stressed, Critical) with well-defined transitions anchored to the forward progress invariant.

4. **"Rules Decide, AI Explains"**: Deterministic rules evaluate primary signals and set health state. The LLM receives the state and explains/ranks issues—it never decides state transitions or applies thresholds.

5. **Signal Taxonomy**: Signals are classified into Primary (decide state), Amplifiers (explain why), and Narrative (logs that explain transitions). This separation ensures health is anchored to progress, not pain.

6. **JSON API for Grafana**: A simple REST API exposes health assessments to Grafana's JSON API data source. Grafana consumes pre-computed values—it never computes health state.

7. **DSQL State Store**: Health assessments are persisted to Aurora DSQL, dogfooding the same database technology as the monitored deployment.

8. **Multi-Agent Architecture**: Following the Pydantic AI Temporal example patterns, we use a dispatcher agent for fast triage and a research agent for deep explanation. This saves costs and reduces latency for simple health checks.

9. **Same VPC Deployment**: The Copilot ECS cluster runs in the same VPC as the monitored Temporal cluster, enabling direct access to AMP, Loki, and DSQL without public endpoints.

10. **Modern Python Tooling**: Python 3.14+ with uv for package management, ruff for linting/formatting, and ty for type checking.


## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COPILOT ECS CLUSTER (Same VPC)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐ │
│  │  Temporal Server    │  │  Copilot Worker     │  │  API Service        │ │
│  │  (single-binary)    │  │  (Pydantic AI)      │  │  (FastAPI)          │ │
│  │                     │  │                     │  │                     │ │
│  │  - DSQL for         │  │  Workflows:         │  │  Endpoints:         │ │
│  │    workflow state   │  │  - MetricWatcher    │  │  - /status          │ │
│  │  - Same DSQL as     │  │  - LogWatcher       │  │  - /status/services │ │
│  │    state store      │  │  - DeepAnalysis     │  │  - /status/issues   │ │
│  │                     │  │  - Scheduled        │  │  - /status/summary  │ │
│  │                     │  │                     │  │  - /status/timeline │ │
│  │                     │  │  Agents:            │  │                     │ │
│  │                     │  │  - Dispatcher       │  │                     │ │
│  │                     │  │    (Sonnet 4.5)     │  │                     │ │
│  │                     │  │  - Researcher       │  │                     │ │
│  │                     │  │    (Opus 4.6)       │  │                     │ │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘ │
│           │                        │                        │              │
│           └────────────────────────┼────────────────────────┘              │
│                                    │                                       │
│  ┌─────────────────────────────────▼─────────────────────────────────────┐ │
│  │                    DSQL STATE STORE                                   │ │
│  │  Tables:                                                              │ │
│  │  - health_assessments (assessment history)                            │ │
│  │  - issues (active/resolved issues)                                    │ │
│  │  - metrics_snapshots (sliding window)                                 │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                    BEDROCK KNOWLEDGE BASE                             │ │
│  │  - S3 data source (AGENTS.md, docs/dsql/*.md, dashboard guides)       │ │
│  │  - Titan Embeddings V2 for vectorization                              │ │
│  │  - S3 Vectors for storage (low-cost vector store)                     │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         │ Queries            │ Invokes            │ Queries
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Amazon Managed  │  │ Amazon Bedrock  │  │ Loki            │
│ Prometheus      │  │                 │  │ (Logs)          │
│ (Metrics)       │  │ Claude Opus 4.6 │  │                 │
│                 │  │ Claude Sonnet   │  │                 │
│                 │  │ Titan Embed V2  │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │
         │ Queries JSON API
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GRAFANA - TEMPORAL COPILOT                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─ Advisor ─────────────────────────────────┐  ┌─ Status Filter ─────────┐│
│  │                                           │  │ 🟢 Happy  🟡 Stressed   ││
│  │  🤖  ● STRESSED                           │  │ 🔴 Critical             ││
│  │      Confidence: 82%  Just now            │  └─────────────────────────┘│
│  │                                           │                              │
│  │  Workflow progress continues, but History │  ┌─ Signal Metrics ────────┐│
│  │  backlog and DSQL contention increasing.  │  │ State Trans/sec  182 ↑  ││
│  │                                           │  │ Backlog Age      47s    ││
│  │  ⚠️ History backlog age rising:           │  │ DSQL Latency     92ms   ││
│  │     persistence latency amplifying        │  │ OCC Conflicts    38/s   ││
│  │     contention.                           │  │ Pool Util        86%    ││
│  └───────────────────────────────────────────┘  └─────────────────────────┘│
│                                                                             │
│  ┌─ Copilot Insights ───────────────────────────────────────────────────────┐
│  │                                                                          │
│  │  📊 Analysis                        💡 Suggested Remediations            │
│  │  ─────────────────────────────      ─────────────────────────────────    │
│  │  ⚠️ Persistence latency rising;     🟢 Increase History replicas   71%  │
│  │     amplifying contention in           History backlog rising faster    │
│  │     History service.                   than processing rate             │
│  │                                                                          │
│  │  🔥 DSQL conflicts increased;       🟡 Increase DSQL connection    58%  │
│  │     OCC contention > 30/s is           pool                             │
│  │     unhealthy.                         Pool utilization > 80%           │
│  │                                                                          │
│  │  📉 Instances shedding DSQL                      [ View Guide > ]        │
│  │     connections ("reservoir                                              │
│  │     discard") repeatedly.                                                │
│  └──────────────────────────────────────────────────────────────────────────┘
│                                                                             │
│  ┌─ Log Pattern Alerts ─────────────────────────────────────────────────────┐
│  │  Occurrences   Pattern                              Service              │
│  │  ───────────   ─────────────────────────────────    ─────────            │
│  │  128 times     DSQL reservoir discard               🏷️ history           │
│  └──────────────────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────────────────┘
```

### Multi-Agent Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         HEALTH EVALUATION FLOW                              │
│                      "Rules Decide, AI Explains"                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐     ┌─────────────────────────────────────────────────┐   │
│  │   Signals   │────▶│        HEALTH STATE MACHINE (Deterministic)     │   │
│  │  Collected  │     │                                                 │   │
│  │             │     │  Primary Signals → Evaluate Forward Progress    │   │
│  └─────────────┘     │                                                 │   │
│                      │  if progress_healthy and no_pressure:           │   │
│                      │      state = HAPPY                              │   │
│                      │  elif progress_continues and pressure_detected: │   │
│                      │      state = STRESSED                           │   │
│                      │  elif progress_impaired:                        │   │
│                      │      state = CRITICAL                           │   │
│                      │                                                 │   │
│                      │  Output: health_state (no LLM involved)         │   │
│                      └─────────────────────────────────────────────────┘   │
│                                         │                                   │
│                                         │ state + signals                   │
│                                         ▼                                   │
│                      ┌─────────────────────────────────────────────────┐   │
│                      │           DISPATCHER AGENT                      │   │
│                      │           (Claude Sonnet 4.5)                   │   │
│                      │                                                 │   │
│                      │  Fast triage: ~1-2 seconds                      │   │
│                      │  Receives: health_state (already decided)       │   │
│                      │                                                 │   │
│                      │  Outputs:                                       │   │
│                      │  ├── NoExplanationNeeded → Return state only    │   │
│                      │  ├── QuickExplanation → Brief summary           │   │
│                      │  └── NeedsDeepExplanation → Delegate            │   │
│                      └─────────────────────────────────────────────────┘   │
│                                         │                                   │
│                                         │ NeedsDeepExplanation              │
│                                         ▼                                   │
│                      ┌─────────────────────────────────────────────────┐   │
│                      │           RESEARCHER AGENT                      │   │
│                      │           (Claude Opus 4.6)                     │   │
│                      │                                                 │   │
│                      │  Deep explanation: ~10-20 seconds               │   │
│                      │  Receives: health_state + all signals + RAG     │   │
│                      │                                                 │   │
│                      │  Output: HealthAssessment                       │   │
│                      │  ├── Explanation of current state               │   │
│                      │  ├── Ranked contributing factors                │   │
│                      │  ├── Suggested actions with confidence          │   │
│                      │  └── Natural language summary                   │   │
│                      │                                                 │   │
│                      │  NOTE: Does NOT change health_state             │   │
│                      └─────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Health State Machine

The Health State Machine is the core of the Copilot's decision-making. It derives health from the **forward progress invariant**: "Is the cluster making forward progress on workflows?"

### Canonical States

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         HEALTH STATE MACHINE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│     ┌─────────┐                                                             │
│     │  HAPPY  │  Forward progress healthy, no concerning amplifiers         │
│     │   🟢    │  "Everything is working as expected"                        │
│     └────┬────┘                                                             │
│          │                                                                  │
│          │ amplifiers indicate pressure                                     │
│          │ (but progress continues)                                         │
│          ▼                                                                  │
│     ┌──────────┐                                                            │
│     │ STRESSED │  Forward progress continues but amplifiers show pressure   │
│     │    🟡    │  "Working, but under strain"                               │
│     └────┬─────┘                                                            │
│          │                                                                  │
│          │ forward progress impaired                                        │
│          │ (backlog growing, completions dropping)                          │
│          ▼                                                                  │
│     ┌──────────┐                                                            │
│     │ CRITICAL │  Forward progress is impaired or stopped                   │
│     │    🔴    │  "Workflows are not completing"                            │
│     └──────────┘                                                            │
│                                                                             │
│  INVARIANT: Happy → Critical transition MUST go through Stressed            │
│             (prevents over-eager critical alerts)                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### State Transition Rules (Pseudo-code)

```python
def evaluate_health_state(
    primary: PrimarySignals,
    current_state: HealthState,
    critical: CriticalThresholds | None = None,
    stressed: StressedThresholds | None = None,
    healthy: HealthyThresholds | None = None,
) -> HealthState:
    """
    Deterministic health evaluation - NO LLM INVOLVED.
    Rules are code, not prompts.
    
    NOTE: Amplifiers are NOT inputs to state transitions.
    Only primary signals (forward progress) decide state.
    Amplifiers explain WHY to the LLM later.
    """
    
    # Check CRITICAL gates first (any one triggers)
    # Signals 1/3/4/5/12: forward progress collapsed
    if _is_critical(primary, critical):
        return _apply_transition_invariant(current_state, HealthState.CRITICAL)
    
    # Check STRESSED gates (trending wrong)
    # Signals 2/4/8/11/6/10: latency + backlog trending wrong
    if _is_stressed(primary, stressed):
        return HealthState.STRESSED
    
    # Check HAPPY gates (all must pass)
    # Signals 1/4/3: throughput, backlog, completion rate all healthy
    if _is_healthy(primary, healthy):
        return HealthState.HAPPY
    
    # Default to STRESSED if between thresholds
    return HealthState.STRESSED


def _apply_transition_invariant(
    current_state: HealthState, raw_state: HealthState
) -> HealthState:
    """Happy → Critical must go through Stressed (prevents over-eager alerts)."""
    if current_state == HealthState.HAPPY and raw_state == HealthState.CRITICAL:
        return HealthState.STRESSED
    return raw_state
```

### Key Principle: Anchor to Progress, Not Pain

The state machine deliberately avoids "over-eager critical" alerts:

| Scenario | State | Rationale |
|----------|-------|-----------|
| High latency, workflows completing | STRESSED | Pain exists, but progress continues |
| Low latency, backlog growing | CRITICAL | No pain, but progress impaired |
| High latency, backlog growing | CRITICAL | Both pain and impaired progress |
| Low latency, workflows completing | HAPPY | No pain, progress healthy |

## Signal Taxonomy

Signals are classified into three categories that serve distinct purposes in health evaluation:

### Primary Signals (Decide State)

Primary signals answer the forward progress question. They are the ONLY inputs to state transitions.

**Health State Gates:**
- **CRITICAL**: Forward progress collapsed (signals 1/3/4/5) or backlog age critical
- **STRESSED**: Progress continues but latency + backlog trending wrong (signals 2/4/8/11)
- **HAPPY**: Otherwise

| # | Signal | Description | Reveals | Critical | Stressed | Healthy |
|---|--------|-------------|---------|----------|----------|---------|
| 1 | State Transition Throughput | Workflow state machine progress | Real forward progress. If drops while RPS flat, systemic trouble. | < 10/sec | - | > 50/sec |
| 2 | State Transition Latency (p99) | Early warning of contention | Often rises before anything fully breaks. | - | > 500ms | - |
| 3 | Workflow Completion Rate | Success + terminal outcomes | User-visible "is work finishing?" | < 50% | - | > 95% |
| 4 | History Backlog Age | Age of oldest pending task | Strongest predictor of cascading failures. | > 120s | > 30s | < 10s |
| 5 | History Processing Rate | Tasks processed per second | Capacity vs demand. Falling rate with steady demand is red flag. | < 10/sec | - | - |
| 6 | History Shard Churn Rate | Shard acquisitions + releases | Membership instability, deploy thrash. High churn is bad. | - | > 5/sec | - |
| 7 | Frontend Error Rate | Errors by status code | When clients are actually impacted. Often lags behind stress. | - | - | - |
| 8 | Frontend Latency (p99) | API surface degradation | Op-level breakdown helps find the hot path. | - | > 1000ms | - |
| 9 | Matching Backlog Age | Workflow + activity task queues | "Work is waiting". Separates server vs worker issues. | - | - | - |
| 10 | Poller Health | Poll success vs timeouts | Starvation and matching pressure. Catches "no poller". | - | timeout > 10% | - |
| 11 | Persistence Latency (p99) | DB operation latency | Primary systemic dependency. If slow, everything amplifies. | - | > 100ms | - |
| 12 | Persistence Error Rate | Errors and retries | "Slow but working" vs "failing". Essential for state transitions. | > 10/sec | - | - |

### Amplifier Signals (14) - Explain Why

Amplifiers explain WHY the state is what it is. They do NOT decide state—they guide the LLM's narrative and remediation suggestions.

| # | Signal | Description | Why It Matters | Remediation Direction |
|---|--------|-------------|----------------|----------------------|
| 1 | Persistence Contention | OCC conflicts, CAS failures, serialization failures | Turns load into retry storms. You'll feel it everywhere. | Tune retries/backoff, increase History capacity, review pool sizes |
| 2 | Connection Pool Saturation | In-use/max, wait count, wait duration | Creates artificial throttling + latency. Hidden "why did everything spike?" | Pool sizing, reduce churn, check token/creds refresh |
| 3 | DB Connection Churn | Opens/sec, closes/sec | Kills performance, triggers auth/token failures with short-lived creds. | Fix token caching, tune reservoir lifetime |
| 4 | Queue Depth | Task backlog size (not just age) | Age tells "lateness"; depth tells "how much work to drain". | Scale capacity, tune concurrency |
| 5 | Retry/Backoff Time | Aggregate time spent retrying | Shows how much time burned just trying again. Great "amplification meter". | Tune retry policies, fix root cause |
| 6 | Worker Saturation | Poller concurrency, task slots available/used | Even for server dashboards, tells if backlog is worker capacity issue. | Scale workers, increase concurrency limits |
| 7 | History Cache Pressure | Hit rate, evictions, size | Cache thrash increases DB reads and latency. Common silent multiplier. | Increase cache size, tune eviction policy |
| 8 | Shard Hot Spotting | Disproportionate load on subset of shards | One hot shard can dominate tail latency for whole cluster. | Rebalance shards, increase shard count |
| 9 | gRPC Saturation | In-flight requests, server-side queueing | Tail latency can be network/serialization, not DB. | Tune connection pools, check network |
| 10 | Runtime Pressure | Goroutines, blocked goroutines | Reveals internal starvation before external symptoms. | Scale instances, tune concurrency |
| 11 | Host Resource Pressure | CPU throttling, memory RSS, GC pauses | GC/heap growth in History is a classic. Shape matters. | Scale instances, tune memory limits |
| 12 | Rate Limiting Events | Internal quotas, persistence throttles | Creates "progress continues but slower" patterns that look like random latency. | Increase quotas, scale capacity |
| 13 | Log Pattern Frequency | "deadline exceeded", "context canceled", etc. | A small set of repeated log messages often explains 80% of incidents. | Address root cause indicated by pattern |
| 14 | Deploy/Scaling Churn | Task restarts, membership changes, leader changes | Change itself is an amplifier. Correlate with every spike. | Stabilize deployments, reduce churn |

### Narrative Signals (Logs Explain Transitions)

Log patterns provide narrative context for state transitions. They are fetched when state changes.

| Pattern | Service | Indicates |
|---------|---------|-----------|
| `deadline exceeded` | all | Timeout pressure |
| `context canceled` | all | Cancellation cascade |
| `shard ownership` | history | Membership instability |
| `member joined/left` | all | Ringpop membership change |
| `no poller` | matching | Worker misconfiguration |
| `reservoir discard` | history | Connection pool pressure |
| `SQLSTATE 40001` | all | OCC serialization failure |
| `rate limit exceeded` | all | DSQL connection rate limit |
| `shard acquired/released` | history | Shard ownership change |

## Worker Health Model

The Worker Health Model extends the signal taxonomy to capture worker-side health separately from server-side health. This enables the Copilot to distinguish between "server can't keep up" and "workers can't keep up" scenarios.

**Source:** Temporal Workers presentation (Tihomir Surdilovic, 2024) - treated as authoritative worker execution doctrine.

### Worker Signals (Primary)

Worker signals answer: "Can workers make forward progress?" These are collected from SDK metrics emitted by worker processes.

| # | Signal | Metric | Healthy | Stressed | Critical |
|---|--------|--------|---------|----------|----------|
| W1 | WFT Schedule-to-Start | `temporal_workflow_task_schedule_to_start_latency` | < 50ms | 50-200ms | > 200ms |
| W2 | Activity Schedule-to-Start | `temporal_activity_schedule_to_start_latency` | < 100ms | 100-500ms | > 500ms |
| W3 | Workflow Slots Available | `temporal_worker_task_slots_available{worker_type="WorkflowWorker"}` | > 50% | 10-50% | 0 |
| W4 | Activity Slots Available | `temporal_worker_task_slots_available{worker_type="ActivityWorker"}` | > 50% | 10-50% | 0 |
| W5 | Workflow Pollers | `temporal_num_pollers{poller_type="workflow_task"}` | > 0 | - | 0 |
| W6 | Activity Pollers | `temporal_num_pollers{poller_type="activity_task"}` | > 0 | - | 0 |

**Critical Threshold:** `task_slots_available == 0` means the worker stops polling entirely.

### Worker Amplifiers

Worker amplifiers explain WHY worker health is degraded.

| # | Signal | Metric | Why It Matters |
|---|--------|--------|----------------|
| WA1 | Sticky Cache Size | `temporal_sticky_cache_size` | Large cache = memory pressure, small cache = replay overhead |
| WA2 | Sticky Cache Hit Rate | `temporal_sticky_cache_hit / (hit + miss)` | Low hit rate = excessive history replay, DB reads |
| WA3 | Sticky Cache Miss Rate | `rate(temporal_sticky_cache_miss[1m])` | High miss rate = workflow state not cached |
| WA4 | Long Poll Latency | `temporal_long_request_latency` | High latency = network/service pressure |
| WA5 | Long Poll Failures | `temporal_long_request_failure` | Failures = connectivity issues |
| WA6 | Poller/Executor Mismatch | pollers > executor slots | "Makes no sense to configure more pollers than executor slots" |

### Bottleneck Classification

The Copilot classifies bottlenecks to guide remediation:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      BOTTLENECK CLASSIFICATION                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Assess Server Health (existing model)                                   │
│     ├─ If CRITICAL → stop (worker advice irrelevant)                        │
│     └─ If HAPPY/STRESSED → continue to step 2                               │
│                                                                             │
│  2. Assess Worker Readiness                                                 │
│     ├─ Slots available?                                                     │
│     ├─ Schedule-to-start latency?                                           │
│     ├─ Poll success vs empty?                                               │
│     └─ Cache miss rate?                                                     │
│                                                                             │
│  3. Classify Bottleneck                                                     │
│     ├─ SERVER_LIMITED: Server can't keep up                                 │
│     │   - High backlog age, persistence latency                             │
│     │   - Workers are idle or underutilized                                 │
│     │                                                                       │
│     ├─ WORKER_LIMITED: Workers can't keep up                                │
│     │   - Slots exhausted, high schedule-to-start                           │
│     │   - Server backlog is low                                             │
│     │                                                                       │
│     ├─ MIXED: Both under pressure                                           │
│     │   - Server backlog AND worker saturation                              │
│     │                                                                       │
│     └─ HEALTHY: Neither constrained                                         │
│                                                                             │
│  4. Generate Explanation + Remediation                                      │
│     └─ LLM explains classification with worker-specific guidance            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Classification Logic (Deterministic)

```python
class BottleneckClassification(str, Enum):
    SERVER_LIMITED = "server_limited"
    WORKER_LIMITED = "worker_limited"
    MIXED = "mixed"
    HEALTHY = "healthy"

def classify_bottleneck(
    primary: PrimarySignals,
    worker: WorkerSignals
) -> BottleneckClassification:
    """
    Classify whether bottleneck is server-side or worker-side.
    This is DETERMINISTIC - no LLM involved.
    """
    server_stressed = (
        primary.history.backlog_age_sec > 30 or
        primary.persistence.latency_p95_ms > 100
    )
    
    worker_stressed = (
        worker.workflow_slots_available == 0 or
        worker.activity_slots_available == 0 or
        worker.wft_schedule_to_start_p95_ms > 50
    )
    
    if server_stressed and worker_stressed:
        return BottleneckClassification.MIXED
    elif server_stressed:
        return BottleneckClassification.SERVER_LIMITED
    elif worker_stressed:
        return BottleneckClassification.WORKER_LIMITED
    else:
        return BottleneckClassification.HEALTHY
```

### Worker Scaling Warnings (Deterministic Rules)

These rules are encoded deterministically and NEVER violated:

| Rule | Condition | Action | Rationale |
|------|-----------|--------|-----------|
| **NEVER_SCALE_DOWN_AT_ZERO** | `task_slots_available == 0` | Block scale-down | Scaling down worsens backlog |
| **STICKY_QUEUE_WARNING** | Long-running workflows with updates | Warn about redistribution | New workers won't get sticky work |
| **RESTART_TO_REDISTRIBUTE** | Sticky imbalance detected | Suggest rolling restart | Redistributes workflow state |
| **POLLER_EXECUTOR_MISMATCH** | pollers > executor slots | Warn about misconfiguration | Pollers should not exceed slots |

### Worker Remediation Guidance (RAG)

The following remediation patterns are encoded in the RAG knowledge base:

```yaml
# docs/rag/worker_scaling.md
topic: worker_scaling
symptoms:
  - temporal_worker_task_slots_available == 0
  - schedule_to_start_latency > 50ms
explanation: |
  Worker stops polling when all executor slots are occupied.
  Scaling down workers in this state worsens backlog.
  Sticky queues prevent new workers from getting long-running workflow work.
recommended_actions:
  - Increase activity executor slots (MaxConcurrentActivityExecutionSize)
  - Scale up workers
  - Investigate blocking/zombie activities
  - Consider restarting % of existing workers to redistribute sticky work
warnings:
  - NEVER scale down when task_slots_available == 0
source: "Temporal Workers presentation (Tihomir Surdilovic, 2024)"
```

```yaml
# docs/rag/sticky_cache_tuning.md
topic: sticky_cache
symptoms:
  - temporal_sticky_cache_miss rate high
  - workflow_task_replay_latency elevated
explanation: |
  Sticky cache stores workflow state to avoid replaying history.
  Cache misses cause full history replay, increasing DB reads and latency.
  Cache eviction under memory pressure amplifies this effect.
recommended_actions:
  - Increase MaxConcurrentWorkflowTaskExecutionSize (cache size)
  - Monitor memory usage vs cache size
  - Consider workflow design (smaller histories)
thresholds:
  - cache_hit_rate < 80%: investigate
  - cache_hit_rate < 50%: critical
source: "Temporal Workers presentation (Tihomir Surdilovic, 2024)"
```

```yaml
# docs/rag/poller_configuration.md
topic: poller_configuration
symptoms:
  - pollers > executor slots
  - poll_success rate low
explanation: |
  "Makes no sense to configure more pollers than executor slots."
  Excess pollers waste resources and don't improve throughput.
  Pollers should be significantly less than executor slots.
recommended_actions:
  - Set MaxConcurrentWorkflowTaskPollers < MaxConcurrentWorkflowTaskExecutionSize
  - Set MaxConcurrentActivityTaskPollers < MaxConcurrentActivityExecutionSize
  - Typical ratio: pollers = 10-20% of executor slots
source: "Temporal Workers presentation (Tihomir Surdilovic, 2024)"
```

## Components and Interfaces

### 1. Copilot Worker Service

The worker service hosts Pydantic AI workflows that perform monitoring and analysis.

#### Workflow: ObserveClusterWorkflow

Continuously observes cluster signals and triggers health assessment when state changes.

```python
from temporalio import workflow
from whenever import TimeDelta

@workflow.defn
class ObserveClusterWorkflow:
    """Continuous signal observation with health state evaluation."""
    
    @workflow.run
    async def run(self, input: ObserveClusterInput) -> None:
        current_state = HealthState.HAPPY
        
        while True:
            # Fetch current signals from AMP
            signals = await workflow.execute_activity(
                fetch_signals_from_amp,
                args=[input.amp_endpoint],
                start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
            )
            
            # Store signals in sliding window
            await workflow.execute_activity(
                store_signals_snapshot,
                args=[signals, input.dsql_endpoint],
                start_to_close_timeout=TimeDelta(seconds=10).py_timedelta(),
            )
            
            # DETERMINISTIC: Evaluate health state (no LLM)
            # NOTE: Only primary signals decide state. Amplifiers are NOT inputs.
            new_state = evaluate_health_state(
                signals.primary,
                current_state,
            )
            
            # Trigger assessment if state changed
            if new_state != current_state:
                await workflow.start_child_workflow(
                    "AssessHealthWorkflow",
                    args=[AssessHealthInput(
                        health_state=new_state,
                        signals=signals,
                        trigger="state_change",
                        dsql_endpoint=input.dsql_endpoint,
                    )],
                    id=f"assess-health-{workflow.now().isoformat()}"
                )
                current_state = new_state
            
            await workflow.sleep(TimeDelta(seconds=30).py_timedelta())
```


#### Workflow: LogWatcherWorkflow

Continuously scans Loki for error patterns (narrative signals).

```python
@workflow.defn
class LogWatcherWorkflow:
    """Continuous log monitoring for narrative signals."""
    
    @workflow.run
    async def run(self, input: LogWatcherInput) -> None:
        while True:
            # Query Loki for error patterns
            log_events = await workflow.execute_activity(
                query_loki_errors,
                args=[input.loki_url],
                start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
            )
            
            # Detect error patterns (narrative signals)
            patterns = detect_error_patterns(log_events, ERROR_PATTERNS)
            
            if patterns:
                # Store patterns for correlation with health assessments
                await workflow.execute_activity(
                    store_log_patterns,
                    args=[patterns],
                    start_to_close_timeout=TimeDelta(seconds=10).py_timedelta(),
                )
            
            await workflow.sleep(TimeDelta(seconds=30).py_timedelta())
```

#### Workflow: AssessHealthWorkflow

LLM-powered explanation of health state. Following "Rules decide, AI explains" principle.

```python
from pydantic_ai import Agent
from pydantic import BaseModel
from typing import List, Optional, Union

# Dispatcher agent - fast, lightweight triage
# NOTE: Receives health_state that was ALREADY DECIDED by rules
class NoExplanationNeeded(BaseModel):
    """State is clear, no detailed explanation required."""
    reason: str

class QuickExplanation(BaseModel):
    """Simple explanation without deep analysis."""
    summary: str

class NeedsDeepExplanation(BaseModel):
    """Complex situation, delegate to research agent for detailed explanation."""
    contributing_factors: List[str]
    priority: str  # low, medium, high

DispatcherOutput = Union[NoExplanationNeeded, QuickExplanation, NeedsDeepExplanation]

dispatcher_agent = Agent(
    'bedrock:eu.anthropic.claude-sonnet-4-5-20250929-v1:0',  # Fast, cost-effective
    instructions="""You are a quick triage agent for Temporal health explanation.
    
    IMPORTANT: The health state has ALREADY BEEN DECIDED by deterministic rules.
    Your job is to decide how much explanation is needed, NOT to change the state.
    
    Given the health state and signals, determine:
    1. NoExplanationNeeded - state is obvious from signals, no explanation needed
    2. QuickExplanation - provide brief summary of why state is what it is
    3. NeedsDeepExplanation - complex situation, delegate for detailed analysis
    
    Be fast and decisive. Only escalate when truly needed.""",
    result_type=DispatcherOutput,
    name='health_dispatcher'
)

# Research agent - thorough explanation with RAG
# NOTE: Does NOT change health_state - only explains it
class Issue(BaseModel):
    severity: str  # warning, critical
    title: str
    description: str
    likely_cause: str
    suggested_actions: List[SuggestedAction]
    related_signals: List[str]

class HealthAssessment(BaseModel):
    timestamp: str
    health_state: str  # Passed in, NOT decided by LLM
    primary_signals: dict
    amplifiers: dict
    log_patterns: List[dict]
    issues: List[Issue]
    recommended_actions: List[dict]
    natural_language_summary: str

research_agent = Agent(
    'bedrock:eu.anthropic.claude-opus-4-6-v1',  # Most capable for deep analysis
    instructions="""You are an SRE expert EXPLAINING Temporal service health.
    
    CRITICAL: The health state has ALREADY BEEN DECIDED by deterministic rules.
    You MUST NOT change the health_state. Your job is to EXPLAIN it.
    
    Given the health state, signals, logs, and context from the knowledge base:
    1. Explain WHY the cluster is in this state
    2. Rank contributing factors by importance
    3. Suggest remediation actions with confidence scores
    
    Be concise but thorough. Focus on actionable insights.""",
    result_type=HealthAssessment,
    name='health_explainer'
)

temporal_dispatcher = TemporalAgent(dispatcher_agent)
temporal_researcher = TemporalAgent(research_agent)

@workflow.defn
class AssessHealthWorkflow(PydanticAIWorkflow):
    """LLM-powered health explanation. Rules decide, AI explains."""
    __pydantic_ai_agents__ = [temporal_dispatcher, temporal_researcher]
    
    @workflow.run
    async def run(
        self, 
        health_state: HealthState,  # ALREADY DECIDED by rules
        signals: Signals, 
        trigger: str
    ) -> HealthAssessment:
        # First, run dispatcher for fast triage
        dispatch_result = await temporal_dispatcher.run(
            f"Health State: {health_state}\n"
            f"Primary Signals: {signals.primary}\n"
            f"Amplifiers: {signals.amplifiers}\n"
            f"Trigger: {trigger}"
        )
        
        # Handle dispatcher output
        if isinstance(dispatch_result.output, NoExplanationNeeded):
            # Return minimal assessment
            return create_minimal_assessment(health_state, signals)
        
        if isinstance(dispatch_result.output, QuickExplanation):
            # Return quick assessment
            return create_quick_assessment(
                health_state,
                signals,
                dispatch_result.output.summary
            )
        
        # NeedsDeepExplanation - run the research agent
        # Fetch RAG context based on contributing factors
        context = await workflow.execute_activity(
            fetch_rag_context,
            args=[dispatch_result.output.contributing_factors],
            start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
        )
        
        # Fetch recent log patterns (narrative signals)
        log_patterns = await workflow.execute_activity(
            fetch_recent_log_patterns,
            start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
        )
        
        # Fetch signal history
        history = await workflow.execute_activity(
            fetch_signal_history,
            start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
        )
        
        # Build prompt with all context
        # NOTE: health_state is passed in, NOT decided by LLM
        prompt = build_explanation_prompt(
            health_state,  # Already decided
            signals, 
            log_patterns, 
            context, 
            history
        )
        
        # Run deep explanation via research agent
        result = await temporal_researcher.run(prompt)
        
        # Ensure health_state wasn't changed by LLM
        result.output.health_state = health_state.value
        
        # Store assessment
        await workflow.execute_activity(
            store_health_assessment,
            args=[result.output],
            start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
        )
        
        return result.output
```


#### Workflow: ScheduledAssessmentWorkflow

Periodic health assessment even without state changes.

```python
@workflow.defn
class ScheduledAssessmentWorkflow:
    """Scheduled periodic health assessment."""
    
    @workflow.run
    async def run(self, input: ScheduledAssessmentInput) -> None:
        while True:
            # Check if recent assessment exists (avoid duplicate work)
            recent = await workflow.execute_activity(
                check_recent_assessment,
                args=[TimeDelta(minutes=4), input.dsql_endpoint],
                start_to_close_timeout=TimeDelta(seconds=10).py_timedelta(),
            )
            
            if not recent:
                # Fetch current signals
                signals = await workflow.execute_activity(
                    fetch_signals_from_amp,
                    args=[input.amp_endpoint],
                    start_to_close_timeout=TimeDelta(seconds=30).py_timedelta(),
                )
                
                # Evaluate health state (deterministic)
                # NOTE: Only primary signals decide state. No amplifiers.
                health_state = evaluate_health_state(
                    signals.primary,
                    HealthState.HAPPY,  # Default for scheduled
                )
                
                await workflow.start_child_workflow(
                    "AssessHealthWorkflow",
                    args=[AssessHealthInput(
                        health_state=health_state,
                        signals=signals,
                        trigger="scheduled",
                        dsql_endpoint=input.dsql_endpoint,
                    )],
                    id=f"scheduled-assessment-{workflow.now().isoformat()}"
                )
            
            await workflow.sleep(TimeDelta(minutes=5).py_timedelta())
```

### 2. Activities

Activities perform I/O operations and are automatically retried by Temporal on failure.

```python
from temporalio import activity
import boto3
import httpx

@activity.defn
async def fetch_metrics_from_amp() -> dict:
    """Query Amazon Managed Prometheus for current metrics."""
    client = boto3.client('amp')
    
    queries = {
        # Reservoir metrics
        'reservoir_size': 'sum(dsql_reservoir_size)',
        'reservoir_target': 'sum(dsql_reservoir_target)',
        'reservoir_empty': 'sum(increase(dsql_reservoir_empty_total[5m]))',
        'checkout_p95_ms': 'histogram_quantile(0.95, sum by (le) (rate(dsql_reservoir_checkout_latency_milliseconds_bucket[1m])))',
        
        # Service metrics
        'service_error_rate': 'sum(rate(service_error_with_type_total[1m]))',
        'persistence_latency_p95': 'histogram_quantile(0.95, sum by (le) (rate(persistence_latency_bucket[5m]))) * 1000',
        
        # History metrics
        'task_latency_p95': 'histogram_quantile(0.95, sum by (le) (rate(task_latency_processing_bucket{service_name="history"}[5m]))) * 1000',
        'shard_churn': 'sum(rate(sharditem_created_count_total[5m])) + sum(rate(sharditem_removed_count_total[5m]))',
        
        # Workflow metrics
        'workflow_success_rate': 'sum(rate(workflow_success_total[1m]))',
        'workflow_failure_rate': 'sum(rate(workflow_failed_total[1m]))',
        
        # OCC metrics
        'occ_conflicts': 'sum(rate(dsql_tx_conflict_total[1m]))',
        
        # Worker metrics
        'schedule_to_start_p95': 'histogram_quantile(0.95, sum(rate(temporal_workflow_task_schedule_to_start_latency_bucket[1m])) by (le)) * 1000',
        'workflow_slots_available': 'sum(temporal_worker_task_slots_available{worker_type="WorkflowWorker"})',
        'activity_slots_available': 'sum(temporal_worker_task_slots_available{worker_type="ActivityWorker"})',
    }
    
    results = {}
    for name, query in queries.items():
        response = await query_prometheus(client, query)
        results[name] = parse_prometheus_response(response)
    
    return results

@activity.defn
async def query_loki_errors() -> List[dict]:
    """Query Loki for error log patterns."""
    async with httpx.AsyncClient() as client:
        now = Instant.now()
        window_start = now - TimeDelta(seconds=30)
        # Query for error-level logs in last 30 seconds
        response = await client.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                'query': '{job=~"temporal.*"} |= "error" or |= "ERROR"',
                'start': window_start.format_common_iso(),
                'end': now.format_common_iso(),
                'limit': 100
            }
        )
        return parse_loki_response(response.json())

@activity.defn
async def fetch_rag_context(anomalies: List[dict]) -> List[str]:
    """Retrieve relevant documentation from Bedrock Knowledge Base."""
    # Build query from anomaly descriptions
    query_text = " ".join([a['description'] for a in anomalies])
    
    bedrock_agent = boto3.client('bedrock-agent-runtime')
    
    response = bedrock_agent.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={
            'text': query_text
        },
        retrievalConfiguration={
            'vectorSearchConfiguration': {
                'numberOfResults': 5
            }
        }
    )
    
    # Extract text content from results
    return [
        result['content']['text'] 
        for result in response['retrievalResults']
    ]
```


### 3. API Service

FastAPI service exposing health assessments to Grafana. Follows "Grafana consumes, not computes" principle.

```python
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from whenever import Instant, TimeDelta
from typing import Optional

app = FastAPI(title="Temporal SRE Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Grafana access
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/status")
async def get_status() -> dict:
    """Current health status with signal taxonomy. Grafana consumes, not computes."""
    assessment = await get_latest_assessment()
    return {
        "health_state": assessment.health_state,
        "timestamp": assessment.timestamp,
        "primary_signals": assessment.primary_signals,
        "amplifiers": assessment.amplifiers,
        "log_patterns": assessment.log_patterns,
        "recommended_actions": assessment.recommended_actions,
        "issue_count": len(assessment.issues)
    }

@app.get("/status/services")
async def get_services() -> dict:
    """Per-service health status for Grafana grid."""
    assessment = await get_latest_assessment()
    # Derive service health from signals (pre-computed)
    return {
        "services": [
            {
                "name": "history",
                "status": derive_service_status("history", assessment),
                "key_signals": extract_service_signals("history", assessment)
            },
            {
                "name": "matching",
                "status": derive_service_status("matching", assessment),
                "key_signals": extract_service_signals("matching", assessment)
            },
            {
                "name": "frontend",
                "status": derive_service_status("frontend", assessment),
                "key_signals": extract_service_signals("frontend", assessment)
            },
            {
                "name": "persistence",
                "status": derive_service_status("persistence", assessment),
                "key_signals": extract_service_signals("persistence", assessment)
            }
        ]
    }

@app.get("/status/issues")
async def get_issues(
    severity: Optional[str] = None,
    limit: int = Query(default=10, le=100)
) -> dict:
    """Active issues list with contributing factors."""
    assessment = await get_latest_assessment()
    issues = assessment.issues
    
    if severity:
        issues = [i for i in issues if i.severity == severity]
    
    return {
        "issues": [
            {
                "severity": i.severity,
                "title": i.title,
                "description": i.description,
                "likely_cause": i.likely_cause,
                "suggested_actions": [
                    {"action": a.description, "confidence": a.confidence}
                    for a in i.suggested_actions
                ],
                "related_signals": i.related_signals
            }
            for i in issues[:limit]
        ]
    }

@app.get("/status/summary")
async def get_summary() -> dict:
    """Natural language summary for Grafana text panel."""
    assessment = await get_latest_assessment()
    return {
        "summary": assessment.natural_language_summary,
        "timestamp": assessment.timestamp,
        "health_state": assessment.health_state
    }

@app.get("/status/timeline")
async def get_timeline(
    start: Optional[str] = None,
    end: Optional[str] = None
) -> dict:
    """Health status changes over time for Grafana state timeline."""
    if not start:
        start_instant = Instant.now() - TimeDelta(hours=24)
    else:
        start_instant = Instant.parse_common_iso(start)
    if not end:
        end_instant = Instant.now()
    else:
        end_instant = Instant.parse_common_iso(end)
    
    assessments = await get_assessments_in_range(start_instant, end_instant)
    
    return {
        "timeline": [
            {
                "timestamp": a.timestamp,
                "health_state": a.health_state,
                "issue_count": len(a.issues),
                "primary_signals": a.primary_signals
            }
            for a in assessments
        ]
    }

@app.post("/actions")
async def execute_action() -> dict:
    """Future: Execute remediation action. Currently returns 501."""
    return {"error": "Not implemented", "status": 501}
```

### 4. RAG Knowledge Base

The knowledge base uses Amazon Bedrock Knowledge Bases for fully managed RAG. This eliminates the need for pgvector (which DSQL doesn't support) and provides automatic chunking, embedding, and retrieval.

#### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    BEDROCK KNOWLEDGE BASE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐     ┌─────────────────────┐     ┌───────────────┐ │
│  │  S3 Data Source     │────▶│  Bedrock KB         │────▶│  S3 Vectors   │ │
│  │                     │     │  (managed)          │     │  (storage)    │ │
│  │  - AGENTS.md        │     │                     │     │               │ │
│  │  - docs/dsql/*.md   │     │  - Auto chunking    │     │  - Low cost   │ │
│  │  - Dashboard guides │     │  - Titan Embed V2   │     │  - Scalable   │ │
│  │  - Runbooks         │     │  - Sync on update   │     │               │ │
│  └─────────────────────┘     └─────────────────────┘     └───────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Terraform Configuration

```hcl
# S3 bucket for knowledge base source documents
resource "aws_s3_bucket" "copilot_kb_source" {
  bucket = "${var.project_name}-copilot-kb-source"
}

# Bedrock Knowledge Base
resource "aws_bedrockagent_knowledge_base" "copilot" {
  name        = "${var.project_name}-copilot-kb"
  description = "Knowledge base for Temporal SRE Copilot"
  role_arn    = aws_iam_role.bedrock_kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }

  storage_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = aws_s3_bucket.copilot_kb_vectors.arn
    }
  }
}

# S3 data source for the knowledge base
resource "aws_bedrockagent_data_source" "copilot_docs" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.copilot.id
  name              = "copilot-documentation"
  
  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = aws_s3_bucket.copilot_kb_source.arn
    }
  }
}
```

#### Activity for RAG Retrieval

```python
@activity.defn
async def fetch_rag_context(anomalies: List[dict]) -> List[str]:
    """Retrieve relevant documentation from Bedrock Knowledge Base."""
    # Build query from anomaly descriptions
    query_text = " ".join([a['description'] for a in anomalies])
    
    bedrock_agent = boto3.client('bedrock-agent-runtime')
    
    response = bedrock_agent.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={
            'text': query_text
        },
        retrievalConfiguration={
            'vectorSearchConfiguration': {
                'numberOfResults': 5
            }
        }
    )
    
    # Extract text content from results
    return [
        result['content']['text'] 
        for result in response['retrievalResults']
    ]
```

#### Document Sync

Documents are synced to S3 and the knowledge base is updated:

```python
async def sync_knowledge_base() -> None:
    """Sync documentation to S3 and trigger KB ingestion."""
    s3 = boto3.client('s3')
    bedrock_agent = boto3.client('bedrock-agent')
    
    # Upload documents to S3
    sources = [
        ('temporal-dsql-deploy-ecs/AGENTS.md', 'AGENTS.md'),
        ('temporal-dsql/docs/dsql/overview.md', 'docs/dsql/overview.md'),
        ('temporal-dsql/docs/dsql/reservoir-design.md', 'docs/dsql/reservoir-design.md'),
    ]
    
    for local_path, s3_key in sources:
        with open(local_path, 'rb') as f:
            s3.upload_fileobj(f, KB_SOURCE_BUCKET, s3_key)
    
    # Trigger knowledge base sync
    bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=DATA_SOURCE_ID
    )
```


## Data Models

### Health Assessment Schema

```sql
CREATE TABLE health_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger VARCHAR(50) NOT NULL,  -- 'anomaly', 'log_error', 'scheduled'
    overall_status VARCHAR(20) NOT NULL,  -- 'happy', 'stressed', 'critical'
    services JSONB NOT NULL,
    issues JSONB NOT NULL,
    natural_language_summary TEXT NOT NULL,
    metrics_snapshot JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ASYNC idx_assessments_timestamp ON health_assessments(timestamp DESC);
CREATE INDEX ASYNC idx_assessments_status ON health_assessments(overall_status);

-- Issues table for efficient querying
CREATE TABLE issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id UUID REFERENCES health_assessments(id) ON DELETE CASCADE,
    severity VARCHAR(20) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT NOT NULL,
    likely_cause TEXT,
    suggested_actions JSONB,
    related_metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX ASYNC idx_issues_severity ON issues(severity);
CREATE INDEX ASYNC idx_issues_created ON issues(created_at DESC);

-- Metrics snapshots for trend analysis
CREATE TABLE metrics_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metrics JSONB NOT NULL
);

CREATE INDEX ASYNC idx_snapshots_timestamp ON metrics_snapshots(timestamp DESC);
```

> **Known Gap:** The `get_latest_assessment` activity in `activities/state_store.py` does not reconstruct issues from the `issues` table — it returns empty lists for `issues` and `recommended_actions`. This means API responses for `/status/issues` will return empty results until this is addressed. The fix requires a JOIN query or a secondary fetch from the `issues` table keyed by `assessment_id`.

### Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from whenever import Instant
from enum import Enum

class HealthState(str, Enum):
    """Canonical health states derived from forward progress."""
    HAPPY = "happy"      # Forward progress healthy, no concerning amplifiers
    STRESSED = "stressed"  # Progress continues but amplifiers indicate pressure
    CRITICAL = "critical"  # Forward progress is impaired or stopped

class Severity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"

class ActionType(str, Enum):
    SCALE = "scale"
    RESTART = "restart"
    CONFIGURE = "configure"
    ALERT = "alert"

class SuggestedAction(BaseModel):
    action_type: ActionType
    target_service: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    parameters: Optional[dict] = None
    risk_level: str = "low"  # low, medium, high

class Issue(BaseModel):
    severity: Severity
    title: str
    description: str
    likely_cause: str
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    related_signals: list[str] = Field(default_factory=list)
    related_logs: Optional[list[str]] = None

# ---------------------------------------------------------------------------
# PRIMARY SIGNALS (12) - Decide Health State
# Organized into 7 sub-models matching the signal taxonomy
# ---------------------------------------------------------------------------

class StateTransitionSignals(BaseModel):
    """Signals 1-2: State transition throughput and latency."""
    throughput_per_sec: float = Field(ge=0)
    latency_p95_ms: float = Field(ge=0)
    latency_p99_ms: float = Field(ge=0)

class WorkflowCompletionSignals(BaseModel):
    """Signal 3: Workflow completion rate."""
    completion_rate: float = Field(ge=0, le=1)
    success_per_sec: float = Field(ge=0)
    failed_per_sec: float = Field(ge=0)

class HistorySignals(BaseModel):
    """Signals 4-6: History service health."""
    backlog_age_sec: float = Field(ge=0)
    task_processing_rate_per_sec: float = Field(ge=0)
    shard_churn_rate_per_sec: float = Field(ge=0)

class FrontendSignals(BaseModel):
    """Signals 7-8: Frontend service health."""
    error_rate_per_sec: float = Field(ge=0)
    latency_p95_ms: float = Field(ge=0)
    latency_p99_ms: float = Field(ge=0)

class MatchingSignals(BaseModel):
    """Signal 9: Matching service health."""
    workflow_backlog_age_sec: float = Field(ge=0)
    activity_backlog_age_sec: float = Field(ge=0)

class PollerSignals(BaseModel):
    """Signal 10: Poller health."""
    poll_success_rate: float = Field(ge=0, le=1)
    poll_timeout_rate: float = Field(ge=0, le=1)
    long_poll_latency_ms: float = Field(ge=0)

class PersistenceSignals(BaseModel):
    """Signals 11-12: Persistence health."""
    latency_p95_ms: float = Field(ge=0)
    latency_p99_ms: float = Field(ge=0)
    error_rate_per_sec: float = Field(ge=0)
    retry_rate_per_sec: float = Field(ge=0)

class PrimarySignals(BaseModel):
    """All 12 primary signals that decide health state.
    These are the ONLY inputs to state transitions."""
    state_transitions: StateTransitionSignals
    workflow_completion: WorkflowCompletionSignals
    history: HistorySignals
    frontend: FrontendSignals
    matching: MatchingSignals
    poller: PollerSignals
    persistence: PersistenceSignals

# ---------------------------------------------------------------------------
# AMPLIFIER SIGNALS (14) - Explain Why
# Organized into 11 sub-models matching the signal taxonomy
# ---------------------------------------------------------------------------

class PersistenceAmplifiers(BaseModel):
    """Amplifier 1: Persistence contention."""
    occ_conflicts_per_sec: float = Field(ge=0)
    cas_failures_per_sec: float = Field(ge=0)
    serialization_failures_per_sec: float = Field(ge=0)

class ConnectionPoolAmplifiers(BaseModel):
    """Amplifiers 2-3: Connection pool health."""
    utilization_pct: float = Field(ge=0, le=100)
    wait_count: int = Field(ge=0)
    wait_duration_ms: float = Field(ge=0)
    churn_rate_per_sec: float = Field(ge=0)
    opens_per_sec: float = Field(ge=0)
    closes_per_sec: float = Field(ge=0)

class QueueAmplifiers(BaseModel):
    """Amplifiers 4-5: Queue depth and retry pressure."""
    task_backlog_depth: int = Field(ge=0)
    retry_time_spent_sec: float = Field(ge=0)

class WorkerAmplifiers(BaseModel):
    """Amplifier 6: Worker-side saturation."""
    poller_concurrency: int = Field(ge=0)
    task_slots_available: int = Field(ge=0)
    task_slots_used: int = Field(ge=0)

class CacheAmplifiers(BaseModel):
    """Amplifier 7: History cache pressure."""
    hit_rate: float = Field(ge=0, le=1)
    evictions_per_sec: float = Field(ge=0)
    size_bytes: int = Field(ge=0)

class ShardAmplifiers(BaseModel):
    """Amplifier 8: Shard-level hot spotting."""
    hot_shard_ratio: float = Field(ge=0)
    max_shard_load_pct: float = Field(ge=0, le=100)

class GrpcAmplifiers(BaseModel):
    """Amplifier 9: gRPC saturation."""
    in_flight_requests: int = Field(ge=0)
    server_queue_depth: int = Field(ge=0)

class RuntimeAmplifiers(BaseModel):
    """Amplifier 10: Thread/goroutine pool pressure."""
    goroutines: int = Field(ge=0)
    blocked_goroutines: int = Field(ge=0)

class HostAmplifiers(BaseModel):
    """Amplifier 11: Host resource pressure."""
    cpu_throttle_pct: float = Field(ge=0, le=100)
    memory_rss_bytes: int = Field(ge=0)
    gc_pause_ms: float = Field(ge=0)

class ThrottlingAmplifiers(BaseModel):
    """Amplifier 12: Rate limiting / throttling events."""
    rate_limit_events_per_sec: float = Field(ge=0)
    admission_rejects_per_sec: float = Field(ge=0)

class DeployAmplifiers(BaseModel):
    """Amplifier 14: Deploy / scaling churn markers."""
    task_restarts: int = Field(ge=0)
    membership_changes_per_min: float = Field(ge=0)
    leader_changes_per_min: float = Field(ge=0)

class AmplifierSignals(BaseModel):
    """All 14 amplifier signals that explain why state changed.
    Amplifiers do NOT decide state—they provide context for explanation."""
    persistence: PersistenceAmplifiers
    connection_pool: ConnectionPoolAmplifiers
    queue: QueueAmplifiers
    worker: WorkerAmplifiers
    cache: CacheAmplifiers
    shard: ShardAmplifiers
    grpc: GrpcAmplifiers
    runtime: RuntimeAmplifiers
    host: HostAmplifiers
    throttling: ThrottlingAmplifiers
    deploy: DeployAmplifiers

# ---------------------------------------------------------------------------
# NARRATIVE SIGNALS
# ---------------------------------------------------------------------------

class LogPattern(BaseModel):
    """Narrative signal from logs."""
    count: int = Field(ge=0)
    pattern: str
    service: str
    sample_message: Optional[str] = None

# ---------------------------------------------------------------------------
# COMBINED SIGNALS
# ---------------------------------------------------------------------------

class Signals(BaseModel):
    """Complete signal collection with taxonomy."""
    primary: PrimarySignals
    amplifiers: AmplifierSignals
    timestamp: Instant = Field(default_factory=Instant.now)

    class Config:
        arbitrary_types_allowed = True

class HealthAssessment(BaseModel):
    """
    Health assessment with signal taxonomy.
    NOTE: health_state is determined by rules, NOT by LLM.
    """
    timestamp: Instant = Field(default_factory=Instant.now)
    trigger: str  # 'state_change', 'scheduled'
    health_state: HealthState  # Determined by rules, passed to LLM
    primary_signals: dict
    amplifiers: dict
    log_patterns: list[LogPattern] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    recommended_actions: list[SuggestedAction] = Field(default_factory=list)
    natural_language_summary: str

    class Config:
        arbitrary_types_allowed = True
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Signal Classification Correctness

*For any* set of signals collected from AMP, primary signals SHALL be forward progress indicators (state transitions, completions, backlog age) and amplifier signals SHALL be resource pressure indicators (latency, conflicts, utilization).

**Validates: Requirements 1.2, 1.3**

### Property 2: Sliding Window Invariant

*For any* sequence of signal snapshots added to the sliding window, the window SHALL contain only the most recent N snapshots (where N is the configured window size), and older snapshots SHALL be evicted in FIFO order.

**Validates: Requirements 1.6**

### Property 3: Log Pattern Detection

*For any* set of log entries containing error patterns, the pattern detection function SHALL identify all matching patterns as narrative signals.

**Validates: Requirements 2.2, 2.3**

### Property 4: Log-Signal Correlation

*For any* set of log events and signal snapshots with timestamps, the correlation function SHALL associate log events with signal snapshots if and only if their timestamps are within the configured proximity window.

**Validates: Requirements 2.5**

### Property 5: RAG Semantic Retrieval

*For any* contributing factor description, the RAG system SHALL return at most 5 documents, and all returned documents SHALL have a semantic similarity score above the configured threshold, ordered by descending similarity. Retrieved documents SHALL NOT contain raw metrics or PromQL queries.

**Validates: Requirements 3.2, 3.3, 3.4, 3.6**

### Property 6: Health Assessment Structure Round-Trip

*For any* valid HealthAssessment object, serializing to JSON and deserializing back SHALL produce an equivalent object with all required fields (timestamp, health_state, primary_signals, amplifiers, log_patterns, recommended_actions, natural_language_summary).

**Validates: Requirements 4.3**

### Property 7: Prompt Construction Completeness

*For any* AssessHealthWorkflow invocation with health_state, signals, logs, and context, the constructed prompt SHALL include the pre-determined health_state and all provided inputs, and SHALL NOT include any values matching sensitive data patterns (credentials, API keys, PII).

**Validates: Requirements 4.5, 4.9**

### Property 8: State Store Round-Trip

*For any* valid HealthAssessment stored in the state store, querying by timestamp range SHALL return the assessment if and only if its timestamp falls within the queried range.

**Validates: Requirements 5.2, 5.4**

### Property 9: API Response Format

*For any* API endpoint response, the response SHALL conform to the signal taxonomy structure (health_state, primary_signals, amplifiers, log_patterns, recommended_actions), include all required fields for the endpoint type, and correctly filter by any provided query parameters (severity, time range, limit).

**Validates: Requirements 6.1, 6.2, 6.3**

### Property 10: Assessment Deduplication

*For any* scheduled assessment trigger, if an assessment was completed within the deduplication window, the scheduled trigger SHALL NOT initiate a new assessment.

**Validates: Requirements 9.5**

### Property 11: Suggested Action Structure

*For any* issue in a health assessment, all suggested actions SHALL include action_type, target_service, description, confidence, and risk_level fields to support future automation.

**Validates: Requirements 10.2**

### Property 12: Health State Machine Invariants

*For any* sequence of signal observations, the Health State Machine SHALL:
1. Derive state from forward progress invariant ("Is the cluster making forward progress?")
2. Never transition directly from Happy to Critical (Stressed is always intermediate)
3. Produce deterministic state for identical inputs (no LLM involvement in state transitions)

**Validates: Requirements 12.2, 12.3, 12.5**

## Error Handling

### Metric Ingestion Failures

- **AMP Query Timeout**: Log error, skip cycle, retry on next iteration
- **AMP Authentication Failure**: Log error, alert, continue with cached metrics
- **Invalid Metric Response**: Log warning, use default/zero value for affected metric

### Log Query Failures

- **Loki Unavailable**: Log error, continue with metric-only analysis
- **Loki Query Timeout**: Log warning, proceed without log context
- **Invalid Log Format**: Skip malformed entries, continue processing

### LLM Analysis Failures

- **Bedrock Timeout**: Retry with exponential backoff (max 3 attempts)
- **Bedrock Rate Limit**: Queue analysis, retry after backoff
- **Bedrock Unavailable**: Fall back to threshold-based assessment without LLM
- **Invalid LLM Response**: Log error, retry with simplified prompt

### State Store Failures

- **DSQL Connection Error**: Retry with exponential backoff
- **OCC Conflict**: Automatic retry (DSQL plugin handles this)
- **Write Failure**: Log error, continue operation (assessment available in memory)

### API Service Failures

- **State Store Unavailable**: Return degraded status response with cached data
- **Request Timeout**: Return partial response with available data
- **Invalid Request**: Return 400 with descriptive error message


## Testing Strategy

### Unit Tests

Unit tests verify specific examples and edge cases:

1. **Threshold Evaluation**: Test each metric type against its threshold
2. **Pattern Matching**: Test each log pattern against sample log entries
3. **Correlation Logic**: Test timestamp proximity calculation
4. **Prompt Construction**: Test sensitive data filtering
5. **API Response Formatting**: Test each endpoint's response structure

### Property-Based Tests

Property tests verify universal properties across generated inputs using `hypothesis`:

```python
from hypothesis import given, strategies as st

@given(st.dictionaries(
    keys=st.sampled_from(['reservoir_empty', 'service_error_rate', 'persistence_latency_p95']),
    values=st.floats(min_value=0, max_value=10000)
))
def test_anomaly_detection_correctness(metrics):
    """Property 1: Anomaly detection identifies all threshold violations."""
    anomalies = detect_anomalies(metrics, THRESHOLDS)
    
    for metric, value in metrics.items():
        threshold = THRESHOLDS.get(metric)
        if threshold and value > threshold:
            assert any(a['metric'] == metric for a in anomalies)
        elif threshold and value <= threshold:
            assert not any(a['metric'] == metric for a in anomalies)

@given(st.lists(st.builds(MetricSnapshot), min_size=0, max_size=100))
def test_sliding_window_invariant(snapshots):
    """Property 2: Sliding window maintains size invariant."""
    window = SlidingWindow(max_size=10)
    
    for snapshot in snapshots:
        window.add(snapshot)
    
    assert len(window) <= 10
    if len(snapshots) >= 10:
        assert len(window) == 10
        # Verify FIFO order
        expected = snapshots[-10:]
        assert list(window) == expected

@given(st.builds(HealthAssessment))
def test_health_assessment_round_trip(assessment):
    """Property 6: Health assessment serialization round-trip."""
    json_str = assessment.model_dump_json()
    restored = HealthAssessment.model_validate_json(json_str)
    
    assert restored.timestamp == assessment.timestamp
    assert restored.overall_status == assessment.overall_status
    assert restored.services == assessment.services
    assert restored.issues == assessment.issues
    assert restored.natural_language_summary == assessment.natural_language_summary
```

### Integration Tests

Integration tests verify component interactions:

1. **Workflow Execution**: Test MetricWatcher → DeepAnalysis workflow chain
2. **RAG Pipeline**: Test Bedrock Knowledge Base retrieval with mocked responses
3. **API → State Store**: Test API queries against populated state store
4. **Bedrock Integration**: Test LLM invocation with mocked responses

### Test Configuration

- Property tests: Minimum 100 iterations per property
- Each property test tagged with: `Feature: temporal-service-health, Property N: {property_text}`
- Integration tests tagged with `integration` marker
- Use `pytest-asyncio` for async test support

## Infrastructure

### Terraform Module Structure

```
terraform/modules/copilot/
├── main.tf           # ECS cluster, services, task definitions
├── variables.tf      # Input variables
├── outputs.tf        # Output values
├── iam.tf            # IAM roles and policies
├── networking.tf     # Security groups, VPC endpoints
├── dsql.tf           # DSQL state store configuration
└── grafana.tf        # Grafana data source configuration
```

### ECS Task Definitions

```hcl
# Temporal Server (single-binary mode with DSQL)
resource "aws_ecs_task_definition" "copilot_temporal" {
  family                   = "${var.project_name}-copilot-temporal"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  
  container_definitions = jsonencode([{
    name  = "temporal"
    image = "${var.temporal_dsql_image}"  # Use temporal-dsql image
    environment = [
      { name = "TEMPORAL_ADDRESS", value = "0.0.0.0:7233" },
      { name = "TEMPORAL_SQL_PLUGIN", value = "dsql" },
      { name = "TEMPORAL_SQL_HOST", value = var.dsql_endpoint },
      { name = "TEMPORAL_SQL_PORT", value = "5432" },
      { name = "TEMPORAL_SQL_DATABASE", value = "copilot" },
      { name = "TEMPORAL_SQL_TLS_ENABLED", value = "true" },
      { name = "TEMPORAL_SQL_IAM_AUTH", value = "true" },
      { name = "AWS_REGION", value = var.aws_region },
      # Reservoir configuration for DSQL
      { name = "DSQL_RESERVOIR_ENABLED", value = "true" },
      { name = "DSQL_RESERVOIR_TARGET_READY", value = "20" },
      { name = "DSQL_RESERVOIR_BASE_LIFETIME", value = "11m" },
    ]
    portMappings = [{ containerPort = 7233 }]
  }])
  
  task_role_arn = aws_iam_role.copilot_task.arn
}

# Copilot Worker
resource "aws_ecs_task_definition" "copilot_worker" {
  family                   = "${var.project_name}-copilot-worker"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 4096
  
  container_definitions = jsonencode([{
    name  = "worker"
    image = "${var.copilot_image}"
    command = ["python", "-m", "copilot.worker"]
    environment = [
      { name = "TEMPORAL_ADDRESS", value = "copilot-temporal:7233" },
      { name = "AMP_WORKSPACE_ID", value = var.amp_workspace_id },
      { name = "LOKI_URL", value = var.loki_url },
      { name = "DSQL_ENDPOINT", value = var.dsql_endpoint },
      { name = "AWS_REGION", value = var.aws_region }
    ]
  }])
  
  task_role_arn = aws_iam_role.copilot_task.arn
}

# API Service
resource "aws_ecs_task_definition" "copilot_api" {
  family                   = "${var.project_name}-copilot-api"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  
  container_definitions = jsonencode([{
    name  = "api"
    image = "${var.copilot_image}"
    command = ["uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8080"]
    portMappings = [{ containerPort = 8080 }]
    environment = [
      { name = "DSQL_ENDPOINT", value = var.dsql_endpoint },
      { name = "AWS_REGION", value = var.aws_region }
    ]
  }])
  
  task_role_arn = aws_iam_role.copilot_task.arn
}
```

### IAM Permissions

```hcl
resource "aws_iam_role_policy" "copilot_task" {
  name = "${var.project_name}-copilot-task-policy"
  role = aws_iam_role.copilot_task.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "aps:QueryMetrics",
          "aps:GetMetricMetadata"
        ]
        Resource = var.amp_workspace_arn
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-opus-4-*",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-sonnet-4-5-*",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:Retrieve"
        ]
        Resource = aws_bedrockagent_knowledge_base.copilot.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dsql:DbConnect",
          "dsql:DbConnectAdmin"
        ]
        Resource = var.dsql_cluster_arn
      }
    ]
  })
}
```

### Grafana Data Source Configuration

```yaml
# provisioning/datasources/copilot.yaml
apiVersion: 1
datasources:
  - name: Copilot
    type: marcusolsson-json-datasource
    access: proxy
    url: http://copilot-api:8080
    jsonData:
      httpMethod: GET
```


## Python Project Structure

### Tooling

The project uses modern Python tooling:

- **Python 3.14+**: Modern Python version for best performance and type hints
- **uv**: Fast Python package manager and project management
- **ruff**: Fast linter and formatter (replaces black, isort, flake8)
- **typer**: Elegant CLI framework with Rich integration
- **rich**: Beautiful terminal formatting

### Project Layout

The Copilot is a separate workspace (`temporal-sre-copilot/`) from the main deployment:

```
temporal-sre-copilot/
├── pyproject.toml          # Project configuration (uv, ruff)
├── uv.lock                  # Locked dependencies
├── terraform/              # Copilot-specific Terraform
│   ├── main.tf             # ECS cluster, log groups
│   ├── variables.tf        # Input variables
│   ├── terraform.tfvars.example  # Template with values from temporal-dsql-deploy-ecs
│   ├── iam.tf              # IAM roles and policies
│   ├── networking.tf       # Security groups
│   ├── ec2.tf              # Launch template, ASG, capacity provider
│   ├── services.tf         # Task definitions and ECS services
│   ├── knowledge_base.tf   # S3 buckets for KB
│   └── outputs.tf          # Output values
├── src/
│   └── copilot/
│       ├── __init__.py
│       ├── api.py           # FastAPI application
│       ├── worker.py        # Temporal worker entry point
│       ├── temporal.py      # Temporal client/worker utilities
│       ├── cli/             # Typer CLI commands
│       │   ├── __init__.py  # Main CLI app
│       │   ├── db.py        # Database commands
│       │   └── kb.py        # Knowledge base commands
│       ├── workflows/
│       │   ├── __init__.py
│       │   ├── observe.py       # ObserveClusterWorkflow
│       │   ├── log_watcher.py   # LogWatcherWorkflow
│       │   ├── assess.py        # AssessHealthWorkflow
│       │   └── scheduled.py     # ScheduledAssessmentWorkflow
│       ├── activities/
│       │   ├── __init__.py
│       │   ├── amp.py           # AMP queries
│       │   ├── loki.py          # Loki queries
│       │   ├── rag.py           # Knowledge base
│       │   └── state_store.py   # DSQL operations
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── dispatcher.py
│       │   └── researcher.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── assessment.py    # HealthAssessment, Issue, SuggestedAction
│       │   ├── signals.py       # PrimarySignals, AmplifierSignals, Signals
│       │   ├── state_machine.py # evaluate_health_state, classify_bottleneck
│       │   ├── workflow_inputs.py # Workflow input models
│       │   └── config.py        # Configuration and threshold models
│       └── db/
│           ├── __init__.py
│           └── schema.sql   # DSQL schema
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Pytest fixtures
│   ├── test_anomaly_detection.py
│   ├── test_pattern_matching.py
│   ├── test_rag.py
│   ├── test_api.py
│   └── properties/          # Property-based tests
│       ├── __init__.py
│       ├── test_sliding_window.py
│       ├── test_health_assessment.py
│       └── test_correlation.py
└── Dockerfile               # Multi-stage build
```

### pyproject.toml

```toml
[project]
name = "temporal-sre-copilot"
version = "0.1.0"
description = "AI-powered observability agent for Temporal deployments on Aurora DSQL"
requires-python = ">=3.14"
dependencies = [
    "pydantic>=2.10",
    "pydantic-ai>=0.1",
    "pydantic-settings>=2.7",
    "temporalio>=1.10",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "httpx>=0.28",
    "boto3>=1.36",
    "asyncpg>=0.30",
    "typer>=0.15",
    "rich>=13.9",
    "whenever>=0.7",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.25",
    "hypothesis>=6.122",
    "ruff>=0.9",
]

[project.scripts]
copilot = "copilot.cli:app"

[build-system]
requires = ["uv_build>=0.9.28,<0.10.0"]
build-backend = "uv_build"

[tool.uv]
package = true

[tool.uv.build-backend]
module-name = "copilot"

[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
```

### CLI Commands

The Copilot provides a Typer CLI for management operations:

```bash
# Database commands
copilot db setup-schema --endpoint <dsql-endpoint> --database copilot
copilot db check-connection --endpoint <dsql-endpoint>
copilot db list-tables --endpoint <dsql-endpoint>

# Knowledge base commands
copilot kb sync --bucket <s3-bucket> --source ./docs
copilot kb start-ingestion --kb-id <kb-id> --ds-id <data-source-id>
copilot kb status --kb-id <kb-id>
copilot kb list-jobs --kb-id <kb-id> --ds-id <data-source-id>
```

### Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src/ src/

FROM python:3.14-slim AS runtime

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Default to worker, override in task definition
CMD ["python", "-m", "copilot.worker"]
```

## Terraform Structure

The Copilot Terraform is in a separate workspace (`temporal-sre-copilot/terraform/`) and references dependent resources from `temporal-dsql-deploy-ecs` via `terraform.tfvars`:

```hcl
# terraform.tfvars.example - values from temporal-dsql-deploy-ecs
project_name = "temporal-bench"
aws_region   = "eu-west-1"

# From: cd ../temporal-dsql-deploy-ecs/terraform/envs/bench && terraform output
vpc_id             = "vpc-xxxxxxxxxxxxxxxxx"
private_subnet_ids = ["subnet-xxx", "subnet-xxx"]
vpc_cidr           = "10.0.0.0/16"
dsql_endpoint      = "xxx.dsql.eu-west-1.on.aws"
dsql_cluster_arn   = "arn:aws:dsql:eu-west-1:123456789012:cluster/xxx"
amp_workspace_id   = "ws-xxx"
amp_workspace_arn  = "arn:aws:aps:eu-west-1:123456789012:workspace/ws-xxx"
loki_url           = "http://loki:3100"
loki_security_group_id = "sg-xxx"
```

## VPC and Networking

The Copilot cluster runs in the same VPC as the monitored Temporal cluster for direct access to internal services.

```hcl
# Copilot services use the same VPC
resource "aws_ecs_service" "copilot_worker" {
  # ...
  network_configuration {
    subnets          = var.private_subnet_ids  # Same subnets as Temporal
    security_groups  = [aws_security_group.copilot.id]
    assign_public_ip = false
  }
}

# Security group allows access to AMP, Loki, DSQL
resource "aws_security_group" "copilot" {
  name        = "${var.project_name}-copilot"
  vpc_id      = var.vpc_id
  
  # Egress to AMP (via VPC endpoint)
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
  
  # Egress to Loki
  egress {
    from_port       = 3100
    to_port         = 3100
    protocol        = "tcp"
    security_groups = [var.loki_security_group_id]
  }
  
  # Egress to DSQL (via VPC endpoint or public endpoint)
  egress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}
```


## Cost Analysis (24-Hour Estimate)

This section provides a cost estimate for running the Temporal SRE Copilot for 24 hours.

### Assumptions

- **Analysis frequency**: 
  - Scheduled deep analysis: every 5 minutes = 288/day
  - Anomaly-triggered analysis: ~50/day (estimated)
  - Total deep analyses: ~340/day
- **Dispatcher calls**: Every 30 seconds = 2,880/day
- **RAG retrievals**: 1 per deep analysis = ~340/day
- **Knowledge base size**: ~50 documents, ~500KB total
- **Average prompt size**: 
  - Dispatcher: ~2,000 input tokens, ~200 output tokens
  - Researcher: ~8,000 input tokens, ~2,000 output tokens

### LLM Costs (Amazon Bedrock)

| Model | Usage | Input Tokens | Output Tokens | Cost |
|-------|-------|--------------|---------------|------|
| Claude Sonnet 4.5 (Dispatcher) | 2,880 calls | 5.76M | 0.58M | $17.28 + $8.64 = **$25.92** |
| Claude Opus 4.6 (Researcher) | 340 calls | 2.72M | 0.68M | $40.80 + $51.00 = **$91.80** |

**Pricing used (Bedrock on-demand):**
- Claude Sonnet 4.5: $3/1M input, $15/1M output
- Claude Opus 4.6: $15/1M input, $75/1M output

> **Note:** Verify current Bedrock pricing at https://aws.amazon.com/bedrock/pricing/ — model pricing changes frequently. Prompt caching (90% discount on cached tokens) can significantly reduce costs.

**Total LLM cost: ~$117.72/day**

### Embedding Costs (Amazon Titan)

| Usage | Tokens | Cost |
|-------|--------|------|
| RAG queries (340 × ~500 tokens) | 170K | $0.0034 |
| KB ingestion (one-time, ~100K tokens) | 100K | $0.002 |

**Pricing:** $0.00002/1K tokens

**Total embedding cost: ~$0.01/day** (negligible)

### Knowledge Base Storage (S3 Vectors)

| Component | Usage | Cost |
|-----------|-------|------|
| Vector storage | ~50 documents, ~500KB | ~$0.01/day |
| Vector queries | 340 queries | ~$0.01/day |
| S3 storage | ~1MB source docs | ~$0.00003/day |

**Total KB cost: ~$0.02/day** (negligible)

### Compute Costs (ECS)

| Service | vCPU | Memory | Hours | Cost |
|---------|------|--------|-------|------|
| Temporal Server | 1 | 2GB | 24 | ~$1.20 |
| Copilot Worker | 2 | 4GB | 24 | ~$2.40 |
| API Service | 0.5 | 1GB | 24 | ~$0.60 |

**Pricing:** ~$0.05/vCPU-hour (Graviton, on-demand)

**Total compute cost: ~$4.20/day**

### DSQL Costs

| Component | Usage | Cost |
|-----------|-------|------|
| Workflow state | ~1000 writes/day | ~$0.50 |
| Health assessments | ~340 writes/day | ~$0.20 |
| Reads | ~5000 reads/day | ~$0.10 |

**Total DSQL cost: ~$0.80/day**

### Summary

| Category | Daily Cost | Monthly Cost |
|----------|------------|--------------|
| LLM (Claude) | $117.72 | $3,531.60 |
| Embeddings (Titan) | $0.01 | $0.30 |
| Knowledge Base (S3 Vectors) | $0.02 | $0.60 |
| Compute (ECS) | $4.20 | $126.00 |
| DSQL | $0.80 | $24.00 |
| **Total** | **$122.75** | **$3,682.50** |

### Cost Optimization Strategies

1. **Reduce dispatcher frequency**: Change from 30s to 60s → saves ~$13/day
2. **Use prompt caching**: Bedrock supports prompt caching at 90% discount for repeated context
3. **Batch analysis**: Combine multiple anomalies into single analysis → fewer Opus calls
4. **Adjust scheduled analysis**: Change from 5min to 15min → saves ~$60/day (fewer Opus calls)
5. **Use Haiku for simple triage**: Replace Sonnet with Haiku for obvious healthy states → saves ~$20/day
6. **Downgrade researcher to Sonnet**: Use Sonnet 4.5 instead of Opus 4.6 for researcher → saves ~$65/day (biggest lever)

### Cost-Optimized Configuration

With optimizations applied:

| Change | Savings |
|--------|---------|
| Dispatcher every 60s | -$13/day |
| Scheduled analysis every 15min | -$60/day |
| Haiku for 80% of dispatches | -$20/day |
| Prompt caching (50% hit rate) | -$25/day |

**Optimized total: ~$40-50/day (~$1,200-1,500/month)**

> **Alternative: Sonnet-only configuration.** Using Sonnet 4.5 for both dispatcher and researcher reduces Opus costs to zero. Total LLM cost drops to ~$30/day, with slightly less detailed explanations for complex scenarios.
