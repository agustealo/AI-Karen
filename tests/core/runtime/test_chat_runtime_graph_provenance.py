"""Graph response metadata preserves observed provider execution provenance."""

from __future__ import annotations

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)


def _request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        context=ChatExecutionContext(
            user_id="user-1", tenant_id="tenant-1", session_id="session-1",
        ),
        preferred_provider="ollama",
        preferred_model="requested:latest",
    )


def test_graph_top_level_provenance_is_preserved() -> None:
    observed = {
        "actual_provider": "vllm",
        "actual_model": "served-model",
        "runtime_engine": "vllm",
        "response_source": "model",
        "fallback_level": 2,
        "fallback_reason": "ollama_unavailable",
        "degraded_mode": True,
        "degradation_reason": "provider_fallback",
    }
    metadata = ChatRuntime._normalize_graph_meta(None, observed, _request())
    for key, value in observed.items():
        assert metadata[key] == value
    assert metadata["requested_provider"] == "ollama"
    assert metadata["requested_model"] == "requested:latest"


def test_graph_nested_observations_override_top_level_and_preserve_zero() -> None:
    metadata = ChatRuntime._normalize_graph_meta(
        None,
        {
            "actual_provider": "stale-provider",
            "actual_model": "stale-model",
            "fallback_level": 3,
            "degraded_mode": True,
            "llm_metadata": {
                "actual_provider": "ollama",
                "actual_model": "correct-model",
                "fallback_level": 0,
                "degraded_mode": False,
            },
        },
        _request(),
    )
    assert metadata["actual_provider"] == "ollama"
    assert metadata["actual_model"] == "correct-model"
    assert metadata["fallback_level"] == 0
    assert metadata["degraded_mode"] is False


def test_graph_never_invents_actual_provider_from_request() -> None:
    metadata = ChatRuntime._normalize_graph_meta(None, {}, _request())
    assert metadata["requested_provider"] == "ollama"
    assert metadata["requested_model"] == "requested:latest"
    assert metadata["actual_provider"] is None
    assert metadata["actual_model"] is None
    assert metadata["fallback_level"] == 0
    assert metadata["degraded_mode"] is False
