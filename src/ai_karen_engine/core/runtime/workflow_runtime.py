from __future__ import annotations

import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatStreamChunk as _SharedChatStreamChunk,
)
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

logger = get_logger(__name__)


class WorkflowRuntime:
    """Runtime-owned adapter for graph-required execution.

    This is the only chat boundary that touches LangGraph/LangChain. Runtime
    supplies trusted identity, the CORTEX execution decision, and the immutable
    RuntimePolicy authorization. LangGraph may consume but not recreate them.
    """

    async def run(
        self,
        request: ChatExecutionRequest,
        decision: Optional[ExecutionDecision] = None,
        plan: Optional[AuthorizedExecutionPlan] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        ctx = request.context
        conversation_id = ctx.conversation_id or _normalize(ctx.session_id)
        config = self._build_config(request, ctx, conversation_id, decision, plan)

        orchestrator = await self._get_orchestrator()
        final_state = await orchestrator.process(
            messages=self._to_langchain(request.messages),
            user_id=ctx.user_id,
            session_id=conversation_id,
            config=config,
        )
        return self._extract_payload(final_state)

    async def stream(
        self,
        request: ChatExecutionRequest,
        decision: Optional[ExecutionDecision] = None,
        plan: Optional[AuthorizedExecutionPlan] = None,
    ) -> AsyncIterator[_SharedChatStreamChunk]:
        ctx = request.context
        conversation_id = ctx.conversation_id or _normalize(ctx.session_id)
        config = self._build_config(request, ctx, conversation_id, decision, plan)

        try:
            orchestrator = await self._get_orchestrator()
            async for chunk in orchestrator.stream_process(
                messages=self._to_langchain(request.messages),
                user_id=ctx.user_id,
                session_id=conversation_id,
                config=config,
            ):
                content, meta = self._extract_stream_payload(chunk)
                if content or meta:
                    yield _SharedChatStreamChunk(
                        type=(
                            "status"
                            if meta.get("status") and not content
                            else "content"
                        ),
                        content=content,
                        correlation_id=ctx.correlation_id,
                        metadata=meta,
                    )
        except Exception as exc:  # pragma: no cover - defensive adapter boundary
            logger.error(
                "WorkflowRuntime.stream failed: %s",
                exc,
                extra={"correlation_id": ctx.correlation_id},
            )
            yield _SharedChatStreamChunk(
                type="error",
                content=str(exc),
                correlation_id=ctx.correlation_id,
                metadata={"event": "error"},
            )

    async def _get_orchestrator(self):
        from ai_karen_engine.core.langgraph_orchestrator import get_default_orchestrator

        return await get_default_orchestrator()

    def _build_config(
        self,
        request: ChatExecutionRequest,
        ctx: ChatExecutionContext,
        conversation_id: str,
        decision: Optional[ExecutionDecision] = None,
        plan: Optional[AuthorizedExecutionPlan] = None,
    ) -> Dict[str, Any]:
        request_id = ctx.request_id or str(uuid.uuid4())
        auth_context = {
            "user_id": ctx.user_id,
            "tenant_id": ctx.tenant_id,
            "roles": list(ctx.roles),
            "permissions": list(ctx.permissions),
        }
        request_config: Dict[str, Any] = {
            "preferred_llm_provider": request.preferred_provider,
            "preferred_model": request.preferred_model,
            "provider": request.preferred_provider,
            "model": request.preferred_model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": request.messages,
            "response_id": request_id,
            "request_id": request_id,
            "correlation_id": ctx.correlation_id,
            "conversation_id": conversation_id,
            "tenant_id": ctx.tenant_id,
            "auth_context": auth_context,
        }

        execution_requirements: Optional[Dict[str, Any]] = None
        if decision is not None:
            execution_requirements = {
                "request_id": request_id,
                "correlation_id": ctx.correlation_id,
                "intent": decision.intent,
                "intent_confidence": decision.intent_confidence,
                "tool_requirements": list(decision.tool_requirements),
                "plugin_candidates": list(decision.plugin_candidates),
                "required_capabilities": list(decision.required_capabilities),
                "forbidden_capabilities": list(decision.forbidden_capabilities),
                "reasoning_depth": decision.reasoning_depth,
                "requires_human_gate": decision.requires_human_gate,
                "requires_resumability": decision.requires_resumability,
                "max_steps": decision.max_steps,
                "time_budget_ms": decision.time_budget_ms,
                "token_budget": decision.token_budget,
                "workflow_id": decision.workflow_id,
                "workflow_version": decision.workflow_version,
                "topology": (
                    decision.topology.value
                    if hasattr(decision.topology, "value")
                    else str(decision.topology)
                ),
            }
            request_config.update(
                {
                    "intent": decision.intent,
                    "intent_confidence": decision.intent_confidence,
                    "tool_requirements": list(decision.tool_requirements),
                    "plugin_candidates": list(decision.plugin_candidates),
                    "workflow_id": decision.workflow_id,
                    "workflow_version": decision.workflow_version,
                    "required_capabilities": list(decision.required_capabilities),
                    "forbidden_capabilities": list(decision.forbidden_capabilities),
                    "token_budget": decision.token_budget,
                    "time_budget_ms": decision.time_budget_ms,
                    "max_steps": decision.max_steps,
                    "reasoning_depth": decision.reasoning_depth,
                    "requires_human_gate": decision.requires_human_gate,
                    "requires_resumability": decision.requires_resumability,
                    "policy_decision_id": decision.policy_decision_id,
                    "policy_version": decision.policy_version,
                    "policy_reason_codes": list(decision.policy_reason_codes),
                    "execution_topology": execution_requirements["topology"],
                    "execution_requirements": execution_requirements,
                }
            )

        serialized_plan = _serialize_plan(plan) if plan is not None else None
        if serialized_plan is not None:
            request_config["runtime_policy"] = serialized_plan

        # Metadata is contextual input only. Trusted Runtime identity and policy
        # values above are re-applied after metadata so callers cannot override them.
        request_config.update(request.metadata or {})
        request_config.update(
            {
                "request_id": request_id,
                "correlation_id": ctx.correlation_id,
                "conversation_id": conversation_id,
                "tenant_id": ctx.tenant_id,
                "auth_context": auth_context,
            }
        )
        if execution_requirements is not None:
            request_config["execution_requirements"] = execution_requirements
            request_config["intent"] = execution_requirements["intent"]
            request_config["intent_confidence"] = execution_requirements[
                "intent_confidence"
            ]
            request_config["tool_requirements"] = list(
                execution_requirements["tool_requirements"]
            )
            request_config["plugin_candidates"] = list(
                execution_requirements["plugin_candidates"]
            )
        if serialized_plan is not None:
            request_config["runtime_policy"] = serialized_plan
            request_config["policy_decision_id"] = serialized_plan["policy_decision_id"]

        return {
            "model": request.preferred_model,
            "provider": request.preferred_provider,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "request_id": request_id,
            "correlation_id": ctx.correlation_id,
            "conversation_id": conversation_id,
            "tenant_id": ctx.tenant_id,
            "auth_context": auth_context,
            "runtime_policy": serialized_plan,
            "execution_requirements": execution_requirements,
            "request_config": request_config,
        }

    def _to_langchain(self, messages: List[Dict[str, Any]]) -> List[BaseMessage]:
        converted: List[BaseMessage] = []
        for msg in messages:
            content = str(msg.get("content") or "")
            role = str(msg.get("role") or msg.get("message_type") or "user").lower()
            if role == "assistant":
                converted.append(AIMessage(content=content))
            elif role == "system":
                converted.append(SystemMessage(content=content))
            else:
                converted.append(HumanMessage(content=content))
        return converted

    def _extract_payload(self, state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        formatted = state.get("formatted_response")
        if formatted is not None:
            if hasattr(formatted, "data"):
                data = getattr(formatted, "data") or {}
                metadata = getattr(formatted, "metadata") or {}
                text = str(data.get("response") or data.get("content") or "")
                return text, metadata
            if isinstance(formatted, dict):
                data = formatted.get("data") or {}
                metadata = formatted.get("metadata") or {}
                text = str(data.get("response") or data.get("content") or "")
                return text, metadata
        return self._extract_from_raw(state)

    def _extract_from_raw(self, state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        text = str(state.get("response") or state.get("llm_response") or "")
        return text, dict(state.get("response_metadata") or {})

    def _extract_stream_payload(self, chunk: Any) -> Tuple[str, Dict[str, Any]]:
        if isinstance(chunk, dict):
            for state_update in chunk.values():
                if not isinstance(state_update, dict):
                    continue
                if (
                    "formatted_response" in state_update
                    or "llm_response" in state_update
                ):
                    return self._extract_payload(state_update)
                if "error" in state_update:
                    return f"Error: {state_update['error']}", {
                        "error": state_update["error"]
                    }
        if isinstance(chunk, str):
            return chunk, {}
        return "", {}


def _normalize(session_id: Optional[str]) -> str:
    from ai_karen_engine.utils.chat_helpers import normalize_session_id

    return normalize_session_id(session_id)


def _dataclass_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _serialize_plan(plan: AuthorizedExecutionPlan) -> Dict[str, Any]:
    return {
        "execution_id": plan.execution_id,
        "policy_decision_id": plan.policy_decision_id,
        "topology": (
            plan.topology.value
            if hasattr(plan.topology, "value")
            else str(plan.topology)
        ),
        "allowed_capabilities": list(plan.allowed_capabilities),
        "allowed_tools": list(plan.allowed_tools),
        "allowed_plugins": list(plan.allowed_plugins),
        "allowed_agents": list(plan.allowed_agents),
        "provider_constraints": dict(plan.provider_constraints),
        "memory_scope": plan.memory_scope,
        "resource_scope": dict(plan.resource_scope),
        "budget": _dataclass_dict(plan.budget),
        "approval_requirements": list(plan.approval_requirements),
        "reasoning_modes": list(plan.reasoning_modes),
        "workflow_id": plan.workflow_id,
        "agent_topology": plan.agent_topology,
        "degraded_allowed": plan.degraded_allowed,
        "degradation_state": (
            _dataclass_dict(plan.degradation_state) if plan.degradation_state else None
        ),
        "audit_context": dict(plan.audit_context),
        "provenance": _dataclass_dict(plan.provenance) if plan.provenance else None,
    }


_workflow_runtime: Optional[WorkflowRuntime] = None


def get_workflow_runtime() -> WorkflowRuntime:
    """Return the singleton graph-required workflow runtime adapter."""
    global _workflow_runtime
    if _workflow_runtime is None:
        _workflow_runtime = WorkflowRuntime()
    return _workflow_runtime
