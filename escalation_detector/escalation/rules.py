"""
Tier 1: Fast deterministic rule engine.

Rules are split into two tiers of confidence:

  Hard rules (evaluate) — short-circuit the pipeline immediately.
    Only rules with near-zero false-positive risk belong here:
    explicit human-agent requests and very high frustration (multi-signal).

  Soft signals (collect_signals) — surface heuristic observations to the LLM
    as labelled context so it can reconcile them against the conversation.
    Bot-failure and bot-repetition patterns live here because they are noisy
    surface heuristics: "I'm not sure which account you mean — could you
    clarify?" matches a knowledge-gap regex but is not an escalation case.
    The LLM reads the full text and can distinguish; the rule engine alone
    cannot.
"""

import re
from .models import Message, EscalationDecision


# ---------------------------------------------------------------------------
# Explicit escalation request
# ---------------------------------------------------------------------------

# Regex fallback — used when no IntentClassifier is configured.
# Covers common phrasings but misses paraphrases, indirect requests, and
# non-English text.  Use IntentClassifier for production.
_EXPLICIT_REQUEST_PATTERNS = re.compile(
    r"\b("
    r"speak to (a |an )?(human|agent|person|representative|rep)"
    r"|talk to (a |an )?(human|agent|person|representative|rep)"
    r"|need (a |an )?(human|agent|real person)"
    r"|want (a |an )?(human|agent|real person)"
    r"|connect me (to|with) (a |an )?(human|agent)"
    r"|transfer me"
    r"|escalate"
    r"|call customer (service|support|care)"
    r"|contact support"
    r"|real (agent|person|human)"
    r"|live (agent|person|chat)"
    r")\b",
    re.IGNORECASE,
)


class IntentClassifier:
    """
    Zero-shot NLI classifier for detecting explicit escalation requests.

    Handles paraphrases ("I give up, just connect me") and indirect phrasings
    that the regex fallback misses.  Swap to the multilingual model for
    non-English support.

    Args:
        model:     HuggingFace model ID.
                   Default (English):      'cross-encoder/nli-MiniLM2-L6-H768' (~80 MB)
                   Multilingual (~550 MB): 'MoritzLaurer/mDeBERTa-v3-base-mnli-xnli'
        threshold: Minimum entailment score to classify as an escalation request.

    Requires: pip install transformers torch
    """

    _ESCALATION_LABEL = "requesting to speak with a human agent"
    _OTHER_LABEL = "describing a problem or asking a question"
    _HYPOTHESIS_TEMPLATE = "The customer is {}."
    DEFAULT_MODEL = "cross-encoder/nli-MiniLM2-L6-H768"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        threshold: float = 0.80,
    ) -> None:
        try:
            from transformers import pipeline as hf_pipeline
        except ImportError as exc:
            raise ImportError(
                "The 'transformers' package is required for NLI intent classification. "
                "Install with: pip install transformers torch"
            ) from exc

        self._threshold = threshold
        print(f"Loading NLI model '{model}'…", flush=True)
        self._pipe = hf_pipeline(
            "zero-shot-classification",
            model=model,
            device=-1,  # CPU; set to 0 for GPU
        )

    def is_escalation_request(self, text: str) -> tuple[bool, float]:
        """Returns (is_escalation, confidence_score)."""
        result = self._pipe(
            text,
            candidate_labels=[self._ESCALATION_LABEL, self._OTHER_LABEL],
            hypothesis_template=self._HYPOTHESIS_TEMPLATE,
        )
        idx = result["labels"].index(self._ESCALATION_LABEL)
        score = result["scores"][idx]
        return score >= self._threshold, score


# ---------------------------------------------------------------------------
# Frustration scoring
# ---------------------------------------------------------------------------

_TIME_URGENCY = re.compile(
    r"\b(\d+\s*(week|day|month|hour)s?|many times|several times|again and again"
    r"|still (not|haven.t|haven't)|nothing (works|happened)|no (response|reply|answer)"
    r"|never (worked|resolved))\b",
    re.IGNORECASE,
)
_PROFANITY = re.compile(
    r"\b(damn|hell|crap|stupid|useless|awful|terrible|horrible|ridiculous|unacceptable)\b",
    re.IGNORECASE,
)
_REPEATED_CHARS = re.compile(r"(.)\1{3,}")   # "nowwwww", "pleaseeeee"
_THREAT_TO_LEAVE = re.compile(
    r"\b(leave|cancel|quit|close (my )?account|go to (a )?competitor|switch)\b",
    re.IGNORECASE,
)

_HARD_FRUSTRATION_THRESHOLD = 6.0   # short-circuit to escalation
_SOFT_FRUSTRATION_THRESHOLD = 2.5   # surface as LLM hint
_BOT_FAILURE_LOOKBACK = 2   # recent bot messages to scan for knowledge-gap patterns


def _compute_frustration_score(user_messages: list[str]) -> tuple[float, str]:
    """Returns (weighted score, comma-separated signal names)."""
    score = 0.0
    signals: list[str] = []

    for msg in user_messages:
        if _PROFANITY.search(msg):
            score += 2.0
            signals.append("profanity/strong language")
        if _TIME_URGENCY.search(msg):
            score += 1.5
            signals.append("time-urgency phrasing")
        if _REPEATED_CHARS.search(msg):
            score += 1.5
            signals.append("emphatic repeated characters")
        if _THREAT_TO_LEAVE.search(msg):
            score += 2.0
            signals.append("threat to leave/cancel")
        caps_words = [w for w in msg.split() if w.isupper() and len(w) >= 4]
        score += len(caps_words) * 0.5
        if caps_words:
            signals.append("ALL-CAPS words")
        exclamations = msg.count("!")
        score += exclamations * 0.5
        if exclamations:
            signals.append("exclamation marks")

    description = ", ".join(dict.fromkeys(signals)) if signals else "none"
    return score, description


