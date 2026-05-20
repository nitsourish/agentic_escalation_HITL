---
noteId: "be98d290530e11f1abc0f9066530b2f7"
tags: []

---

# Agentic Escalation Detector (HITL)

Detects when a customer support chatbot conversation should be escalated to a human agent using a two-tier pipeline: deterministic rule engine + LLM classifier.

## Project structure

```
escalation_detector/   ← Core Python library (rules, LLM classifier, CLI, evaluator)
deploy/
  api/                 ← FastAPI REST wrapper + Dockerfile
  terraform/           ← Full AWS infrastructure (VPC, ALB, ECS Fargate, ECR, CloudWatch)
  scripts/             ← Build / deploy / teardown shell scripts
  DEPLOYMENT.md        ← Architecture diagrams and ops runbook
```

## Quick start (local)

```bash
cd escalation_detector
pip install -r requirements.txt
cp .env.example .env    # fill in your LLM API key
python cli.py           # interactive mode
python evaluate.py      # offline evaluation
```

## REST API (AWS deployment)

See [deploy/DEPLOYMENT.md](deploy/DEPLOYMENT.md) for the full deployment guide including architecture diagrams, Terraform setup, and operations runbook.

```bash
# One-command deploy to AWS ECS Fargate
bash deploy/scripts/deploy.sh
```

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/escalation/check` | Evaluate conversation history |
| `GET` | `/health` | ALB health check |
| `GET` | `/v1/config` | Active runtime configuration |


