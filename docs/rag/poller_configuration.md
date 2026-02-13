# Poller Configuration

**Source:** Temporal Workers presentation (Tihomir Surdilovic, 2024)

## Topic: Poller Configuration

### Symptoms

- Pollers > executor slots (misconfiguration)
- `poll_success` rate low
- High `temporal_long_request_latency`
- Workers not picking up tasks efficiently

### Explanation

Pollers are long-poll connections that fetch tasks from the Temporal server:

1. **Workflow task pollers**: Fetch workflow tasks from task queue
2. **Activity task pollers**: Fetch activity tasks from task queue

**Key insight from presentation:**

> "Makes no sense to configure more pollers than executor slots."

Excess pollers:
- Waste resources (connections, goroutines)
- Don't improve throughput (limited by executor slots)
- Can cause connection pressure on server

### Poller vs Executor Relationship

```
┌─────────────────────────────────────────────────────────────────┐
│                    WORKER ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Pollers (fetch tasks)          Executors (process tasks)       │
│  ┌─────┐ ┌─────┐ ┌─────┐       ┌─────┐ ┌─────┐ ┌─────┐ ...     │
│  │Poll │ │Poll │ │Poll │  ───▶ │Exec │ │Exec │ │Exec │         │
│  └─────┘ └─────┘ └─────┘       └─────┘ └─────┘ └─────┘         │
│                                                                 │
│  If pollers > executors:                                        │
│  - Pollers fetch tasks faster than executors can process        │
│  - Tasks queue up internally                                    │
│  - No throughput benefit                                        │
│  - Wasted resources                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended Configuration

**Rule of thumb:** Pollers should be 10-20% of executor slots.

```go
worker.Options{
    // Executor slots (how many tasks can run concurrently)
    MaxConcurrentWorkflowTaskExecutionSize:  200,
    MaxConcurrentActivityExecutionSize:      200,
    MaxConcurrentLocalActivityExecutionSize: 200,
    
    // Pollers (should be significantly less than executor slots)
    MaxConcurrentWorkflowTaskPollers: 32,  // ~16% of workflow executors
    MaxConcurrentActivityTaskPollers: 32,  // ~16% of activity executors
}
```

### Recommended Actions

1. **Fix poller/executor mismatch**
   - Set `MaxConcurrentWorkflowTaskPollers < MaxConcurrentWorkflowTaskExecutionSize`
   - Set `MaxConcurrentActivityTaskPollers < MaxConcurrentActivityExecutionSize`
   - Typical ratio: pollers = 10-20% of executor slots

2. **Monitor poll success rate**
   - Low success rate may indicate server-side issues
   - High success rate with high latency may indicate network issues

3. **Review long-poll timeout**
   - Default is 70 seconds
   - Adjust if network conditions require it

### Thresholds

| Configuration | Minimum | Recommended | Maximum |
|---------------|---------|-------------|---------|
| Workflow pollers | 1 | 16-32 | executor slots |
| Activity pollers | 1 | 16-32 | executor slots |
| Poller/executor ratio | 5% | 10-20% | 100% |

### Related Metrics

- `temporal_num_pollers{poller_type="workflow_task"}`: Active workflow pollers
- `temporal_num_pollers{poller_type="activity_task"}`: Active activity pollers
- `temporal_long_request_latency_seconds`: Long-poll request latency
- `temporal_long_request_total`: Long-poll request count
- `temporal_long_request_failure_total`: Long-poll failures

### Anti-Patterns

1. **Pollers == Executors**: No benefit, wastes resources
2. **Pollers > Executors**: Definitely wrong, wastes resources
3. **Too few pollers**: May not fetch tasks fast enough under load
4. **Ignoring poller metrics**: Miss early warning signs of issues
