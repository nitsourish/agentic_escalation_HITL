"""
LLM configuration loaded from a .env file (or plain environment variables).

Supported providers: "gemini" (default, free tier) and "openai".
See .env.example for all available settings.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    api_key: str
    model: str
    confidence_threshold: float


_PROVIDER_DEFAULTS = {
    "gemini": ("GEMINI_API_KEY", "gemini-2.0-flash-lite", "GEMINI_MODEL"),
    "openai": ("OPENAI_API_KEY", "gpt-4o-mini", "OPENAI_MODEL"),
}


def load_llm_config() -> LLMConfig:
    """
    Build an LLMConfig from environment variables.

    Raises EnvironmentError if the provider is unsupported or the API key is missing.
    """
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()

    if provider not in _PROVIDER_DEFAULTS:
        supported = ", ".join(f"'{p}'" for p in _PROVIDER_DEFAULTS)
        raise EnvironmentError(
            f"Unknown LLM_PROVIDER={provider!r}. Supported: {supported}."
        )

    key_var, default_model, model_var = _PROVIDER_DEFAULTS[provider]
    api_key = os.environ.get(key_var, "")
    if not api_key:
        raise EnvironmentError(
            f"API key required for provider '{provider}'. "
            f"Set {key_var} in .env or the environment."
        )

    model = os.environ.get(model_var, default_model)
    threshold = float(os.environ.get("LLM_CONFIDENCE_THRESHOLD", "0.7"))
    return LLMConfig(provider=provider, api_key=api_key, model=model,
                     confidence_threshold=threshold)
