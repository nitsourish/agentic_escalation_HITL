# ── Secrets Manager — API keys ────────────────────────────────────────────────
#
# Secrets are created here and populated with placeholder values.
# Set the real values after first apply:
#   aws secretsmanager put-secret-value \
#       --secret-id <arn> --secret-string '{"key":"<value>"}'

resource "aws_secretsmanager_secret" "openai_api_key" {
  name                    = "${local.name_prefix}/openai-api-key"
  description             = "OpenAI API key for the escalation LLM classifier."
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-openai-key" }
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  secret_id = aws_secretsmanager_secret.openai_api_key.id
  # Inject via var (tfvars / CI secret) or update manually post-apply.
  secret_string = var.openai_api_key != "" ? var.openai_api_key : "REPLACE_ME"

  lifecycle {
    # Prevent Terraform from overwriting a key that was manually updated.
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "gemini_api_key" {
  name                    = "${local.name_prefix}/gemini-api-key"
  description             = "Gemini API key for the escalation LLM classifier."
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-gemini-key" }
}

resource "aws_secretsmanager_secret_version" "gemini_api_key" {
  secret_id     = aws_secretsmanager_secret.gemini_api_key.id
  secret_string = var.gemini_api_key != "" ? var.gemini_api_key : "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}
