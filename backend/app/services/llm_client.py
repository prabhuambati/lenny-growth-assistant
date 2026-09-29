"""LLM provider abstraction. One interface, swappable implementations — this
is the file that satisfies the 'flexible LLM configuration' requirement.

Fallback behavior (per architecture.md): if the configured cloud provider is
unreachable or misconfigured, we log a warning and fall back to Ollama for
that request rather than failing outright. If Ollama itself is unavailable,
we raise ProviderUnavailableError so the API returns a clear error.
"""

import logging
import time
from typing import Protocol

import httpx

from app.config import Settings

log = logging.getLogger("llm_client")


class Message(dict):
    """{'role': 'user'|'assistant'|'system', 'content': str}"""


class ProviderUnavailableError(Exception):
    def __init__(self, provider: str, detail: str):
        self.provider = provider
        self.detail = detail
        super().__init__(f"{provider} unavailable: {detail}")


class LLMClient(Protocol):
    name: str

    async def generate(self, messages: list[Message], **kwargs) -> str: ...
    async def is_reachable(self) -> bool: ...


class OllamaClient:
    """Default, mandatory-for-demo local provider."""

    name = "ollama"

    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/")
        self.model = model

    async def is_reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.host}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def generate(self, messages: list[Message], **kwargs) -> str:
        timeout = kwargs.get("timeout", 60.0)
        started_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self.host}/api/chat",
                    json={
                        "model": self.model,
                        "messages": list(messages),
                        "stream": False,
                        **({"options": kwargs["options"]} if "options" in kwargs else {}),
                        **({"keep_alive": kwargs["keep_alive"]} if "keep_alive" in kwargs else {}),
                    },
                )
                resp.raise_for_status()
                content = resp.json()["message"]["content"]
                log.info(
                    "Ollama generation succeeded model=%s timeout=%.1fs elapsed=%.2fs input_messages=%d output_chars=%d",
                    self.model,
                    timeout,
                    time.monotonic() - started_at,
                    len(messages),
                    len(content),
                )
                return content
        except httpx.HTTPError as exc:
            elapsed = time.monotonic() - started_at
            response = getattr(exc, "response", None)
            status = response.status_code if response is not None else None
            response_body = response.text[:500] if response is not None else ""
            detail = str(exc) or f"{type(exc).__name__} after {elapsed:.2f}s"
            log.error(
                "Ollama generation failed model=%s timeout=%.1fs elapsed=%.2fs exception=%s status=%s body=%s",
                self.model,
                timeout,
                elapsed,
                type(exc).__name__,
                status,
                response_body,
            )
            raise ProviderUnavailableError("ollama", detail) from exc


class AnthropicClient:
    """Optional cloud provider."""

    name = "anthropic"

    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    async def is_reachable(self) -> bool:
        return bool(self.api_key)

    async def generate(self, messages: list[Message], **kwargs) -> str:
        if not self.api_key:
            raise ProviderUnavailableError("anthropic", "ANTHROPIC_API_KEY not set")
        try:
            import anthropic  # local import: optional dependency

            client = anthropic.AsyncAnthropic(api_key=self.api_key)
            system = next((m["content"] for m in messages if m["role"] == "system"), None)
            convo = [m for m in messages if m["role"] != "system"]
            resp = await client.messages.create(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", 2000),
                system=system,
                messages=convo,
            )
            return resp.content[0].text
        except Exception as exc:  # noqa: BLE001 — surface as provider error, don't leak internals
            raise ProviderUnavailableError("anthropic", str(exc)) from exc


class OpenAIClient:
    """Optional cloud provider."""

    name = "openai"

    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    async def is_reachable(self) -> bool:
        return bool(self.api_key)

    async def generate(self, messages: list[Message], **kwargs) -> str:
        if not self.api_key:
            raise ProviderUnavailableError("openai", "OPENAI_API_KEY not set")
        try:
            from openai import AsyncOpenAI  # local import: optional dependency

            client = AsyncOpenAI(api_key=self.api_key)
            resp = await client.chat.completions.create(
                model=self.model,
                messages=list(messages),
                max_tokens=kwargs.get("max_tokens", 2000),
            )
            return resp.choices[0].message.content
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError("openai", str(exc)) from exc


class GeminiClient:
    """Optional Google Gemini REST adapter; no request is made without a key."""

    name = "gemini"

    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    async def is_reachable(self) -> bool:
        return bool(self.api_key)

    async def generate(self, messages: list[Message], **kwargs) -> str:
        if not self.api_key:
            raise ProviderUnavailableError("gemini", "GEMINI_API_KEY is not set")

        system_messages = [message["content"] for message in messages if message["role"] == "system"]
        contents = [
            {
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
            for message in messages
            if message["role"] != "system"
        ]
        payload = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": kwargs.get("max_tokens", 2000)},
        }
        if system_messages:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_messages)}]}

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        try:
            async with httpx.AsyncClient(timeout=kwargs.get("timeout", 60.0)) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                body = response.json()
                return body["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            detail = str(exc) or "Gemini returned no usable response"
            raise ProviderUnavailableError("gemini", detail) from exc


def build_client(provider: str, settings: Settings) -> LLMClient:
    if provider == "ollama":
        return OllamaClient(settings.ollama_host, settings.ollama_model)
    if provider == "anthropic":
        return AnthropicClient(settings.anthropic_api_key, settings.anthropic_model)
    if provider == "openai":
        return OpenAIClient(settings.openai_api_key, settings.openai_model)
    if provider == "gemini":
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)
    raise ValueError(f"Unknown provider: {provider}")


async def generate_with_fallback(
    provider: str, messages: list[Message], settings: Settings, **kwargs
) -> tuple[str, str]:
    """Try the configured provider; if it's a cloud provider and unavailable,
    fall back to Ollama and return which provider actually served the request.
    If Ollama (the mandatory path) is down, this raises."""
    client = build_client(provider, settings)

    if provider == "gemini":
        return await client.generate(messages, **kwargs), provider

    if provider != "ollama":
        try:
            text = await client.generate(messages, **kwargs)
            return text, provider
        except ProviderUnavailableError as exc:
            log.warning("Provider %s unavailable (%s) — falling back to ollama", provider, exc.detail)

    ollama = OllamaClient(settings.ollama_host, settings.ollama_model)
    text = await ollama.generate(messages, **kwargs)  # lets ProviderUnavailableError propagate if Ollama is also down
    return text, "ollama"
