environment        = "staging"
region             = "us-east-1"
vpc_cidr           = "10.30.0.0/16"
single_nat_gateway = true

# RDS / Redis — smaller, single-AZ for staging.
rds_instance_class = "db.t4g.small"
rds_multi_az       = false
redis_node_type    = "cache.t4g.small"
redis_replicas     = 0

# Vector store: "cloud" (set qdrant_url / qdrant_api_key) or "self_host".
qdrant_mode = "cloud"

enable_waf = true

# Provide via TF_VAR_* in CI (do NOT commit real secrets):
#   acm_certificate_arn, openai_api_key, qdrant_url, qdrant_api_key
