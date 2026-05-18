variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Deployment environment tag (e.g. prod, staging)."
  type        = string
  default     = "prod"
}

variable "project" {
  description = "Project name used in resource naming and tagging."
  type        = string
  default     = "agentic-escalation-hitl"
}

# ── Networking ───────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of AZs to use (minimum 2 for HA)."
  type        = list(string)
  default     = ["eu-west-1a", "eu-west-1b"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (one per AZ)."
  type        = list(string)
  default     = ["10.0.11.0/24", "10.0.12.0/24"]
}

# ── Container ────────────────────────────────────────────────────────────────

variable "container_port" {
  description = "Port exposed by the container."
  type        = number
  default     = 8080
}

variable "task_cpu" {
  description = "Fargate task CPU units (256, 512, 1024, 2048, 4096)."
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 2048
}

# ── Service scaling ──────────────────────────────────────────────────────────

variable "desired_count" {
  description = "Desired number of running ECS tasks."
  type        = number
  default     = 2
}

variable "min_count" {
  description = "Minimum number of ECS tasks (auto-scaling floor)."
  type        = number
  default     = 2
}

variable "max_count" {
  description = "Maximum number of ECS tasks (auto-scaling ceiling)."
  type        = number
  default     = 10
}

variable "scale_out_cpu_threshold" {
  description = "CPU utilisation % that triggers scale-out."
  type        = number
  default     = 60
}

variable "scale_in_cpu_threshold" {
  description = "CPU utilisation % that triggers scale-in."
  type        = number
  default     = 30
}

# ── Application ──────────────────────────────────────────────────────────────

variable "llm_provider" {
  description = "LLM provider: 'openai' or 'gemini'."
  type        = string
  default     = "openai"
}

variable "llm_confidence_threshold" {
  description = "Confidence threshold for LLM escalation decision."
  type        = string
  default     = "0.7"
}

variable "skip_nli" {
  description = "Set to 'true' to disable NLI intent classifier."
  type        = string
  default     = "false"
}

# ── Secrets — values supplied via tfvars / environment, never committed ──────

variable "openai_api_key" {
  description = "OpenAI API key (stored in Secrets Manager)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Gemini API key (stored in Secrets Manager)."
  type        = string
  sensitive   = true
  default     = ""
}

# ── ALB / HTTPS ──────────────────────────────────────────────────────────────

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS listener. Leave empty to use HTTP only."
  type        = string
  default     = ""
}

variable "health_check_path" {
  description = "Path the ALB uses for target health checks."
  type        = string
  default     = "/health"
}
