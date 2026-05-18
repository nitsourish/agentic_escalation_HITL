"""
Tier 2: LLM-based escalation classifier.

Supports Google Gemini and OpenAI via a shared base class.
Use create_classifier(config) to get the right implementation for the
configured provider.
"""

import json
import re
from abc import ABC, abstractmethod

from .config import LLMConfig
from .models import EscalationDecision, Message
from .prompts import SYSTEM_PROMPT, build_prompt

_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


class BaseLLMClassifier(ABC):
    """
    Contract for LLM-backed escalation classifiers.
    Subclasses implement _call_api(); response parsing is shared here.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    def classify(self, history: list[Message], signals: list[str] | None = None) -> EscalationDecision:
        prompt = build_prompt(history, signals=signals)
        try:
            text = self._call_api(prompt)
            return self._parse_response(text)
        except (OSError, ValueError, RuntimeError) as exc:
            return EscalationDecision(
                escalate=False,
                tier="llm",
                reason=f"LLM call failed ({type(exc).__name__}); defaulting to no-escalation.",
                confidence=0.0,
            )

    @abstractmethod
    def _call_api(self, prompt: str) -> str:
        """Send prompt to the provider and return the raw response text."""

    def _parse_response(self, text: str) -> EscalationDecision:
        match = _JSON_RE.search(text)
        if not match:
            return EscalationDecision(
                escalate=False,
                tier="llm",
                reason="Could not parse LLM response; defaulting to no-escalation.",
                confidence=0.0,
            )
        try:
            data = json.loads(match.group())
            escalate_raw = bool(data.get("escalate", False))
            confidence = float(data.get("confidence", 0.5))
            reason = str(data.get("reason", "LLM decision."))
            escalate = escalate_raw and confidence >= self._config.confidence_threshold
            return EscalationDecision(escalate=escalate, tier="llm",
                                      reason=reason, confidence=confidence)
        except (json.JSONDecodeError, ValueError, KeyError):
            return EscalationDecision(
                escalate=False,
                tier="llm",
                reason="Malformed LLM response; defaulting to no-escalation.",
                confidence=0.0,
            )


class GeminiClassifier(BaseLLMClassifier):
    """Escalation classifier backed by Google Gemini."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        from google import genai
        from google.genai import types
        self._client = genai.Client(api_key=config.api_key)
        self._gen_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.0,
            max_output_tokens=128,
        )

    def _call_api(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._config.model,
            contents=prompt,
            config=self._gen_config,
        )
        return response.text


class OpenAIClassifier(BaseLLMClassifier):
    """Escalation classifier backed by OpenAI."""

    def __init__(self, config: LLMConfig) -> None:
        super().__init__(config)
        from openai import OpenAI
        self._client = OpenAI(api_key=config.api_key)

    def _call_api(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=128,
        )
        return response.choices[0].message.content


def create_classifier(config: LLMConfig) -> BaseLLMClassifier:
    """Factory: return the right classifier for the configured provider."""
    if config.provider == "gemini":
        return GeminiClassifier(config)
    if config.provider == "openai":
        return OpenAIClassifier(config)
    raise ValueError(f"Unsupported provider: {config.provider!r}")
