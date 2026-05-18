#!/usr/bin/env bash
# deploy.sh — Full deployment pipeline.
#
# Steps:
#   1. terraform init + apply   (idempotent infrastructure)
#   2. Build & push Docker image to ECR
#   3. Force a new ECS deployment (picks up the new image)
#   4. Wait for ECS service to stabilise
#
# Usage:
#   ./deploy/scripts/deploy.sh [IMAGE_TAG]
#
# Prerequisites:
#   - AWS CLI configured (profile or IAM role)
#   - Terraform >= 1.6 installed
#   - Docker running
#   - deploy/terraform/terraform.tfvars or environment variables set

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

AWS_REGION="${AWS_REGION:-eu-west-1}"
TF_DIR="$REPO_ROOT/deploy/terraform"
IMAGE_TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo "latest")}"

# ── Step 1: Terraform ─────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║  Step 1/4 — Terraform init + apply       ║"
echo "╚══════════════════════════════════════════╝"

terraform -chdir="$TF_DIR" init -input=false
terraform -chdir="$TF_DIR" apply -input=false -auto-approve

# Read outputs
ECS_CLUSTER=$(terraform -chdir="$TF_DIR" output -raw ecs_cluster_name)
ECS_SERVICE=$(terraform -chdir="$TF_DIR" output -raw ecs_service_name)
API_BASE_URL=$(terraform -chdir="$TF_DIR" output -raw api_base_url)

echo ""
echo "    ECS cluster: $ECS_CLUSTER"
echo "    ECS service: $ECS_SERVICE"
echo "    API URL    : $API_BASE_URL"
echo ""

# ── Step 2: Build & push image ───────────────────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║  Step 2/4 — Build & push Docker image    ║"
echo "╚══════════════════════════════════════════╝"

bash "$REPO_ROOT/deploy/scripts/build_and_push.sh" "$IMAGE_TAG"

# ── Step 3: Force new ECS deployment ─────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Step 3/4 — Trigger ECS deployment       ║"
echo "╚══════════════════════════════════════════╝"

aws ecs update-service \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --force-new-deployment \
  --output text \
  --query "service.serviceName"

echo "    Deployment triggered."

# ── Step 4: Wait for stability ────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Step 4/4 — Waiting for service stable   ║"
echo "╚══════════════════════════════════════════╝"

echo "    Polling ECS service (timeout 10 min) …"
aws ecs wait services-stable \
  --region "$AWS_REGION" \
  --cluster "$ECS_CLUSTER" \
  --services "$ECS_SERVICE"

echo ""
echo "✓ Deployment complete."
echo "  API endpoint: $API_BASE_URL"
echo "  Health check: $API_BASE_URL/health"
echo ""

# ── Smoke test ────────────────────────────────────────────────────────────────
echo "==> Running smoke test …"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API_BASE_URL/health" || echo "000")
if [ "$HTTP_STATUS" = "200" ]; then
  echo "✓ Health check passed (HTTP $HTTP_STATUS)"
else
  echo "⚠ Health check returned HTTP $HTTP_STATUS — check CloudWatch logs."
  echo "  Log group: $(terraform -chdir="$TF_DIR" output -raw cloudwatch_log_group)"
fi
