output "alb_dns_name" {
  description = "Public ALB DNS name (point your domain / api subdomain here)."
  value       = aws_lb.this.dns_name
}

output "ecr_repository_urls" {
  description = "ECR repo URLs by image name (used by CI to push)."
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "rds_endpoint" {
  value = aws_db_instance.this.address
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "s3_buckets" {
  value = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "private_subnet_ids" {
  description = "Private app subnet IDs (for the migration run-task network config)."
  value       = aws_subnet.app[*].id
}

output "ecs_security_group_id" {
  value = aws_security_group.ecs.id
}

# CI runs the migration as the ingest task family with the command overridden to
# `python -m db.migrate`. Family == container name == the ingest module name.
output "migration_task_family" {
  value = "${local.name}-ingest"
}

output "migration_container_name" {
  value = "${local.name}-ingest"
}
