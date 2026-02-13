variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "bedrock_kb_role_arn" {
  description = "ARN of the Bedrock KB service role"
  type        = string
}

variable "bedrock_kb_role_id" {
  description = "ID of the Bedrock KB service role (for attaching policies)"
  type        = string
}
