"""LLM providers behind one tiny interface, so they can be swapped or mocked.

Any object with a `generate(system_prompt, messages) -> str` method works.
`messages` uses the common chat format: [{"role": "user"|"assistant", "content": str}].

Most providers (OpenAI, Gemini, Grok, Qwen, Kimi, DeepSeek, Groq, OpenRouter,
Ollama, ...) expose an OpenAI-compatible `/chat/completions` endpoint, so one
generic client covers all of them; only the base URL, API key and model differ.
Anthropic is served by its native SDK.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_PROVIDER, PROVIDERS, Provider

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    def generate(self, system_prompt: str, messages: list[dict]) -> str: ...


class OpenAICompatibleClient:
    """Calls any OpenAI-compatible `/chat/completions` endpoint over plain HTTP."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        max_tokens: int | None = None,
        timeout: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._max_tokens = max_tokens
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http_client or httpx.Client(timeout=timeout)

    def generate(self, system_prompt: str, messages: list[dict]) -> str:
        payload: dict = {
            "model": self._model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens

        response = self._http.post(self._url, headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""


class AnthropicClient:
    """Claude via the official Anthropic SDK."""

    def __init__(self, model: str, api_key: str | None = None, max_tokens: int = 1024) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def generate(self, system_prompt: str, messages: list[dict]) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return "".join(block.text for block in response.content if block.type == "text")


class MockLLM:
    """Deterministic stand-in for tests and offline runs.

    Records every call in `self.calls`, so tests can assert on exactly
    what context was sent to the model.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, system_prompt: str, messages: list[dict]) -> str:
        self.calls.append({"system": system_prompt, "messages": messages})
        return f"[mock reply] You asked: {messages[-1]['content']}"


def get_llm_client() -> LLMClient:
    """Build the client described by the environment (see config.py)."""
    if LLM_PROVIDER == "mock":
        logger.warning("LLM provider=mock model=none (set LLM_PROVIDER and LLM_MODEL for real responses)")
        return MockLLM()

    if not LLM_MODEL:
        raise ValueError(f"LLM_MODEL must be set when LLM_PROVIDER={LLM_PROVIDER}")

    if LLM_PROVIDER == "anthropic":
        logger.info("LLM provider=anthropic model=%s", LLM_MODEL)
        return AnthropicClient(model=LLM_MODEL, api_key=LLM_API_KEY)

    if LLM_PROVIDER == "custom":
        preset = Provider(base_url="", api_key_env=None)
    elif LLM_PROVIDER in PROVIDERS:
        preset = PROVIDERS[LLM_PROVIDER]
    else:
        known = ", ".join(["mock", "anthropic", "custom", *PROVIDERS])
        raise ValueError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Choose one of: {known}")

    base_url = LLM_BASE_URL or preset.base_url
    if not base_url:
        raise ValueError("LLM_BASE_URL must be set when LLM_PROVIDER=custom")

    api_key = LLM_API_KEY or (os.getenv(preset.api_key_env) if preset.api_key_env else None)
    if preset.api_key_env and not api_key:
        raise ValueError(f"Set LLM_API_KEY or {preset.api_key_env} for LLM_PROVIDER={LLM_PROVIDER}")

    logger.info("LLM provider=%s model=%s base_url=%s", LLM_PROVIDER, LLM_MODEL, base_url)
    return OpenAICompatibleClient(base_url=base_url, model=LLM_MODEL, api_key=api_key)
