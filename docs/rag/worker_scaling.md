# Worker Scaling Guidance

**Source:** Temporal Workers presentation (Tihomir Surdilovic, 2024)

## Topic: Worker Scaling

### Symptoms

- `temporal_worker_task_slots_available == 0`
- `temporal_workflow_task_schedule_to_start_latency > 50ms`
- `temporal_activity_schedule_to_start_latency` elevated

### Explanation

Worker stops polling when all executor slots are occupied. This is a critical state because:

1. **No new work pickup**: When `task_slots_available == 0`, the worker stops polling the task queue entirely
2. **Backlog accumulates**: Work piles up on the server side while workers are saturated
3. **Scaling down worsens the problem**: Removing workers when slots are exhausted increases backlog further

### Critical Rule: NEVER_SCALE_DOWN_AT_ZERO

**NEVER scale down workers when `task_slots_available == 0`.**

This rule is absolute and must never be violated. Scaling down saturated workers:
- Removes capacity when it's most needed
- Increases backlog age
- Can trigger cascading failures

### Sticky Queue Consideration

Sticky queues prevent new workers from getting long-running workflow work:

- Workflows with updates are "sticky" to specific workers
- New workers won't receive tasks for these workflows
- Scaling up may not immediately help with long-running workflows

**Mitigation:** Consider restarting a percentage of existing workers to redistribute sticky work.

### Recommended Actions

1. **Increase executor slots**
   - `MaxConcurrentActivityExecutionSize`: Increase activity executor slots
   - `MaxConcurrentWorkflowTaskExecutionSize`: Increase workflow task executor slots
   - `MaxConcurrentLocalActivityExecutionSize`: Increase local activity slots

2. **Scale up workers**
   - Add more worker instances
   - Note: New workers may not immediately help with sticky workflows

3. **Investigate blocking activities**
   - Look for zombie activities (started but never completed)
   - Check for activities with very long execution times
   - Review activity timeout configurations

4. **Redistribute sticky work**
   - Consider rolling restart of existing workers
   - This redistributes workflow state across all workers

### Thresholds

| Metric | Healthy | Stressed | Critical |
|--------|---------|----------|----------|
| WFT schedule-to-start | < 50ms | 50-200ms | > 200ms |
| Activity schedule-to-start | < 100ms | 100-500ms | > 500ms |
| Workflow slots available | > 50% | 10-50% | 0 |
| Activity slots available | > 50% | 10-50% | 0 |

### Related Metrics

- `temporal_worker_task_slots_available{worker_type="WorkflowWorker"}`
- `temporal_worker_task_slots_available{worker_type="ActivityWorker"}`
- `temporal_worker_task_slots_used{worker_type="WorkflowWorker"}`
- `temporal_worker_task_slots_used{worker_type="ActivityWorker"}`
- `temporal_workflow_task_schedule_to_start_latency_seconds`
- `temporal_activity_schedule_to_start_latency_seconds`
