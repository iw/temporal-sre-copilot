# Sticky Cache Tuning

**Source:** Temporal Workers presentation (Tihomir Surdilovic, 2024)

## Topic: Sticky Cache

### Symptoms

- `temporal_sticky_cache_miss` rate high
- `temporal_workflow_task_replay_latency` elevated
- Increased persistence read load
- Worker memory pressure

### Explanation

The sticky cache stores workflow state to avoid replaying history on every workflow task:

1. **Cache hit**: Workflow state is in memory, task executes immediately
2. **Cache miss**: Full history must be replayed from persistence, increasing latency and DB load

Cache misses cause:
- Full history replay (CPU intensive)
- Increased database reads
- Higher workflow task latency
- Amplified persistence pressure

### How Sticky Execution Works

1. Worker completes a workflow task
2. Workflow state is cached in memory (sticky cache)
3. Next task for same workflow is dispatched to same worker (sticky queue)
4. If cache hit: execute immediately with cached state
5. If cache miss: replay full history from persistence

### Cache Eviction

Cache eviction occurs when:
- Cache reaches `MaxConcurrentWorkflowTaskExecutionSize` limit
- Worker memory pressure triggers eviction
- Workflow hasn't had activity for extended period

Eviction causes cache misses, which amplify:
- Database read load
- Workflow task latency
- Overall system pressure

### Recommended Actions

1. **Increase cache size**
   - `MaxConcurrentWorkflowTaskExecutionSize`: Controls cache size
   - Larger cache = fewer evictions = fewer replays
   - Trade-off: More memory usage

2. **Monitor memory vs cache size**
   - Watch worker memory usage
   - Balance cache size against available memory
   - Consider worker instance sizing

3. **Optimize workflow design**
   - Smaller histories = faster replay
   - Use continue-as-new for long-running workflows
   - Avoid excessive signals/updates

4. **Review sticky schedule-to-start timeout**
   - `StickyScheduleToStartTimeout`: How long to wait for sticky worker
   - Too short: Falls back to non-sticky, loses cache benefit
   - Too long: Delays task if sticky worker is slow

### Thresholds

| Metric | Healthy | Investigate | Critical |
|--------|---------|-------------|----------|
| Cache hit rate | > 80% | 50-80% | < 50% |
| Cache miss rate | Low | Moderate | High |
| Replay latency | < 100ms | 100-500ms | > 500ms |

### Related Metrics

- `temporal_sticky_cache_size`: Current number of cached workflows
- `temporal_sticky_cache_hit_total`: Cache hits (counter)
- `temporal_sticky_cache_miss_total`: Cache misses (counter)
- `temporal_workflow_task_replay_latency_seconds`: Time to replay history

### Configuration Options

```go
worker.Options{
    // Cache size (number of workflows to cache)
    MaxConcurrentWorkflowTaskExecutionSize: 200,
    
    // How long to wait for sticky worker before falling back
    StickyScheduleToStartTimeout: 5 * time.Second,
}
```
