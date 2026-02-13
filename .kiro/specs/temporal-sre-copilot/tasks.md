# Implementation Plan: Temporal SRE Copilot

## Overview

This implementation plan creates an AI-powered observability agent for Temporal deployments. The Copilot uses Pydantic AI workflows running on a separate Temporal cluster to observe signals, derive health state from forward progress using deterministic rules, and expose assessments via a JSON API for Grafana.

**Key Architectural Principle**: "Rules decide, AI explains" - The Health State Machine uses deterministic rules to evaluate primary signals and set health state. The LLM receives the state and explains/ranks issues—it never decides state transitions.

The Copilot is implemented in a separate workspace (`temporal-sre-copilot/`) with its own Terraform that references dependent resources from `temporal-dsql-deploy-ecs` via `terraform.tfvars`.

## Tasks

- [x] 1. Project Setup and Infrastructure Foundation
  - [x] 1.1 Initialize Python project with uv
    - Create `temporal-sre-copilot/pyproject.toml` with Python 3.14+, dependencies (pydantic-ai, temporalio, fastapi, boto3, asyncpg, httpx, typer, rich)
    - Configure ruff for linting/formatting
    - Create project directory structure (src/copilot/, tests/)
    - Add CLI entry point `copilot = "copilot.cli:app"`
    - _Requirements: 8.4, 8.5, 11.1, 11.5_

  - [x] 1.2 Create Terraform in separate workspace
    - Create `temporal-sre-copilot/terraform/` directory structure
    - Define variables for DSQL endpoint, AMP workspace, Loki URL, VPC configuration
    - Create `terraform.tfvars.example` with values from temporal-dsql-deploy-ecs
    - Create ECS cluster for Copilot services
    - _Requirements: 8.1, 8.2, 8.5_

  - [x] 1.3 Create IAM roles and policies
    - Create task execution role with ECR, CloudWatch Logs permissions
    - Create task role with AMP read, Bedrock invoke, DSQL connect, Loki read permissions
    - Create Bedrock Knowledge Base service role
    - _Requirements: 8.3_

  - [x] 1.4 Create DSQL schema and CLI commands
    - Create `health_assessments` table schema
    - Create `issues` table schema
    - Create `metrics_snapshots` table schema
    - Implement `copilot db setup-schema` CLI command
    - Implement `copilot db check-connection` CLI command
    - Implement `copilot db list-tables` CLI command
    - _Requirements: 5.1, 5.4, 11.2_

- [x] 2. Checkpoint - Verify infrastructure foundation
  - Ensure Terraform validates successfully
  - Ensure CLI commands work with DSQL
  - Ask the user if questions arise

- [x] 3. Bedrock Knowledge Base Setup
  - [x] 3.1 Create S3 buckets for knowledge base
    - S3 bucket for source documents (versioning enabled)
    - S3 bucket for vector storage
    - Configure bucket policies for Bedrock access
    - _Requirements: 3.1_

  - [x] 3.2 Create Bedrock Knowledge Base (manual or future Terraform)
    - Create knowledge base with Titan Embeddings V2
    - Configure S3 Vectors as storage backend
    - Create S3 data source pointing to source bucket
    - _Requirements: 3.1, 3.2_

  - [x] 3.3 Implement knowledge base CLI commands
    - Implement `copilot kb sync` to upload docs to S3
    - Implement `copilot kb start-ingestion` to trigger KB ingestion
    - Implement `copilot kb status` to check KB/job status
    - Implement `copilot kb list-jobs` to list recent ingestion jobs
    - _Requirements: 3.5, 11.3_

- [x] 4. Pydantic Models and Core Types
  - [x] 4.1 Create health state machine and signal models
    - Define `HealthState` enum (happy, stressed, critical)
    - Define `PrimarySignals` model (forward progress indicators)
    - Define `AmplifierSignals` model (explain why)
    - Define `LogPattern` model (narrative signals)
    - Define `Signals` model combining all signal types
    - _Requirements: 1.2, 12.1_

  - [x] 4.2 Create health assessment models
    - Define `Severity` enum (warning, critical)
    - Define `ActionType` enum (scale, restart, configure, alert)
    - Define `SuggestedAction`, `Issue`, `HealthAssessment` models
    - Ensure `HealthAssessment.health_state` is passed in, not decided by LLM
    - _Requirements: 4.3, 10.2_

  - [ ]* 4.3 Write property test for HealthAssessment round-trip
    - **Property 6: Health Assessment Structure Round-Trip**
    - **Validates: Requirements 4.3**

  - [x] 4.4 Create configuration models
    - Define threshold configuration for primary signals
    - Define pressure thresholds for amplifier signals
    - Define error pattern configuration for narrative signals
    - Define environment variable parsing
    - _Requirements: 1.3, 1.4, 2.2_

  - [x] 4.5 Implement Health State Machine
    - Implement `evaluate_health_state()` function
    - Ensure deterministic evaluation (no LLM)
    - Implement state transition rules (Happy → Stressed → Critical)
    - Ensure Happy → Critical requires intermediate Stressed state
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 4.6 Write property test for Health State Machine
    - **Property 12: Health State Machine Invariants**
    - Test forward progress invariant
    - Test no direct Happy → Critical transition
    - **Validates: Requirements 12.2, 12.3**

