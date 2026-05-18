#!/usr/bin/env bash
# set_secret.sh — Store an API key in AWS Secrets Manager.
#
# Usage:
#   ./deploy/scripts/set_secret.sh openai  sk-...
#   ./deploy/scripts/set_secret.sh gemini  AIza...

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TF_DIR="$REPO_ROOT/deploy/terraform"
AWS_REGION="${AWS_REGION:-eu-west-1}"

PROVIDER="${1:-}"
SECRET_VALUE="${2:-}"

if [[ -z "$PROVIDER" || -z "$SECRET_VALUE" ]]; then
  echo "Usage: $0 <openai|gemini> <secret-value>"
  exit 1
fi

case "$PROVIDER" in
  openai)
    SECRET_ARN=$(terraform -chdir="$TF_DIR" output -raw openai_secret_arn)
    ;;
  gemini)
    SECRET_ARN=$(terraform -chdir="$TF_DIR" output -raw gemini_secret_arn)
    ;;
  *)
    echo "Unknown provider '$PROVIDER'. Use 'openai' or 'gemini'."
    exit 1
    ;;
esac

echo "==> Writing $PROVIDER key to Secrets Manager …"
aws secretsmanager put-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$SECRET_ARN" \
  --secret-string "$SECRET_VALUE"

echo "✓ Secret updated: $SECRET_ARN"
echo ""
echo "  Force a new ECS deployment to pick up the new secret:"
echo "    ./deploy/scripts/deploy.sh"
