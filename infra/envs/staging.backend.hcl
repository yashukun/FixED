# terraform init -backend-config=envs/staging.backend.hcl
# Fill in the bucket created by global/backend-bootstrap.
bucket         = "REPLACE_WITH_TFSTATE_BUCKET"
key            = "fixed/staging/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "fixed-tflock"
encrypt        = true
