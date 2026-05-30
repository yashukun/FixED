# ---------------------------------------------------------------------------
# Secrets Manager. Sensitive values are injected into ECS tasks via `secrets`
# (never baked into images or task-def environment). Non-sensitive config is
# set as task-def `environment` (see ecs.tf locals.common_env).
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "postgres_url" {
  name = "${local.name}/postgres-url"
}
resource "aws_secretsmanager_secret_version" "postgres_url" {
  secret_id     = aws_secretsmanager_secret.postgres_url.id
  secret_string = "postgresql://raguser:${random_password.db.result}@${aws_db_instance.this.address}:5432/ragdb"
}

resource "aws_secretsmanager_secret" "redis_url" {
  name = "${local.name}/redis-url"
}
resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
}

resource "aws_secretsmanager_secret" "openai_api_key" {
  name = "${local.name}/openai-api-key"
}
resource "aws_secretsmanager_secret_version" "openai_api_key" {
  secret_id     = aws_secretsmanager_secret.openai_api_key.id
  secret_string = var.openai_api_key
}

# Qdrant Cloud API key (only in cloud mode).
resource "aws_secretsmanager_secret" "qdrant_api_key" {
  count = var.qdrant_mode == "cloud" ? 1 : 0
  name  = "${local.name}/qdrant-api-key"
}
resource "aws_secretsmanager_secret_version" "qdrant_api_key" {
  count         = var.qdrant_mode == "cloud" ? 1 : 0
  secret_id     = aws_secretsmanager_secret.qdrant_api_key[0].id
  secret_string = var.qdrant_api_key
}

locals {
  # Secret ARNs injected into every backend task as `secrets`.
  common_secrets = merge(
    {
      POSTGRES_URL   = aws_secretsmanager_secret.postgres_url.arn
      REDIS_URL      = aws_secretsmanager_secret.redis_url.arn
      OPENAI_API_KEY = aws_secretsmanager_secret.openai_api_key.arn
    },
    var.qdrant_mode == "cloud" ? { QDRANT_API_KEY = aws_secretsmanager_secret.qdrant_api_key[0].arn } : {}
  )

  secret_arns = values(local.common_secrets)
}
