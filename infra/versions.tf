terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state. Bootstrap the bucket + lock table once via global/backend-bootstrap,
  # then configure per-env with: terraform init -backend-config=envs/<env>.backend.hcl
  backend "s3" {}
}
