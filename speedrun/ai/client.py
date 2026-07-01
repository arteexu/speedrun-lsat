# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pluggable LLM client. Stub implementation works with AI_OFF=true."""
from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass

from speedrun.ai.config import ai_enabled


@dataclass
class LLMResponse:
    text: str
    source: str  # model name or "stub"


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        ...


class StubLLMClient(LLMClient):
    """Deterministic stub — no network, always available."""

    def complete(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        return LLMResponse(text="", source="stub")


class OpenAILLMClient(LLMClient):
    """Optional real client; only used when AI is enabled and API key is set."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        import os

        self.model = model
        self._api_key = os.environ.get("OPENAI_API_KEY", "")

    def complete(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        if not ai_enabled():
            return LLMResponse(text="", source="stub-disabled")
        if not self._api_key:
            return LLMResponse(text="", source="stub-no-key")
        # Real call would go here; kept stubbed until keys are provided.
        return LLMResponse(text="", source=f"openai:{self.model}-stub")


def default_client() -> LLMClient:
    if ai_enabled():
        return OpenAILLMClient()
    return StubLLMClient()
