# FixED — AWS Deployment Guide

Deploys to **AWS ECS Fargate** via Terraform (`infra/`) and GitHub Actions
(`.github/workflows/`). Read [ARCHITECTURE.md](ARCHITECTURE.md) first.

## Prerequisites (one-time, manual)

1. **Rotate the OpenAI key.** The old key was written to `FixED/.env` on disk —
   treat it as compromised, rotate it, and store the new one only in Secrets
   Manager (via `TF_VAR_openai_api_key`). Delete the on-disk `.env` for prod use.
2. **AWS account + region**, and an **ACM certificate** for your domain in that
   region (for the ALB HTTPS listener). Without a cert the ALB serves plain HTTP
   (fine for first bring-up).
3. **Qdrant**: default `qdrant_mode = "cloud"` — create a Qdrant Cloud cluster and
   note its URL + API key. (Or set `qdrant_mode = "self_host"`.)
4. **Remote state backend** (run once):
   ```bash
   cd infra/global/backend-bootstrap
   terraform init && terraform apply -var=state_bucket=<globally-unique-bucket>
   ```
   Put that bucket name into `infra/envs/*.backend.hcl` (or pass it in CI as `TFSTATE_BUCKET`).
5. **GitHub OIDC**: create an IAM OIDC provider for GitHub Actions and two roles
   (`fixed-ci-staging`, `fixed-ci-prod`) with a trust policy scoped to this repo.
   Staging role needs ECR push + Terraform/ECS/RDS/etc.; prod role needs the same
   minus ECR push (it promotes existing images).

## Manual deploy (from a workstation)

```bash
cd infra
terraform init -backend-config=envs/staging.backend.hcl
export TF_VAR_openai_api_key=...  TF_VAR_qdrant_url=...  TF_VAR_qdrant_api_key=...
export TF_VAR_acm_certificate_arn=arn:aws:acm:...
terraform apply -var-file=envs/staging.tfvars -var="image_tag=<git-sha>"
# then run the migration + smoke (the CI scripts do this automatically):
#   scripts/run-migration.sh   scripts/smoke.sh
```
Point your DNS (or `api.` subdomain) at the `alb_dns_name` output.

## CI/CD (GitHub Actions)

- **`ci.yml`** (every PR/push): frontend lint+test+build, backend `unittest`
  matrix, and `tofu fmt/validate`.
- **`deploy.yml`**:
  - **push to `main`** → `build` (build + push all 6 images to ECR, tagged by SHA)
    → `deploy-staging` (`terraform apply` staging → migration task → smoke).
  - **`workflow_dispatch`** (manual, `image_tag` input) → `deploy-prod` against the
    protected `production` GitHub Environment (requires reviewer approval); promotes
    the already-built image — no rebuild (ECR tags are immutable).

### Required GitHub configuration

Create two **Environments** (`staging`, `production`; add required reviewers to
`production`) with these **variables** and **secrets**:

| Type | Name | Notes |
|---|---|---|
| var | `AWS_REGION` | e.g. `us-east-1` |
| var | `AWS_DEPLOY_ROLE_ARN` | the per-env OIDC role |
| var | `TFSTATE_BUCKET` | state bucket from bootstrap |
| var | `QDRANT_URL` | Qdrant Cloud URL |
| var | `ACM_CERTIFICATE_ARN` | ALB cert (optional) |
| var | `ALB_BASE_URL` | e.g. `https://api.example.com` (smoke target; optional) |
| var | `ALARM_EMAIL` | optional SNS subscriber |
| secret | `OPENAI_API_KEY` | the rotated key |
| secret | `QDRANT_API_KEY` | Qdrant Cloud key |

## Migrations

Schema changes ship as Alembic revisions in `services/shared/db/migrations/versions`.
Author locally:
```bash
cd services/shared/db
POSTGRES_URL=postgresql://... alembic -c alembic.ini revision --autogenerate -m "describe change"
```
CI applies them via a one-shot ECS task (`python -m db.migrate`) before traffic
relies on the new schema. Prefer **expand/contract** (backward-compatible)
migrations; for breaking changes, sequence them in a maintenance window.

## Cost / scaling knobs

- Per-service CPU/memory/min/max in `infra/envs/*.tfvars` (`services` map).
- `single_nat_gateway`, `rds_multi_az`, `redis_replicas` differ per env.
- API services autoscale on CPU; tune `UVICORN_WORKERS` + DB pool env vars together
  (more workers × pool size = more RDS connections).
