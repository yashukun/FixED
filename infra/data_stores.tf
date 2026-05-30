data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# RDS for PostgreSQL (pgvector). The vector extension is created by the
# migration job (rds master role), not by the app.
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.data[*].id
}

resource "aws_db_parameter_group" "this" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_instance" "this" {
  identifier     = "${local.name}-pg"
  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "ragdb"
  username = "raguser"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  multi_az                     = var.rds_multi_az
  backup_retention_period      = local.is_prod ? 14 : 1
  performance_insights_enabled = true
  deletion_protection          = local.is_prod
  skip_final_snapshot          = !local.is_prod
  final_snapshot_identifier    = local.is_prod ? "${local.name}-pg-final" : null
  apply_immediately            = !local.is_prod
}

# ---------------------------------------------------------------------------
# ElastiCache for Redis (Celery broker + result backend), TLS + AUTH.
# ---------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.name}-redis"
  subnet_ids = aws_subnet.data[*].id
}

resource "random_password" "redis" {
  length  = 32
  special = false
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.name}-redis"
  description          = "${local.name} Celery broker/result backend"
  engine               = "redis"
  node_type            = var.redis_node_type
  num_cache_clusters   = 1 + var.redis_replicas
  port                 = 6379

  automatic_failover_enabled = var.redis_replicas > 0
  multi_az_enabled           = var.redis_replicas > 0

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis.result

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.redis.id]
  apply_immediately  = !local.is_prod
}

# ---------------------------------------------------------------------------
# S3 buckets — documents + viva media. Private, encrypted, TLS-only.
# ---------------------------------------------------------------------------

locals {
  buckets = {
    documents = "${local.name}-documents-${data.aws_caller_identity.current.account_id}"
    viva      = "${local.name}-viva-media-${data.aws_caller_identity.current.account_id}"
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = each.value
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.this["documents"].id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    id     = "abort-incomplete-mpu"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Deny any non-TLS request.
resource "aws_s3_bucket_policy" "tls_only" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [each.value.arn, "${each.value.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
