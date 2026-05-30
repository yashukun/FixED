variable "project" {
  description = "Project name, used as a resource name prefix."
  type        = string
  default     = "fixed"
}

variable "environment" {
  description = "Deployment environment (staging | prod)."
  type        = string
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "az_count" {
  description = "Number of Availability Zones to span (2 is sufficient)."
  type        = number
  default     = 2
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway (cheaper, staging) instead of one per AZ (prod)."
  type        = bool
  default     = true
}

# ---- Edge / DNS ----
variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the ALB HTTPS listener (must be in this region)."
  type        = string
  default     = ""
}

variable "enable_waf" {
  description = "Attach an AWS WAF web ACL (rate limiting + managed rules) to the ALB."
  type        = bool
  default     = true
}

variable "alb_idle_timeout" {
  description = "ALB idle timeout (seconds). Must comfortably exceed SSE/streaming gaps and large uploads."
  type        = number
  default     = 300
}

# ---- RDS ----
variable "rds_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "rds_allocated_storage" {
  type    = number
  default = 50
}

variable "rds_max_allocated_storage" {
  type    = number
  default = 200
}

variable "rds_multi_az" {
  type    = bool
  default = false
}

variable "rds_engine_version" {
  description = "Postgres engine version (must support the pgvector extension, >= 15)."
  type        = string
  default     = "16.4"
}

# ---- ElastiCache (Redis) ----
variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "redis_replicas" {
  description = "Number of read replicas (1 in prod enables Multi-AZ failover; 0 in staging)."
  type        = number
  default     = 0
}

# ---- Qdrant (vector store) ----
variable "qdrant_mode" {
  description = "How Qdrant is provided: \"cloud\" (managed; URL+key via Secrets Manager) or \"self_host\" (ECS Fargate + EBS)."
  type        = string
  default     = "cloud"
  validation {
    condition     = contains(["cloud", "self_host"], var.qdrant_mode)
    error_message = "qdrant_mode must be \"cloud\" or \"self_host\"."
  }
}

variable "qdrant_self_host_volume_gb" {
  description = "EBS volume size for self-hosted Qdrant."
  type        = number
  default     = 20
}

# ---- Secrets (supplied out-of-band, e.g. via TF_VAR_* in CI or a tfvars not in VCS) ----
variable "openai_api_key" {
  description = "OpenAI API key (rotate the old on-disk one). Stored in Secrets Manager."
  type        = string
  sensitive   = true
  default     = ""
}

variable "qdrant_url" {
  description = "Qdrant Cloud URL (when qdrant_mode = cloud)."
  type        = string
  default     = ""
}

variable "qdrant_api_key" {
  description = "Qdrant Cloud API key (when qdrant_mode = cloud)."
  type        = string
  sensitive   = true
  default     = ""
}

# ---- Per-service sizing. Map keyed by logical service name. ----
variable "services" {
  description = "Per-service Fargate sizing and scaling."
  type = map(object({
    cpu     = number
    memory  = number
    desired = number
    min     = number
    max     = number
  }))
  default = {
    gateway = { cpu = 256, memory = 512, desired = 1, min = 1, max = 4 }
    ingest  = { cpu = 512, memory = 1024, desired = 1, min = 1, max = 4 }
    search  = { cpu = 512, memory = 1024, desired = 1, min = 1, max = 6 }
    qpaper  = { cpu = 512, memory = 1024, desired = 1, min = 1, max = 4 }
    viva    = { cpu = 1024, memory = 2048, desired = 1, min = 1, max = 6 }
    worker  = { cpu = 1024, memory = 2048, desired = 1, min = 1, max = 8 }
    front   = { cpu = 256, memory = 512, desired = 2, min = 2, max = 6 }
  }
}

variable "image_tag" {
  description = "Container image tag to deploy (git SHA in CI)."
  type        = string
  default     = "latest"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alarm_email" {
  description = "Optional email subscribed to the CloudWatch alarm SNS topic."
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