- [x] 4.7 Review and expand signals from benchmark findings
  - Review Grafana dashboards from benchmark runs (Server Health, DSQL Persistence, Workers)
  - Identify additional primary signals (forward progress indicators)
  - Identify additional amplifier signals (resource pressure, contention)
  - Identify additional narrative patterns (log patterns from benchmark stress)
  - Document PromQL queries for each signal
  - Update `PrimarySignals`, `AmplifierSignals` models with new fields
  - Update `NarrativePatterns` config with new log patterns
  - Update design.md Signal Taxonomy tables
  - _Requirements: 1.2, 1.3, 1.4, 2.2_

- [-] 4.8 Implement Worker Health Model
  - [x] 4.8.1 Create WorkerSignals model
    - Define `WorkerSignals` model with schedule-to-start latencies
    - Add workflow/activity slots available fields
    - Add poller count fields
    - Define thresholds (50ms WFT schedule-to-start, 0 slots = critical)
    - _Requirements: 14.1, 14.4_

  - [x] 4.8.2 Create WorkerAmplifiers model
    - Define `WorkerCacheAmplifiers` (sticky cache size, hit/miss rate)
    - Define `WorkerPollAmplifiers` (long poll latency, failures)
    - Add poller/executor mismatch detection
    - _Requirements: 14.6_

  - [x] 4.8.3 Implement BottleneckClassification
    - Define `BottleneckClassification` enum (server_limited, worker_limited, mixed, healthy)
    - Implement `classify_bottleneck()` function
    - Ensure deterministic classification (no LLM)
    - _Requirements: 14.2, 14.3_

  - [x] 4.8.4 Implement worker scaling rules
    - Implement NEVER_SCALE_DOWN_AT_ZERO rule
    - Implement STICKY_QUEUE_WARNING rule
    - Implement RESTART_TO_REDISTRIBUTE suggestion
    - Implement POLLER_EXECUTOR_MISMATCH warning
    - _Requirements: 14.5_

  - [x] 4.8.5 Add worker signal queries to AMP activity
    - Add PromQL queries for worker SDK metrics
    - Query `temporal_workflow_task_schedule_to_start_latency`
    - Query `temporal_worker_task_slots_available`
    - Query `temporal_num_pollers`
    - Query sticky cache metrics
    - _Requirements: 14.1_

  - [x] 4.8.6 Create worker remediation RAG documents
    - Create `docs/rag/worker_scaling.md`
    - Create `docs/rag/sticky_cache_tuning.md`
    - Create `docs/rag/poller_configuration.md`
    - _Requirements: 14.7_

  - [x] 4.8.7 Write property test for bottleneck classification
    - **Property 14: Bottleneck Classification Correctness**
    - Test server-limited vs worker-limited classification
    - Test NEVER_SCALE_DOWN_AT_ZERO rule
    - **Validates: Requirements 14.2, 14.5**

- [x] 5. Activities Implementation
  - [x] 5.1 Implement AMP signal fetching activity
    - Create `fetch_signals_from_amp` activity
    - Query primary signals (state transitions, completions, backlog age)
    - Query amplifier signals (DSQL latency, OCC conflicts, pool utilization)
    - Parse Prometheus response format
    - _Requirements: 1.1, 1.3, 1.4_

  - [ ]* 5.2 Write property test for signal classification
    - **Property 1: Signal Classification Correctness**
    - Verify primary signals are forward progress indicators
    - Verify amplifiers explain resource pressure
    - **Validates: Requirements 1.2, 1.3**

  - [x] 5.3 Implement Loki log querying activity
    - Create `query_loki_errors` activity
    - Query for narrative signal patterns (service errors, DSQL errors, ringpop, shard events)
    - Parse Loki response format
    - _Requirements: 2.1, 2.2_

  - [ ]* 5.4 Write property test for log pattern detection
    - **Property 3: Log Pattern Detection**
    - **Validates: Requirements 2.2, 2.3**

  - [x] 5.5 Implement RAG context retrieval activity
    - Create `fetch_rag_context` activity
    - Use Bedrock Knowledge Base retrieve API
    - Limit to 5 results
    - Exclude raw metrics/PromQL (per RAG corpus guidance)
    - _Requirements: 3.3, 3.4, 3.6_

  - [ ]* 5.6 Write property test for RAG retrieval
    - **Property 5: RAG Semantic Retrieval**
    - **Validates: Requirements 3.2, 3.3, 3.4**

  - [x] 5.7 Implement state store activities
    - Create `store_health_assessment` activity
    - Create `store_signals_snapshot` activity
    - Create `get_latest_assessment` activity
    - Create `get_assessments_in_range` activity
    - _Requirements: 5.2, 5.4_

  - [ ]* 5.8 Write property test for state store round-trip
    - **Property 8: State Store Round-Trip**
    - **Validates: Requirements 5.2, 5.4**

