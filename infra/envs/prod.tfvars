environment        = "prod"
region             = "us-east-1"
vpc_cidr           = "10.20.0.0/16"
single_nat_gateway = false # one NAT per AZ for AZ-resilient egress

# RDS / Redis — Multi-AZ, with a Redis replica for failover.
rds_instance_class = "db.t4g.medium"
rds_multi_az       = true
redis_node_type    = "cache.t4g.small"
redis_replicas     = 1

qdrant_mode = "cloud"
enable_waf  = true

# Larger desired counts in prod.
services = {
  gateway = { cpu = 256, memory = 512, desired = 2, min = 2, max = 6 }
  ingest  = { cpu = 512, memory = 1024, desired = 2, min = 2, max = 6 }
  search  = { cpu = 512, memory = 1024, desired = 2, min = 2, max = 8 }
  qpaper  = { cpu = 512, memory = 1024, desired = 2, min = 2, max = 6 }
  viva    = { cpu = 1024, memory = 2048, desired = 2, min = 2, max = 8 }
  worker  = { cpu = 1024, memory = 2048, desired = 2, min = 1, max = 10 }
  front   = { cpu = 256, memory = 512, desired = 2, min = 2, max = 6 }
}

# Provide via TF_VAR_* in CI:
#   acm_certificate_arn, openai_api_key, qdrant_url, qdrant_api_key, alarm_email
