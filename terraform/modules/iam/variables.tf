variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "dsql_cluster_arn" {
  description = "ARN of the Aurora DSQL cluster"
  type        = string
}

variable "amp_workspace_arn" {
  description = "ARN of the AMP workspace"
  type        = string
}