# ---------------------------------------------------------------------------
# Bot-failure and bot-repetition — soft signals only
# ---------------------------------------------------------------------------

_BOT_FAILURE_PATTERNS = re.compile(
    r"(could not find|cannot find|don't have (the )?information"
    r"|no information|unable to find|i don.t know"
    r"|please clarify|please rephrase)",
    re.IGNORECASE,
)


def _count_bot_repetitions(bot_messages: list[str]) -> int:
    """
    Counts bot messages that are near-duplicates of an earlier bot message.
    Two messages are considered duplicates if their word-level Jaccard overlap
    exceeds 60%.  This is a cheap heuristic — the LLM is the authority on
    whether repetition is actually problematic.
    """
    duplicates = 0
    for i, msg_a in enumerate(bot_messages):
        words_a = set(msg_a.lower().split())
        for msg_b in bot_messages[:i]:
            words_b = set(msg_b.lower().split())
            if not words_a or not words_b:
                continue
            overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
            if overlap >= 0.60:
                duplicates += 1
                break
    return duplicates


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def load_intent_classifier(
    model: str = IntentClassifier.DEFAULT_MODEL,
    threshold: float = 0.80,
) -> "IntentClassifier | None":
    """
    Try to instantiate IntentClassifier for NLI-based explicit-request detection.

    Returns None with a warning if 'transformers' is not installed — the rule
    engine then falls back to regex.  Pass --no-nli at the CLI to skip NLI
    entirely and suppress the warning.
    """
    try:
        return IntentClassifier(model=model, threshold=threshold)
    except ImportError:
        print(
            "Warning: 'transformers' not installed — using regex fallback for "
            "explicit-request detection.\n"
            "  Install with: pip install transformers torch\n"
            "  Or pass --no-nli to suppress this warning."
        )
        return None


class RuleEngine:
    """
    Produces hard decisions (evaluate) and soft context signals (collect_signals).

    Args:
        repetition_threshold: Number of near-duplicate bot messages before
                              flagging as a soft repetition signal.
        intent_classifier:    Optional NLI classifier for explicit-request
                              detection.  When None, falls back to regex.
    """

    def __init__(
        self,
        repetition_threshold: int = 2,
        intent_classifier: IntentClassifier | None = None,
    ) -> None:
        self._repetition_threshold = repetition_threshold
        self._intent = intent_classifier

    def evaluate(self, history: list[Message]) -> EscalationDecision | None:
        """
        Hard rules only.  Returns a decision to short-circuit on, or None if
        the conversation should proceed to Tier 2.
        """
        user_msgs = [m.message for m in history if m.role == "user"]

        if decision := self._check_explicit_request(user_msgs):
            return decision

        score, signals = _compute_frustration_score(user_msgs)
        if score >= _HARD_FRUSTRATION_THRESHOLD:
            return EscalationDecision(
                escalate=True,
                tier="rules",
                reason=f"Very high user frustration ({signals}; score={score:.1f}).",
            )

        return None

    def collect_signals(self, history: list[Message]) -> list[str]:
        """
        Soft signals — heuristic observations for LLM context, not hard decisions.
        Returned as human-readable strings so the prompt is self-explanatory.
        """
        user_msgs = [m.message for m in history if m.role == "user"]
        bot_msgs = [m.message for m in history if m.role == "bot"]
        signals: list[str] = []

        for msg in bot_msgs[-_BOT_FAILURE_LOOKBACK:]:
            if _BOT_FAILURE_PATTERNS.search(msg):
                signals.append(
                    "Bot's recent response may indicate a knowledge gap "
                    "(pattern match — verify against the full conversation)."
                )
                break

        repeats = _count_bot_repetitions(bot_msgs)
        if repeats >= self._repetition_threshold:
            signals.append(
                f"Bot has given structurally similar advice {repeats + 1} times "
                f"(repetition heuristic — verify whether the advice actually varied)."
            )

        score, desc = _compute_frustration_score(user_msgs)
        if _SOFT_FRUSTRATION_THRESHOLD <= score < _HARD_FRUSTRATION_THRESHOLD:
            signals.append(
                f"Moderate user frustration detected ({desc}; score={score:.1f})."
            )

        return signals

    def _check_explicit_request(self, user_messages: list[str]) -> EscalationDecision | None:
        """
        Detect explicit human-agent requests.

        NLI and regex are used in combination, not as alternatives.  NLI runs
        first (when configured) to catch paraphrases and indirect phrasing the
        regex misses.  Regex always runs as a safety net — if NLI scores a
        clear pattern like "speak to human" below its threshold, regex still
        fires rather than silently skipping the hard rule.
        """
        for msg in user_messages:
            if self._intent is not None:
                escalate, score = self._intent.is_escalation_request(msg)
                if escalate:
                    return EscalationDecision(
                        escalate=True,
                        tier="rules",
                        reason=f"User requested a human agent (NLI confidence={score:.2f}).",
                    )
            if _EXPLICIT_REQUEST_PATTERNS.search(msg):
                return EscalationDecision(
                    escalate=True,
                    tier="rules",
                    reason="User explicitly requested a human agent.",
                )
        return None
