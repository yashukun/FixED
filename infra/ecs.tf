resource "aws_ecs_cluster" "this" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# Service Connect namespace — backends advertise "<name>:8000" here; the frontend
# (and search) resolve those aliases. This replaces Docker DNS (gateway:8000, ...).
resource "aws_service_discovery_http_namespace" "this" {
  name = local.sc_namespace
}

locals {
  # Vector store URL: managed Qdrant Cloud, or the self-hosted SC alias.
  qdrant_url = var.qdrant_mode == "cloud" ? var.qdrant_url : "http://qdrant:6333"

  # Non-sensitive config injected as task-def environment (secrets go via `secrets`).
  common_env = {
    APP_ENV              = "production"
    LOG_FORMAT           = "json"
    LOG_LEVEL            = "INFO"
    AWS_REGION           = var.region
    PGSSLMODE            = "require"
    UVICORN_WORKERS      = "2"
    EMBEDDING_DIMENSIONS = "1536"

    VECTOR_DB_PROVIDER = "qdrant"
    QDRANT_URL         = local.qdrant_url
    QDRANT_COLLECTION  = "document_chunks"

    STORAGE_PROVIDER  = "s3"
    STORAGE_BUCKET    = aws_s3_bucket.this["documents"].bucket
    VIVA_MEDIA_BUCKET = aws_s3_bucket.this["viva"].bucket

    # Internal service-to-service (resolved via Service Connect alias).
    QPAPER_SERVICE_URL = "http://qpaper:8000"
  }

  health_http   = ["CMD-SHELL", "python -c 'import urllib.request; urllib.request.urlopen(\"http://localhost:8000/health\", timeout=3)'"]
  health_celery = ["CMD-SHELL", "celery -A shared.queue.celery_app inspect ping || exit 1"]
  health_front  = ["CMD-SHELL", "wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1"]
}

# ---- 5 backend services (Service Connect, no ALB, private) ----
module "backend" {
  source   = "./modules/ecs-service"
  for_each = toset(local.backend_services)

  name         = "${local.name}-${each.value}"
  cluster_arn  = aws_ecs_cluster.this.arn
  cluster_name = aws_ecs_cluster.this.name
  region       = var.region

  image  = "${aws_ecr_repository.this[each.value].repository_url}:${var.image_tag}"
  cpu    = var.services[each.value].cpu
  memory = var.services[each.value].memory

  environment    = local.common_env
  secrets        = local.common_secrets
  health_command = local.health_http

  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn
  subnets            = aws_subnet.app[*].id
  security_groups    = [aws_security_group.ecs.id]

  # Env-scoped resource name, but a short Service Connect alias so the SAME
  # hostnames (gateway:8000, qpaper:8000, ...) resolve as in local Docker.
  namespace_arn  = aws_service_discovery_http_namespace.this.arn
  advertise_name = "${each.value}-8000"
  dns_name       = each.value

  desired_count      = var.services[each.value].desired
  min_capacity       = var.services[each.value].min
  max_capacity       = var.services[each.value].max
  log_retention_days = var.log_retention_days
}

# ---- Celery worker (ingest image, no port, no ALB, no Service Connect) ----
module "worker" {
  source = "./modules/ecs-service"

  name         = "${local.name}-worker"
  cluster_arn  = aws_ecs_cluster.this.arn
  cluster_name = aws_ecs_cluster.this.name
  region       = var.region

  image          = "${aws_ecr_repository.this["ingest"].repository_url}:${var.image_tag}"
  cpu            = var.services["worker"].cpu
  memory         = var.services["worker"].memory
  container_port = 0
  command        = ["celery", "-A", "shared.queue.celery_app", "worker", "--loglevel=info", "--concurrency=2"]

  environment    = local.common_env
  secrets        = local.common_secrets
  health_command = local.health_celery

  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn
  subnets            = aws_subnet.app[*].id
  security_groups    = [aws_security_group.ecs.id]

  desired_count      = var.services["worker"].desired
  min_capacity       = var.services["worker"].min
  max_capacity       = var.services["worker"].max
  log_retention_days = var.log_retention_days
}

# ---- Frontend (nginx ingress): ALB target + Service Connect client ----
module "frontend" {
  source = "./modules/ecs-service"

  name         = "${local.name}-frontend"
  cluster_arn  = aws_ecs_cluster.this.arn
  cluster_name = aws_ecs_cluster.this.name
  region       = var.region

  image          = "${aws_ecr_repository.this["frontend"].repository_url}:${var.image_tag}"
  cpu            = var.services["front"].cpu
  memory         = var.services["front"].memory
  container_port = 80

  environment = {
    UPSTREAM_GATEWAY      = "gateway:8000"
    UPSTREAM_INGEST       = "ingest:8000"
    UPSTREAM_SEARCH       = "search:8000"
    UPSTREAM_QPAPER       = "qpaper:8000"
    UPSTREAM_VIVA         = "viva:8000"
    NGINX_ENVSUBST_FILTER = "UPSTREAM_"
  }
  secrets        = {}
  health_command = local.health_front

  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.task.arn
  subnets            = aws_subnet.app[*].id
  security_groups    = [aws_security_group.ecs.id]

  # Client-only Service Connect so nginx can resolve gateway:8000 etc.
  namespace_arn = aws_service_discovery_http_namespace.this.arn

  alb_target_group_arn = aws_lb_target_group.frontend.arn

  desired_count      = var.services["front"].desired
  min_capacity       = var.services["front"].min
  max_capacity       = var.services["front"].max
  log_retention_days = var.log_retention_days

  depends_on = [aws_lb_listener.http]
}
