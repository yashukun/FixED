# One-time bootstrap of the Terraform remote-state backend (S3 bucket + DynamoDB
# lock table). Run this ONCE with a local backend, before init-ing the main
# config against the S3 backend.
#
#   cd infra/global/backend-bootstrap
#   terraform init && terraform apply -var=state_bucket=<globally-unique-name>
#
# Then put that bucket name into infra/envs/<env>.backend.hcl.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "state_bucket" {
  description = "Globally-unique S3 bucket name for Terraform state."
  type        = string
}

variable "lock_table" {
  type    = string
  default = "fixed-tflock"
}

provider "aws" {
  region = var.region
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "lock" {
  name         = var.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}
output "lock_table" {
  value = aws_dynamodb_table.lock.name
}
