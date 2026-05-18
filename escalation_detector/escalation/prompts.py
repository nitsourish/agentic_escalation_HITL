"""
Prompt templates for the LLM-based escalation classifier (Tier 2).

The system prompt and few-shot examples only cover cases the LLM will actually
receive — those that slipped past Tier 1's hard rules.  Explicit agent requests
are caught by the rule engine before the LLM is called, so they are excluded
here intentionally.
"""

import json

from .models import Message

SYSTEM_PROMPT = """You are an escalation judge for a customer support chatbot.
You only see conversations that have already passed basic rule checks — explicit
human-agent requests are handled before you are called.

Escalate (output escalate=true) when ANY of the following is true:
- The bot has given the same advice at least twice across separate turns with no progress (repetition requires ≥2 bot failures, not just 1).
- The bot explicitly admitted it cannot find the relevant information.
- The user expresses clear frustration or anger (strong language, ALL-CAPS, repeated complaints, threats to leave).
- The user reports an unresolved problem that has persisted for a significant amount of time (days, weeks).

Do NOT escalate when:
- The conversation is still in early troubleshooting and the bot has not yet exhausted reasonable options.
- The user's tone is neutral and the issue appears resolvable with one more step.
- The bot's most recent response directly and helpfully addressed the user's question.
- The user reported the issue persisting after a single genuine troubleshooting attempt where the bot did NOT admit a knowledge gap — one incomplete step is not multi-turn failure. This exemption does NOT apply if the bot said it could not find the information.

Respond with a single JSON object:
{"escalate": true|false, "confidence": 0.0-1.0, "reason": "<one sentence>"}

No other text — only valid JSON."""

# Three representative few-shot examples covering the cases the LLM will
# actually receive (all reached here because Tier 1 did not short-circuit).
_FEW_SHOT_EXAMPLES = [
    # Pattern: bot repetition + time-urgency frustration (c001)
    # Tier 1 miss: frustration score below hard threshold, no explicit request.
    {
        "history": [
            {"role": "bot", "message": "Hello there. Feel free to enter a new message."},
            {"role": "user", "message": "I have tried to verify my ID but haven't heard anything back. The email said it expired but it hasn't."},
            {"role": "bot", "message": "Ensure the ID is clear and valid, and matches the registered profile name."},
            {"role": "user", "message": "So I resent and haven't heard anything back"},
            {"role": "bot", "message": "Verification may take a couple of days. Ensure all documents are clear and valid."},
            {"role": "user", "message": "It's been 2 weeks"},
            {"role": "bot", "message": "Verification can sometimes take longer. Ensure your documents are clear and valid. Check your spam folder."},
        ],
        "decision": {"escalate": True, "confidence": 0.95, "reason": "Bot repeated the same advice three times while the user's unresolved issue has persisted for two weeks."},
    },
    # Pattern: moderate frustration + bot knowledge failure (c020)
    # Tier 1 miss: threat-to-leave signal is soft (score 2.5), no explicit request.
    {
        "history": [
            {"role": "bot", "message": "Hello! I'm here to help. What can I help you with today?"},
            {"role": "user", "message": "I am missing some money on my account"},
            {"role": "bot", "message": "Sorry, we could not find the information you are looking for. Could you please clarify your issue?"},
            {"role": "user", "message": "did you take all my money"},
            {"role": "bot", "message": "Sorry, we could not find the information you are looking for."},
            {"role": "user", "message": "you suck! I am going leave the service"},
        ],
        "decision": {"escalate": True, "confidence": 0.95, "reason": "Bot repeatedly failed to find relevant information while the user expressed anger and threatened to leave."},
    },
    # Pattern: no escalation — early troubleshooting, issue still resolvable (c016)
    {
        "history": [
            {"role": "bot", "message": "Hello! I'm here to assist you. What can I help you with today?"},
            {"role": "user", "message": "I need to update my bank account details"},
            {"role": "bot", "message": "To update your bank account: go to Account > Settings > Bank Account and follow the prompts."},
            {"role": "user", "message": "Thank you"},
        ],
        "decision": {"escalate": False, "confidence": 0.95, "reason": "The bot resolved the user's query directly; no frustration or failure signals present."},
    },
    # Pattern: no escalation — one failed attempt, bot has not exhausted options (c018)
    # Key teaching: "issue still persisting" after a single troubleshooting step is NOT
    # multi-turn failure. The bot has more options available and the user shows no strong frustration.
    {
        "history": [
            {"role": "bot", "message": "Hello! Feel free to enter a new message."},
            {"role": "user", "message": "I changed my phone and can't receive the verification code"},
            {"role": "bot", "message": "Please ensure your phone has a stable network connection and can receive SMS from other senders. Let me know if the issue persists."},
            {"role": "user", "message": "Issue is still persisting"},
        ],
        "decision": {"escalate": False, "confidence": 0.90, "reason": "The bot has attempted only one troubleshooting step; further options remain before escalation is warranted."},
    },
]


def _format_history(history: list[dict | Message]) -> str:
    lines = []
    for turn in history:
        if isinstance(turn, dict):
            role, msg = turn["role"], turn["message"]
        else:
            role, msg = turn.role, turn.message
        lines.append(f"{role.upper()}: {msg}")
    return "\n".join(lines)


def _format_example(example: dict) -> str:
    history_str = _format_history(example["history"])
    return (
        f"Conversation:\n{history_str}\n\n"
        f"Decision: {json.dumps(example['decision'])}"
    )


def build_prompt(history: list[Message], signals: list[str] | None = None) -> str:
    """Assembles the full user-turn prompt: few-shot examples, live conversation, and soft signals."""
    examples_block = "\n\n---\n\n".join(
        _format_example(ex) for ex in _FEW_SHOT_EXAMPLES
    )
    live_history = _format_history(history)

    signals_block = ""
    if signals:
        bullet_list = "\n".join(f"  - {s}" for s in signals)
        signals_block = (
            f"\nHeuristic signals (treat as supporting context, not facts):\n"
            f"{bullet_list}\n"
        )

    return (
        f"Here are example decisions:\n\n"
        f"{examples_block}\n\n"
        f"---\n\n"
        f"Now decide for this conversation:\n\n"
        f"{live_history}\n"
        f"{signals_block}\n"
        f"Decision:"
    )
