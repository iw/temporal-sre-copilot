# -----------------------------------------------------------------------------
# Temporal SRE Copilot - Dev Environment
# -----------------------------------------------------------------------------
# Cost-optimized: 1x t4g.medium, halved CPU/memory, 3-day logs.
# -----------------------------------------------------------------------------

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 1.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "awscc" {
  region = var.aws_region
}

# -----------------------------------------------------------------------------
# Modules
# -----------------------------------------------------------------------------

module "ecs_cluster" {
  source = "../../modules/ecs-cluster"

  project_name       = var.project_name
  log_retention_days = var.log_retention_days
}

module "networking" {
  source = "../../modules/networking"

  project_name           = var.project_name
  vpc_id                 = var.vpc_id
  vpc_cidr               = var.vpc_cidr
  loki_security_group_id = var.loki_security_group_id
}

module "ec2_capacity" {
  source = "../../modules/ec2-capacity"

  project_name       = var.project_name
  cluster_name       = module.ecs_cluster.cluster_name
  security_group_id  = module.networking.security_group_id
  private_subnet_ids = var.private_subnet_ids
  instance_type      = var.instance_type
  instance_count     = var.instance_count
}

module "iam" {
  source = "../../modules/iam"

  project_name      = var.project_name
  aws_region        = var.aws_region
  dsql_cluster_arn  = var.dsql_cluster_arn
  amp_workspace_arn = var.amp_workspace_arn
}

module "knowledge_base" {
  source = "../../modules/knowledge-base"

  project_name        = var.project_name
  aws_region          = var.aws_region
  bedrock_kb_role_arn = module.iam.bedrock_kb_role_arn
  bedrock_kb_role_id  = module.iam.bedrock_kb_role_id
}

# -----------------------------------------------------------------------------
# Services
# -----------------------------------------------------------------------------

module "temporal_server" {
  source = "../../modules/copilot-service"

  project_name           = var.project_name
  aws_region             = var.aws_region
  service_name           = "temporal"
  image                  = var.temporal_dsql_image
  cpu                    = var.temporal_cpu
  memory                 = var.temporal_memory
  desired_count          = var.desired_count
  is_primary             = true
  port                   = 7233
  port_name              = "grpc"
  cluster_id             = module.ecs_cluster.cluster_id
  namespace_arn          = module.ecs_cluster.namespace_arn
  capacity_provider_name = module.ec2_capacity.capacity_provider_name
  execution_role_arn     = module.iam.ecs_execution_role_arn
  task_role_arn          = module.iam.copilot_task_role_arn
  security_group_id      = module.networking.security_group_id
  private_subnet_ids     = var.private_subnet_ids
  log_retention_days     = var.log_retention_days

  environment = [
    { name = "TEMPORAL_ADDRESS", value = "0.0.0.0:7233" },
    { name = "TEMPORAL_SQL_PLUGIN", value = "dsql" },
    { name = "TEMPORAL_SQL_HOST", value = var.dsql_endpoint },
    { name = "TEMPORAL_SQL_PORT", value = "5432" },
    { name = "TEMPORAL_SQL_DATABASE", value = var.dsql_database },
    { name = "TEMPORAL_SQL_TLS_ENABLED", value = "true" },
    { name = "TEMPORAL_SQL_IAM_AUTH", value = "true" },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "DSQL_RESERVOIR_ENABLED", value = "true" },
    { name = "DSQL_RESERVOIR_TARGET_READY", value = "5" },
    { name = "DSQL_RESERVOIR_BASE_LIFETIME", value = "11m" },
    { name = "DSQL_RESERVOIR_LIFETIME_JITTER", value = "2m" },
    { name = "DSQL_RESERVOIR_GUARD_WINDOW", value = "45s" },
  ]
}

module "worker" {
  source = "../../modules/copilot-service"

  project_name           = var.project_name
  aws_region             = var.aws_region
  service_name           = "worker"
  image                  = var.copilot_image
  command                = ["python", "-m", "copilot.worker"]
  cpu                    = var.worker_cpu
  memory                 = var.worker_memory
  desired_count          = var.desired_count
  cluster_id             = module.ecs_cluster.cluster_id
  namespace_arn          = module.ecs_cluster.namespace_arn
  capacity_provider_name = module.ec2_capacity.capacity_provider_name
  execution_role_arn     = module.iam.ecs_execution_role_arn
  task_role_arn          = module.iam.copilot_task_role_arn
  security_group_id      = module.networking.security_group_id
  private_subnet_ids     = var.private_subnet_ids
  log_retention_days     = var.log_retention_days

  environment = [
    { name = "TEMPORAL_ADDRESS", value = "copilot-temporal:7233" },
    { name = "AMP_WORKSPACE_ID", value = var.amp_workspace_id },
    { name = "LOKI_URL", value = var.loki_url },
    { name = "DSQL_ENDPOINT", value = var.dsql_endpoint },
    { name = "DSQL_DATABASE", value = var.dsql_database },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "KNOWLEDGE_BASE_ID", value = module.knowledge_base.knowledge_base_id },
  ]
}

module "api" {
  source = "../../modules/copilot-service"

  project_name           = var.project_name
  aws_region             = var.aws_region
  service_name           = "api"
  image                  = var.copilot_image
  command                = ["uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8080"]
  cpu                    = var.api_cpu
  memory                 = var.api_memory
  desired_count          = var.desired_count
  port                   = 8080
  port_name              = "http"
  cluster_id             = module.ecs_cluster.cluster_id
  namespace_arn          = module.ecs_cluster.namespace_arn
  capacity_provider_name = module.ec2_capacity.capacity_provider_name
  execution_role_arn     = module.iam.ecs_execution_role_arn
  task_role_arn          = module.iam.copilot_task_role_arn
  security_group_id      = module.networking.security_group_id
  private_subnet_ids     = var.private_subnet_ids
  log_retention_days     = var.log_retention_days

  environment = [
    { name = "DSQL_ENDPOINT", value = var.dsql_endpoint },
    { name = "DSQL_DATABASE", value = var.dsql_database },
    { name = "AWS_REGION", value = var.aws_region },
  ]
}
