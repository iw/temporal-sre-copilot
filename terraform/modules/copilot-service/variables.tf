variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "service_name" {
  description = "Service name (e.g., worker, api, temporal)"
  type        = string
}

variable "image" {
  description = "Docker image"
  type        = string
}

variable "command" {
  description = "Container command override"
  type        = list(string)
  default     = null
}

variable "cpu" {
  description = "CPU units"
  type        = number
}

variable "memory" {
  description = "Memory in MiB"
  type        = number
}

variable "environment" {
  description = "Environment variables for the container"
  type        = list(object({ name = string, value = string }))
  default     = []
}

variable "port" {
  description = "Container port (null for no port mapping)"
  type        = number
  default     = null
}

variable "port_name" {
  description = "Port name for Service Connect"
  type        = string
  default     = "http"
}

variable "desired_count" {
  description = "Desired task count"
  type        = number
  default     = 0
}

variable "is_primary" {
  description = "Whether this is a primary service (gets base=1 in capacity strategy)"
  type        = bool
  default     = false
}

variable "cluster_id" {
  description = "ECS cluster ID"
  type        = string
}

variable "namespace_arn" {
  description = "Service Connect namespace ARN"
  type        = string
}

variable "capacity_provider_name" {
  description = "ECS capacity provider name"
  type        = string
}

variable "execution_role_arn" {
  description = "ECS task execution role ARN"
  type        = string
}

variable "task_role_arn" {
  description = "ECS task role ARN"
  type        = string
}

variable "security_group_id" {
  description = "Security group ID"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs"
  type        = list(string)
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 7
}


