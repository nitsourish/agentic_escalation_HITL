output "alb_dns_name" {
  description = "Public DNS name of the Application Load Balancer."
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "Hosted-zone ID of the ALB (use for Route53 alias records)."
  value       = aws_lb.main.zone_id
}

output "ecr_repository_url" {
  description = "ECR repository URL to push the API image to."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster."
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Name of the ECS service."
  value       = aws_ecs_service.app.name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for ECS task output."
  value       = aws_cloudwatch_log_group.app.name
}

output "openai_secret_arn" {
  description = "ARN of the OpenAI API key secret in Secrets Manager."
  value       = aws_secretsmanager_secret.openai_api_key.arn
  sensitive   = true
}

output "gemini_secret_arn" {
  description = "ARN of the Gemini API key secret in Secrets Manager."
  value       = aws_secretsmanager_secret.gemini_api_key.arn
  sensitive   = true
}

output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.main.id
}

output "api_base_url" {
  description = "Base URL for the REST API."
  value       = var.certificate_arn != "" ? "https://${aws_lb.main.dns_name}" : "http://${aws_lb.main.dns_name}"
}
