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
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint
from ai_karen_engine.core.model_runtime.runtime_engine import EndpointProtocol, RuntimeEngine


@dataclass(frozen=True)
class ProviderExecutionResult:
    text: str
    model: str | None
    provider_id: str
    runtime_engine: str | None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None


class ProviderExecutionError(RuntimeError):
    """Raised when a canonical provider endpoint cannot execute a request."""


def _inherit_registered_api_path(
    runtime_url: str,
    registered_url: str | None,
) -> str:
    """Preserve the canonical API path when a runtime override only changes host.

    Environment overrides commonly point at a Docker/host gateway origin.
    Built-in OpenAI-compatible endpoints register their required API prefix
    (for example /v1). Treat a host-only override as a host replacement
    rather than silently dropping that prefix. Explicit override paths remain
    authoritative.
    """
    normalized = runtime_url.rstrip("/")
    if not registered_url:
        return normalized

    runtime_parts = urlsplit(normalized)
    if runtime_parts.path not in {"", "/"}:
        return normalized

    registered_parts = urlsplit(registered_url.rstrip("/"))
    registered_path = registered_parts.path.rstrip("/")
    if not registered_path:
        return normalized

    return urlunsplit(
        (
            runtime_parts.scheme,
            runtime_parts.netloc,
            registered_path,
            runtime_parts.query,
            runtime_parts.fragment,
        )
    ).rstrip("/")


def _resolve_base_url(endpoint: ProviderEndpoint) -> str | None:
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
            return _inherit_registered_api_path(value, endpoint.base_url)

    if endpoint.base_url:
        return endpoint.base_url.rstrip("/")
    return defaults.get(endpoint.runtime_engine)


def _resolve_api_key(endpoint: ProviderEndpoint) -> str | None:
    if endpoint.api_key_env:
        value = (os.getenv(endpoint.api_key_env) or "").strip()
        return value or None
    return None


def _post_chat_completions(
    endpoint: ProviderEndpoint,
    base_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Single OpenAI-compatible HTTP transport for text and tool-call models."""
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
        # Do not echo a potentially sensitive provider response into telemetry.
        raise ProviderExecutionError(
            f"provider_http_error:{endpoint.provider_id}:{exc.code}"
        ) from exc
    except URLError as exc:
        raise ProviderExecutionError(
            f"provider_connection_error:{endpoint.provider_id}"
        ) from exc
    if not isinstance(body, dict):
        raise ProviderExecutionError("provider_invalid_response_object")
    return body


@dataclass(frozen=True)
class StructuredChatResult:
    """Canonical structured output, retaining provider-emitted tool calls."""

    message: dict[str, Any]
    provider_id: str
    model: str
    runtime_engine: str
    finish_reason: str | None
    usage: dict[str, int]


def _sync_structured_chat_request(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, Any]],
    model: str,
    tools: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float,
) -> StructuredChatResult:
    """Emit only explicitly registered tools, never model-side fake calls."""
    if endpoint.protocol is not EndpointProtocol.OPENAI_COMPATIBLE:
        raise ProviderExecutionError("tool_call_protocol_unsupported")
    if not endpoint.enabled or "tools" not in set(endpoint.capabilities):
        raise ProviderExecutionError("tool_call_provider_not_eligible")
    if not model or model == "auto":
        raise ProviderExecutionError("tool_call_model_identity_required")
    base_url = _resolve_base_url(endpoint)
    if not base_url:
        raise ProviderExecutionError("tool_call_endpoint_unavailable")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [dict(message) for message in messages],
        "tools": [dict(tool) for tool in tools],
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = _post_chat_completions(endpoint, base_url, payload)
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderExecutionError("tool_call_response_has_no_choices")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderExecutionError("tool_call_response_invalid_choice")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ProviderExecutionError("tool_call_response_invalid_assistant")
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        raise ProviderExecutionError("tool_call_response_invalid_calls")
    verified_calls: list[dict[str, Any]] = []
    allowed = {
        tool.get("function", {}).get("name")
        for tool in tools if isinstance(tool.get("function"), dict)
    }
    for call in tool_calls:
        if not isinstance(call, dict):
            raise ProviderExecutionError("tool_call_response_invalid_call")
        function = call.get("function")
        if (
            not isinstance(function, dict)
            or not isinstance(call.get("id"), str)
            or not call["id"]
            or function.get("name") not in allowed
            or not isinstance(function.get("arguments"), str)
        ):
            raise ProviderExecutionError("tool_call_response_unknown_tool")
        try:
            arguments = json.loads(function["arguments"])
        except (ValueError, TypeError) as exc:
            raise ProviderExecutionError("tool_call_response_invalid_arguments") from exc
        if not isinstance(arguments, dict):
            raise ProviderExecutionError("tool_call_response_arguments_not_object")
        verified_calls.append({
            "id": call["id"],
            "name": function["name"],
            "args": arguments,
        })
    content = message.get("content") or ""
    if not isinstance(content, str):
        raise ProviderExecutionError("tool_call_response_invalid_content")
    if not content.strip() and not verified_calls:
        raise ProviderExecutionError("tool_call_response_empty")
    usage: dict[str, int] = {}
    if isinstance(body.get("usage"), dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = body["usage"].get(key)
            if isinstance(value, int) and value >= 0:
                usage[key] = value
    actual_model = str(body.get("model") or model)
    if actual_model != model:
        raise ProviderExecutionError("tool_call_model_changed_unexpectedly")
    return StructuredChatResult(
        message={"content": content, "tool_calls": verified_calls},
        provider_id=endpoint.provider_id,
        model=actual_model,
        runtime_engine=endpoint.runtime_engine.value,
        finish_reason=str(choice.get("finish_reason") or "") or None,
        usage=usage,
    )


async def execute_structured_provider_endpoint(
    endpoint: ProviderEndpoint,
    *,
    messages: Sequence[Mapping[str, Any]],
    model: str,
    tools: Sequence[Mapping[str, Any]],
    max_tokens: int,
    temperature: float,
) -> StructuredChatResult:
    """Canonical provider transport used by governed LangChain adapters."""
    return await asyncio.to_thread(
        _sync_structured_chat_request,
        endpoint,
        messages=messages,
        model=model,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
    )


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

    body = _post_chat_completions(endpoint, base_url, payload)

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
    raw_usage = body.get("usage")
    usage = None
    if isinstance(raw_usage, dict):
        usage = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = raw_usage.get(key)
            if isinstance(value, int) and value >= 0:
                usage[key] = value
        if not usage:
            usage = None

    return ProviderExecutionResult(
        text=text,
        model=str(actual_model) if actual_model else None,
        provider_id=endpoint.provider_id,
        runtime_engine=endpoint.runtime_engine.value,
        usage=usage,
        finish_reason=(str(first.get("finish_reason")).strip() or None)
        if first.get("finish_reason") is not None else None,
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