- [x] 6. Checkpoint - Verify activities
  - Ensure all activities can be imported
  - Run property tests
  - Ask the user if questions arise

- [x] 6.1 Migrate to `whenever` for date/time handling
  - Add `whenever` dependency to pyproject.toml
  - Update `Signals` model to use `Instant` instead of `datetime`
  - Update `HealthAssessment` model to use `Instant`
  - Update activities to use `Instant` and `TimeDelta`
  - Update state store activities for DSQL `TIMESTAMPTZ` conversion
  - Ensure all JSON serialization uses ISO 8601 format
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_


- [x] 7. Pydantic AI Agents
  - [x] 7.1 Implement dispatcher agent
    - Define `NoExplanationNeeded`, `QuickExplanation`, `NeedsDeepExplanation` output types
    - Create dispatcher agent with Claude Sonnet 4.5
    - Configure instructions emphasizing "health state already decided"
    - Agent decides explanation depth, NOT health state
    - _Requirements: 4.3, 4.4_

  - [x] 7.2 Implement researcher agent
    - Create researcher agent with Claude Opus 4.6
    - Configure instructions emphasizing "explain, don't decide"
    - Set `HealthAssessment` as output type
    - Ensure agent cannot change `health_state` field
    - _Requirements: 4.4, 4.5, 4.6_

  - [ ]* 7.3 Write property test for prompt construction
    - **Property 7: Prompt Construction Completeness**
    - Verify health_state is passed in, not computed
    - Verify no sensitive data in prompts
    - **Validates: Requirements 4.5, 4.9**

- [x] 8. Temporal Workflows
  - [x] 8.1 Implement ObserveClusterWorkflow
    - Create continuous workflow with 30-second sleep
    - Fetch signals, evaluate health state (deterministic)
    - Trigger AssessHealthWorkflow on state change
    - Maintain sliding window of signals
    - _Requirements: 1.1, 1.5, 1.6, 12.1_

  - [ ]* 8.2 Write property test for sliding window
    - **Property 2: Sliding Window Invariant**
    - **Validates: Requirements 1.6**

  - [x] 8.3 Implement LogWatcherWorkflow
    - Create continuous workflow with 30-second sleep
    - Query Loki, detect narrative signal patterns
    - Store patterns for correlation
    - _Requirements: 2.1, 2.2_

  - [x] 8.4 Implement AssessHealthWorkflow
    - Create workflow with dispatcher → researcher pattern
    - Receive health_state (already decided by rules)
    - Fetch RAG context, log patterns, signal history
    - Ensure LLM explains but doesn't change state
    - Store health assessment
    - _Requirements: 4.3, 4.4, 4.5, 4.6_

  - [ ]* 8.5 Write property test for log-signal correlation
    - **Property 4: Log-Signal Correlation**
    - **Validates: Requirements 2.5**

  - [x] 8.6 Implement ScheduledAssessmentWorkflow
    - Create workflow with 5-minute sleep
    - Check for recent assessment to avoid duplicates
    - Evaluate health state and trigger assessment if needed
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 8.7 Write property test for assessment deduplication
    - **Property 10: Assessment Deduplication**
    - **Validates: Requirements 9.5**

- [x] 9. Checkpoint - Verify workflows
  - Ensure all workflows can be registered
  - Run property tests
  - Ask the user if questions arise

