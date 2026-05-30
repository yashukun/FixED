# FixED — Infrastructure (Terraform, AWS ECS Fargate)

Provisions the AWS production/staging stack: VPC, ECS Fargate (5 services + Celery
worker + nginx ingress), RDS Postgres (pgvector), ElastiCache Redis, S3, ALB (+WAF),
ECR, Secrets Manager, Service Connect, CloudWatch alarms, and Qdrant (Cloud or self-hosted).

## Layout
```
infra/
  versions.tf variables.tf main.tf      # provider, vars, locals
  network.tf                            # VPC, subnets, NAT, VPC endpoints, security groups
  data_stores.tf                        # RDS, ElastiCache, S3
  ecr.tf secrets.tf iam.tf              # registries, secrets, ECS roles
  alb.tf                                # ALB, listeners, target group, WAF
  ecs.tf                                # cluster, Service Connect, all services
  qdrant.tf                             # cloud (no-op) or self-hosted ECS+EBS
  observability.tf outputs.tf
  modules/ecs-service/                  # reusable task-def + service + autoscaling
  envs/{staging,prod}.tfvars            # per-env sizing
  envs/{staging,prod}.backend.hcl       # per-env remote state config
  global/backend-bootstrap/             # one-time S3 state bucket + DynamoDB lock
```

## Edge topology
Internet → **ALB** (HTTPS) → **frontend (nginx ingress)** → reverse-proxies `/api/*`
to the backends over **Service Connect** (`gateway:8000`, `qpaper:8000`, …). Only the
ALB is public; backends, the worker, RDS, Redis and Qdrant are all in private subnets.

## Manual prerequisites (not created here)
- **ACM certificate** for your domain in this region → `acm_certificate_arn` (HTTPS listener; without it the ALB serves plain HTTP for bring-up).
- **OpenAI API key** (rotate the old on-disk one) → `TF_VAR_openai_api_key`.
- **Qdrant** (default `qdrant_mode = "cloud"`): a Qdrant Cloud cluster → `TF_VAR_qdrant_url`, `TF_VAR_qdrant_api_key`. (Or set `qdrant_mode = "self_host"`.)
- A **Route53 / DNS** record pointing your domain at the ALB output.

## Usage
```bash
# 0) One-time: create the remote-state backend
cd infra/global/backend-bootstrap
terraform init && terraform apply -var=state_bucket=<globally-unique-bucket>
# put that bucket name into infra/envs/<env>.backend.hcl

# 1) Init + plan + apply an environment
cd infra
terraform init -backend-config=envs/staging.backend.hcl
export TF_VAR_openai_api_key=...    TF_VAR_qdrant_url=...    TF_VAR_qdrant_api_key=...
export TF_VAR_acm_certificate_arn=arn:aws:acm:...
terraform plan  -var-file=envs/staging.tfvars -var="image_tag=<git-sha>"
terraform apply -var-file=envs/staging.tfvars -var="image_tag=<git-sha>"
```

## Database migrations
Schema is applied by a one-shot run of the **ingest** task family with the command
overridden to `python -m db.migrate` (Alembic upgrade + `CREATE EXTENSION vector`).
The CI pipeline runs this before deploying services; see `.github/workflows/deploy.yml`.

## Notes
- Secrets are injected into tasks from Secrets Manager via the task-def `secrets` block; non-secret config is task-def `environment` (TF-managed). Nothing secret is baked into images.
- `random_password` (RDS, Redis) lives in Terraform state — keep state in the encrypted S3 backend.
- Self-hosted Qdrant on Fargate uses a per-task EBS volume that does **not** survive task replacement; for durable self-hosting use Qdrant Cloud (default) or EC2+EBS with snapshots. See `qdrant.tf`.
- Worker autoscaling uses CPU target-tracking; queue-depth scaling is a documented follow-up.
