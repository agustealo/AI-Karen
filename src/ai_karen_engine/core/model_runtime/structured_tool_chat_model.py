"""LangChain message adapter backed by Karen's canonical provider transport.

This is a format adapter, not a model router. The trusted Runtime/Medusa
composition selects a healthy registered endpoint and explicit model before
constructing it. The actual HTTP call remains in core.model_runtime.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint
from ai_karen_engine.core.model_runtime.provider_execution import (
    execute_structured_provider_endpoint,
)


def _message_to_wire(message: BaseMessage) -> dict[str, Any]:
    content = message.content
    if not isinstance(content, str):
        raise TypeError("Governed tool model currently accepts text-only messages")
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": content}
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": content}
    if isinstance(message, ToolMessage):
        if not message.tool_call_id:
            raise ValueError("A tool result must identify its originating call")
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": content,
        }
    if isinstance(message, AIMessage):
        payload: dict[str, Any] = {"role": "assistant", "content": content}
        if message.tool_calls:
            calls: list[dict[str, Any]] = []
            for call in message.tool_calls:
                if not call.get("id") or not isinstance(call.get("args"), dict):
                    raise ValueError("Malformed tool call in LangChain history")
                calls.append({
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": __import__("json").dumps(call["args"]),
                    },
                })
            payload["tool_calls"] = calls
        return payload
    raise TypeError("Unsupported chat role for governed provider model")


class KarenGovernedChatModel(BaseChatModel):
    """Actual tool-call-capable model using the canonical endpoint, not an SDK router."""

    endpoint: ProviderEndpoint = Field(exclude=True)
    selected_model: str
    selection_source: str = "canonical_registry"
    learning_signal_status: str = "not_consulted"
    learning_signal_version: str = ""
    tool_schemas: list[dict[str, Any]] = Field(default_factory=list)
    selected_temperature: float = 0.0
    selected_max_tokens: int = 1024

    @property
    def _llm_type(self) -> str:
        return "karen-governed-chat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "provider": self.endpoint.provider_id,
            "model": self.selected_model,
            "engine": self.endpoint.runtime_engine.value,
        }

    def bind_tools(
        self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any
    ) -> "KarenGovernedChatModel":
        if kwargs:
            raise ValueError("Unsupported ungoverned tool binding options")
        if tool_choice not in (None, "auto"):
            raise ValueError("Governed model only supports automatic tool selection")
        schemas = [convert_to_openai_tool(tool) for tool in tools]
        for schema in schemas:
            if schema.get("type") != "function" or not schema.get("function", {}).get("name"):
                raise ValueError("Invalid governed function tool schema")
        return self.model_copy(update={"tool_schemas": schemas})

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del run_manager
        if stop or kwargs:
            raise ValueError("Unsupported model request options bypass canonical policy")
        result = await execute_structured_provider_endpoint(
            self.endpoint,
            messages=[_message_to_wire(message) for message in messages],
            model=self.selected_model,
            tools=self.tool_schemas,
            max_tokens=self.selected_max_tokens,
            temperature=self.selected_temperature,
        )
        response = AIMessage(
            content=result.message["content"],
            tool_calls=result.message["tool_calls"],
            response_metadata={
                "actual_provider": result.provider_id,
                "actual_model": result.model,
                "runtime_engine": result.runtime_engine,
                "finish_reason": result.finish_reason,
            },
            usage_metadata={
                "input_tokens": result.usage.get("prompt_tokens", 0),
                "output_tokens": result.usage.get("completion_tokens", 0),
                "total_tokens": result.usage.get("total_tokens", 0),
            },
        )
        return ChatResult(generations=[ChatGeneration(message=response)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        # LangGraph's async execution uses _agenerate. Synchronous use is
        # supported outside an active event loop for framework compatibility.
        return asyncio.run(
            self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        )


def build_medusa_deepagents_model(registration: Any, execution: Any) -> KarenGovernedChatModel:
    """Runtime-owned provider selection with strict capability and model matching."""
    from ai_karen_engine.core.model_runtime.model_manager import get_model_manager

    plan = execution.authorized_plan
    if not plan.matches_execution_scope(
        user_id=execution.user_id,
        tenant_id=execution.tenant_id,
        session_id=execution.session_id,
        policy_decision_id=execution.policy_decision_id,
    ):
        raise PermissionError("Governed tool model principal scope mismatch")
    policy_provider = plan.provider_constraints.get("provider")
    policy_model = plan.provider_constraints.get("model")
    requested_provider = execution.preferred_provider or policy_provider
    explicit_model = execution.preferred_model or policy_model
    if policy_provider and requested_provider != policy_provider:
        raise PermissionError("RuntimePolicy provider constraint cannot be overridden")
    if policy_model and explicit_model != policy_model:
        raise PermissionError("RuntimePolicy model constraint cannot be overridden")
    if explicit_model is not None and (
        not isinstance(explicit_model, str) or not explicit_model.strip()
    ):
        raise RuntimeError("Deep Agents requested model identity is invalid")
    manager = get_model_manager()
    selection = manager.select_provider(
        "function_calling",
        context={"preferred_provider": requested_provider},
    )
    if selection is None:
        raise RuntimeError("No provider available with real tool-calling support")
    if requested_provider and requested_provider != selection.provider_id:
        raise RuntimeError("Requested Deep Agents provider was not selected")
    endpoint = manager.registry.get_provider_endpoint(selection.provider_id)
    if (
        endpoint is None
        or not endpoint.enabled
        or "tools" not in set(endpoint.capabilities)
    ):
        raise RuntimeError("Selected canonical endpoint has no tools capability")
    if not manager._provider_is_healthy(selection.provider_id):
        raise RuntimeError("Selected canonical provider is unhealthy")
    known_models = manager.registry.get_registered_models(
        selection.provider_id, healthy_only=True
    )
    if not known_models:
        raise RuntimeError("Deep Agents model inventory is not verified")
    # A learned ranker may only compare models remaining after RuntimePolicy's
    # explicit allowlist and the healthy provider registry have intersected.
    allowed_models = plan.provider_constraints.get("allowed_models")
    if allowed_models is not None:
        if not isinstance(allowed_models, (list, tuple, set)):
            raise PermissionError("RuntimePolicy model allowlist is invalid")
        if not all(isinstance(model, str) and model for model in allowed_models):
            raise PermissionError("RuntimePolicy model allowlist contains invalid identities")
        known_models = [model for model in known_models if model in allowed_models]
        if not known_models:
            raise PermissionError("No verified tool model remains authorized")

    signal = getattr(execution, "learned_model_signals", None)
    signal_status = getattr(signal, "status", "not_consulted")
    signal_version = getattr(signal, "version", "")
    selection_source = "explicit_runtime_or_user" if explicit_model else "canonical_registry"
    requested_model = explicit_model
    if requested_model is None:
        # A registered provider default is the deterministic cold-start
        # baseline. We do not guess a model from the first inventory entry.
        baseline_model = selection.model or endpoint.default_model
        if not isinstance(baseline_model, str) or not baseline_model:
            raise RuntimeError("Deep Agents has no registered default tool model")
        if baseline_model not in known_models:
            raise RuntimeError("Default tool model is not in canonical model inventory")
        task_type = getattr(execution, "learning_task_type", "") or ""
        if (
            isinstance(task_type, str) and task_type
            and callable(getattr(manager, "choose_tool_model_from_learning", None))
        ):
            requested_model, selection_source = manager.choose_tool_model_from_learning(
                provider_id=selection.provider_id,
                baseline_model=baseline_model,
                eligible_models=list(known_models),
                tenant_id=execution.tenant_id,
                user_id=execution.user_id,
                task_type=task_type,
                signals=signal,
            )
        else:
            requested_model = baseline_model
            selection_source = "baseline_no_learning"
    if requested_model not in known_models:
        raise RuntimeError("Requested tool model is not in canonical model inventory")
    if not manager.registry.is_model_available(
        selection.provider_id, requested_model, healthy_only=True
    ):
        raise RuntimeError("Deep Agents model availability is not verified")
    return KarenGovernedChatModel(
        endpoint=endpoint,
        selected_model=requested_model,
        selection_source=selection_source,
        learning_signal_status=signal_status,
        learning_signal_version=signal_version,
        selected_max_tokens=min(4096, plan.budget.max_output_tokens),
    )
