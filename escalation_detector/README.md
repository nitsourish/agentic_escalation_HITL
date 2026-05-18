---
noteId: "0a2bd8c044ae11f190f10fc298efba94"
tags: []

---

# Agentic Escalation Detector (HITL)

Detects when a customer support chatbot conversation should be escalated to a human agent.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your key
```

**Gemini (free tier — recommended):**
```
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.0-flash-lite
```
Get a free key at [aistudio.google.com](https://aistudio.google.com).

**OpenAI (alternative):**
```
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

See `.env.example` for all available settings (model overrides, confidence threshold).

## Usage

**Interactive session** — type messages turn-by-turn:
```bash
python cli.py
```

**Replay a labeled conversation** from the dataset:
```bash
python cli.py --replay c001
python cli.py --replay c003
```

**Evaluate on the full dataset** (reports accuracy/precision/recall/F1):
```bash
python evaluate.py
python evaluate.py --rules-only   # no API key needed
```

**Flags:**
- `--llm-only` — skip the rule engine, send every turn to the LLM (requires API key)
- `--rules-only` — skip the LLM, use deterministic rules only (no API key required)
- `--no-nli` — use regex fallback instead of the NLI model for explicit-request detection (NLI is on by default; requires `transformers torch`)
- `--data PATH` — custom dataset JSON path (default: `data/escalation_dataset.json`)
- `--output PATH` — save evaluation results + metrics to a JSON file

## Project layout

```
escalation/
  config.py         # Reads .env; builds LLMConfig
  models.py         # Data classes: Message, EscalationDecision
  rules.py          # Tier 1: deterministic rule engine
  prompts.py        # System prompt + few-shot examples
  llm_classifier.py # Tier 2: BaseLLMClassifier, GeminiClassifier, OpenAIClassifier
  detector.py       # Orchestrates both tiers
cli.py              # Interactive / replay CLI
evaluate.py         # Offline evaluation script
.env.example        # Env template to keep secrets
DESIGN.md           # Architecture decisions and open questions
```

See [DESIGN.md](DESIGN.md) for the full design rationale.
