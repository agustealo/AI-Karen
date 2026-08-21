"""
Ollama LLM Provider Implementation.

Keeps Karen's Ollama runtime on the same provider registry path used by the
rest of chat execution so settings/model discovery and generation stay aligned.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Union
from urllib.parse import urlparse

from ai_karen_engine.integrations.llm_utils import (
    GenerationFailed,
    LLMProviderBase,
    record_llm_metric,
)

logger = logging.getLogger("kari.ollama_provider")


class OllamaProvider(LLMProviderBase):
    """Ollama HTTP provider for host or container runtimes."""

    def __init__(
        self,
        model: str = "",
        base_url: Optional[str] = None,
        timeout: int = 60,
        max_retries: int = 2,
    ):
        self.provider_name = "ollama"
        self.model = str(model or "").strip()
        from ai_karen_engine.config.llm_provider_config import DEFAULT_OLLAMA_BASE_URL

        self.base_url = self._normalize_base_url(
            base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
        )
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)
        self.initialization_error: Optional[str] = None
        self.last_usage: Dict[str, Any] = {}

        try:
            import requests  # type: ignore

            self._requests = requests
        except ImportError:
            self._requests = None
            self.initialization_error = "requests library required for Ollama provider"

    def _normalize_base_url(self, base_url: str) -> str:
        from ai_karen_engine.config.llm_provider_config import DEFAULT_OLLAMA_BASE_URL

        normalized = str(base_url or "").strip().rstrip("/")
        if not normalized:
            normalized = DEFAULT_OLLAMA_BASE_URL
        if not normalized.endswith("/api"):
            normalized = f"{normalized}/api"
        return normalized

    def _endpoint(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _build_messages(
        self, prompt: Union[str, Sequence[Dict[str, Any]]], kwargs: Dict[str, Any]
    ) -> Optional[List[Dict[str, str]]]:
        raw_messages = kwargs.get("messages")
        messages_source: Union[Sequence[Dict[str, Any]], None] = None
        if isinstance(prompt, list):
            messages_source = prompt
        elif isinstance(raw_messages, list):
            messages_source = raw_messages

        if not messages_source:
            return None

        messages: List[Dict[str, str]] = []
        for raw in messages_source:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "user").strip() or "user"
            content = str(raw.get("content") or "").strip()
            if not content:
                continue
            messages.append({"role": role, "content": content})
        return messages or None

    def _request(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        if self._requests is None:
            raise GenerationFailed(self.initialization_error or "requests unavailable")

        last_error: Optional[Exception] = None
        for attempt in range(1, max(self.max_retries, 1) + 1):
            try:
                if payload is None:
                    response = self._requests.get(
                        self._endpoint(path), timeout=self.timeout
                    )
                else:
                    response = self._requests.post(
                        self._endpoint(path),
                        json=payload,
                        timeout=self.timeout,
                    )
                response.raise_for_status()
                return response.json()
            except self._requests.exceptions.RequestException as exc:  # type: ignore[attr-defined]
                last_error = exc
                if attempt >= max(self.max_retries, 1):
                    break
                time.sleep(min(0.5 * attempt, 1.5))

        parsed = urlparse(self.base_url)
        host_hint = parsed.netloc or self.base_url
        raise GenerationFailed(f"Ollama request failed for {host_hint}: {last_error}")

    def _record_usage(self, result: Dict[str, Any]) -> None:
        prompt_tokens = int(result.get("prompt_eval_count") or 0)
        completion_tokens = int(result.get("eval_count") or 0)
        total_duration_ns = int(result.get("total_duration") or 0)
        total_duration_s = (
            (total_duration_ns / 1_000_000_000) if total_duration_ns else None
        )
        tokens_per_second = None
        if total_duration_s and completion_tokens > 0:
            tokens_per_second = completion_tokens / total_duration_s

        self.last_usage = {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_seconds": total_duration_s,
            "tokens_per_second": tokens_per_second,
        }

    def generate_text(
        self, prompt: Union[str, Sequence[Dict[str, Any]]], **kwargs
    ) -> str:
        if self.initialization_error:
            raise GenerationFailed(self.initialization_error)
        if not self.model:
            raise GenerationFailed("No Ollama model selected")

        t0 = time.time()
        try:
            max_tokens = kwargs.get("max_tokens")
            temperature = kwargs.get("temperature")

            messages = self._build_messages(prompt, kwargs)
            options = {
                key: value
                for key, value in {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": kwargs.get("top_p"),
                    "top_k": kwargs.get("top_k"),
                    "repeat_penalty": kwargs.get("repeat_penalty"),
                    "stop": kwargs.get("stop"),
                }.items()
                if value is not None
            }

            if messages is not None:
                payload: Dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                }
                if options:
                    payload["options"] = options
                result = self._request("/chat", payload)
                self._record_usage(result)
                message = result.get("message") or {}
                content = str(message.get("content") or "").strip()
                
                # Fallback to thinking field if content is empty (common for reasoning models)
                if not content and message.get("thinking"):
                    content = str(message.get("thinking")).strip()
            else:
                payload = {
                    "model": self.model,
                    "prompt": str(prompt),
                    "stream": False,
                }
                if options:
                    payload["options"] = options
                result = self._request("/generate", payload)
                self._record_usage(result)
                content = str(result.get("response") or "").strip()
                
                # Fallback to thinking field if response is empty
                if not content and result.get("thinking"):
                    content = str(result.get("thinking")).strip()

            record_llm_metric("generate_text", time.time() - t0, True, "ollama")
            if not content:
                raise GenerationFailed("Ollama returned an empty response")
            return content
        except Exception as exc:
            record_llm_metric(
                "generate_text", time.time() - t0, False, "ollama", error=str(exc)
            )
            if isinstance(exc, GenerationFailed):
                raise
            raise GenerationFailed(f"Ollama generation failed: {exc}")

    def embed(self, text: Union[str, List[str]], **kwargs) -> List[float]:
        raise NotImplementedError("Ollama embeddings are not implemented in Karen")

    def get_models(self) -> List[str]:
        result = self._request("/tags")
        models = result.get("models") or []
        resolved: List[str] = []
        for item in models:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("model") or "").strip()
                if name:
                    resolved.append(name)
            elif item:
                resolved.append(str(item))
        return resolved

    def get_provider_info(self) -> Dict[str, Any]:
        try:
            models = self.get_models()
        except Exception:
            models = []
        return {
            "name": "ollama",
            "model": self.model,
            "base_url": self.base_url,
            "available_models": models,
            "supports_streaming": True,
            "supports_embeddings": False,
            "initialization_error": self.initialization_error,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }

    def health_check(self) -> Dict[str, Any]:
        if self.initialization_error:
            return {
                "status": "unhealthy",
                "error": self.initialization_error,
                "provider": "ollama",
            }
        try:
            start = time.time()
            models = self.get_models()
            return {
                "status": "healthy",
                "provider": "ollama",
                "response_time": time.time() - start,
                "models_found": len(models),
                "sample_models": models[:5],
            }
        except Exception as exc:
            return {"status": "unhealthy", "provider": "ollama", "error": str(exc)}
