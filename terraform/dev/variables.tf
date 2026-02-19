variable "project_name" {
  type        = string
  description = "Resource name prefix"
}

variable "region" {
  type        = string
  default     = "eu-west-1"
  description = "AWS region"
}
