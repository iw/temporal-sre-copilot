# Requirements Document

## Introduction

Migrate the local development environment for the Temporal SRE Copilot from the `temporal-dsql-deploy` repository into the `temporal-sre-copilot` repository itself. This eliminates the cross-repo dependency for day-to-day Copilot development by bringing the Docker Compose stack (15 services), observability configuration, Terraform for ephemeral AWS resources, and CLI commands into a self-contained `dev/` directory. The only remaining external dependency is the `temporal-dsql` repository for building the Temporal runtime Docker image.

## Glossary

- **Dev_Environment**: The local Docker Compose stack comprising a monitored Temporal cluster, observability services, and the Copilot cluster, all running on a single Docker network.
- **Monitored_Cluster**: The Temporal deployment (history, matching, frontend, worker) backed by Aurora DSQL and Elasticsearch that the Copilot observes.
- **Copilot_Cluster**: A separate single-binary Temporal instance backed by its own DSQL cluster, used to run the Copilot's Pydantic AI workflows.
- **Observability_Stack**: Mimir (metrics), Loki (logs), Alloy (collection), and Grafana (dashboards).
- **Dev_CLI**: The `copilot dev` subcommand group in the existing Typer-based CLI that orchestrates the Dev_Environment.
- **Runtime_Image**: The `temporal-dsql-runtime:test` Docker image built from the `temporal-dsql` repository, layered with persistence config templates and an entrypoint script.
- **Copilot_Image**: The `temporal-sre-copilot:dev` Docker image built from the Copilot Dockerfile in this repository.
- **Ephemeral_Infra**: AWS resources (DSQL clusters, Bedrock Knowledge Base, S3 buckets) provisioned via Terraform for local development and destroyed after use.
- **DSQL**: Amazon Aurora DSQL, a serverless PostgreSQL-compatible database with IAM authentication.
- **Bedrock_KB**: Amazon Bedrock Knowledge Base used for RAG retrieval in health explanations.

## Requirements

### Requirement 1: Docker Compose Stack

**User Story:** As a Copilot developer, I want a self-contained Docker Compose stack in the `temporal-sre-copilot` repo, so that I can run the full development environment without cloning or depending on `temporal-dsql-deploy`.

#### Acceptance Criteria

1. THE Dev_Environment SHALL include a `dev/docker-compose.yml` file defining all 15 services across three groups: Monitored_Cluster (elasticsearch, elasticsearch-setup, temporal-history, temporal-matching, temporal-frontend, temporal-worker, temporal-ui), Observability_Stack (mimir, loki, alloy, grafana), and Copilot_Cluster (copilot-temporal, copilot-ui, copilot-worker, copilot-api).
2. WHEN the Dev_Environment starts, THE Monitored_Cluster SHALL connect to a real Aurora DSQL cluster for persistence and a local Elasticsearch instance for visibility.
3. WHEN the Dev_Environment starts, THE Copilot_Cluster SHALL connect to a separate Aurora DSQL cluster for its own persistence and reuse the same local Elasticsearch instance with a distinct visibility index.
4. THE Dev_Environment SHALL include a `dev/.env.example` file documenting all required and optional environment variables for both DSQL clusters, Elasticsearch, AWS region, and Bedrock KB configuration.
5. WHEN the Dev_Environment starts, THE Observability_Stack SHALL collect Prometheus metrics from all four Monitored_Cluster services via Alloy, store them in Mimir, collect container logs via Loki, and expose all data through Grafana with pre-provisioned datasources and dashboards.
6. THE Dev_Environment SHALL use `platform: linux/arm64` for all service definitions to target Apple Silicon and Graviton architectures.
7. THE Dev_Environment SHALL define health checks for elasticsearch, temporal-history, temporal-frontend, copilot-temporal, copilot-worker, and copilot-api services with appropriate start periods and retry counts.
8. THE Dev_Environment SHALL mount the host `~/.aws` directory as read-only into all services that require AWS credentials for DSQL IAM authentication.

### Requirement 2: Service Configuration Files

**User Story:** As a Copilot developer, I want all service configuration files co-located in the `dev/` directory, so that I can modify observability and Temporal settings without switching repositories.

#### Acceptance Criteria

