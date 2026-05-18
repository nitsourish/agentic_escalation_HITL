---
noteId: "8286c250523511f1abc0f9066530b2f7"
tags: []

---

# Deployment Guide — Agentic Escalation Detector (HITL)

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Repository Layout](#3-repository-layout)
4. [Prerequisites](#4-prerequisites)
5. [First-Time Setup](#5-first-time-setup)
6. [Day-to-Day Operations](#6-day-to-day-operations)
7. [REST API Reference](#7-rest-api-reference)
8. [Configuration Reference](#8-configuration-reference)
9. [Scaling & Cost Estimates](#9-scaling--cost-estimates)
10. [Observability](#10-observability)
11. [Security Controls](#11-security-controls)
12. [Troubleshooting](#12-troubleshooting)
13. [Teardown](#13-teardown)

---

## 1. Overview

The escalation detector runs as a stateless REST API service inside Docker containers
managed by **AWS ECS Fargate**. Each container exposes a single prediction endpoint
that accepts a conversation history and returns an escalation decision.

Traffic enters through an **Application Load Balancer (ALB)** that:
- Distributes requests across all healthy containers.
- Performs health checks and automatically drains unhealthy targets.
- Optionally terminates TLS with an ACM certificate.

API keys for OpenAI / Gemini are stored in **AWS Secrets Manager** and injected at
container start-up — they are never baked into the image.

---

## 2. Architecture

### 2.1 High-Level Diagram

```
                           ┌──────────────────────────────────────────────┐
                           │                  AWS Cloud                    │
                           │                                               │
  Client                   │   ┌──────────────────────────────────────┐   │
  (chatbot /    ─── HTTPS ─┼──►│  Application Load Balancer (ALB)     │   │
   internal     ◄── JSON ──┼───│  • HTTP → HTTPS redirect              │   │
   service)                │   │  • /health target health checks       │   │
                           │   │  • Access logs → S3                   │   │
                           │   └────────────┬─────────────────────────┘   │
                           │                │ HTTP :8080 (private)         │
                           │   ┌────────────▼─────────────────────────┐   │
                           │   │       ECS Fargate Cluster             │   │
                           │   │                                       │   │
                           │   │  ┌──────────────┐ ┌──────────────┐  │   │
                           │   │  │ Task (AZ-1a) │ │ Task (AZ-1b) │  │   │
                           │   │  │              │ │              │  │   │
                           │   │  │ FastAPI+uvicorn FastAPI+uvicorn│  │   │
                           │   │  │              │ │              │  │   │
                           │   │  │ ┌──────────┐ │ │ ┌──────────┐│  │   │
                           │   │  │ │Rule Engine│ │ │ │Rule Engine││  │   │
                           │   │  │ │  (sync)  │ │ │ │  (sync)  ││  │   │
                           │   │  │ └────┬─────┘ │ │ └────┬─────┘│  │   │
                           │   │  │      │        │ │      │       │  │   │
                           │   │  │ ┌────▼─────┐ │ │ ┌────▼─────┐│  │   │
                           │   │  │ │LLM Client│ │ │ │LLM Client││  │   │
                           │   │  │ └──────────┘ │ │ └──────────┘│  │   │
                           │   │  └──────────────┘ └──────────────┘  │   │
                           │   │                                       │   │
                           │   │  Auto Scaling: 2–10 tasks             │   │
                           │   │  CPU target: 60% scale-out            │   │
                           │   └───────────────────────────────────────┘   │
                           │           │                    │               │
                           │    ┌──────▼──────┐   ┌────────▼──────┐       │
                           │    │  Secrets     │   │  CloudWatch   │       │
                           │    │  Manager     │   │  Logs + Alarms│       │
                           │    │              │   │  + Dashboard  │       │
                           │    │  OPENAI_KEY  │   │               │       │
                           │    │  GEMINI_KEY  │   └───────────────┘       │
                           │    └─────────────┘                            │
                           │                                               │
                           │  ┌──────────────────────────────────────┐    │
                           │  │              ECR Registry             │    │
                           │  │  agentic-escalation-hitl-prod-api:latest    │    │
                           │  └──────────────────────────────────────┘    │
                           └──────────────────────────────────────────────┘
```

### 2.2 Network Topology

```
VPC  10.0.0.0/16
│
├── Public Subnets  (ALB, NAT Gateways, Internet Gateway)
│   ├── 10.0.1.0/24  — eu-west-1a
│   └── 10.0.2.0/24  — eu-west-1b
│
└── Private Subnets  (ECS tasks — no direct internet ingress)
    ├── 10.0.11.0/24 — eu-west-1a
    └── 10.0.12.0/24 — eu-west-1b

Internet Gateway  ──► Public subnets
NAT Gateways      ──► Private subnets (outbound for LLM API calls)

Security Groups:
  alb-sg      : inbound 80, 443 from 0.0.0.0/0  │  outbound all
  ecs-tasks-sg: inbound :8080 from alb-sg only    │  outbound all
```

### 2.3 Request Lifecycle

```
1.  Client sends:  POST /v1/escalation/check  (JSON body)
                   →  ALB listener :443
2.  ALB forwards to a healthy ECS task on port :8080
3.  FastAPI validates the Pydantic request body
4.  Tier 1 — RuleEngine evaluates hard rules (<1 ms):
      a. Explicit human-agent request (NLI / regex)
      b. Very high frustration score (≥ 6.0)
      → If fired: return EscalationDecision immediately
5.  Tier 1 — collect soft signals (bot failure, repetition, moderate frustration)
6.  Tier 2 — LLM Classifier calls OpenAI / Gemini API (1–3 s)
      → JSON { escalate, confidence, reason }
7.  API returns EscalationResult to client (< 5 s total P99)
8.  Access log written to S3; structured log written to CloudWatch
```

### 2.4 Component Inventory

| Component | AWS Service | Notes |
|---|---|---|
| API containers | ECS Fargate | 1 vCPU, 2 GB RAM per task; 2–10 tasks |
| Load balancer | Application Load Balancer | Multi-AZ, HTTPS termination |
| Container registry | ECR | Image scanning on push; 10-image lifecycle |
| Secrets | Secrets Manager | API keys injected at task launch |
| Logging | CloudWatch Logs | 30-day retention |
| Metrics & Alarms | CloudWatch | 5xx rate, latency P99, CPU/memory |
| Dashboard | CloudWatch Dashboard | Prebuilt 4-panel overview |
| Auto-scaling | Application Auto Scaling | CPU step scaling + ALB request tracking |
| Network | VPC | 2 AZs, public + private subnets, NAT GW |
| State store | S3 + DynamoDB | Terraform remote state |

---

## 3. Repository Layout

```
repo-root/
├── escalation_detector/          ← Core Python library (unchanged)
│   ├── escalation/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── detector.py
│   │   ├── llm_classifier.py
│   │   ├── models.py
│   │   ├── prompts.py
│   │   └── rules.py
│   ├── cli.py
│   ├── evaluate.py
│   └── requirements.txt
│
└── deploy/
    ├── DEPLOYMENT.md          ← This file
    ├── api/
    │   ├── app.py             ← FastAPI REST wrapper
    │   ├── requirements.txt   ← API + library dependencies
    │   ├── Dockerfile         ← Multi-stage Docker build
    │   └── .dockerignore
    ├── terraform/
    │   ├── main.tf            ← Provider + backend config
    │   ├── variables.tf       ← All tunable parameters
    │   ├── outputs.tf         ← Exported values
    │   ├── vpc.tf             ← VPC, subnets, NAT, security groups
    │   ├── ecr.tf             ← Container registry + lifecycle policy
    │   ├── secrets.tf         ← Secrets Manager entries
    │   ├── iam.tf             ← Execution role, task role, ASG role
    │   ├── alb.tf             ← ALB, target group, listeners, S3 logs
    │   ├── ecs.tf             ← Cluster, task definition, service
    │   ├── autoscaling.tf     ← Step scaling + target tracking
    │   └── cloudwatch.tf      ← Log group, alarms, dashboard
    └── scripts/
        ├── build_and_push.sh  ← Build image; push to ECR
        ├── deploy.sh          ← End-to-end deploy pipeline
        ├── set_secret.sh      ← Rotate/set API keys in Secrets Manager
        └── teardown.sh        ← Destroy all AWS resources
```

---

## 4. Prerequisites

### Local tooling

| Tool | Version | Install |
|---|---|---|
| AWS CLI | ≥ 2.15 | `brew install awscli` |
| Terraform | ≥ 1.6 | `brew install terraform` |
| Docker Desktop | ≥ 24 | https://docs.docker.com/desktop/mac/ |
| Python | ≥ 3.11 | `brew install python` |

### AWS permissions (deployer IAM role/user)

The identity running Terraform and the deploy scripts needs at minimum:

- `ecs:*`, `ecr:*`, `elasticloadbalancing:*`
- `ec2:*` (VPC provisioning)
- `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PassRole`
- `secretsmanager:*`
- `cloudwatch:*`, `logs:*`
- `s3:*` (Terraform state bucket + ALB logs bucket)
- `dynamodb:*` (Terraform lock table)
- `application-autoscaling:*`

> Tip: attach `AdministratorAccess` for initial setup in a sandbox account.

### Terraform remote state (one-time)

Create the S3 bucket and DynamoDB table before the first `terraform init`:

```bash
# S3 bucket for state
aws s3api create-bucket \
  --bucket agentic-escalation-hitl-tfstate \
  --region eu-west-1 \
  --create-bucket-configuration LocationConstraint=eu-west-1

aws s3api put-bucket-versioning \
  --bucket agentic-escalation-hitl-tfstate \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket agentic-escalation-hitl-tfstate \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# DynamoDB table for state locking
aws dynamodb create-table \
  --table-name agentic-escalation-hitl-tf-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region eu-west-1
```

---

## 5. First-Time Setup

### Step 1 — Configure Terraform variables

Create `deploy/terraform/terraform.tfvars` (never commit this file):

```hcl
# deploy/terraform/terraform.tfvars
aws_region  = "eu-west-1"
environment = "prod"

# LLM provider settings
llm_provider             = "openai"
llm_confidence_threshold = "0.7"

# Optional: HTTPS (paste your ACM certificate ARN)
# certificate_arn = "arn:aws:acm:eu-west-1:123456789012:certificate/..."

# Optional: inject secrets via tfvars instead of set_secret.sh
# openai_api_key = "sk-..."
```

### Step 2 — Run the full deploy pipeline

```bash
cd /path/to/repo
bash deploy/scripts/deploy.sh
```

This performs all four steps automatically:
1. `terraform init` + `terraform apply`
2. `docker build` + `docker push` to ECR
3. `aws ecs update-service --force-new-deployment`
4. Wait for ECS service to be stable + smoke test `/health`

### Step 3 — Store API keys (if not provided via tfvars)

```bash
bash deploy/scripts/set_secret.sh openai  "sk-your-openai-key"
bash deploy/scripts/set_secret.sh gemini  "AIza-your-gemini-key"

# Restart containers to pick up the new secrets
bash deploy/scripts/deploy.sh
```

### Step 4 — Verify

```bash
# Read the ALB DNS name from Terraform
API_URL=$(terraform -chdir=deploy/terraform output -raw api_base_url)

# Health check
curl "$API_URL/health"
# → {"status":"ok","version":"1.0.0"}

# Test prediction
curl -X POST "$API_URL/v1/escalation/check" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test-001",
    "history": [
      {"role": "bot",  "message": "Hello! How can I help you today?"},
      {"role": "user", "message": "I want to speak to a human agent NOW."}
    ]
  }'
# → {"escalate":true,"tier":"rules","reason":"...","confidence":1.0,"latency_ms":2.1}
```

---

## 6. Day-to-Day Operations

### Deploy a new image (e.g., after a code change)

```bash
# Build, push, and force-redeploy in one command
bash deploy/scripts/deploy.sh

# Or pin an explicit tag
bash deploy/scripts/deploy.sh v2.3.1
```

ECS uses a **rolling update** (default) — new tasks start before old ones drain,
so there is no downtime during deployment.

### Roll back to a previous image

```bash
# List available tags
aws ecr describe-images \
  --repository-name agentic-escalation-hitl-prod-api \
  --query 'sort_by(imageDetails,& imagePushedAt)[-5:].imageTags' \
  --output text

# Force ECS to use a specific tag by updating the task definition:
ECR_URL=$(terraform -chdir=deploy/terraform output -raw ecr_repository_url)
OLD_TAG="abc1234"

aws ecs update-service \
  --cluster agentic-escalation-hitl-prod-cluster \
  --service agentic-escalation-hitl-prod-service \
  --task-definition "$(
    aws ecs register-task-definition \
      --cli-input-json "$(
        aws ecs describe-task-definition \
          --task-definition agentic-escalation-hitl-prod-task \
          --query 'taskDefinition' \
        | jq --arg img "$ECR_URL:$OLD_TAG" \
            '.containerDefinitions[0].image = $img |
             del(.taskDefinitionArn,.revision,.status,.requiresAttributes,.compatibilities,.registeredAt,.registeredBy)'
      )" \
      --query 'taskDefinition.taskDefinitionArn' \
      --output text
  )" \
  --force-new-deployment
```

### Rotate API keys

```bash
bash deploy/scripts/set_secret.sh openai "sk-new-key"
bash deploy/scripts/deploy.sh          # restarts tasks to pull new secret
```

### Scale manually

```bash
aws ecs update-service \
  --cluster agentic-escalation-hitl-prod-cluster \
  --service agentic-escalation-hitl-prod-service \
  --desired-count 6
```

### View live logs

```bash
aws logs tail /ecs/agentic-escalation-hitl-prod \
  --follow \
  --format short
```

### SSH into a running task (ECS Exec)

```bash
TASK_ARN=$(aws ecs list-tasks \
  --cluster agentic-escalation-hitl-prod-cluster \
  --service-name agentic-escalation-hitl-prod-service \
  --query 'taskArns[0]' --output text)

aws ecs execute-command \
  --cluster agentic-escalation-hitl-prod-cluster \
  --task "$TASK_ARN" \
  --container escalation-api \
  --interactive \
  --command "/bin/bash"
```

---

## 7. REST API Reference

### Base URL

```
https://<alb-dns-name>        # HTTPS (when certificate_arn is set)
http://<alb-dns-name>         # HTTP (fallback / internal)
```

Read the URL from Terraform at any time:
```bash
terraform -chdir=deploy/terraform output api_base_url
```

---

### `GET /health`

Readiness probe used by the ALB. Returns `200 OK` when the detector is loaded.

**Response**
```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

### `GET /v1/config`

Returns the active runtime configuration. No secrets are exposed.

**Response**
```json
{
  "llm_provider": "openai",
  "llm_only": false,
  "skip_nli": false,
  "confidence_threshold": 0.7
}
```

---

### `POST /v1/escalation/check`

Evaluate a conversation history and decide whether to escalate.

**Request body**

```json
{
  "conversation_id": "conv-abc123",
  "history": [
    { "role": "bot",  "message": "Hello! How can I help you today?" },
    { "role": "user", "message": "My account has been frozen for 3 weeks!" },
    { "role": "bot",  "message": "I'm sorry to hear that. Let me look into it." },
    { "role": "user", "message": "I want to speak to a manager NOW." }
  ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `conversation_id` | string | No | Logged for tracing; not used in logic |
| `history` | array | Yes | Full history, oldest first; ≥ 1 user message |
| `history[].role` | "user"\|"bot" | Yes | |
| `history[].message` | string | Yes | 1–4096 characters |

**Response**

```json
{
  "escalate": true,
  "tier": "rules",
  "reason": "User explicitly requested to speak with a human agent.",
  "confidence": 1.0,
  "latency_ms": 3.2
}
```

| Field | Type | Notes |
|---|---|---|
| `escalate` | bool | `true` → hand off to human agent |
| `tier` | "rules"\|"llm" | Which tier made the decision |
| `reason` | string | Human-readable explanation |
| `confidence` | float 0–1 | 1.0 for rules-tier; LLM-calibrated for llm-tier |
| `latency_ms` | float | Server-side processing time |

**Error responses**

| Status | Condition |
|---|---|
| `422 Unprocessable Entity` | Malformed request body or no user message in history |
| `503 Service Unavailable` | Detector not yet loaded (cold start) |
| `500 Internal Server Error` | LLM API failure or unexpected exception |

---

## 8. Configuration Reference

All configuration is in `deploy/terraform/variables.tf` and overridden in `terraform.tfvars`.

| Variable | Default | Description |
|---|---|---|
| `aws_region` | `eu-west-1` | AWS deployment region |
| `environment` | `prod` | Environment tag (also in resource names) |
| `task_cpu` | `1024` (1 vCPU) | Fargate task CPU units |
| `task_memory` | `2048` (2 GB) | Fargate task memory |
| `desired_count` | `2` | Initial task count |
| `min_count` | `2` | ASG minimum |
| `max_count` | `10` | ASG maximum |
| `scale_out_cpu_threshold` | `60` | CPU % to add tasks |
| `scale_in_cpu_threshold` | `30` | CPU % to remove tasks |
| `llm_provider` | `openai` | `openai` or `gemini` |
| `llm_confidence_threshold` | `0.7` | Escalation confidence threshold |
| `skip_nli` | `false` | Disable NLI intent classifier |
| `certificate_arn` | `""` | ACM cert ARN for HTTPS |
| `health_check_path` | `/health` | ALB health check path |

---

## 9. Scaling & Cost Estimates

### Scaling behaviour

| Metric | Action | Cooldown |
|---|---|---|
| CPU > 60% for 3 min | Add 2 tasks | 120 s |
| CPU < 30% for 10 min | Remove 1 task | 300 s |
| > 1000 ALB requests/task | Target tracking scale-out | 60 s |

Each task handles ~4–10 concurrent requests comfortably at the default 2-worker
uvicorn configuration. The LLM call (1–3 s) is the dominant latency driver.

### Approximate monthly cost (eu-west-1, 2 tasks baseline)

| Service | Qty | ~USD/month |
|---|---|---|
| ECS Fargate (1 vCPU, 2 GB × 2 tasks × 24h) | 2 tasks | ~$85 |
| ALB (fixed + LCU) | 1 ALB | ~$20 |
| NAT Gateways (2 AZs) | 2 × $0.048/h | ~$70 |
| ECR storage | < 5 GB | ~$0.50 |
| CloudWatch (logs + alarms) | moderate traffic | ~$5 |
| Secrets Manager | 2 secrets | ~$1 |
| **Total baseline** | | **~$180/month** |

> LLM API costs (OpenAI/Gemini) are separate and depend on call volume.
> At 10k requests/day with ~50% LLM-tier calls, gpt-4o-mini adds ~$5–$15/day.

---

## 10. Observability

### CloudWatch Dashboard

Available at:
```
https://console.aws.amazon.com/cloudwatch/home?region=eu-west-1#dashboards:name=agentic-escalation-hitl-prod-overview
```

Panels:
- ALB request count + 5xx errors
- ALB P50 / P99 latency
- ECS CPU + memory utilisation
- ECS running task count

### Alarms

| Alarm | Condition | Action |
|---|---|---|
| `alb-5xx-high` | > 10 HTTP 5xx per minute for 3 min | SNS → alert |
| `ecs-cpu-high` | CPU > 80% for 3 min | SNS → alert |
| `ecs-memory-high` | Memory > 80% for 3 min | SNS → alert |
| `alb-p99-latency` | P99 > 5 s for 2 min | SNS → alert |

Subscribe to alerts:
```bash
aws sns subscribe \
  --topic-arn "$(terraform -chdir=deploy/terraform output -raw)" \
  --protocol email \
  --notification-endpoint oncall@yourcompany.com
```

### Structured logs

Each request emits a structured log line:
```
2025-05-17 10:23:45,123 INFO escalation_api conv=conv-001 escalate=True tier=rules conf=1.00 latency=2.1ms
```

Query in CloudWatch Logs Insights:
```sql
fields @timestamp, conv, escalate, tier, conf, latency
| filter tier = "llm"
| stats avg(latency) as p50_ms, pct(latency, 99) as p99_ms by bin(5m)
```

---

## 11. Security Controls

| Control | Implementation |
|---|---|
| API keys | AWS Secrets Manager; injected at launch, never in image |
| Network ingress | ALB SG: 80/443 from internet; ECS SG: :8080 from ALB only |
| Container user | Non-root `appuser` (UID 1001) |
| HTTPS | ALB TLS 1.3 policy when `certificate_arn` is set |
| ECR image scan | `scan_on_push = true` |
| Deletion protection | `enable_deletion_protection = true` in prod |
| Remote state | S3 versioning + SSE-S3 encryption + DynamoDB lock |
| IAM least-privilege | Separate execution role (ECR/SM read) and task role (CW write) |
| Prompt injection | System prompt frames LLM as a passive judge; JSON parser rejects non-conforming responses |

---

## 12. Troubleshooting

### Containers fail to start

```bash
# Check ECS service events
aws ecs describe-services \
  --cluster agentic-escalation-hitl-prod-cluster \
  --services agentic-escalation-hitl-prod-service \
  --query "services[0].events[:5]"

# Check CloudWatch logs
aws logs tail /ecs/agentic-escalation-hitl-prod --follow
```

Common causes:
- Secret value still set to `REPLACE_ME` → run `set_secret.sh`
- Image missing from ECR → run `build_and_push.sh`
- Task role missing permissions → check `iam.tf`

### ALB returns 502 Bad Gateway

The container is running but the health check is failing:
```bash
# Check target health
aws elbv2 describe-target-health \
  --target-group-arn "$(terraform -chdir=deploy/terraform output -raw)" \
  --query "TargetHealthDescriptions[*].{Target:Target.Id,State:TargetHealth.State,Reason:TargetHealth.Reason}"
```

### LLM calls failing

Symptom: requests that reach Tier 2 return HTTP 500.

Check logs for `openai.AuthenticationError` or similar:
```bash
aws logs filter-log-events \
  --log-group-name /ecs/agentic-escalation-hitl-prod \
  --filter-pattern "ERROR"
```

Rotate the key: `bash deploy/scripts/set_secret.sh openai sk-new-key`

### NLI model takes too long on cold start

The NLI model (~80 MB) downloads from Hugging Face on first use. Subsequent
tasks use the container-local cache (`/app/.hf_cache`). In production, consider
baking the model into the image to eliminate cold-start latency:

```dockerfile
# Add to Dockerfile (after COPY layers)
RUN python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='cross-encoder/nli-MiniLM2-L6-H768')"
```

---

## 13. Teardown

To destroy all AWS resources (irreversible):

```bash
bash deploy/scripts/teardown.sh
# → Type 'destroy' to confirm
```

This will:
1. Scale the ECS service to 0 tasks.
2. Run `terraform destroy` to remove all resources.

> S3 buckets for ALB logs are **force-deleted** in non-prod environments.
> In prod, `force_destroy = false` — delete bucket contents manually first.
