#!/usr/bin/env bash
# teardown.sh — Destroy all AWS resources created by Terraform.
#
# WARNING: This is DESTRUCTIVE. It will delete the ECS service, load balancer,
#          VPC, ECR repository, and all data in them.
#
# Usage:
#   ./deploy/scripts/teardown.sh [--yes]
#
# Pass --yes to skip the interactive confirmation prompt (for CI use).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="$REPO_ROOT/deploy/terraform"

SKIP_CONFIRM="${1:-}"

if [[ "$SKIP_CONFIRM" != "--yes" ]]; then
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║  WARNING: This will DESTROY all AWS resources.           ║"
  echo "║  All ECS tasks, the ALB, VPC, ECR images will be lost.  ║"
  echo "╚══════════════════════════════════════════════════════════╝"
  echo ""
  read -r -p "Type 'destroy' to confirm: " CONFIRM
  if [[ "$CONFIRM" != "destroy" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

echo "==> Scaling ECS service to 0 tasks …"
ECS_CLUSTER=$(terraform -chdir="$TF_DIR" output -raw ecs_cluster_name 2>/dev/null || echo "")
ECS_SERVICE=$(terraform -chdir="$TF_DIR" output -raw ecs_service_name 2>/dev/null || echo "")

if [[ -n "$ECS_CLUSTER" && -n "$ECS_SERVICE" ]]; then
  aws ecs update-service \
    --cluster "$ECS_CLUSTER" \
    --service "$ECS_SERVICE" \
    --desired-count 0 \
    --region "${AWS_REGION:-eu-west-1}" \
    --output text --query "service.serviceName" || true
  sleep 15
fi

echo "==> Running terraform destroy …"
terraform -chdir="$TF_DIR" destroy -input=false -auto-approve

echo ""
echo "✓ All resources destroyed."