1. THE Dev_Environment SHALL include a `dev/config/loki.yaml` file configuring Loki in single-binary mode with filesystem storage and 72-hour retention.
2. THE Dev_Environment SHALL include a `dev/config/alloy.alloy` file configuring Alloy to scrape Prometheus metrics from temporal-history, temporal-matching, temporal-frontend, and temporal-worker on port 9090, forward metrics to Mimir, discover Docker containers for log collection, and forward logs to Loki.
3. THE Dev_Environment SHALL include a `dev/config/mimir.yaml` file configuring Mimir in single-binary mode with filesystem storage and high-cardinality limits suitable for Temporal metrics.
4. THE Dev_Environment SHALL include a `dev/config/grafana-datasources.yaml` file provisioning four datasources: Prometheus (Mimir), CloudWatch, Loki, and Copilot JSON API.
5. THE Dev_Environment SHALL include a `dev/config/grafana-dashboards.yaml` file provisioning dashboard folders for Temporal Server, DSQL Persistence, and SRE Copilot, sourcing JSON files from the `grafana/` directory.
6. THE Dev_Environment SHALL include a `dev/dynamicconfig/development-dsql.yaml` file with Temporal dynamic configuration for DSQL optimizations, eager execution, visibility settings, and CHASM scheduler support.

### Requirement 3: Temporal Runtime Image Build

**User Story:** As a Copilot developer, I want to build the Temporal DSQL runtime image from within this repository, so that I can set up the monitored cluster without running build scripts from `temporal-dsql-deploy`.

#### Acceptance Criteria

1. THE Dev_Environment SHALL include a `dev/docker/Dockerfile` that layers persistence configuration templates and an entrypoint script onto a `temporal-dsql:latest` base image built from the `temporal-dsql` repository.
2. THE Dev_Environment SHALL include a `dev/docker/render-and-start.sh` entrypoint script that renders persistence YAML templates by substituting environment variables, validates all required variables are present, checks for unsubstituted variables, and delegates to the base image entrypoint.
3. THE Dev_Environment SHALL include a `dev/docker/persistence-dsql-elasticsearch.template.yaml` persistence configuration template supporting DSQL as the default store and Elasticsearch as the visibility store, with environment variable placeholders for all connection parameters.
4. WHEN the Dev_CLI builds the Runtime_Image, THE Dev_CLI SHALL verify that the `temporal-dsql` repository exists at the configured path, build the base `temporal-dsql:latest` image from that repository, and then build the `temporal-dsql-runtime:test` image using the `dev/docker/Dockerfile`.

### Requirement 4: Grafana Dashboards

**User Story:** As a Copilot developer, I want all Grafana dashboards available in this repository, so that I can view Temporal server health, DSQL persistence metrics, and Copilot health state without depending on external dashboard files.

#### Acceptance Criteria

1. THE Dev_Environment SHALL include a `grafana/server/server.json` dashboard for Temporal server health metrics.
2. THE Dev_Environment SHALL include a `grafana/dsql/persistence.json` dashboard for DSQL persistence metrics.
3. WHEN Grafana starts, THE Observability_Stack SHALL mount the `grafana/` directory and provision all three dashboard folders (server, dsql, copilot) automatically.

### Requirement 5: Ephemeral Infrastructure

**User Story:** As a Copilot developer, I want to provision and destroy ephemeral AWS resources (DSQL clusters, Bedrock KB) from within this repository, so that I can manage the full development lifecycle without `temporal-dsql-deploy`.

#### Acceptance Criteria

1. THE Dev_Environment SHALL include a `terraform/dev/` directory with Terraform configuration for provisioning two Aurora DSQL clusters (monitored and copilot), a Bedrock Knowledge Base with S3 Vectors storage, S3 source document bucket, and associated IAM roles.
2. WHEN the Dev_CLI provisions Ephemeral_Infra, THE Dev_CLI SHALL run `terraform init` and `terraform apply` in the `terraform/dev/` directory.
3. WHEN the Dev_CLI destroys Ephemeral_Infra, THE Dev_CLI SHALL run `terraform destroy` in the `terraform/dev/` directory.
4. THE Ephemeral_Infra SHALL output the DSQL endpoints, Knowledge Base ID, data source ID, and S3 bucket names so the Dev_CLI can populate the `.env` file.
5. THE Ephemeral_Infra SHALL tag all resources with `Lifecycle=ephemeral` and `ManagedBy=terraform` tags.

### Requirement 6: Dev CLI Commands

**User Story:** As a Copilot developer, I want a `copilot dev` CLI subcommand group, so that I can manage the entire development environment with simple commands.

#### Acceptance Criteria

