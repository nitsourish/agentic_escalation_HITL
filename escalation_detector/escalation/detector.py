"""
EscalationDetector: orchestrates the two-tier decision pipeline.

Flow:
  1. Hard rules (RuleEngine.evaluate) — short-circuit on explicit agent requests
     and very high frustration.  Near-zero false-positive risk.
  2. Soft signals (RuleEngine.collect_signals) — heuristic observations (bot
     failure pattern, repetition, moderate frustration) passed as labelled
     context to the LLM.  The LLM reconciles them against the full conversation
     text and makes the final call.

This separation ensures surface heuristics that can plausibly misfire (e.g. a
clarification question matching a "bot doesn't know" regex) are never silently
escalated without the LLM having a chance to veto.
"""

from .llm_classifier import BaseLLMClassifier
from .models import EscalationDecision, Message
from .rules import RuleEngine

_NO_DECISION = EscalationDecision(
    escalate=False,
    tier="rules",
    reason="Conversation is within normal bounds; no escalation warranted.",
    confidence=1.0,
)


class EscalationDetector:
    """
    Predicts whether the current conversation state warrants escalation to a
    human agent.  Call check() after every new user message.

    Args:
        rule_engine:     Tier 1 deterministic checker. Pass None to disable.
        llm_classifier:  Tier 2 LLM-based checker. Pass None to disable.

    At least one tier should be enabled.
    """

    def __init__(
        self,
        rule_engine: RuleEngine | None = None,
        llm_classifier: BaseLLMClassifier | None = None,
    ) -> None:
        self._rules = rule_engine
        self._llm = llm_classifier

    def check(self, history: list[Message]) -> EscalationDecision:
        """
        Evaluate the full conversation history and return a decision.

        Hard rules short-circuit immediately.  Soft signals are collected and
        forwarded to the LLM as context — the LLM makes the final call on
        ambiguous cases rather than trusting noisy heuristics alone.
        """
        signals: list[str] = []

        if self._rules is not None:
            hard_decision = self._rules.evaluate(history)
            if hard_decision is not None:
                return hard_decision
            signals = self._rules.collect_signals(history)

        if self._llm is not None:
            return self._llm.classify(history, signals=signals)

        return _NO_DECISION
