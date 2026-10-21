"""Canonical tool-call transport retains structured provider results.

All HTTP is mocked. Tests validate actual OpenAI-compatible wire shape rather
than accepting fake text-as-tool responses.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import (
    ProviderExecutionError,
    _sync_structured_chat_request,
    _sync_openai_compatible_request,
)
from ai_karen_engine.core.model_runtime.runtime_engine import RuntimeEngine


def endpoint() -> ProviderEndpoint:
    return ProviderEndpoint(
        provider_id="local-tools",
        display_name="Local Tools",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:12345/v1",
        runtime_engine=RuntimeEngine.CUSTOM,
        capabilities=("chat_completion", "tools"),
        default_model="verified-local-model",
    )


def reply(*, content="", calls=None, model="verified-local-model") -> dict:
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": calls or [],
            },
            "finish_reason": "tool_calls" if calls else "stop",
        }],
        "model": model,
        "usage": {"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17},
    }


TOOL = {
    "type": "function",
    "function": {
        "name": "karen_approved_tool",
        "description": "Governed tool",
        "parameters": {"type": "object", "properties": {}},
    },
}
CALL = {
    "id": "toolcall-1",
    "type": "function",
    "function": {
        "name": "karen_approved_tool",
        "arguments": '{"tool_name":"web_search","parameters":{"query":"topic"}}',
    },
}


def execute():
    return _sync_structured_chat_request(
        endpoint(),
        messages=[{"role": "user", "content": "Search"}],
        model="verified-local-model",
        tools=[TOOL],
        max_tokens=256,
        temperature=0.0,
    )


def test_structured_call_preserves_real_tool_identity_and_args():
    with patch(
        "ai_karen_engine.core.model_runtime.provider_execution._post_chat_completions",
        return_value=reply(calls=[CALL]),
    ) as transport:
        result = execute()
    payload = transport.call_args.args[2]
    assert payload["model"] == "verified-local-model"
    assert payload["tools"] == [TOOL]
    assert result.message["tool_calls"][0]["id"] == "toolcall-1"
    assert result.message["tool_calls"][0]["args"]["tool_name"] == "web_search"
    assert result.usage["total_tokens"] == 17
    assert result.provider_id == "local-tools"


@pytest.mark.parametrize("calls,error", [
    ([{"id": "call-1", "function": {"name": "unregistered", "arguments": "{}"}}],
     "unknown_tool"),
    ([{"id": "call-1", "function": {"name": "karen_approved_tool", "arguments": "{broken"}}],
     "invalid_arguments"),
    ([{"id": "call-1", "function": {"name": "karen_approved_tool", "arguments": "[]"}}],
     "arguments_not_object"),
])
def test_structured_response_rejects_unsupported_or_invalid_calls(calls, error):
    with patch(
        "ai_karen_engine.core.model_runtime.provider_execution._post_chat_completions",
        return_value=reply(calls=calls),
    ):
        with pytest.raises(ProviderExecutionError, match=error):
            execute()


def test_structured_response_rejects_unexpected_model_swap():
    with patch(
        "ai_karen_engine.core.model_runtime.provider_execution._post_chat_completions",
        return_value=reply(content="Hello", model="another-provider-model"),
    ):
        with pytest.raises(ProviderExecutionError, match="model_changed"):
            execute()


def test_existing_text_only_provider_path_still_uses_same_transport():
    with patch(
        "ai_karen_engine.core.model_runtime.provider_execution._post_chat_completions",
        return_value=reply(content="Unchanged answer"),
    ):
        result = _sync_openai_compatible_request(
            endpoint(),
            messages=[{"role": "user", "content": "Hello"}],
            model="verified-local-model",
            max_tokens=100,
            temperature=0.0,
        )
    assert result.text == "Unchanged answer"


def test_tool_execution_never_defaults_to_unspecified_model():
    with pytest.raises(ProviderExecutionError, match="model_identity"):
        _sync_structured_chat_request(
            endpoint(),
            messages=[{"role": "user", "content": "Research"}],
            model="auto",
            tools=[TOOL],
            max_tokens=100,
            temperature=0.0,
        )
