# Implementation Plan: Standalone Dev Environment

## Overview

Migrate the Copilot's local development environment from `temporal-dsql-deploy` into `temporal-sre-copilot`. Implementation proceeds bottom-up: static files first (configs, templates, Dockerfile), then Terraform, then Grafana dashboards, then the Docker Compose stack, then the CLI, and finally documentation.

## Tasks

- [x] 1. Create Temporal runtime image files
  - [x] 1.1 Create `dev/docker/Dockerfile` layering persistence templates onto `temporal-dsql:latest` base image
    - Copy from `temporal-dsql-deploy/Dockerfile`, adjust COPY paths to reference local `dev/docker/` files
    - Remove OpenSearch-specific env vars (not used in local dev)
    - _Requirements: 3.1_
  - [x] 1.2 Create `dev/docker/render-and-start.sh` entrypoint script
    - Copy from `temporal-dsql-deploy/docker/render-and-start.sh`
    - Validates required env vars, renders template via Python string.Template, checks for unsubstituted vars
    - Must be executable (chmod +x)
    - _Requirements: 3.2_
  - [x] 1.3 Create `dev/docker/persistence-dsql-elasticsearch.template.yaml` persistence config template
    - Copy from `temporal-dsql-deploy/docker/config/persistence-dsql-elasticsearch.template.yaml`
    - Defines DSQL as default store, Elasticsearch as visibility store, service ports, membership, dynamic config path
    - _Requirements: 3.3_

- [x] 2. Create service configuration files
  - [x] 2.1 Create `dev/config/loki.yaml`
    - Copy from `temporal-dsql-deploy/profiles/copilot/config/loki.yaml`
    - Single-binary mode, filesystem storage, 72h retention, TSDB schema v13
    - _Requirements: 2.1_
  - [x] 2.2 Create `dev/config/alloy.alloy`
    - Copy from `temporal-dsql-deploy/profiles/copilot/config/alloy.alloy`
    - 4 Prometheus scrape targets (history, matching, frontend, worker), Docker log discovery, Mimir + Loki forwarding
    - _Requirements: 2.2_
  - [x] 2.3 Create `dev/config/mimir.yaml`
    - Copy from `temporal-dsql-deploy/docker/config/mimir.yaml`
    - Single-binary, memberlist ring, 500k series limit
    - _Requirements: 2.3_
  - [x] 2.4 Create `dev/config/grafana-datasources.yaml`
    - Copy from `temporal-dsql-deploy/profiles/copilot/config/grafana-datasources.yaml`
    - Prometheus (Mimir), CloudWatch, Loki, Copilot JSON API datasources
    - _Requirements: 2.4_
  - [x] 2.5 Create `dev/config/grafana-dashboards.yaml`
    - Copy from `temporal-dsql-deploy/profiles/copilot/config/grafana-dashboards.yaml`
    - 3 dashboard folders: Temporal, DSQL, Copilot
    - _Requirements: 2.5_
  - [x] 2.6 Create `dev/dynamicconfig/development-dsql.yaml`
    - Copy from `temporal-dsql-deploy/profiles/copilot/dynamicconfig/development-dsql.yaml`
    - DSQL optimizations, eager execution, visibility, CHASM scheduler
    - _Requirements: 2.6_
  - [x] 2.7 Create `dev/.env.example`
    - Copy from `temporal-dsql-deploy/profiles/copilot/.env.example`
    - Document all required and optional env vars for both clusters
    - _Requirements: 1.4_

- [x] 3. Create Grafana dashboards
  - [x] 3.1 Copy `grafana/server/server.json` from `temporal-dsql-deploy/grafana/server/server.json`
    - Temporal server health dashboard
    - _Requirements: 4.1_
  - [x] 3.2 Copy `grafana/dsql/persistence.json` from `temporal-dsql-deploy/grafana/dsql/persistence.json`
    - DSQL persistence metrics dashboard
    - _Requirements: 4.2_

