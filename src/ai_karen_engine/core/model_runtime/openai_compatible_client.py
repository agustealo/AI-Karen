from __future__ import annotations

"""Small Core-native client for OpenAI-compatible model servers.

This is protocol infrastructure, not a provider integration. It speaks the
OpenAI-compatible HTTP contract used by vLLM, LM Studio, Ollama, and llama.cpp
without importing provider SDKs or integration registries.
"""

import json
from typing import Any, Dict, Iterator, List, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai_karen_engine.core.model_runtime.provider_contracts import (
    EmbeddingFailed,
    GenerationFailed,
    ProviderNotAvailable,
)


class OpenAICompatibleRuntimeClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        provider_name: str = "openai_compatible",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.provider_name = provider_name
        self.display_name = provider_name
        self.timeout_seconds = timeout_seconds

    def _request(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GenerationFailed(
                f"{self.provider_name} HTTP {exc.code}: {detail[:500]}"
            ) from exc
        except URLError as exc:
            raise ProviderNotAvailable(
                f"{self.provider_name} unavailable: {exc.reason}"
            ) from exc

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        messages = kwargs.pop("messages", None) or [{"role": "user", "content": prompt}]
        payload: Dict[str, Any] = {
            "messages": messages,
            "max_tokens": int(kwargs.pop("max_tokens", 512)),
            "temperature": float(kwargs.pop("temperature", 0.7)),
            "stream": False,
        }
        model = kwargs.pop("model", None) or self.model
        if model and model != "auto":
            payload["model"] = model
        payload.update(kwargs)
        body = self._request("/chat/completions", payload)
        choices = body.get("choices") or []
        if not choices:
            raise GenerationFailed(f"{self.provider_name} returned no choices")
        first = choices[0] or {}
        message = first.get("message") or {}
        text = str(message.get("content") or first.get("text") or "").strip()
        if not text:
            raise GenerationFailed(f"{self.provider_name} returned empty text")
        if body.get("model"):
            self.model = str(body["model"])
        return text

    def generate_response(self, prompt: str, **kwargs: Any) -> str:
        return self.generate_text(prompt, **kwargs)

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        # Core keeps one execution implementation for beta; streaming transport can
        # chunk this text while native SSE support is added behind the same contract.
        text = self.generate_text(prompt, **kwargs)
        if text:
            yield text

    def embed(
        self,
        text: Union[str, List[str]],
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]:
        payload: Dict[str, Any] = {"input": text}
        model = kwargs.pop("model", None) or self.model
        if model and model != "auto":
            payload["model"] = model
        payload.update(kwargs)
        try:
            body = self._request("/embeddings", payload)
        except (GenerationFailed, ProviderNotAvailable) as exc:
            raise EmbeddingFailed(str(exc)) from exc
        data = body.get("data") or []
        vectors = [item.get("embedding") for item in data if item.get("embedding") is not None]
        if not vectors:
            raise EmbeddingFailed(f"{self.provider_name} returned no embeddings")
        return vectors[0] if isinstance(text, str) else vectors

    def health_check(self) -> Dict[str, Any]:
        request = Request(f"{self.base_url}/models", method="GET")
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urlopen(request, timeout=min(self.timeout_seconds, 10.0)) as response:
                return {
                    "status": "healthy" if response.status < 400 else "unhealthy",
                    "provider": self.provider_name,
                }
        except Exception as exc:
            return {"status": "unhealthy", "provider": self.provider_name, "error": str(exc)}

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "name": self.provider_name,
            "provider": self.provider_name,
            "model": self.model,
            "base_url": self.base_url,
        }
