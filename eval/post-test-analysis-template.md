# Post-Test Analysis: [Test Name] [Date] [Window UTC]

## Test Profile

- **Workload**: [e.g., ~50 state transitions/sec (STARTER band)]
- **Duration**: [e.g., ~14 minutes active load, ~5 minutes drain]
- **Workflow type**: [e.g., Simple workflows with activities]
- **Completion rate**: [e.g., 100% (zero failures)]
- **Scale band**: [STARTER / MID_SCALE / HIGH_THROUGHPUT]

## Test Phases

| Phase | Window | st/s | Characteristics |
|-------|--------|------|-----------------|
| Ramp-up | | | |
| Steady state | | | |
| Ramp-down | | | |
| Drain | | | |

## Service-by-Service Analysis

For each service, document:
1. **Observed behaviour** — what the metrics showed
2. **Why** — the Temporal-informed explanation of that behaviour
3. **Supporting metrics** — the specific values that support the explanation

### History Service

History is the persistence-heavy workhorse. It processes every state transition,
manages shard ownership, and executes all persistence operations against DSQL.

**Observed behaviour**: [Describe task processing rate, persistence latency trajectory,
any warm-up or drain behaviour]

**Why**: [Explain using Temporal internals. Remember: persistence_latency is the full
History→DSQL round-trip (serialization + pool checkout + query execution + deserialization
+ OCC retry), not raw database latency. Decompose the path.]

**Supporting metrics**:
- Persistence p99: [value range]
- OCC conflicts: [value]
- Persistence errors: [value]
- Pool utilization: [value range]
- Reservoir checkout: [value]
- Shard churn: [value]

### Matching Service

Matching dispatches workflow and activity tasks to workers. It maintains task queues
and matches pollers to available tasks.

**Observed behaviour**: [Describe backlog age, persistence latency, poller behaviour]

**Why**: [Explain. Zero backlog = instant matching. Persistence spikes = metadata updates.
Poller timeout rate context: 30-50% is normal under bursty load.]

**Supporting metrics**:
- Workflow backlog age: [value]
- Activity backlog age: [value]
- Persistence p99: [value range]
- Poller timeout rate: [value range]

### Frontend Service

Frontend is the gRPC gateway. It routes API calls to History/Matching and handles
worker long-poll requests.

**Observed behaviour**: [Describe error rate, filtered vs raw latency, any spikes]

**Why**: [Explain. Note which operations are excluded by the Poll*TaskQueue filter
and which long-running operations remain (visibility queries, GetWorkflowExecutionHistory
with wait). Distinguish filtered p99 from raw p99.]

**Supporting metrics**:
- Error rate: [value]
- Filtered p99: [value range]
- Raw p99 (incl. long-polls): [value range]
- Persistence p99: [value range]

### Worker Service (Temporal internal)

The Temporal Worker service handles system workflows (archival, replication, cleanup).

**Observed behaviour**: [Describe deletion rate, cleanup rate]

**Why**: [Explain. These are background retention operations, not user workload.]

### Benchmark / SDK Workers

**Observed behaviour**: [Describe task slots, throughput]

**Why**: [Explain. Note which SDK exports metrics to this Mimir instance and which doesn't.]

## Connection Pool & Reservoir

- **Utilization**: [value range]
- **Wait duration**: [value]
- **Checkout latency**: [value]
- **Reservoir refills**: [value range]
- **Reservoir discards**: [value range]

## Cluster Stability

- **Shard churn**: [value]
- **Membership changes**: [value]
- **Goroutines**: [value range]
- **Cache hit rate**: [value range]

## Key Findings

[Numbered list of findings. Each should state the observation and its significance.
Focus on forward progress, not individual metric values.]

## Copilot Assessment Evaluation

This section evaluates how well the Copilot performed during the test.

### State Machine Accuracy

Which gates fired and which passed? Was the health state determination correct?

| Signal | Observed | Threshold | Gate |
|--------|----------|-----------|------|
| Signal 2 (st latency p99) | | | OK / FIRES |
| Signal 4 (backlog age) | | | OK / FIRES |
| Signal 8 (fe latency p99) | | | OK / FIRES |
| Signal 10 (poller timeout) | | | OK / FIRES |
| Signal 11 (persist p99) | | | OK / FIRES |

**Verdict**: [Was the state machine correct? Did it fire on the right signal?]

### LLM Narrative Accuracy

- Did the LLM correctly identify which signal triggered the state?
- Did the LLM cite specific metric values? (violation of "Grafana Consumes, Not Computes")
- Did the LLM misattribute the cause? (e.g., blaming persistence when frontend latency fired)
- Was the severity assessment consistent between summary and issues list?
- Did the LLM understand the persistence path decomposition?

**Verdict**: [Summary of LLM performance and specific failures]

### Prompt Design Implications

[What needs to change in the researcher/dispatcher prompts based on this test?
Focus on structural issues, not one-off fixes.]

## Methodology Notes

[Any notes on the test methodology, data collection, or analysis approach
that should inform future tests.]
