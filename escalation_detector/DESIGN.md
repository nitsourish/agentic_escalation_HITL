---
noteId: "aa94ef50430911f190f10fc298efba94"
tags: []

---

# Design Document — Agentic Escalation Detector (HITL)

## Problem

A customer support chatbot handles high volumes of inquiries. Some conversations
reach a point where the bot can no longer help — due to knowledge gaps, repetitive
failure, or user frustration — and a human agent is needed. Escalating too early
wastes agent capacity; too late risks user churn. The system must make this
judgment in real time, after each user message.

---

## Dataset Observations

The labeled corpus has 20 conversations (12 escalation=true, 8=false). Examining
the reasoning annotations, two dominant failure patterns emerged:

| Pattern | Example conversations | Signal |
|---|---|---|
| **Bot failure** | c001, c002, c006–c012 | Bot repeats same advice, or admits it cannot find the answer |
| **User frustration** | c003, c004, c011, c020 | Explicit human request, emotional language, time-urgency |

The distribution is roughly 60/40 (escalate/not), which is manageable without
class-weighting tricks for a prototype. Labels are annotated at conversation end,
not at the specific turn where escalation should have triggered — this is a
key limitation discussed below.

---

## Architecture

```
New user message
      │
      ▼
┌──────────────────────────────────────────────┐
│  RuleEngine.evaluate()  — hard rules only     │  sub-millisecond
│                                               │
│  • Explicit human-agent request  (NLI / regex) │
│  • Very high frustration  (score ≥ 6.0)        │
└──────────────┬───────────────────────────────┘
               │ fires                │ None
               ▼                      ▼
      EscalationDecision    RuleEngine.collect_signals()
      (tier="rules")                  │
                            soft heuristics as labelled strings:
                            • bot knowledge-gap pattern match
                            • bot repetition count
                            • moderate frustration (2.5 ≤ score < 6.0)
                                      │
                                      ▼
                          ┌───────────────────────────────┐
                          │  BaseLLMClassifier.classify()  │  ~1-2s
                          │                                │
                          │  system prompt (policy)        │
                          │  + 3 few-shot examples         │
                          │  + soft signals as context     │
                          │  → JSON {escalate, conf, reason}│
                          └───────────────┬───────────────┘
                                          │
                                EscalationDecision
                                (tier="llm")
```

### Why hard/soft signal separation?

The aggressive short-circuiting on all rule types is risky for bot-failure and bot-repetition
patterns, which are surface heuristics. The canonical(hard) false positive: a bot
saying "I'm not sure which account you mean — could you clarify?" will trip the
bot-knowledge-gap regex (`please clarify`) but is not an escalation case.

The fix: only rules with near-zero FP risk short-circuit. Noisy heuristics are
passed as labelled context to the LLM, which can reconcile them against the full
conversation text. The LLM can see that "please clarify" was a targeted
disambiguation question, not a dead-end knowledge failure.

Benefits:

- **Precision**: hard rules never fire on ambiguous cases.
- **Latency/Cost**: the LLM is skipped for explicit agent requests (~16% of escalations in this dataset) and for extreme-frustration cases, reducing cost for the most obvious cases.
- **Signal amplification**: the LLM performs better when it receives pre-computed structural observations (turn count, repetition) alongside the raw text it would have to infer those from anyway.
- **Reliability**: hard rules still fire if the LLM API is down.

---

## Key Design Decisions

### LLM over a fine-tuned classifier

With 20 labeled examples, fine-tuning any encoder (BERT, DeBERTa) is impossible —
too few samples to avoid severe overfitting. An LLM used in-context can generalise
from 3–4 demonstrations, and its escalation policy is fully inspectable in the
prompt. When the policy evolves (new escalation criteria, new markets), only the
prompt changes — no retraining cycle.

### IntentClassifier (NLI for explicit-request detection)

