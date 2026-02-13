# -----------------------------------------------------------------------------
# Copilot Service Module
# -----------------------------------------------------------------------------
# Generic module for Copilot ECS services (worker, API).
# Creates task definition, log group, and ECS service.
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.project_name}/copilot-${var.service_name}"
  retention_in_days = var.log_retention_days

  tags = { Name = "${var.project_name}-copilot-${var.service_name}-logs" }
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.project_name}-copilot-${var.service_name}"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name      = var.service_name
    image     = var.image
    essential = true
    command   = var.command

    environment = var.environment

    portMappings = var.port != null ? [{
      containerPort = var.port
      hostPort      = var.port
      protocol      = "tcp"
      name          = var.port_name
    }] : []

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = var.service_name
      }
    }

    linuxParameters = {
      initProcessEnabled = true
    }
  }])

  tags = { Name = "${var.project_name}-copilot-${var.service_name}" }
}

resource "aws_ecs_service" "this" {
  name            = "copilot-${var.service_name}"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count

  capacity_provider_strategy {
    capacity_provider = var.capacity_provider_name
    weight            = 100
    base              = var.is_primary ? 1 : 0
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  service_connect_configuration {
    enabled   = true
    namespace = var.namespace_arn

    dynamic "service" {
      for_each = var.port != null ? [1] : []
      content {
        port_name = var.port_name
        client_alias {
          port     = var.port
          dns_name = "copilot-${var.service_name}"
        }
      }
    }
  }

  enable_execute_command = true

  tags = { Name = "${var.project_name}-copilot-${var.service_name}" }

  lifecycle {
    ignore_changes = [desired_count]
  }
}
