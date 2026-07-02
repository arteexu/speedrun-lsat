# Copyright: Speedrun LSAT contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pluggable LLM client.

Three implementations:
  * ``StubLLMClient``    - deterministic, returns empty text; always available.
  * ``OpenAILLMClient``  - real HTTP call to an OpenAI-compatible chat endpoint,
                           used only when AI is enabled AND a key is present.
  * ``ScriptedLLMClient`` - returns canned responses; for offline unit tests so
                           CI never touches the network.

Every response carries a named ``source`` (model id or "stub"), which downstream
code requires before showing AI output (the traceability rule). All calls honor
the global off switch (``SPEEDRUN_AI_OFF``, default off).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from speedrun.ai.config import ai_enabled

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass
class LLMResponse:
    text: str
    source: str  # model name, "stub", or an error marker like "openai-error:..."

    @property
    def ok(self) -> bool:
        """A usable response: non-empty text from a real, named source."""
        return bool(self.text.strip()) and not self.source.startswith(
            ("stub", "openai-error")
        )


class LLMClient(ABC):
    @abstractmethod
    def complete(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        ...


class StubLLMClient(LLMClient):
    """Deterministic stub - no network, always available."""

    def complete(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        return LLMResponse(text="", source="stub")


class ScriptedLLMClient(LLMClient):
    """Returns canned responses in order (then repeats the last). For tests only,
    so the AI pipeline can be exercised without any network access."""

    def __init__(self, responses: Iterable[str], *, source: str = "scripted") -> None:
        self._responses = list(responses)
        self._source = source
        self._i = 0

    def complete(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        if not self._responses:
            return LLMResponse(text="", source="stub")
        idx = min(self._i, len(self._responses) - 1)
        self._i += 1
        return LLMResponse(text=self._responses[idx], source=self._source)


class OpenAILLMClient(LLMClient):
    """Real client for an OpenAI-compatible chat completions endpoint.

    Reads the key from ``OPENAI_API_KEY``; model from ``OPENAI_MODEL`` (default
    ``gpt-4o-mini``); base URL from ``OPENAI_BASE_URL`` (so a local/proxy server
    also works). Never raises on network/API failure - returns an empty response
    with an ``openai-error:`` source so callers fall back to the offline path.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        temperature: float = 0.2,
        timeout: float = 30.0,
    ) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        self.base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self._api_key = os.environ.get("OPENAI_API_KEY", "")

    @property
    def source(self) -> str:
        return f"openai:{self.model}"

    def complete(self, prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        if not ai_enabled():
            return LLMResponse(text="", source="stub-disabled")
        if not self._api_key:
            return LLMResponse(text="", source="stub-no-key")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = (
                body.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            )
            return LLMResponse(text=text.strip(), source=self.source)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            return LLMResponse(text="", source=f"openai-error:{type(exc).__name__}")


def default_client() -> LLMClient:
    """The client used in production code paths: a real client when AI is enabled
    (falls back internally if no key), else the deterministic stub."""
    if ai_enabled():
        return OpenAILLMClient()
    return StubLLMClient()
