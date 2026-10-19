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
