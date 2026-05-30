resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.cluster_name}/${var.name}"
  retention_in_days = var.log_retention_days
}

locals {
  port_mappings = var.container_port > 0 ? [merge(
    { containerPort = var.container_port, protocol = "tcp" },
    var.advertise_name != "" ? { name = var.advertise_name, appProtocol = "http" } : {}
  )] : []
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([{
    name         = var.name
    image        = var.image
    essential    = true
    command      = length(var.command) > 0 ? var.command : null
    portMappings = local.port_mappings
    environment  = [for k, v in var.environment : { name = k, value = v }]
    secrets      = [for k, v in var.secrets : { name = k, valueFrom = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = var.name
      }
    }
    healthCheck = length(var.health_command) > 0 ? {
      command     = var.health_command
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    } : null
  }])
}

resource "aws_ecs_service" "this" {
  name            = var.name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  network_configuration {
    subnets          = var.subnets
    security_groups  = var.security_groups
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = var.alb_target_group_arn != "" ? [1] : []
    content {
      target_group_arn = var.alb_target_group_arn
      container_name   = var.name
      container_port   = var.container_port
    }
  }

  dynamic "service_connect_configuration" {
    for_each = var.namespace_arn != "" ? [1] : []
    content {
      enabled   = true
      namespace = var.namespace_arn
      dynamic "service" {
        for_each = var.advertise_name != "" ? [1] : []
        content {
          port_name = var.advertise_name
          client_alias {
            port     = var.container_port
            dns_name = var.dns_name != "" ? var.dns_name : var.name
          }
        }
      }
    }
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Let autoscaling own desired_count without TF reverting it.
  lifecycle {
    ignore_changes = [desired_count]
  }
}

resource "aws_appautoscaling_target" "this" {
  count              = var.enable_autoscaling ? 1 : 0
  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  count              = var.enable_autoscaling ? 1 : 0
  name               = "${var.name}-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.this[0].resource_id
  scalable_dimension = aws_appautoscaling_target.this[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.this[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = var.cpu_target
  }
}
