"""Adapters that speak plain HTTP: OpenAI-compatible endpoints, Azure OpenAI and Ollama."""

from __future__ import annotations

import json
from typing import Iterator

import httpx

from ..tokens import count_messages, count_tokens
from .base import (
    FINISH_LENGTH,
    FINISH_OTHER,
    FINISH_REFUSAL,
    FINISH_STOP,
    ChatRequest,
    ChatResult,
    Provider,
    ProviderError,
)

_FINISH = {"stop": FINISH_STOP, "length": FINISH_LENGTH, "content_filter": FINISH_REFUSAL}


def _timeout(seconds: float) -> httpx.Timeout:
    return httpx.Timeout(seconds, connect=10.0)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        body = response.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"HTTP {response.status_code}: {body}", status=response.status_code)


class OpenAICompatProvider(Provider):
    """Any endpoint that implements POST {base_url}/chat/completions with SSE streaming:
    OpenAI, OpenRouter, Groq, DeepSeek, Together, Gemini's OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, api_key: str, timeout_s: float, max_tokens_field: str = "max_tokens"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_tokens_field = max_tokens_field

    def _url(self, req: ChatRequest) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _body(self, req: ChatRequest) -> dict:
        body: dict = {"model": req.model_id, "messages": req.messages, "stream": True}
        if req.params.get("stream_usage", True):
            body["stream_options"] = {"include_usage": True}
        body[req.params.get("max_tokens_field", self.max_tokens_field)] = req.max_tokens
        if req.temperature is not None:
            body["temperature"] = req.temperature
        body.update(req.params.get("request", {}))
        return body

    def stream(self, req: ChatRequest) -> Iterator[str | ChatResult]:
        parts: list[str] = []
        usage: dict = {}
        finish = FINISH_OTHER
        served = None
        try:
            with httpx.Client(timeout=_timeout(self.timeout_s)) as client:
                with client.stream("POST", self._url(req), headers=self._headers(), json=self._body(req)) as r:
                    _raise_for_status(r)
                    for line in r.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("error"):
                            raise ProviderError(f"stream error: {str(chunk['error'])[:300]}")
                        served = chunk.get("model") or served
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        for choice in chunk.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content")
                            if piece:
                                parts.append(piece)
                                yield piece
                            if choice.get("finish_reason"):
                                finish = _FINISH.get(choice["finish_reason"], FINISH_OTHER)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        text = "".join(parts)
        # OpenAI-style automatic prefix caching reports the cached part here.
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        yield ChatResult(
            text=text,
            in_tokens=int(usage.get("prompt_tokens") or count_messages(req.messages)),
            out_tokens=int(usage.get("completion_tokens") or count_tokens(text)),
            finish_reason=finish,
            served_model=served,
            cache_read_tokens=cached,
        )


class AzureOpenAIProvider(OpenAICompatProvider):
    """Azure OpenAI: the registry's model_id is the DEPLOYMENT name, the credential
    carries the resource endpoint and API version, and auth uses the `api-key` header."""

    def __init__(self, endpoint: str, api_key: str, api_version: str, timeout_s: float, max_tokens_field: str):
        super().__init__(endpoint, api_key, timeout_s, max_tokens_field)
        self.api_version = api_version

    def _url(self, req: ChatRequest) -> str:
        return (
            f"{self.base_url}/openai/deployments/{req.model_id}/chat/completions"
            f"?api-version={self.api_version}"
        )

    def _headers(self) -> dict:
        return {"api-key": self.api_key, "Content-Type": "application/json"}

    def _body(self, req: ChatRequest) -> dict:
        body = super()._body(req)
        body.pop("model", None)  # the deployment in the URL selects the model
        return body


class OllamaProvider(Provider):
    """Local inference through Ollama's native /api/chat endpoint."""

    def __init__(self, base_url: str, timeout_s: float):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def stream(self, req: ChatRequest) -> Iterator[str | ChatResult]:
        options = {"num_predict": req.max_tokens, **req.params.get("options", {})}
        if req.temperature is not None:
            options["temperature"] = req.temperature
        body = {"model": req.model_id, "messages": req.messages, "stream": True, "options": options}
        parts: list[str] = []
        final: dict = {}
        try:
            with httpx.Client(timeout=_timeout(self.timeout_s)) as client:
                with client.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                    _raise_for_status(r)
                    for line in r.iter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise ProviderError(f"ollama error: {str(chunk['error'])[:300]}")
                        piece = (chunk.get("message") or {}).get("content")
                        if piece:
                            parts.append(piece)
                            yield piece
                        if chunk.get("done"):
                            final = chunk
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        text = "".join(parts)
        yield ChatResult(
            text=text,
            in_tokens=int(final.get("prompt_eval_count") or count_messages(req.messages)),
            out_tokens=int(final.get("eval_count") or count_tokens(text)),
            finish_reason=FINISH_LENGTH if final.get("done_reason") == "length" else FINISH_STOP,
            served_model=final.get("model"),
        )

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                return client.get(f"{self.base_url}/api/tags").status_code == 200
        except httpx.HTTPError:
            return False
