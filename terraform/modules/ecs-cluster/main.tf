# -----------------------------------------------------------------------------
# ECS Cluster Module
# -----------------------------------------------------------------------------
# Creates the Copilot ECS cluster with Service Connect namespace,
# CloudWatch log groups, and Container Insights.
# -----------------------------------------------------------------------------

resource "aws_service_discovery_http_namespace" "this" {
  name        = "${var.project_name}-copilot"
  description = "Service Connect namespace for ${var.project_name} Copilot services"

  tags = {
    Name = "${var.project_name}-copilot-namespace"
  }
}

resource "aws_cloudwatch_log_group" "ecs_exec" {
  name              = "/ecs/${var.project_name}/copilot-ecs-exec"
  retention_in_days = var.log_retention_days

  tags = { Name = "${var.project_name}-copilot-ecs-exec-logs" }
}

resource "aws_ecs_cluster" "this" {
  name = "${var.project_name}-copilot-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs_exec.name
      }
    }
  }

  service_connect_defaults {
    namespace = aws_service_discovery_http_namespace.this.arn
  }

  tags = { Name = "${var.project_name}-copilot-cluster" }
}
