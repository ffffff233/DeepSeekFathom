from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Iterator

import httpx

from .config import Settings
from .messages import Message


# Provider format normalization. Users may save any of the aliases on the left;
# they collapse to one of the canonical families on the right.
FORMAT_ALIASES = {
    "deepseek": "deepseek",
    "openai": "openai",
    "openai-compatible": "openai",
    "openai-chat": "openai",
    "openai-responses": "openai-responses",
    "responses": "openai-responses",
    "gemini": "gemini",
    "google": "gemini",
    "google-gemini": "gemini",
    "anthropic": "anthropic",
    "claude": "anthropic",
}

# Default host for each family, used when the saved base_url is empty or still points
# at the generic DeepSeek default while a different family is selected.
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openai-responses": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com",
    "anthropic": "https://api.anthropic.com",
}

_DEEPSEEK_DEFAULT = "https://api.deepseek.com"

# Anthropic / Gemini reject the very large max_tokens the DeepSeek thinking modes
# request (up to 384000). Cap output so those providers don't 400.
_OUTPUT_CAP = 32000


def normalize_format(value: str | None) -> str:
    return FORMAT_ALIASES.get((value or "deepseek").strip().lower(), "deepseek")


class DeepSeekClient:
    """OpenAI/DeepSeek/Anthropic/Gemini chat client.

    The class name is kept for backwards compatibility (cli.py, desktop/app.py, and the
    test-suite reference it), but requests are dispatched by ``settings.provider_format``.
    """

    def __init__(self, settings: Settings, timeout: float | None = None):
        self.settings = settings
        self.timeout = timeout or settings.request_timeout
        self._client: httpx.Client | None = None
        self.format = normalize_format(getattr(settings, "provider_format", "deepseek"))

    # ---- shared http ----
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _require_key(self) -> str:
        if not self.settings.api_key:
            raise RuntimeError("API key is not set")
        return self.settings.api_key

    def _base_url(self) -> str:
        base = (self.settings.base_url or "").rstrip("/")
        # Fall back to the family default when the base is empty or still the DeepSeek
        # default but the selected family is something else.
        if self.format in DEFAULT_BASE_URLS and (not base or base == _DEEPSEEK_DEFAULT):
            return DEFAULT_BASE_URLS[self.format]
        if not base:
            return _DEEPSEEK_DEFAULT
        return base

    def _output_tokens(self) -> int:
        tokens = int(self.settings.max_tokens or 8192)
        # Only DeepSeek accepts the very large thinking budgets (up to 384000). OpenAI /
        # Gemini / Anthropic reject them, so cap output for every other family.
        if self.format != "deepseek":
            return max(1, min(tokens, _OUTPUT_CAP))
        return tokens

    # ---- public API ----
    def chat(self, messages: Iterable[Message]) -> str:
        messages = list(messages)
        if self.format == "anthropic":
            return self._anthropic_chat(messages, stream=False)  # type: ignore[return-value]
        if self.format == "gemini":
            return self._gemini_chat(messages, stream=False)  # type: ignore[return-value]
        if self.format == "openai-responses":
            return self._responses_chat(messages, stream=False)  # type: ignore[return-value]
        return self._openai_chat(messages, stream=False)  # type: ignore[return-value]

    def stream_chat(self, messages: Iterable[Message]) -> Iterator[str]:
        messages = list(messages)
        if self.format == "anthropic":
            return self._anthropic_chat(messages, stream=True)  # type: ignore[return-value]
        if self.format == "gemini":
            return self._gemini_chat(messages, stream=True)  # type: ignore[return-value]
        if self.format == "openai-responses":
            return self._responses_chat(messages, stream=True)  # type: ignore[return-value]
        return self._openai_chat(messages, stream=True)  # type: ignore[return-value]

    def models(self) -> list[str]:
        if self.format == "anthropic":
            return self._anthropic_models()
        if self.format == "gemini":
            return self._gemini_models()
        # openai + openai-responses share GET /models
        return self._openai_models()

    def ping(self) -> dict[str, object]:
        models = self.models()
        return {
            "base_url": self._base_url(),
            "model": self.settings.model,
            "provider_format": self.format,
            "model_available": self.settings.model in models,
            "models": models,
        }

    # ---- OpenAI / DeepSeek ----
    def _openai_chat(self, messages: list[Message], *, stream: bool):
        self._require_key()
        payload = {
            "model": self.settings.model,
            "messages": [message.to_api() for message in messages],
            "temperature": 0.2,
            "max_tokens": self._output_tokens(),
            "stream": stream,
        }
        apply_thinking_payload(payload, self.settings)
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url()}/chat/completions"
        if not stream:
            response = self._http().post(url, headers=headers, json=payload)
            raise_for_status_with_body(response)
            data = response.json()
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                compact = json.dumps(data, ensure_ascii=False)[:1000]
                raise RuntimeError(f"Unexpected response: {compact}") from exc
        return self._openai_stream(url, headers, payload)

    def _openai_stream(self, url: str, headers: dict, payload: dict) -> Iterator[str]:
        with self._http().stream("POST", url, headers=headers, json=payload) as response:
            raise_for_status_with_body(response)
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                chunk = line.removeprefix("data: ").strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                    delta = data["choices"][0].get("delta", {})
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                content = delta.get("content")
                if content:
                    yield content

    def _openai_models(self) -> list[str]:
        self._require_key()
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        url = f"{self._base_url()}/models"
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        data = response.json()
        return [item["id"] for item in data.get("data", []) if isinstance(item, dict) and "id" in item]

    # ---- OpenAI Responses API (newest format) ----
    def _responses_chat(self, messages: list[Message], *, stream: bool):
        self._require_key()
        system, turns = split_system(messages)
        payload: dict = {
            "model": self.settings.model,
            "input": [{"role": m.role, "content": m.content} for m in turns],
            "max_output_tokens": self._output_tokens(),
            "stream": stream,
        }
        if system:
            payload["instructions"] = system
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url()}/responses"
        if not stream:
            response = self._http().post(url, headers=headers, json=payload)
            raise_for_status_with_body(response)
            data = response.json()
            text = data.get("output_text")
            if isinstance(text, str) and text:
                return text
            parts: list[str] = []
            for item in data.get("output", []) if isinstance(data, dict) else []:
                if isinstance(item, dict) and item.get("type") == "message":
                    for block in item.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "output_text":
                            parts.append(block.get("text", ""))
            if parts:
                return "".join(parts)
            compact = json.dumps(data, ensure_ascii=False)[:1000]
            raise RuntimeError(f"Unexpected Responses payload: {compact}")
        return self._responses_stream(url, headers, payload)

    def _responses_stream(self, url: str, headers: dict, payload: dict) -> Iterator[str]:
        with self._http().stream("POST", url, headers=headers, json=payload) as response:
            raise_for_status_with_body(response)
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "response.output_text.delta":
                    delta = data.get("delta")
                    if delta:
                        yield delta

    # ---- Anthropic / Claude ----
    def _anthropic_chat(self, messages: list[Message], *, stream: bool):
        self._require_key()
        system, turns = split_system(messages)
        payload: dict = {
            "model": self.settings.model,
            "max_tokens": self._output_tokens(),
            "messages": [{"role": m.role, "content": m.content} for m in turns],
            "stream": stream,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self.settings.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        url = f"{self._base_url()}/v1/messages"
        if not stream:
            response = self._http().post(url, headers=headers, json=payload)
            raise_for_status_with_body(response)
            data = response.json()
            try:
                parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
                return "".join(parts)
            except (AttributeError, TypeError) as exc:
                compact = json.dumps(data, ensure_ascii=False)[:1000]
                raise RuntimeError(f"Unexpected Anthropic response: {compact}") from exc
        return self._anthropic_stream(url, headers, payload)

    def _anthropic_stream(self, url: str, headers: dict, payload: dict) -> Iterator[str]:
        with self._http().stream("POST", url, headers=headers, json=payload) as response:
            raise_for_status_with_body(response)
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if data.get("type") != "content_block_delta":
                    continue
                delta = data.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]

    def _anthropic_models(self) -> list[str]:
        self._require_key()
        headers = {"x-api-key": self.settings.api_key or "", "anthropic-version": "2023-06-01"}
        url = f"{self._base_url()}/v1/models"
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        data = response.json()
        return [item["id"] for item in data.get("data", []) if isinstance(item, dict) and "id" in item]

    # ---- Google Gemini ----
    def _gemini_chat(self, messages: list[Message], *, stream: bool):
        key = self._require_key()
        system, turns = split_system(messages)
        payload: dict = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in turns
            ],
            "generationConfig": {"maxOutputTokens": self._output_tokens(), "temperature": 0.2},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        base = f"{self._base_url()}/v1beta/models/{self.settings.model}"
        headers = {"Content-Type": "application/json"}
        if not stream:
            url = f"{base}:generateContent?key={key}"
            response = self._http().post(url, headers=headers, json=payload)
            raise_for_status_with_body(response)
            data = response.json()
            try:
                parts = data["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts)
            except (KeyError, IndexError, TypeError) as exc:
                compact = json.dumps(data, ensure_ascii=False)[:1000]
                raise RuntimeError(f"Unexpected Gemini response: {compact}") from exc
        url = f"{base}:streamGenerateContent?alt=sse&key={key}"
        return self._gemini_stream(url, headers, payload)

    def _gemini_stream(self, url: str, headers: dict, payload: dict) -> Iterator[str]:
        with self._http().stream("POST", url, headers=headers, json=payload) as response:
            raise_for_status_with_body(response)
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if not chunk:
                    continue
                try:
                    data = json.loads(chunk)
                    parts = data["candidates"][0]["content"]["parts"]
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                for part in parts:
                    text = part.get("text")
                    if text:
                        yield text

    def _gemini_models(self) -> list[str]:
        key = self._require_key()
        url = f"{self._base_url()}/v1beta/models?key={key}"
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
        data = response.json()
        names = []
        for item in data.get("models", []):
            name = item.get("name", "") if isinstance(item, dict) else ""
            if name:
                names.append(name.removeprefix("models/"))
        return names


def split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    """Pull system messages into a single top-level string; keep the rest as turns.

    Anthropic and Gemini take the system prompt out-of-band rather than as a message
    with role ``system``.
    """
    system_parts: list[str] = []
    turns: list[Message] = []
    for message in messages:
        if message.role == "system":
            if message.content:
                system_parts.append(message.content)
        else:
            turns.append(message)
    return "\n\n".join(system_parts), turns


def raise_for_status_with_body(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:1000]
        raise RuntimeError(f"API error {response.status_code}: {body}") from exc


def apply_thinking_payload(payload: dict, settings: Settings) -> None:
    if normalize_format(getattr(settings, "provider_format", "deepseek")) != "deepseek":
        return
    payload["thinking"] = {"type": "enabled" if settings.thinking_enabled else "disabled"}
    if settings.thinking_enabled and settings.reasoning_effort:
        payload["reasoning_effort"] = settings.reasoning_effort
