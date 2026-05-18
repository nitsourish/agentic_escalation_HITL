#!/usr/bin/env bash
# build_and_push.sh — Build the Docker image and push it to ECR.
#
# Usage:
#   ./deploy/scripts/build_and_push.sh [IMAGE_TAG]
#
# Environment variables:
#   AWS_REGION   — defaults to eu-west-1
#   IMAGE_TAG    — defaults to git SHA (or first argument)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# ── Configuration ─────────────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-eu-west-1}"
IMAGE_TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo "latest")}"

echo "==> Resolving ECR repository URL from Terraform outputs …"
ECR_URL=$(terraform -chdir=deploy/terraform output -raw ecr_repository_url 2>/dev/null) || {
  echo "ERROR: Could not read ecr_repository_url from Terraform. Run 'terraform apply' first."
  exit 1
}

echo "    ECR URL  : $ECR_URL"
echo "    Image tag: $IMAGE_TAG"
echo ""

# ── Authenticate to ECR ───────────────────────────────────────────────────────
echo "==> Authenticating to ECR …"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_URL"

# ── Build ─────────────────────────────────────────────────────────────────────
echo "==> Building image (context: repo root) …"
docker build \
  --file deploy/api/Dockerfile \
  --tag "$ECR_URL:$IMAGE_TAG" \
  --tag "$ECR_URL:latest" \
  --platform linux/amd64 \
  .

# ── Push ──────────────────────────────────────────────────────────────────────
echo "==> Pushing $ECR_URL:$IMAGE_TAG …"
docker push "$ECR_URL:$IMAGE_TAG"

echo "==> Pushing $ECR_URL:latest …"
docker push "$ECR_URL:latest"

echo ""
echo "✓ Image pushed: $ECR_URL:$IMAGE_TAG"
