variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "cluster_name" {
  description = "ECS cluster name"
  type        = string
}

variable "security_group_id" {
  description = "Security group ID for EC2 instances"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the ASG"
  type        = list(string)
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "m7g.large"
}

variable "instance_count" {
  description = "Number of EC2 instances"
  type        = number
  default     = 2
}
