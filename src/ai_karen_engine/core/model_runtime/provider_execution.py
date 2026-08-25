from __future__ import annotations

"""Core-owned provider execution for canonical runtime endpoints.

This module deliberately depends only on Core contracts and the Python standard
library. Extensions and integrations may register/configure endpoints, but Core
never imports their implementations to execute a model request.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint
from ai_karen_engine.core.model_runtime.runtime_engine import EndpointProtocol, RuntimeEngine


@dataclass(frozen=True)
class ProviderExecutionResult:
    text: str
    model: str | None
    provider_id: str
    runtime_engine: str | None


class ProviderExecutionError(RuntimeError):
    """Raised when a canonical provider endpoint cannot execute a request."""


def _resolve_base_url(endpoint: ProviderEndpoint) -> str | None:
    if endpoint.base_url:
        return endpoint.base_url.rstrip("/")

    env_names = {
        RuntimeEngine.VLLM: ("VLLM_BASE_URL", "KAREN_VLLM_BASE_URL"),
        RuntimeEngine.LMSTUDIO: ("LMSTUDIO_BASE_URL", "LM_STUDIO_BASE_URL"),
        RuntimeEngine.OLLAMA: ("OLLAMA_BASE_URL",),
        RuntimeEngine.LLAMACPP: ("LLAMACPP_BASE_URL", "LLAMA_CPP_BASE_URL"),
    }
    defaults = {
        RuntimeEngine.VLLM: "http://localhost:8000/v1",
        RuntimeEngine.LMSTUDIO: "http://localhost:1234/v1",
        RuntimeEngine.OLLAMA: "http://localhost:11434/v1",
        RuntimeEngine.LLAMACPP: "http://localhost:8080/v1",
    }

    for env_name in env_names.get(endpoint.runtime_engine, ()):
        value = (os.getenv(env_name) or "").strip()
        if value:
            return value.rstrip("/")
    return defaults.get(endpoint.runtime_engine)


def _resolve_api_key(endpoint: ProviderEndpoint) -> str | None:
    if endpoint.api_key_env:
        value = (os.getenv(endpoint.api_key_env) or "").strip()
        return value or None
    return None


def _sync_openai_compatible_request(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, str]],
    model: str | None,
    max_tokens: int,
    temperature: float,
) -> ProviderExecutionResult:
    base_url = _resolve_base_url(endpoint)
    if not base_url:
        raise ProviderExecutionError(
            f"provider_endpoint_missing_base_url:{endpoint.provider_id}"
        )

    request_model = model or endpoint.default_model
    if request_model == "auto":
        request_model = None

    payload: dict[str, Any] = {
        "messages": [dict(message) for message in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if request_model:
        payload["model"] = request_model

    headers = {"Content-Type": "application/json"}
    api_key = _resolve_api_key(endpoint)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=endpoint.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ProviderExecutionError(
            f"provider_http_error:{endpoint.provider_id}:{exc.code}:{detail[:500]}"
        ) from exc
    except URLError as exc:
        raise ProviderExecutionError(
            f"provider_connection_error:{endpoint.provider_id}:{exc.reason}"
        ) from exc

    choices = body.get("choices") or []
    if not choices:
        raise ProviderExecutionError(
            f"provider_empty_choices:{endpoint.provider_id}"
        )

    first = choices[0] or {}
    message = first.get("message") or {}
    text = str(message.get("content") or first.get("text") or "").strip()
    if not text:
        raise ProviderExecutionError(
            f"provider_empty_response:{endpoint.provider_id}"
        )

    actual_model = body.get("model") or request_model
    return ProviderExecutionResult(
        text=text,
        model=str(actual_model) if actual_model else None,
        provider_id=endpoint.provider_id,
        runtime_engine=endpoint.runtime_engine.value,
    )


async def execute_provider_endpoint(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, str]],
    model: str | None,
    max_tokens: int,
    temperature: float,
) -> ProviderExecutionResult:
    """Execute a canonical endpoint without importing extension implementations."""

    if endpoint.protocol is not EndpointProtocol.OPENAI_COMPATIBLE:
        raise ProviderExecutionError(
            f"unsupported_core_provider_protocol:{endpoint.provider_id}:{endpoint.protocol.value}"
        )

    return await asyncio.to_thread(
        _sync_openai_compatible_request,
        endpoint,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
