# ---------------------------------------------------------------------------
# Qdrant — two modes (var.qdrant_mode):
#   "cloud"     : managed Qdrant Cloud. No infra here; the app reads QDRANT_URL
#                 (common_env) + QDRANT_API_KEY (Secrets Manager). RECOMMENDED.
#   "self_host" : a single ECS Fargate Qdrant task with a service-managed EBS
#                 volume, advertised via Service Connect as qdrant:6333.
#
# DURABILITY WARNING (self_host): an ECS service-managed EBS volume is created
# per task and removed when the task stops — it does NOT survive task
# replacement. For durable self-hosting, schedule Qdrant snapshots to S3 and
# restore on boot, or run Qdrant on EC2+EBS. Qdrant Cloud avoids this entirely.
# ---------------------------------------------------------------------------

locals {
  qdrant_self_host = var.qdrant_mode == "self_host"
}

# Allow the vector DB ports between ECS tasks when self-hosting.
resource "aws_security_group_rule" "qdrant" {
  count             = local.qdrant_self_host ? 1 : 0
  type              = "ingress"
  from_port         = 6333
  to_port           = 6334
  protocol          = "tcp"
  security_group_id = aws_security_group.ecs.id
  self              = true
  description       = "Qdrant (self-hosted) between ECS tasks"
}

# Infrastructure role ECS uses to manage the task EBS volume.
data "aws_iam_policy_document" "qdrant_ebs_assume" {
  count = local.qdrant_self_host ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "qdrant_ebs" {
  count              = local.qdrant_self_host ? 1 : 0
  name               = "${local.name}-qdrant-ebs"
  assume_role_policy = data.aws_iam_policy_document.qdrant_ebs_assume[0].json
}

resource "aws_iam_role_policy_attachment" "qdrant_ebs" {
  count      = local.qdrant_self_host ? 1 : 0
  role       = aws_iam_role.qdrant_ebs[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRolePolicyForVolumes"
}

resource "aws_cloudwatch_log_group" "qdrant" {
  count             = local.qdrant_self_host ? 1 : 0
  name              = "/ecs/${local.name}/qdrant"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_task_definition" "qdrant" {
  count                    = local.qdrant_self_host ? 1 : 0
  family                   = "${local.name}-qdrant"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn

  volume {
    name                = "qdrant-data"
    configure_at_launch = true
  }

  container_definitions = jsonencode([{
    name      = "qdrant"
    image     = "qdrant/qdrant:latest"
    essential = true
    portMappings = [{
      containerPort = 6333
      protocol      = "tcp"
      name          = "qdrant-6333"
      appProtocol   = "http"
    }]
    mountPoints = [{
      sourceVolume  = "qdrant-data"
      containerPath = "/qdrant/storage"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.qdrant[0].name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "qdrant"
      }
    }
  }])
}

resource "aws_ecs_service" "qdrant" {
  count           = local.qdrant_self_host ? 1 : 0
  name            = "qdrant"
  cluster         = aws_ecs_cluster.this.arn
  task_definition = aws_ecs_task_definition.qdrant[0].arn
  desired_count   = 1 # single-node store — do NOT scale.
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.this.arn
    service {
      port_name = "qdrant-6333"
      client_alias {
        port     = 6333
        dns_name = "qdrant"
      }
    }
  }

  volume_configuration {
    name = "qdrant-data"
    managed_ebs_volume {
      role_arn         = aws_iam_role.qdrant_ebs[0].arn
      size_in_gb       = var.qdrant_self_host_volume_gb
      volume_type      = "gp3"
      file_system_type = "ext4"
    }
  }
}
