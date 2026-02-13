# -----------------------------------------------------------------------------
# Bench Environment Variables
# -----------------------------------------------------------------------------

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
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

# Service sizing
variable "temporal_cpu" {
  type    = number
  default = 1024
}

variable "temporal_memory" {
  type    = number
  default = 2048
}

variable "worker_cpu" {
  type    = number
  default = 2048
}

variable "worker_memory" {
  type    = number
  default = 4096
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 0
}

# EC2 capacity
variable "instance_type" {
  type    = string
  default = "m7g.large"
}

variable "instance_count" {
  type    = number
  default = 2
}

variable "log_retention_days" {
  type    = number
  default = 7
}
