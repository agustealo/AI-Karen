"""Emergency model recovery must retain previously authorized memory evidence."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.runtime_fallback import build_runtime_fallback


@pytest.mark.asyncio
async def test_emergency_fallback_passes_scoped_memory_to_prompt_path():
    class Runtime:
        def __init__(self):
            self.memory_meta = None

        async def _run_simple(self, request, decision, plan, meter, memory_meta=None):
            self.memory_meta = memory_meta
            assert decision.memory_recall_required
            return "Your name is Alex.", {
                "actual_provider": "ollama-local",
                "actual_model": "deepseek-r1:1.5b",
                "response_source": "model",
            }

    runtime = Runtime()
    fact = {"id": "saved-name", "content": "name: Alex"}
    request = SimpleNamespace(
        context=SimpleNamespace(
            request_id="test-request",
            user_id="test-user",
            tenant_id="test-tenant",
        ),
        metadata={"memory_context": {"recall": [fact]}},
        max_tokens=256,
        preferred_provider="ollama",
        preferred_model="deepseek-r1:1.5b",
    )
    result = await build_runtime_fallback(
        runtime=runtime,
        request=request,
        failure=RuntimeError("primary provider unavailable"),
        correlation_id="test-correlation",
        conversation_id="test-conversation",
        decision=ExecutionDecision(
            memory_recall_required=True,
            memory_top_k=10,
        ),
    )
    assert result is not None
    assert result.answer == "Your name is Alex."
    assert runtime.memory_meta["memory_context"]["recall"] == [fact]
    assert result.metadata.degraded_mode is True
    recovery = result.metadata.extra["recovery"]
    assert recovery["occurred"] is True
    assert recovery["actual_response_healthy"] is True
    assert recovery["provider_identity_verified"] is False
    assert recovery["same_provider_family"] is True
    assert recovery["same_registered_provider"] is True
    assert recovery["provider_switched"] is False
    assert recovery["canonical_requested_provider"] == "ollama-local"
    assert recovery["canonical_actual_provider"] == "ollama-local"
    assert recovery["requested_provider_class"] == "local_openai_endpoint"
    assert recovery["actual_provider_class"] == "local_openai_endpoint"
    assert recovery["model_changed"] is False


def test_recovered_ollama_provider_is_not_claimed_distinct_without_registry_proof():
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatRuntimeMetadata
    # Metadata keeps the requested and actual identifiers separate; display
    # name differences alone do not prove a backend or engine change.
    meta = ChatRuntimeMetadata(
        requested_provider="ollama",
        actual_provider="ollama-local",
        requested_model="deepseek-r1:1.5b",
        actual_model="deepseek-r1:1.5b",
        degraded_mode=True,
    )
    assert meta.requested_provider != meta.actual_provider
    assert meta.requested_model == meta.actual_model


@pytest.mark.asyncio
async def test_emergency_model_fallback_preserves_authorized_prior_user_fact():
    """Provider recovery must not discard conversation evidence or the latest turn."""
    class Runtime:
        async def _run_simple(self, request, decision, plan, meter, memory_meta=None):
            assert request.messages == [
                {"role": "user", "content": "I Jamaican."},
                {"role": "assistant", "content": "Thanks for sharing."},
                {"role": "user", "content": "Where am I from?"},
            ]
            assert request.context.tenant_id == "tenant-a"
            assert request.context.user_id == "user-a"
            return "You said you're Jamaican.", {
                "actual_provider": "ollama-local",
                "actual_model": "deepseek-r1:1.5b",
                "response_source": "model",
            }

    request = SimpleNamespace(
        context=SimpleNamespace(
            request_id="context-fallback-request",
            user_id="user-a",
            tenant_id="tenant-a",
        ),
        messages=[
            {"role": "user", "content": "I Jamaican."},
            {"role": "assistant", "content": "Thanks for sharing."},
            {"role": "user", "content": "Where am I from?"},
        ],
        metadata={"conversation_history_source": "canonical_repository"},
        max_tokens=256,
        preferred_provider="builtin_transformers",
        preferred_model="local-primary",
    )
    result = await build_runtime_fallback(
        runtime=Runtime(),
        request=request,
        failure=RuntimeError("primary provider unavailable"),
        correlation_id="corr-self-description",
        conversation_id="conversation-1",
        decision=ExecutionDecision(memory_recall_required=False),
    )
    assert result is not None
    assert result.answer == "You said you're Jamaican."
    assert result.metadata.degraded_mode is True