- [x] 10. FastAPI Service
  - [x] 10.1 Create FastAPI application
    - Initialize FastAPI app with CORS middleware
    - Configure JSON API data source compatibility
    - Follow "Grafana consumes, not computes" principle
    - _Requirements: 6.2, 6.5, 6.6_

  - [x] 10.2 Implement /status endpoint
    - Return current health state with signal taxonomy
    - Include primary_signals, amplifiers, log_patterns, recommended_actions
    - _Requirements: 6.1, 6.2_

  - [x] 10.3 Implement /status/services endpoint
    - Return per-service health status
    - Derive from pre-computed signals
    - Format for Grafana grid panel
    - _Requirements: 6.1_

  - [x] 10.4 Implement /status/issues endpoint
    - Return active issues list with contributing factors
    - Support severity filter and limit parameter
    - Include related_signals for each issue
    - _Requirements: 6.1_

  - [x] 10.5 Implement /status/summary endpoint
    - Return natural language summary
    - Include timestamp and health_state
    - _Requirements: 6.1_

  - [x] 10.6 Implement /status/timeline endpoint
    - Return health state changes over time
    - Support time range parameters
    - Include primary_signals for each point
    - _Requirements: 6.1, 6.3_

  - [x] 10.7 Implement /actions endpoint (stub)
    - Return 501 Not Implemented
    - Structure for future automation
    - _Requirements: 10.3_

  - [ ]* 10.8 Write property test for API response format
    - **Property 9: API Response Format**
    - Verify signal taxonomy structure
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [ ]* 10.9 Write property test for suggested action structure
    - **Property 11: Suggested Action Structure**
    - **Validates: Requirements 10.2**


- [x] 11. Worker Entry Point
  - [x] 11.1 Create worker main module
    - Initialize Temporal client with PydanticAIPlugin
    - Register all workflows and activities
    - Start worker on task queue
    - _Requirements: 8.2_

  - [x] 11.2 Create workflow starter
    - Start ObserveClusterWorkflow
    - Start LogWatcherWorkflow
    - Start ScheduledAssessmentWorkflow
    - _Requirements: 1.1, 2.1, 9.1_

- [x] 12. Checkpoint - Verify worker
  - Ensure worker starts successfully
  - Ensure workflows can be started
  - Ask the user if questions arise

- [x] 13. Docker and ECS Deployment
  - [x] 13.1 Create Dockerfile
    - Multi-stage build with uv
    - Python 3.14-slim base
    - Configure for worker and API entry points
    - _Requirements: 8.2_

  - [x] 13.2 Verify ECS task definitions
    - Temporal server task definition (DSQL backend)
    - Copilot worker task definition
    - API service task definition
    - _Requirements: 8.2_

  - [x] 13.3 Verify ECS services
    - Temporal server service
    - Copilot worker service
    - API service with Service Connect
    - _Requirements: 8.2_

  - [x] 13.4 Verify networking
    - Security groups for internal communication
    - VPC endpoint access for AMP, Bedrock
    - Service Connect for inter-service communication
    - _Requirements: 8.1_

- [x] 14. Grafana Dashboard
  - [x] 14.1 Create Grafana data source configuration
    - Configure JSON API data source for Copilot API
    - _Requirements: 7.1_

  - [x] 14.2 Create Copilot Insights hero panel
    - Robot avatar with status badge (Happy/Stressed/Critical)
    - Confidence score and "Last Analysis" timestamp
    - Natural language summary
    - Warning callout for critical issue
    - _Requirements: 7.1_

  - [x] 14.3 Create status filter toggle
    - Happy/Stressed/Critical filter buttons
    - Filter applies to entire dashboard
    - _Requirements: 7.2_

  - [x] 14.4 Create Analysis and Suggested Remediations panel
    - Two-column layout
    - Analysis: bullet points explaining what's happening
    - Remediations: actionable recommendations with confidence %
    - "View Guide" link for RAG documentation
    - _Requirements: 7.3, 7.4_

  - [x] 14.5 Create Signal Metrics grid
    - Key metrics with current value and sparkline
    - Specific metrics TBD based on operational experience
    - _Requirements: 7.5_

  - [x] 14.6 Create Log Pattern Alerts table
    - Occurrence count, pattern description, service tag
    - Sortable by occurrences
    - _Requirements: 7.6_

  - [x] 14.7 Configure dashboard auto-refresh and links
    - 30-second auto-refresh
    - Links to related dashboards (Server Health, DSQL Persistence, Workers)
    - _Requirements: 7.7, 7.8_

- [x] 15. Final Checkpoint
  - Ensure all tests pass
  - Ensure Terraform applies successfully
  - Ensure Grafana dashboard loads
  - Ask the user if questions arise

## Notes

- Tasks marked with `*` are optional property-based tests
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The Copilot is in a separate workspace (`temporal-sre-copilot/`) from the main deployment
- CLI commands use Python Typer with Rich for elegant terminal output
- **Key Principle**: "Rules decide, AI explains" - Health state is determined by deterministic rules, LLM only explains
- **Signal Taxonomy**: Primary (decide state), Amplifiers (explain why), Narrative (logs explain transitions)
- **Health State Machine**: Happy → Stressed → Critical, anchored to forward progress invariant
