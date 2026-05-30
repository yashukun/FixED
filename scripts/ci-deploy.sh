#!/usr/bin/env bash
# Deploy one environment: terraform apply -> DB migration -> smoke test.
# Run from the infra/ directory. Required env:
#   ENVNAME (staging|prod), IMAGE_TAG, TFSTATE_BUCKET
# Optional: ALB_BASE_URL, plus TF_VAR_* for secrets/cert.
set -euo pipefail
: "${ENVNAME:?}" "${IMAGE_TAG:?}" "${TFSTATE_BUCKET:?}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

tofu init -input=false \
  -backend-config="envs/${ENVNAME}.backend.hcl" \
  -backend-config="bucket=${TFSTATE_BUCKET}"

tofu apply -auto-approve -input=false \
  -var-file="envs/${ENVNAME}.tfvars" \
  -var="image_tag=${IMAGE_TAG}"

# --- Apply DB migrations (one-shot ECS task) before relying on new schema ---
export CLUSTER=$(tofu output -raw ecs_cluster_name)
export TASK_FAMILY=$(tofu output -raw migration_task_family)
export CONTAINER=$(tofu output -raw migration_container_name)
export SECURITY_GROUP=$(tofu output -raw ecs_security_group_id)
export SUBNETS=$(tofu output -json private_subnet_ids | tr -d '[]"\n ')
bash "$SCRIPT_DIR/run-migration.sh"

# --- Smoke test through the ALB ---
if [ -n "${ALB_BASE_URL:-}" ]; then
  export BASE_URL="$ALB_BASE_URL"
else
  export BASE_URL="http://$(tofu output -raw alb_dns_name)"
fi
bash "$SCRIPT_DIR/smoke.sh"
