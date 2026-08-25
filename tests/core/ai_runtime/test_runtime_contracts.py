from ai_karen_engine.core.ai_runtime.capability_types import CapabilityId
from ai_karen_engine.core.ai_runtime.runtime_contracts import (
    CapabilityAttempt,
    CapabilityExecutionResult,
    CapabilityRequest,
)


def test_capability_request_has_no_provider_requirement() -> None:
    request = CapabilityRequest(
        capability_id=CapabilityId.CHAT_GENERATE,
        input={"messages": [{"role": "user", "content": "hello"}]},
        requested_target="core:transformers",
        preferred_model="gpt2",
        correlation_id="corr-1",
    )

    assert request.capability_id == CapabilityId.CHAT_GENERATE
    assert request.requested_target == "core:transformers"
    assert request.preferred_model == "gpt2"


def test_capability_execution_result_supports_core_runtime() -> None:
    result = CapabilityExecutionResult(
        capability_id=CapabilityId.CHAT_GENERATE,
        output="hello",
        requested_target="core:transformers",
        resolved_target="core:transformers",
        execution_layer="core",
        runtime_engine="transformers",
        requested_model="gpt2",
        actual_model="gpt2",
        response_source="core_runtime",
        correlation_id="corr-1",
    )

    assert result.provider_id is None
    assert result.runtime_engine == "transformers"
    assert result.response_source == "core_runtime"
    assert result.degraded_mode is False


def test_capability_execution_result_supports_provider_runtime() -> None:
    attempt = CapabilityAttempt(
        target="provider:gemini",
        execution_layer="provider",
        status="success",
        provider_id="gemini",
        model="gemini-2.5-flash",
        latency_ms=100.0,
    )

    result = CapabilityExecutionResult(
        capability_id=CapabilityId.CHAT_GENERATE,
        output="hello",
        requested_target="provider:gemini",
        resolved_target="provider:gemini",
        execution_layer="provider",
        provider_id="gemini",
        requested_model="gemini-2.5-flash",
        actual_model="gemini-2.5-flash",
        response_source="provider_runtime",
        attempts=(attempt,),
        correlation_id="corr-2",
    )

    assert result.provider_id == "gemini"
    assert result.runtime_engine is None
    assert result.attempts[0].status == "success"