The regex fallback for explicit agent requests misses paraphrases ("I give up,
just connect me"), indirect phrasing, and non-English text.  `IntentClassifier`
wraps a `zero-shot-classification` NLI pipeline (`cross-encoder/nli-MiniLM2-L6-H768`,
~80 MB) to classify whether a user message entails "requesting to speak with a
human agent".  It runs locally (~5–30 ms on CPU), needs no training data, and
handles paraphrases the regex cannot.

**NLI is enabled by default.**  If `transformers`/`torch` are not installed the
system warns at startup and falls back to regex automatically — no crash.  Pass
`--no-nli` to bypass NLI explicitly (e.g., for fast smoke tests or environments
where torch cannot be installed).  For multilingual support swap the model to
`MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`.

### Structured JSON output from the LLM

Asking the LLM to emit `{"escalate": bool, "confidence": float, "reason": str}`
instead of free text makes parsing deterministic and exposes a confidence score.
The confidence score enables threshold tuning without prompt changes — a lower
threshold increases recall (catches more escalations) at the cost of precision
(more false alarms). We default to 0.7, which is conservative.

### Per-turn evaluation

The system calls `detector.check(history)` after every user message. This is the
only design that can trigger escalation at the *right moment* rather than after
the conversation has already failed. The cost is one rule evaluation + potentially
one LLM call per user turn.

### Prompt-driven escalation policy

The escalation criteria live in `prompts.SYSTEM_PROMPT` as a concise bulleted
list, not hardcoded in logic. When the Operations team decides to add a new
escalation criterion (e.g., "always escalate if the user mentions a regulatory
complaint"), they update one string — the code is unchanged.

---

## Frustration Score Design

The rule engine scores frustration across all user messages in the conversation,
not just the most recent one. This captures accumulated frustration that no single
message fully expresses. The weighted signals and their rationale:

| Signal | Weight | Rationale |
|---|---|---|
| Profanity / strong language | 2.0 | Strong emotion signal |
| Threat to leave / cancel | 2.0 | High business-risk signal |
| Time-urgency phrases | 1.5 | "It's been 2 weeks" = unresolved issue |
| Emphatic repeated chars | 1.5 | "nowwwwww" = written frustration |
| ALL-CAPS words (per word) | 0.5 | Shouting |
| Exclamation marks (per mark) | 0.5 | Mild frustration, accumulates |

Two thresholds:

- **Hard (≥ 6.0 — short-circuit)**: requires a multi-signal combination such as profanity + threat-to-leave (4.0) plus additional signals.  This fires only when the evidence is unambiguous, e.g. "you're useless! I'm cancelling my account right now!"
- **Soft (2.5 ≤ score < 6.0 — LLM context)**: single strong signal or a few mild ones.  Surfaced to the LLM as "Moderate user frustration detected (…; score=X.X)" so it can weigh it alongside the full conversation rather than acting on it blindly.

---

## Assumptions

1. The `is_escalation_needed` label reflects whether escalation was warranted at
   any point in the conversation, not specifically at the last turn. The system
   evaluates the full history on each turn, which means it may escalate earlier
   than the annotation implies — this is conservative but safe.

2. Conversations are in English by default. The regex fallback is English-only;
   `IntentClassifier` with a multilingual model handles other languages.
   The LLM handles non-English text well in inference, but the few-shot examples
   are English, which may bias confidence calibration for other languages.

3. The bot reply stub used in the CLI (`cli.py`) is a placeholder — in production,
   the real bot's reply would be injected into history by the calling system.

---

## Technical Challenges in Production

### 1. Label granularity
Labels are per-conversation, not per-turn. We cannot know from the dataset exactly
*when* escalation should have fired. A future improvement is to have annotators
mark the specific turn that triggered escalation, which would allow training a
sequence model that optimises for early-but-not-premature triggering.

### 2. LLM latency
Each Tier 2 call adds ~1–2 seconds. For a synchronous chatbot, this is noticeable.
Mitigation: make the detector call asynchronous — the bot response is sent immediately,
and escalation is evaluated in parallel. If escalation fires, the *next* message from
the bot redirects to a human agent.

`evaluate.py` measures wall-clock latency per conversation and reports p50 and p99
(via linear interpolation, same method as `numpy.percentile`).  With the 20-conversation
dataset, p99 is effectively the worst-case sample; it becomes meaningful on larger
evaluation sets.  Latency is also written to the `--output` JSON for offline analysis.
Rule-only decisions (Tier 1 short-circuit) appear as sub-millisecond outliers in the
distribution, making the p50/p99 split a useful proxy for LLM vs. rule cost.

### 3. LLM non-determinism
Even at temperature=0, LLM can produce slightly different outputs across API
versions or during model updates.

### 4. Threshold calibration
The cost of a false positive (wasted agent time) and a false negative (frustrated
merchant who churns) are not symmetric. The team should decide the acceptable FP/FN
tradeoff. The LLM confidence threshold (currently 0.7), the hard frustration threshold
(currently 6.0), and the NLI entailment threshold (currently 0.80) are the
dials to tune, ideally on a labelled held-out set.

### 5. Multilingual conversations
The platform operates in 35+ countries. The regex fallback is English-only; `IntentClassifier`
with `mDeBERTa-v3-base-mnli-xnli` handles 100 languages for explicit-request detection.
The remaining gap is the LLM tier: few-shot examples are English, which may bias
confidence calibration for other languages. Fix: translate few-shot examples or
provide language-specific prompt variants.

### 6. Prompt injection
A user could embed instructions in their message to manipulate the LLM's decision. Mitigations already in place: the system prompt frames the LLM as a passive judge, and the JSON parser rejects any non-conforming response. Remaining risk: a successful injection attack would inflate the escalation rate, so alerting on abnormal rate increases provides indirect detection without inspecting every individual LLM decision.

---

## What I Would Do Differently With More Time

| Area | Improvement |
|---|---|
| **Turn-level labels** | Annotate the exact turn that warranted escalation; train a recurrent or attention-based sequence classifier |
| **Synthetic data** | LLM-assisted synthetic conversation generation followed by manual label review to grow the dataset cheaply |
| **Fine-tuning** | With 1000+ examples, fine-tune a small encoder (DeBERTa-base) — faster and cheaper than LLM inference at scale |
| **Calibration** | Platt scaling on a held-out set to get well-calibrated confidence scores |
| **Async pipeline** | Decouple bot response from escalation check using a background task queue |
| **Active learning** | Flag low-confidence decisions for human review; use reviewed examples to update few-shot set |
| **Proper train/test split** | With only 20 examples all evaluation is in-sample. Collecting ~200 labeled conversations would allow a held-out test set and reliable generalization estimates |