- [x] 4. Create Docker Compose stack
  - [x] 4.1 Create `dev/docker-compose.yml` with all 15 services
    - Migrate from `temporal-dsql-deploy/profiles/copilot/docker-compose.yml`
    - Adjust all volume mount paths from `../../docker/config/` and `../../grafana/` to use paths relative to `dev/` directory
    - All services use `platform: linux/arm64`
    - Health checks on elasticsearch, temporal-history, temporal-frontend, copilot-temporal, copilot-worker, copilot-api
    - AWS credential mounts on all DSQL-dependent services
    - Named volumes for persistent data
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 1.8_

- [x] 5. Checkpoint - Verify static files
  - Ensure all config files, templates, Dockerfile, and docker-compose.yml are created correctly. Ask the user if questions arise.

- [x] 6. Create Terraform for ephemeral infrastructure
  - [x] 6.1 Create `terraform/dev/main.tf` with two DSQL clusters, Bedrock KB, S3 buckets, and IAM roles
    - Adapt from `temporal-dsql-deploy/terraform/copilot/main.tf`
    - Add a second DSQL cluster for the monitored cluster
    - Keep Bedrock KB, S3 source bucket, S3 Vectors, IAM role
    - Tag all resources with Lifecycle=ephemeral, ManagedBy=terraform
    - _Requirements: 5.1, 5.5_
  - [x] 6.2 Create `terraform/dev/variables.tf` with project_name and region variables
    - _Requirements: 5.1_
  - [x] 6.3 Create `terraform/dev/outputs.tf` with both DSQL endpoints, KB ID, data source ID, S3 bucket names
    - _Requirements: 5.4_

- [x] 7. Implement Dev CLI
  - [x] 7.1 Create `packages/copilot/src/copilot/cli/dev.py` with the `copilot dev` subcommand group
    - Implement helper functions: `_repo_root()`, `_dev_dir()`, `_compose_cmd()`, `_temporal_dsql_path()`
    - Implement `up`, `down`, `ps`, `logs` commands wrapping Docker Compose
    - Implement `build` command building both Runtime_Image and Copilot_Image
    - Implement `schema` subgroup with `setup` command
    - Implement `infra` subgroup with `apply` and `destroy` commands
    - Use Rich Console for formatted output
    - Use subprocess.run with inherited stdout/stderr
    - Handle errors: missing temporal-dsql repo, subprocess failures, missing tools
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12, 7.1, 7.2, 7.3, 7.4, 7.5_
  - [x] 7.2 Register the dev subcommand in `packages/copilot/src/copilot/cli/__init__.py`
    - Import and add the dev app alongside db and kb
    - _Requirements: 6.1, 9.1, 9.2_
  - [ ]* 7.3 Write unit tests for Dev CLI in `tests/test_dev_cli.py`
    - Test CLI registration (dev subcommand exists alongside db and kb)
    - Test command construction with mocked subprocess
    - Test error handling for missing temporal-dsql path
    - Test path resolution logic
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.10, 9.1, 9.2_
  - [ ]* 7.4 Write property test for template rendering in `tests/properties/test_dev_environment.py`
    - **Property 3: Persistence template rendering completeness**
    - **Validates: Requirements 3.2**
  - [ ]* 7.5 Write property test for schema setup resilience in `tests/properties/test_dev_environment.py`
    - **Property 4: Schema setup resilience**
    - **Validates: Requirements 7.5**

- [x] 8. Checkpoint - Verify CLI and tests
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Update documentation
  - [x] 9.1 Create `dev/README.md` with detailed setup instructions
    - Prerequisites, step-by-step guide, architecture diagram, port mapping, env var reference, troubleshooting
    - _Requirements: 8.3_
  - [x] 9.2 Update `README.md` with a "Local Development" section
    - Prerequisites, quick-start steps, link to dev/README.md
    - _Requirements: 8.1_
  - [x] 9.3 Update `AGENTS.md` with dev/ directory structure and Dev CLI commands
    - _Requirements: 8.2_
  - [x] 9.4 Update `Justfile` with dev recipe group
    - Add `dev-up`, `dev-down`, `dev-build`, `dev-logs`, `dev-ps` recipes
    - _Requirements: 8.4_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Config files are copied from temporal-dsql-deploy and adapted for the new directory structure
- The temporal-dsql repo remains an external dependency for building the Go-based Temporal server image
- Property tests use Hypothesis (already in the project)
- Unit tests mock subprocess calls to avoid requiring Docker/Terraform during test runs
