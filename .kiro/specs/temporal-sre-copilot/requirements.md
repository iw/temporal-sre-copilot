# Requirements Document

## Introduction

The Temporal SRE Copilot is an AI-powered observability agent that provides intelligent health monitoring, analysis, and remediation guidance for Temporal deployments running on Aurora DSQL. Rather than presenting raw metrics, the Copilot distills complex telemetry into actionable "Happy/Stressed/Critical" health assessments with natural language explanations and suggested remediations.

The system uses a separate Temporal cluster running Pydantic AI workflows to continuously monitor metrics (via Amazon Managed Prometheus), logs (via Loki), and correlate signals across services. A RAG-powered knowledge base provides context from deployment documentation, troubleshooting guides, and historical patterns. Health assessments are exposed via a JSON API that powers custom Grafana panels.

## Glossary

- **Copilot**: The Temporal SRE Copilot system - the AI-powered observability agent
- **Health_Assessment**: A structured evaluation of system health including status, issues, and recommendations
- **Health_State_Machine**: Deterministic state machine that derives health from forward progress
- **Primary_Signals**: Metrics that decide health state (forward progress indicators)
- **Amplifier_Signals**: Metrics that explain why state changed (resource pressure, contention)
- **Narrative_Signals**: Log patterns that explain state transitions
- **RAG_System**: Retrieval-Augmented Generation system that provides relevant context to the LLM
- **Knowledge_Base**: The indexed collection of documentation, runbooks, and failure mode heuristics
- **ObserveClusterWorkflow**: The continuous monitoring workflow that collects signals
- **AssessHealthWorkflow**: LLM-powered workflow that explains health state (rules decide, AI explains)
- **State_Store**: DSQL database storing health assessments and issue history
- **API_Service**: JSON API exposing health data to Grafana
- **AMP**: Amazon Managed Prometheus - the metrics data source
- **Loki**: Log aggregation system - the logs data source
- **Bedrock**: Amazon Bedrock with Claude - the LLM provider

## Requirements

### Requirement 1: Signal Observation and Collection

**User Story:** As an operator, I want the Copilot to continuously observe Temporal signals using a structured taxonomy, so that health can be derived from forward progress rather than arbitrary thresholds.

#### Acceptance Criteria

1. THE ObserveClusterWorkflow SHALL query AMP for current signals every 30 seconds
2. THE Copilot SHALL classify signals into three categories:
   - **Primary Signals**: Decide health state (forward progress indicators)
   - **Amplifier Signals**: Explain why state changed (resource pressure, contention)
   - **Narrative Signals**: Logs that explain state transitions
3. THE Primary Signals SHALL include (specific metrics TBD based on operational experience):
   - Workflow state transitions per second (forward progress indicator)
   - Task completion rate (forward progress indicator)
   - Backlog age (inverse progress indicator)
4. THE Amplifier Signals SHALL include (specific metrics TBD):
   - DSQL latency and OCC conflicts (explain contention)
   - Connection pool utilization (explain resource pressure)
   - Shard churn rate (explain instability)
5. IF the AMP query fails, THEN THE ObserveClusterWorkflow SHALL log the error and retry on the next cycle
6. THE ObserveClusterWorkflow SHALL maintain a sliding window of recent signals for trend analysis
7. THE Copilot SHALL NOT use raw threshold violations alone to determine health state

### Requirement 2: Log Monitoring and Correlation

**User Story:** As an operator, I want the Copilot to monitor logs alongside metrics, so that error patterns are detected and correlated with metric anomalies.

#### Acceptance Criteria

1. THE Copilot SHALL continuously scan Loki for error patterns every 30 seconds
2. WHEN scanning logs, THE Copilot SHALL detect the following patterns:
   - Temporal service error logs (level=error)
   - DSQL connection errors (connection refused, timeout, rate limit)
   - Ringpop membership changes (member joined, member left)
   - Shard acquisition/release events
   - OCC serialization failures (SQLSTATE 40001)
3. WHEN an error pattern is detected, THE Copilot SHALL trigger a Deep_Analysis workflow
4. WHEN Deep_Analysis is triggered by a metric anomaly, THE Copilot SHALL fetch recent logs for context
5. THE Copilot SHALL correlate log events with metric anomalies by timestamp proximity
6. IF the Loki query fails, THEN THE Copilot SHALL log the error and continue with metric-only analysis

### Requirement 3: RAG-Powered Knowledge Base

**User Story:** As an operator, I want the Copilot to have access to deployment documentation and troubleshooting guides, so that its analysis is informed by relevant context.

#### Acceptance Criteria

