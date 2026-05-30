provider "aws" {
  region = var.region
  default_tags {
    tags = merge({
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }, var.tags)
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name    = "${var.project}-${var.environment}"
  azs     = slice(data.aws_availability_zones.available.names, 0, var.az_count)
  is_prod = var.environment == "prod"

  # Logical backend services (reached via Service Connect). Order is not significant.
  backend_services = ["gateway", "ingest", "search", "qpaper", "viva"]

  # ECS Service Connect namespace (env-scoped so staging/prod don't collide).
  sc_namespace = "${local.name}.internal"
}
