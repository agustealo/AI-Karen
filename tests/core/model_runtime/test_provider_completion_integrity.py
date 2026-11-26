"""Adversarial non-stream transport parity with native SSE receipts."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
)
from ai_karen_engine.core.model_runtime.provider_execution import (
    ProviderExecutionError,
    execute_provider_endpoint,
)


def _endpoint():
    return next(
        endpoint
        for endpoint in BUILTIN_PROVIDER_ENDPOINTS
        if endpoint.provider_id == "ollama-local"
    )


async def _execute(body: dict, *, model: str | None = "qwen3:4b"):
    with patch(
        "ai_karen_engine.core.model_runtime.provider_execution._post_chat_completions",
        return_value=body,
    ) as request:
        result = await execute_provider_endpoint(
            _endpoint(),
            messages=[{"role": "user", "content": "Explain the result"}],
            model=model,
            max_tokens=96,
            temperature=0,
        )
    assert request.call_args.args[2]["stream"] is False
    return result


def _valid() -> dict:
    return {
        "model": "qwen3:4b",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "Observed reply."}}
        ],
    }


@pytest.mark.asyncio
async def test_sync_response_requires_observed_matching_model():
    result = await _execute(_valid())
    assert result.model == "qwen3:4b"
    assert result.text == "Observed reply."


@pytest.mark.parametrize(
    ("replacement", "error"),
    [
        ({"model": ""}, "provider_response_unverified_model"),
        ({"model": None}, "provider_response_unverified_model"),
        ({"model": "other-model"}, "provider_response_requested_model_mismatch"),
        ({"model": {"id": "qwen3:4b"}}, "provider_response_unverified_model"),
        ({"choices": []}, "provider_response_unsupported_choices"),
        ({"choices": [{}, {}]}, "provider_response_unsupported_choices"),
        ({"choices": ["not-a-choice"]}, "provider_response_invalid_choice"),
        ({"choices": [{"index": 1}]}, "provider_response_invalid_choice"),
        (
            {"choices": [{"message": {"role": "system", "content": "Impersonation"}}]},
            "provider_response_non_assistant_role",
        ),
        (
            {"choices": [{"message": {"role": "assistant", "content": ["text"]}}]},
            "provider_response_invalid_content",
        ),
        (
            {"choices": [{"message": {"role": "assistant", "content": {"text": "fake"}}}]},
            "provider_response_invalid_content",
        ),
        (
            {"choices": [{"message": {"role": "assistant", "content": "X", "tool_calls": [{"id": "x"}]}}]},
            "provider_response_tool_call_not_authorized",
        ),
        (
            {"choices": [{"message": {"role": "assistant", "content": "X", "function_call": {"name": "admin"}}}]},
            "provider_response_tool_call_not_authorized",
        ),
        (
            {"choices": [{"message": {"role": "assistant", "content": "X"}, "finish_reason": 123}]},
            "provider_response_invalid_finish_reason",
        ),
    ],
)
@pytest.mark.asyncio
async def test_malformed_or_unverified_sync_completion_fails_closed(replacement, error):
    body = _valid()
    body.update(replacement)
    with pytest.raises(ProviderExecutionError, match=error):
        await _execute(body)


@pytest.mark.asyncio
async def test_sync_unselected_model_still_requires_an_actual_model_receipt():
    result = await _execute(_valid(), model="auto")
    assert result.model == "qwen3:4b"

    missing_model = _valid()
    missing_model.pop("model")
    with pytest.raises(ProviderExecutionError, match="provider_response_unverified_model"):
        await _execute(missing_model, model="auto")


@pytest.mark.asyncio
async def test_sync_metadata_does_not_treat_boolean_usage_as_tokens():
    body = _valid()
    body["usage"] = {"prompt_tokens": True, "completion_tokens": 10}
    result = await _execute(body)
    assert result.usage == {"completion_tokens": 10}


@pytest.mark.asyncio
async def test_sync_token_limit_finish_is_retained_as_observed():
    body = _valid()
    body["choices"][0]["finish_reason"] = "length"
    result = await _execute(body)
    assert result.finish_reason == "length"
