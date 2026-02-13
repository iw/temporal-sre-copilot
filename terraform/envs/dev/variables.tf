# -----------------------------------------------------------------------------
# Dev Environment Variables
# -----------------------------------------------------------------------------
# Cost-optimized defaults: 1x t4g.medium, halved CPU/memory, 3-day logs.
#
# Bench vs Dev comparison:
#   Instance:  m7g.large (2 vCPU, 8 GiB) x2  →  t4g.medium (2 vCPU, 4 GiB) x1
#   Temporal:  1024 CPU / 2048 MiB             →  512 CPU / 1024 MiB
#   Worker:    2048 CPU / 4096 MiB             →  1024 CPU / 2048 MiB
#   API:       512 CPU / 1024 MiB              →  256 CPU / 512 MiB
#   Logs:      7 days                          →  3 days
#   Reservoir: 20 ready connections            →  5 ready connections
# -----------------------------------------------------------------------------

variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

# VPC (from temporal-dsql-deploy-ecs)
variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "vpc_cidr" {
  type = string
}

# DSQL (from temporal-dsql-deploy-ecs)
variable "dsql_endpoint" {
  type = string
}

variable "dsql_cluster_arn" {
  type = string
}

variable "dsql_database" {
  type    = string
  default = "postgres"
}

# Observability (from temporal-dsql-deploy-ecs)
variable "amp_workspace_id" {
  type = string
}

variable "amp_workspace_arn" {
  type = string
}

variable "loki_url" {
  type = string
}

variable "loki_security_group_id" {
  type = string
}

# Container images
variable "temporal_dsql_image" {
  type = string
}

variable "copilot_image" {
  type = string
}

# Service sizing — halved from bench
variable "temporal_cpu" {
  type    = number
  default = 512
}

variable "temporal_memory" {
  type    = number
  default = 1024
}

variable "worker_cpu" {
  type    = number
  default = 1024
}

variable "worker_memory" {
  type    = number
  default = 2048
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "desired_count" {
  type    = number
  default = 0
}

# EC2 — single small Graviton instance
variable "instance_type" {
  type    = string
  default = "t4g.medium"
}

variable "instance_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 3
}
