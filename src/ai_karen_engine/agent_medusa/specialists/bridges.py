"""Canonical execution bridges for Medusa specialists.

These replace the direct `llm_router_service.get_llm_router()` and
`tools.execute_tool(...)` calls currently inside Analyst/Researcher specialists.

GenerationBridge  -> builds a canonical GenerationRequest and executes it through
                     the ProviderRouter-selected provider (no specialist owns
                     provider selection).  (P0-2 / A7 / A8)

ToolBridge        -> routes every external action through ActionExecutionGate
                     before the tool runtime, carrying tenant/user/policy/
                     trajectory/agent/step identity for audit.  (P0-3 / A9)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...core.runtime.contracts import AuthorizedExecutionPlan, ExecutionBudgetMeter, GenerationRequest

logger = logging.getLogger(__name__)


def resolve_prompt_text(
    prompt_contract_id: Optional[str],
    prompt_version: Optional[str],
    fallback: str,
) -> str:
    """Resolve a prompt contract's text from PromptRegistry, else fallback."""
    if prompt_contract_id:
        try:
            from ...core.runtime.prompt.prompt_assembler import get_prompt_registry

            definition = get_prompt_registry().get(prompt_contract_id, prompt_version)
            if definition and definition.system_instructions:
                return definition.system_instructions
        except Exception:
            pass
    return fallback


class CanonicalGenerationExecutor:
    """Thin executor that consumes a canonical GenerationRequest.

    Translates GenerationRequest -> ChatRequest, routes via the canonical
    llm_router (ProviderRouter), and executes via ProviderRuntime. This is the
    single generation seam for all Medusa model work.
    """

    async def generate(self, request: GenerationRequest) -> str:
        from ai_karen_engine.services.models.routing.llm_router_service import (
            get_llm_router,
            ChatRequest,
        )
        from ai_karen_engine.services.provider_runtime import ProviderRuntime

        router = get_llm_router()
        chat_request = ChatRequest(
            message=(request.messages[-1].get("content", "") if request.messages else ""),
            context={"messages": request.messages},
            stream=request.streaming,
            preferred_provider=request.provider_constraints.get("provider"),
            preferred_model=request.model_constraints.get("model"),
            response_schema=request.response_schema or None,
        )
        route_decision = await router.select_provider(chat_request)
        if not route_decision:
            raise RuntimeError("No provider route decision for canonical generation request")
        result = await ProviderRuntime(router).execute_chat(route_decision, chat_request)
        return result.text


class GenerationBridge:
    """Specialist-facing helper for model work via the canonical path."""

    def __init__(self, executor: Optional[CanonicalGenerationExecutor] = None) -> None:
        self._executor = executor or CanonicalGenerationExecutor()

    async def invoke(
        self,
        *,
        request_id: str,
        correlation_id: str,
        messages: List[Dict[str, Any]],
        prompt_contract_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        provider_constraints: Optional[Dict[str, Any]] = None,
        model_constraints: Optional=None,
        response_schema: Optional[Dict[str, Any]] = None,
        budget: Any = None,
        execution: Optional["SpecialistExecutionContext"] = None,
    ) -> str:
        # A17: enforce per-call model budget before invoking generation.
        if execution is not None and execution.budget_meter is not None:
            if not execution.budget_meter.consume_model_call():
                raise RuntimeError("ExecutionBudget exhausted: model calls")
        req = GenerationRequest(
            request_id=request_id,
            correlation_id=correlation_id,
            prompt_contract_id=prompt_contract_id,
            prompt_version=prompt_version,
            messages=messages,
            provider_constraints=provider_constraints or {},
            model_constraints=model_constraints or {},
            response_schema=response_schema or {},
            policy_decision_id=policy_decision_id,
            budget=budget,
        )
        return await self._executor.generate(req)


class ToolBridge:
    """Specialist-facing helper for tool side-effects via ActionExecutionGate."""

    async def execute(
        self,
        *,
        tool_name: str,
        parameters: Dict[str, Any],
        authorized_plan: AuthorizedExecutionPlan,
        tenant_id: str,
        user_id: str,
        policy_decision_id: str,
        trajectory_id: str,
        agent_id: str,
        step_id: str,
        execution: Optional["SpecialistExecutionContext"] = None,
    ) -> Dict[str, Any]:
        # A17: enforce per-call tool budget before executing the action.
        if execution is not None and execution.budget_meter is not None:
            if not execution.budget_meter.consume_tool_call():
                raise PermissionError("ExecutionBudget exhausted: tool calls")
        # 1. Gate: no authorization -> no execution.
        if not await self._authorize(tool_name, authorized_plan):
            raise PermissionError(
                f"Tool '{tool_name}' not authorized by plan {authorized_plan.policy_decision_id}"
            )

        # 2. Execute through the canonical tool runtime.
        from ai_karen_engine.services.tooling.tool_service import get_tool_service, ToolInput
        from ..contracts.events import AgentEvent, AgentEventType

        tools = get_tool_service()
        if execution is not None and execution.event_emitter is not None:
            await execution.event_emitter.emit(AgentEvent(
                type=AgentEventType.TOOL_CALL_STARTED,
                agent_id=agent_id,
                message=f"tool {tool_name} started",
                correlation_id=trajectory_id,
                metadata={"tool": tool_name, "step_id": step_id},
            ))

        result = await tools.execute_tool(
            ToolInput(
                tool_name=tool_name,
                parameters=parameters,
                user_id=user_id,
                session_id=trajectory_id,
            )
        )

        success = getattr(result, "success", False)
        # 3. Audit/observability record (emit to telemetry + trajectory).
        logger.info(
            "medusa.tool.executed",
            extra={
                "tool": tool_name,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "policy_decision_id": policy_decision_id,
                "trajectory_id": trajectory_id,
                "agent_id": agent_id,
                "step_id": step_id,
                "success": success,
            },
        )
        if execution is not None and execution.event_emitter is not None:
            await execution.event_emitter.emit(AgentEvent(
                type=AgentEventType.TOOL_CALL_COMPLETED if success else AgentEventType.TOOL_CALL_FAILED,
                agent_id=agent_id,
                message=f"tool {tool_name} {'completed' if success else 'failed'}",
                correlation_id=trajectory_id,
                metadata={"tool": tool_name, "step_id": step_id, "success": success},
            ))
        return {
            "tool": tool_name,
            "success": success,
            "result": getattr(result, "result", None),
        }

    @staticmethod
    async def _authorize(tool_name: str, plan: AuthorizedExecutionPlan) -> bool:
        from ...core.runtime.contracts import ActionExecutionGate

        return await ActionExecutionGate.authorize(plan, tool_name)