1. THE Dev_CLI SHALL be implemented as a Typer subcommand group registered under the existing `copilot` CLI entry point at `packages/copilot/src/copilot/cli/dev.py`.
2. WHEN a user runs `copilot dev up`, THE Dev_CLI SHALL start all Docker Compose services in the `dev/` directory, passing through the `-d` flag for detached mode when specified.
3. WHEN a user runs `copilot dev down`, THE Dev_CLI SHALL stop all Docker Compose services, passing through the `-v` flag to remove volumes when specified.
4. WHEN a user runs `copilot dev build`, THE Dev_CLI SHALL build both the Runtime_Image (from `temporal-dsql` base) and the Copilot_Image (from the repo root Dockerfile), tagging them as `temporal-dsql-runtime:test` and `temporal-sre-copilot:dev` respectively.
5. WHEN a user runs `copilot dev ps`, THE Dev_CLI SHALL display the status of all Docker Compose services.
6. WHEN a user runs `copilot dev logs`, THE Dev_CLI SHALL tail logs from all services, or from a specific service when a service name argument is provided.
7. WHEN a user runs `copilot dev schema setup`, THE Dev_CLI SHALL apply the Temporal DSQL schema to both the monitored and copilot DSQL clusters, and apply the Copilot application schema to the copilot DSQL cluster.
8. WHEN a user runs `copilot dev infra apply`, THE Dev_CLI SHALL provision the Ephemeral_Infra using Terraform and display the output values.
9. WHEN a user runs `copilot dev infra destroy`, THE Dev_CLI SHALL destroy the Ephemeral_Infra using Terraform.
10. IF the `temporal-dsql` repository is not found at the configured path during `copilot dev build`, THEN THE Dev_CLI SHALL display an error message indicating the expected path and how to configure it via the `TEMPORAL_DSQL_PATH` environment variable.
11. THE Dev_CLI SHALL use Rich for formatted terminal output consistent with the existing `copilot db` and `copilot kb` commands.
12. THE Dev_CLI SHALL execute Docker Compose and Terraform commands via `subprocess` with real-time stdout/stderr streaming.

### Requirement 7: Schema Management

**User Story:** As a Copilot developer, I want a single command to set up all database schemas, so that I can initialize both DSQL clusters and the Copilot state store in one step.

#### Acceptance Criteria

1. WHEN the Dev_CLI sets up schemas, THE Dev_CLI SHALL apply the Temporal persistence schema to the monitored DSQL cluster using the `temporal-dsql-tool` from the Runtime_Image.
2. WHEN the Dev_CLI sets up schemas, THE Dev_CLI SHALL apply the Temporal persistence schema to the copilot DSQL cluster using the `temporal-dsql-tool` from the Runtime_Image.
3. WHEN the Dev_CLI sets up schemas, THE Dev_CLI SHALL apply the Copilot application schema (from `packages/copilot/src/copilot/db/schema.sql`) to the copilot DSQL cluster.
4. WHEN the Dev_CLI sets up schemas, THE Dev_CLI SHALL create the Elasticsearch visibility indices for both clusters.
5. IF a schema setup step fails, THEN THE Dev_CLI SHALL report the specific failure and continue with remaining steps.

### Requirement 8: Documentation Updates

**User Story:** As a Copilot developer, I want all project documentation updated to reflect the standalone development environment, so that new contributors can set up and use the local dev stack without referencing `temporal-dsql-deploy`.

#### Acceptance Criteria

1. WHEN the Dev_Environment is added, THE README.md SHALL be updated with a "Local Development" section documenting prerequisites (Docker Desktop 6GB+, AWS credentials, `temporal-dsql` repo), quick-start steps, and links to detailed documentation.
2. WHEN the Dev_Environment is added, THE AGENTS.md SHALL be updated to describe the `dev/` directory structure, the Dev_CLI commands, and the relationship between the standalone dev environment and the existing ECS deployment infrastructure.
3. THE Dev_Environment SHALL include a `dev/README.md` file with detailed setup instructions, architecture diagram, service descriptions, port mappings, environment variable reference, and troubleshooting guidance.
4. WHEN the Dev_Environment is added, THE Justfile SHALL be updated with a `dev` recipe group providing shortcuts for common dev environment operations (e.g., `just dev-up`, `just dev-down`, `just dev-build`).

### Requirement 9: Existing CLI Preservation

**User Story:** As a Copilot developer, I want the existing `copilot db` and `copilot kb` commands to remain unchanged, so that production-oriented workflows are not disrupted.

#### Acceptance Criteria

1. WHEN the Dev_CLI is added, THE existing `copilot db` subcommand group SHALL continue to function with the same interface and behavior.
2. WHEN the Dev_CLI is added, THE existing `copilot kb` subcommand group SHALL continue to function with the same interface and behavior.
3. THE Dev_CLI SHALL not introduce new required dependencies that affect the `copilot db` or `copilot kb` commands.
