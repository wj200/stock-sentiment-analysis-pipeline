"""Pluggable LLM provider for the event explainer (Anthropic by default).

The explainer is low-volume (events, not per-post), so a cheap, fast model is
the right default for price-move explanations, with a stronger model available
for the harder macro reasoning. Both are configurable; if no API key is set the
provider is None and the explainer degrades to non-LLM output (never fabricates).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from config import settings

logger = logging.getLogger(__name__)

# Anthropic model IDs per task tier (overridable via LLM_MODEL). Bare IDs — no
# date suffix. price -> cheap/fast; macro -> stronger reasoning.
DEFAULT_MODELS = {
    "price": "claude-haiku-4-5",
    "macro": "claude-sonnet-5",
}


class LLMRefusal(RuntimeError):
    """Raised when the model declines to answer (safety stop)."""


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, *, model: str, max_tokens: int = 300) -> str:
        """Return the model's plain-text reply, or raise on error/refusal."""


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, timeout: int):
        import anthropic  # lazy import so the package imports without the SDK

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def complete(self, system: str, user: str, *, model: str, max_tokens: int = 300) -> str:
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if getattr(resp, "stop_reason", None) == "refusal":
            raise LLMRefusal("model refused to answer")
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()


def get_provider() -> LLMProvider | None:
    """Build the configured provider, or None if it can't run (no key)."""
    if settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicProvider(settings.ANTHROPIC_API_KEY, settings.LLM_TIMEOUT_SECONDS)
    logger.info(
        "LLM explainer disabled (no ANTHROPIC_API_KEY / provider unset); "
        "events will send with degraded, non-LLM explanations."
    )
    return None


def model_for(kind: str) -> str:
    return settings.LLM_MODEL or DEFAULT_MODELS.get(kind, DEFAULT_MODELS["price"])
