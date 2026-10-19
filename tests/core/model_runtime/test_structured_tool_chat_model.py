"""Real LangChain adapter delegates provider execution exclusively to Karen."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint, ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import StructuredChatResult
from ai_karen_engine.core.model_runtime.structured_tool_chat_model import (
    KarenGovernedChatModel, _message_to_wire, build_medusa_deepagents_model,
)


def endpoint():
    return ProviderEndpoint(
        provider_id="ollama-local",
        display_name="Ollama",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:11434/v1",
        capabilities=("chat_completion", "tools"),
    )


def model():
    return KarenGovernedChatModel(
        endpoint=endpoint(),
        selected_model="model-with-tools",
    )


@pytest.mark.asyncio
async def test_langchain_model_round_trips_real_tool_call(monkeypatch):
    execute = AsyncMock(return_value=StructuredChatResult(
        message={
            "content": "",
            "tool_calls": [{
                "id": "tc-1", "name": "karen_approved_tool",
                "args": {"tool_name": "web_search", "parameters": {"query": "test"}},
            }],
        },
        provider_id="ollama-local",
        model="model-with-tools",
        runtime_engine="ollama",
        finish_reason="tool_calls",
        usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
    ))
    monkeypatch.setattr(
        "ai_karen_engine.core.model_runtime.structured_tool_chat_model."
        "execute_structured_provider_endpoint", execute,
    )

    from langchain_core.tools import tool

    @tool
    def karen_approved_tool(tool_name: str, parameters: dict) -> str:
        """Invoke governed Karen tool by name and parameter object."""
        return "not executed by adapter"

    wrapped = model().bind_tools([karen_approved_tool])
    assert wrapped.tool_schemas[0]["function"]["name"] == "karen_approved_tool"
    result = await wrapped.ainvoke([HumanMessage(content="Research this")])
    assert result.tool_calls[0]["id"] == "tc-1"
    assert result.tool_calls[0]["args"]["tool_name"] == "web_search"
    assert result.response_metadata["actual_provider"] == "ollama-local"
    assert execute.await_args.kwargs["model"] == "model-with-tools"
    assert execute.await_args.kwargs["tools"] == wrapped.tool_schemas


def test_message_converter_preserves_tool_call_pairing():
    call = AIMessage(
        content="",
        tool_calls=[{"name": "karen_approved_tool", "args": {"query": "x"}, "id": "tc-1"}],
    )
    payload = _message_to_wire(call)
    assert payload["tool_calls"][0]["id"] == "tc-1"
    assert _message_to_wire(ToolMessage(content="found", tool_call_id="tc-1")) == {
        "role": "tool", "tool_call_id": "tc-1", "content": "found",
    }


def test_model_resolver_rejects_unregistered_user_model(monkeypatch):
    from ai_karen_engine.core.model_runtime import model_manager

    mock_registry = SimpleNamespace(
        get_provider_endpoint=lambda _: endpoint(),
        get_registered_models=lambda *_args, **_kwargs: ["approved"],
        is_model_available=lambda *_args, **_kwargs: False,
    )
    mock_manager = SimpleNamespace(
        select_provider=lambda *args, **kwargs: SimpleNamespace(provider_id="ollama-local"),
        registry=mock_registry,
        _provider_is_healthy=lambda *_args: True,
    )
    monkeypatch.setattr(model_manager, "get_model_manager", lambda: mock_manager)

    class Plan:
        provider_constraints = {}
        budget = SimpleNamespace(max_output_tokens=200)
        def matches_execution_scope(self, **kwargs):
            return True

    execution = SimpleNamespace(
        authorized_plan=Plan(),
        user_id="u-1",
        tenant_id="t-1",
        session_id="s-1",
        policy_decision_id="policy-1",
        preferred_provider="ollama-local",
        preferred_model="unverified",
    )
    with pytest.raises(RuntimeError, match="inventory"):
        build_medusa_deepagents_model(SimpleNamespace(agent_id="researcher"), execution)


def _model_selection_execution(*, explicit_model=None, signals=None):
    from ai_karen_engine.core.runtime.contracts import (
        AuthorizedExecutionPlan, ExecutionTopology,
    )

    plan = AuthorizedExecutionPlan(
        execution_id="req-1",
        policy_decision_id="policy-1",
        authorized_user_id="u-1",
        authorized_tenant_id="t-1",
        authorized_session_id="s-1",
        topology=ExecutionTopology.MULTI_AGENT,
    )
    return SimpleNamespace(
        authorized_plan=plan,
        user_id="u-1", tenant_id="t-1", session_id="s-1",
        policy_decision_id="policy-1",
        preferred_provider="ollama-local",
        preferred_model=explicit_model,
        learning_task_type="research",
        learned_model_signals=signals,
    )


def _mock_canonical_model_manager(monkeypatch):
    from ai_karen_engine.core.model_runtime import model_manager
    from dataclasses import replace

    registry = SimpleNamespace(
        get_provider_endpoint=lambda _: replace(
            endpoint(), default_model="model-a"
        ),
        get_registered_models=lambda *_args, **_kwargs: ["model-a", "model-b"],
        is_model_available=lambda _provider, name, healthy_only: (
            name in {"model-a", "model-b"} and healthy_only is True
        ),
    )
    manager = SimpleNamespace(
        select_provider=lambda *args, **kwargs: SimpleNamespace(
            provider_id="ollama-local", model="model-a",
        ),
        registry=registry,
        _provider_is_healthy=lambda *_args: True,
    )
    manager.choose_tool_model_from_learning = lambda **kwargs: (
        model_manager.ModelManager.choose_tool_model_from_learning(
            manager, **kwargs
        )
    )
    monkeypatch.setattr(model_manager, "get_model_manager", lambda: manager)
    return manager


def test_auto_model_uses_scoped_intelligence_signals_and_canonical_manager(monkeypatch):
    from ai_karen_engine.core.intelligence.ml.model_outcome_signals import (
        MODEL_SIGNAL_VERSION, ModelOperationalProfile, ScopedModelSignals,
    )

    manager = _mock_canonical_model_manager(monkeypatch)
    signals = ScopedModelSignals(
        tenant_id="t-1", user_id="u-1", task_type="research",
        version=MODEL_SIGNAL_VERSION, status="ready",
        profiles=(
            ModelOperationalProfile("ollama-local", "model-a", 20, 2, 800),
            ModelOperationalProfile("ollama-local", "model-b", 20, 19, 300),
        ),
    )
    result = build_medusa_deepagents_model(
        SimpleNamespace(agent_id="researcher"),
        _model_selection_execution(signals=signals),
    )
    assert result.selected_model == "model-b"
    assert result.selection_source == "learning_operational_reliability_v1"
    assert result.learning_signal_version == MODEL_SIGNAL_VERSION
    assert result.endpoint.provider_id == "ollama-local"


def test_user_override_wins_even_if_learning_prefers_other_model(monkeypatch):
    from ai_karen_engine.core.intelligence.ml.model_outcome_signals import (
        MODEL_SIGNAL_VERSION, ModelOperationalProfile, ScopedModelSignals,
    )

    manager = _mock_canonical_model_manager(monkeypatch)
    manager.choose_tool_model_from_learning = lambda **kwargs: (
        (_ for _ in ()).throw(AssertionError("explicit model must skip learning"))
    )
    signals = ScopedModelSignals(
        "t-1", "u-1", "research", MODEL_SIGNAL_VERSION, "ready",
        (
            ModelOperationalProfile("ollama-local", "model-a", 20, 2, 800),
            ModelOperationalProfile("ollama-local", "model-b", 20, 19, 300),
        ),
    )
    result = build_medusa_deepagents_model(
        SimpleNamespace(agent_id="researcher"),
        _model_selection_execution(explicit_model="model-a", signals=signals),
    )
    assert result.selected_model == "model-a"
    assert result.selection_source == "explicit_runtime_or_user"


def test_no_evidence_retains_registered_default_and_cannot_invent_model(monkeypatch):
    manager = _mock_canonical_model_manager(monkeypatch)
    result = build_medusa_deepagents_model(
        SimpleNamespace(agent_id="researcher"),
        _model_selection_execution(signals=None),
    )
    assert result.selected_model == "model-a"
    assert result.selection_source == "baseline_no_learning"
    manager.registry.get_registered_models = lambda *args, **kwargs: ["model-b"]
    with pytest.raises(RuntimeError, match="Default tool model"):
        build_medusa_deepagents_model(
            SimpleNamespace(agent_id="researcher"),
            _model_selection_execution(signals=None),
        )


def test_learned_signal_wrong_tenant_cannot_select_foreign_model(monkeypatch):
    from ai_karen_engine.core.intelligence.ml.model_outcome_signals import (
        MODEL_SIGNAL_VERSION, ModelOperationalProfile, ScopedModelSignals,
    )
    _mock_canonical_model_manager(monkeypatch)
    signals = ScopedModelSignals(
        "other-tenant", "u-1", "research", MODEL_SIGNAL_VERSION, "ready",
        (
            ModelOperationalProfile("ollama-local", "model-a", 20, 2, 800),
            ModelOperationalProfile("ollama-local", "model-b", 20, 19, 300),
        ),
    )
    result = build_medusa_deepagents_model(
        SimpleNamespace(agent_id="researcher"),
        _model_selection_execution(signals=signals),
    )
    assert result.selected_model == "model-a"
    assert result.selection_source == "baseline_scope_mismatch"
