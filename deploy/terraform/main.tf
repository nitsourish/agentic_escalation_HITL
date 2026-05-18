terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state — update bucket/key for your account before first apply.
  # Comment out this block to use local state during development.
  backend "s3" {
    bucket         = "agentic-escalation-hitl-tfstate"
    key            = "escalation-api/terraform.tfstate"
    region         = "eu-west-1"
    encrypt        = true
    dynamodb_table = "agentic-escalation-hitl-tf-locks"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ── Data sources ─────────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.name
  name_prefix = "${var.project}-${var.environment}"
}
