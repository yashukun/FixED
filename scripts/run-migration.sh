#!/usr/bin/env bash
# Run the FixED DB migration as a one-shot ECS task: the ingest task family with
# the container command overridden to `python -m db.migrate`. Waits for the task
# to stop and fails unless it exited 0.
#
# Required env: CLUSTER TASK_FAMILY CONTAINER SUBNETS SECURITY_GROUP
set -euo pipefail

: "${CLUSTER:?}" "${TASK_FAMILY:?}" "${CONTAINER:?}" "${SUBNETS:?}" "${SECURITY_GROUP:?}"

overrides="{\"containerOverrides\":[{\"name\":\"${CONTAINER}\",\"command\":[\"python\",\"-m\",\"db.migrate\"]}]}"
netcfg="awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SECURITY_GROUP}],assignPublicIp=DISABLED}"

task_arn=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_FAMILY" \
  --launch-type FARGATE \
  --count 1 \
  --network-configuration "$netcfg" \
  --overrides "$overrides" \
  --query 'tasks[0].taskArn' --output text)

echo "Migration task started: $task_arn"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task_arn"

exit_code=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
  --query 'tasks[0].containers[0].exitCode' --output text)
reason=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" \
  --query 'tasks[0].stoppedReason' --output text)

echo "Migration exit code: ${exit_code} (${reason})"
if [ "$exit_code" != "0" ]; then
  echo "::error::Database migration failed"
  exit 1
fi
echo "Database migration succeeded."
