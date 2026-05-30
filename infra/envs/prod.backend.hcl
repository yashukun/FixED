# terraform init -backend-config=envs/prod.backend.hcl
# Fill in the bucket created by global/backend-bootstrap.
bucket         = "REPLACE_WITH_TFSTATE_BUCKET"
key            = "fixed/prod/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "fixed-tflock"
encrypt        = true