1. THE Knowledge_Base SHALL index the following documentation sources:
   - AGENTS.md files from temporal-dsql-deploy-ecs repository
   - docs/dsql/*.md files (DSQL-specific knowledge)
   - Temporal official troubleshooting documentation
   - Failure mode heuristics and remediation patterns
   - Existing Grafana dashboard descriptions and interpretation guides
2. THE RAG_System SHALL use vector embeddings to enable semantic search
3. WHEN AssessHealthWorkflow is triggered, THE RAG_System SHALL retrieve relevant context based on the detected signals
4. THE RAG_System SHALL limit retrieved context to the most relevant 5 documents
5. THE Knowledge_Base SHALL be refreshable without restarting the Copilot
6. THE Knowledge_Base SHALL exclude:
   - Dated benchmark results that are no longer current
   - Raw metrics definitions or PromQL queries (these belong in code, not RAG)
   - Threshold values (these are in deterministic rules, not RAG)

### Requirement 4: Health State Machine and LLM Analysis

**User Story:** As an operator, I want the Copilot to derive health from forward progress using deterministic rules, with LLM providing explanations rather than decisions.

#### Acceptance Criteria

1. THE Copilot SHALL implement a Health State Machine with canonical states:
   - **Happy**: Forward progress is healthy, no concerning amplifiers
   - **Stressed**: Forward progress continues but amplifiers indicate pressure
   - **Critical**: Forward progress is impaired or stopped
2. THE Health State Machine SHALL derive state from forward progress invariant:
   - "Is the cluster making forward progress on workflows?"
   - Primary signals (state transitions, completions) determine the answer
   - Amplifiers explain WHY progress may be impaired
3. THE AssessHealthWorkflow SHALL follow "Rules decide, AI explains" principle:
   - Deterministic rules evaluate primary signals and set health state
   - LLM receives the state and explains/ranks issues
   - LLM SHALL NOT decide state transitions or apply thresholds
4. WHEN AssessHealthWorkflow runs, THE Copilot SHALL call Amazon Bedrock Claude for explanation
5. THE LLM SHALL receive as input:
   - Current health state (already determined by rules)
   - Primary signal values
   - Amplifier signal values
   - Recent log patterns (narrative signals)
   - RAG-retrieved context
6. THE LLM SHALL produce:
   - Natural language explanation of current state
   - Ranked list of contributing factors
   - Suggested remediation actions with confidence scores
7. THE AssessHealthWorkflow SHALL complete within 30 seconds
8. IF Bedrock is unavailable, THEN THE Copilot SHALL return rule-based assessment without LLM explanation
9. THE AssessHealthWorkflow SHALL not send sensitive data (credentials, PII) to the LLM

### Requirement 5: Health Assessment State Storage

**User Story:** As an operator, I want health assessments to be persisted, so that I can view historical health and track issue resolution.

#### Acceptance Criteria

1. THE State_Store SHALL use Aurora DSQL as the persistence layer
2. WHEN a Health_Assessment is produced, THE Copilot SHALL store it in the State_Store
3. THE State_Store SHALL retain health assessments for at least 7 days
4. THE State_Store SHALL support querying:
   - Current health assessment
   - Health assessments within a time range
   - Issues by severity
   - Health timeline (status changes over time)
5. THE State_Store SHALL use optimistic concurrency control for updates
6. IF a storage operation fails, THEN THE Copilot SHALL retry with exponential backoff

### Requirement 6: JSON API for Grafana Integration

**User Story:** As an operator, I want to view health assessments in Grafana, so that I have a unified observability interface.

#### Acceptance Criteria

1. THE API_Service SHALL expose a JSON API with the following endpoints:
   - GET /status - Current overall health status with signal taxonomy
   - GET /status/services - Per-service health status
   - GET /status/issues - Active issues list with contributing factors
   - GET /status/summary - Natural language summary
   - GET /status/timeline - Health status changes over time
2. THE API_Service SHALL return responses with structured signal taxonomy:
   ```json
   {
     "health_state": "stressed",
     "primary_signals": { "state_transitions_per_sec": 182, "backlog_age_sec": 47 },
     "amplifiers": { "dsql_latency_ms": 92, "occ_conflicts_per_sec": 38 },
     "log_patterns": [{ "count": 128, "pattern": "reservoir discard", "service": "history" }],
     "recommended_actions": [{ "action": "scale history", "confidence": 0.71 }]
   }
   ```
3. THE API_Service SHALL support time range parameters for historical queries
4. THE API_Service SHALL respond within 500ms for current health queries
5. THE API_Service SHALL include CORS headers for Grafana access
6. THE API_Service SHALL follow "Grafana consumes, not computes" principle:
   - All computation happens in the Copilot
   - Grafana only displays pre-computed values
7. IF the State_Store is unavailable, THEN THE API_Service SHALL return a degraded status response

### Requirement 7: Grafana Dashboard

**User Story:** As an operator, I want a Grafana dashboard that displays the Copilot's health assessments, so that I can see system health at a glance.

#### Acceptance Criteria

1. THE Dashboard SHALL display a Copilot Insights hero panel containing:
   - Status badge (Happy/Stressed/Critical) with color coding
   - Confidence score percentage
   - Last analysis timestamp
   - Natural language summary of current state
   - Warning callout for the most critical issue (if any)
2. THE Dashboard SHALL display a status filter toggle (Happy/Stressed/Critical) that filters the entire dashboard
3. THE Dashboard SHALL display a Copilot Insights section with two columns:
   - Analysis column: bullet points explaining what's happening
   - Suggested Remediations column: actionable recommendations with confidence percentages
4. THE Dashboard SHALL include a "View Guide" link to RAG-powered documentation
5. THE Dashboard SHALL display a Signal Metrics grid with key metrics and sparklines (specific metrics TBD based on operational experience)
6. THE Dashboard SHALL display a Log Pattern Alerts table showing:
   - Occurrence count
   - Pattern description
   - Affected service tag
7. THE Dashboard SHALL auto-refresh every 30 seconds
8. THE Dashboard SHALL link to related detailed dashboards (Server Health, DSQL Persistence, Workers)

### Requirement 8: Agent Infrastructure

**User Story:** As a platform engineer, I want the Copilot to run on a separate ECS cluster, so that it is isolated from the monitored Temporal deployment.

#### Acceptance Criteria

1. THE Copilot SHALL run on a separate ECS cluster from the monitored Temporal deployment
2. THE Copilot cluster SHALL include:
   - Temporal server (single-binary mode)
   - Agent worker service (Pydantic AI workflows)
   - API service (JSON API)
3. THE Copilot SHALL use IAM roles for accessing:
   - Amazon Managed Prometheus (read)
   - Amazon Bedrock (invoke)
   - Aurora DSQL (read/write to state store)
   - Loki (read)
4. THE Copilot SHALL be deployable via Terraform in a separate workspace
5. THE Copilot Terraform SHALL reference dependent resources from temporal-dsql-deploy-ecs via terraform.tfvars
6. IF the Copilot fails, THEN the monitored Temporal deployment SHALL continue operating normally

### Requirement 11: CLI Tooling

**User Story:** As a platform engineer, I want elegant CLI tools for managing the Copilot, so that I can easily set up and operate the system.

#### Acceptance Criteria

1. THE Copilot SHALL provide a Python Typer CLI for all management operations
2. THE CLI SHALL include database commands:
   - `copilot db setup-schema` - Apply DSQL schema
   - `copilot db check-connection` - Test DSQL connectivity
   - `copilot db list-tables` - Show tables and row counts
3. THE CLI SHALL include knowledge base commands:
   - `copilot kb sync` - Upload documentation to S3
   - `copilot kb start-ingestion` - Trigger KB ingestion job
   - `copilot kb status` - Check KB or job status
   - `copilot kb list-jobs` - List recent ingestion jobs
4. THE CLI SHALL use Rich for formatted console output
5. THE CLI SHALL be installable via `uv pip install -e .` with entry point `copilot`

### Requirement 9: Scheduled Health Assessment

**User Story:** As an operator, I want periodic health assessments even when no anomalies are detected, so that I have regular health summaries.

#### Acceptance Criteria

1. THE Copilot SHALL trigger AssessHealthWorkflow on a configurable schedule (default: every 5 minutes)
2. WHEN scheduled assessment runs, THE Copilot SHALL evaluate current signals and recent logs
3. THE scheduled assessment SHALL produce a Health_Assessment even if all signals indicate healthy state
4. THE scheduled assessment SHALL update the natural language summary with current system state
5. WHEN both signal-triggered and scheduled assessment are pending, THE Copilot SHALL deduplicate to avoid redundant LLM calls

### Requirement 10: Future Remediation Capability

**User Story:** As an operator, I want the Copilot architecture to support future automated remediation, so that common issues can be resolved without manual intervention.

#### Acceptance Criteria

1. THE Health_Assessment structure SHALL include suggested_actions for each issue
2. THE suggested_actions SHALL be structured to support future automation:
   - Action type (scale, restart, configure, alert)
   - Target service
   - Parameters
   - Risk level
3. THE API_Service SHALL expose a POST /actions endpoint (initially returning 501 Not Implemented)
4. THE Copilot workflow architecture SHALL support adding a RemediationWorkflow in the future
5. THE Dashboard SHALL display suggested actions in a format that could support "execute" buttons in the future

### Requirement 12: Health State Machine Architecture

**User Story:** As a platform engineer, I want health to be derived from forward progress using deterministic rules, so that health assessments are predictable and explainable.

#### Acceptance Criteria

1. THE Health_State_Machine SHALL implement the forward progress invariant:
   - "Is the cluster making forward progress on workflows?"
   - This is the ONLY question that determines health state
2. THE Health_State_Machine SHALL use canonical state transitions:
   - Happy → Stressed: When amplifiers indicate pressure but progress continues
   - Stressed → Critical: When forward progress is impaired
   - Critical → Stressed: When progress resumes but pressure remains
   - Stressed → Happy: When pressure subsides and progress is healthy
3. THE Health_State_Machine SHALL NOT transition directly from Happy to Critical
   - Stressed is always an intermediate state
   - This prevents over-eager critical alerts
4. THE Health_State_Machine SHALL anchor health to progress, not pain:
   - High latency alone does not make the system Critical
   - High latency WITH impaired progress makes the system Critical
5. THE Health_State_Machine rules SHALL be deterministic and auditable:
   - No LLM involvement in state transitions
   - Rules are code, not prompts
   - State transitions are logged with contributing signals

### Requirement 13: Date and Time Handling

**User Story:** As a platform engineer, I want all date and time handling to use a modern, type-safe library with UTC-first design, so that timezone bugs are eliminated and code is more maintainable.

#### Acceptance Criteria

1. THE Copilot SHALL use the `whenever` library (https://github.com/ariebovenberg/whenever) for all date and time handling
2. ALL timestamps SHALL be stored and processed in UTC
3. THE Copilot SHALL use `whenever` types instead of Python's `datetime`:
   - `Instant` for points in time (replaces `datetime.datetime`)
   - `TimeDelta` for durations (replaces `datetime.timedelta`)
4. THE Copilot SHALL use the Rust-backed `whenever` package for performance
5. WHEN serializing timestamps for JSON API responses, THE Copilot SHALL use ISO 8601 format
6. WHEN storing timestamps in DSQL, THE Copilot SHALL convert to `TIMESTAMPTZ`
7. THE Copilot SHALL NOT use Python's `datetime` module directly for any new code

### Requirement 14: Worker Health Model

**User Story:** As an operator, I want the Copilot to understand worker-side health separately from server-side health, so that I can distinguish between "server can't keep up" and "workers can't keep up" scenarios.

#### Acceptance Criteria

1. THE Copilot SHALL collect worker-side signals from SDK metrics:
   - `temporal_workflow_task_schedule_to_start_latency` (< 50ms is healthy)
   - `temporal_activity_schedule_to_start_latency`
   - `temporal_worker_task_slots_available` (0 = worker stops polling)
   - `temporal_worker_task_slots_used`
   - `temporal_num_pollers` (by poller_type)
   - `temporal_sticky_cache_size`, `temporal_sticky_cache_hit`, `temporal_sticky_cache_miss`
2. THE Copilot SHALL classify bottlenecks into four categories:
   - **Server-limited**: Server can't keep up (high backlog, persistence latency)
   - **Worker-limited**: Workers can't keep up (slots exhausted, high schedule-to-start)
   - **Mixed**: Both server and workers under pressure
   - **Healthy**: Neither constrained
3. THE Health_State_Machine SHALL evaluate worker health AFTER server health:
   - If server is Critical, worker advice is irrelevant
   - If server is Happy/Stressed, assess worker readiness
4. THE Copilot SHALL apply worker-specific thresholds:
   - Workflow task schedule-to-start > 50ms indicates worker pressure
   - `task_slots_available == 0` indicates worker saturation
5. THE Copilot SHALL encode worker scaling warnings as deterministic rules:
   - NEVER recommend scaling down workers when `task_slots_available == 0`
   - Sticky queues prevent new workers from getting long-running workflow work
   - Consider recommending restart of % of existing workers to redistribute
6. THE Copilot SHALL collect worker amplifier signals:
   - Sticky cache hit/miss rate (cache thrash increases DB reads)
   - Long-poll latency and failures
   - Poller vs executor slot mismatch
7. THE RAG knowledge base SHALL include worker remediation guidance:
   - Worker scaling best practices
   - Sticky cache tuning
   - Poller configuration
   - Executor slot sizing

**Source:** Temporal Workers presentation (Tihomir Surdilovic, 2024) - treated as authoritative worker execution doctrine.
