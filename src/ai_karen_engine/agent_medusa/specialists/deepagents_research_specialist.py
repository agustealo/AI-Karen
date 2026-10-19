"""Governed Deep Agents harness for an existing Medusa research specialist.

Deep Agents handles its own task planning, context compaction, ephemeral
workspace and bounded child tasks. Medusa still owns specialist selection,
authorization, lifecycle and audit. The model MUST be supplied by the trusted
Karen runtime model factory: no Deep Agents default provider or secret lookup.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ai_karen_engine.agent_medusa.contracts.registration import AgentRegistration
from ai_karen_engine.agent_medusa.contracts.specialist_execution import (
    SpecialistExecutionContext,
)
from ai_karen_engine.agent_medusa.specialists.bridges import ToolBridge
from ai_karen_engine.core.runtime.contracts import ExecutionTopology

logger = logging.getLogger(__name__)

# Constructed exclusively at trusted runtime composition / factory setup.
TrustedModelFactory = Callable[
    [AgentRegistration, SpecialistExecutionContext],
    Any | Awaitable[Any],
]


class DeepAgentsResearchSpecialist:
    """Medusa-compatible specialist backed by the real Deep Agents SDK.

    This is not an alternate runtime. No model string, endpoint, credentials,
    plugin, tools, tenant identity or system prompt is accepted from task input.
    """

    def __init__(
        self,
        registration: AgentRegistration,
        *,
        model_factory: TrustedModelFactory | None,
    ) -> None:
        self.registration = registration
        self._model_factory = model_factory

    @staticmethod
    def _verify_scope(
        registration: AgentRegistration, execution: SpecialistExecutionContext | None
    ) -> SpecialistExecutionContext:
        if execution is None:
            raise PermissionError("Deep Agents requires a governed Medusa execution")
        plan = execution.authorized_plan
        if not execution.user_id or not execution.tenant_id or not execution.session_id:
            raise PermissionError("Deep Agents requires trusted user, tenant and session")
        if not execution.trajectory_id or not execution.step_id:
            raise PermissionError("Deep Agents requires run and specialist step identity")
        if (
            not execution.policy_decision_id
            or execution.policy_decision_id != plan.policy_decision_id
            or getattr(plan.topology, "value", plan.topology)
            != ExecutionTopology.MULTI_AGENT.value
            or not plan.matches_execution_scope(
                user_id=execution.user_id,
                tenant_id=execution.tenant_id,
                session_id=execution.session_id,
                policy_decision_id=execution.policy_decision_id,
            )
        ):
            raise PermissionError("Deep Agents execution is outside RuntimePolicy")
        if (
            registration.agent_id not in plan.allowed_agents
            and "*" not in plan.allowed_agents
        ):
            raise PermissionError("Deep Agents specialist is not authorized")
        return execution

    @staticmethod
    def _get_prompt(registration: AgentRegistration) -> str:
        from ai_karen_engine.core.runtime.prompt.prompt_registry import (
            get_prompt_registry,
        )

        if not registration.prompt_contract_id or not registration.prompt_version:
            raise RuntimeError("Deep Agents requires a versioned Karen prompt contract")
        definition = get_prompt_registry().get_prompt(
            registration.prompt_contract_id, registration.prompt_version
        )
        if not definition.system_instructions.strip():
            raise RuntimeError("Deep Agents registered prompt is empty")
        return definition.system_instructions

    async def run(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
        *,
        execution: SpecialistExecutionContext | None = None,
    ) -> dict[str, Any]:
        del context  # Upstream context is not a new prompt or state authority.
        execution = self._verify_scope(self.registration, execution)
        from ai_karen_engine.config.agent_medusa import get_agent_medusa_runtime_settings

        if not get_agent_medusa_runtime_settings().deepagents_research_enabled:
            raise RuntimeError("Deep Agents research harness is disabled")
        if self._model_factory is None:
            raise RuntimeError("Deep Agents trusted runtime model factory is not configured")

        query = input_data.get("query") or input_data.get("raw")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Deep Agents research requires a nonempty task query")
        prompt = self._get_prompt(self.registration)

        # Optional dependency is deliberately imported only for selected runs.
        # No stub classes or synthetic completed results are permitted.
        from deepagents import create_deep_agent
        from deepagents.backends import StateBackend
        from langchain_core.callbacks import AsyncCallbackHandler
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, Field

        model = self._model_factory(self.registration, execution)
        if inspect.isawaitable(model):
            model = await model
        if isinstance(model, str) or model is None or not callable(getattr(model, "bind_tools", None)):
            raise TypeError("Trusted Deep Agents factory must supply a tool-capable chat model")

        budget = execution.authorized_plan.budget
        meter = execution.budget_meter
        if meter is None:
            raise PermissionError("Deep Agents requires the shared Medusa execution budget")
        permitted_tools = sorted(
            set(execution.authorized_plan.allowed_tools)
            & set(self.registration.allowed_tools)
        )
        accepted_receipts: list[dict[str, str]] = []

        class ApprovedToolArguments(BaseModel):
            tool_name: str = Field(description="One authorized Karen tool name")
            parameters: dict[str, Any] = Field(
                default_factory=dict, description="Tool parameters"
            )

        async def run_approved_tool(tool_name: str, parameters: dict[str, Any]) -> str:
            if tool_name not in permitted_tools:
                raise PermissionError("Requested tool is outside specialist authorization")
            result = await ToolBridge().execute(
                tool_name=tool_name,
                parameters=parameters,
                authorized_plan=execution.authorized_plan,
                tenant_id=execution.tenant_id,
                user_id=execution.user_id,
                policy_decision_id=execution.policy_decision_id,
                trajectory_id=execution.trajectory_id,
                agent_id=self.registration.agent_id,
                step_id=execution.step_id,
                execution=execution,
            )
            if result.get("success") is not True or not result.get("receipt_id"):
                raise RuntimeError("Governed tool has no acknowledged execution receipt")
            accepted_receipts.append({
                "tool_name": tool_name,
                "receipt_id": str(result["receipt_id"]),
            })
            tool_payload = json.dumps(
                {"result": result.get("result"), "receipt_id": result["receipt_id"]},
                ensure_ascii=False,
                default=str,
            )
            if len(tool_payload) > 16000:
                # Keep the agent-facing response valid JSON and explicitly
                # identify truncation instead of handing it malformed data.
                tool_payload = json.dumps({
                    "receipt_id": result["receipt_id"],
                    "result_preview": tool_payload[:12000],
                    "truncated": True,
                })
            return tool_payload

        class ModelBudgetCallback(AsyncCallbackHandler):
            raise_error = True

            async def on_chat_model_start(self, serialized: dict, messages: list, **kwargs: Any) -> None:
                del serialized, messages, kwargs
                if not await meter.check_duration() or not await meter.consume_model_call():
                    raise RuntimeError("Deep Agents model execution exceeded RuntimePolicy budget")

        tools: list[Any] = []
        if permitted_tools:
            tools.append(StructuredTool.from_function(
                coroutine=run_approved_tool,
                name="karen_approved_tool",
                description=(
                    "Invoke an authorized Karen tool. Valid tool names: "
                    + ", ".join(permitted_tools)
                    + ". All calls are checked and audited by Karen RuntimePolicy."
                ),
                args_schema=ApprovedToolArguments,
            ))

        # The nested general-purpose subagent is not a new Medusa agent identity.
        # It gets exactly the same model, prompt and ToolBridge-scoped tools.
        # The shared model budget callback applies to graph and child calls.
        subagents: list[dict[str, Any]] = [{
            "name": "general-purpose",
            "description": "Handle bounded subtasks of the authorized research request.",
            "system_prompt": prompt,
            "model": model,
            "tools": tools,
        }]

        agent = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=prompt,
            subagents=subagents,
            backend=StateBackend(),  # No host filesystem/shell/memory writes.
            skills=[],
            memory=[],
            checkpointer=None,  # No unverified cross-process resume claims.
        )
        namespace = ":".join((
            execution.tenant_id,
            execution.session_id,
            execution.trajectory_id,
            execution.step_id,
        ))
        thread_id = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        limit = max(6, min(128, budget.max_reasoning_steps * 4))
        timeout_seconds = max(0.001, budget.max_duration_ms / 1000.0)

        # Disable ambient external LangSmith tracing for a local-first worker.
        from langsmith import tracing_context

        logger.info(
            "medusa.deepagents.started",
            extra={
                "tenant_id": execution.tenant_id,
                "correlation_id": execution.correlation_id,
                "step_id": execution.step_id,
                "agent_id": self.registration.agent_id,
                "harness": "deepagents",
            },
        )
        async with asyncio.timeout(timeout_seconds):
            with tracing_context(enabled=False):
                result = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": query.strip()}]},
                    config={
                        "configurable": {"thread_id": thread_id},
                        "callbacks": [ModelBudgetCallback()],
                        "recursion_limit": limit,
                    },
                )

        messages = result.get("messages") if isinstance(result, Mapping) else None
        final_message = messages[-1] if isinstance(messages, list) and messages else None
        raw_content = getattr(final_message, "content", None)
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise RuntimeError("Deep Agents returned no validated final text")

        logger.info(
            "medusa.deepagents.completed",
            extra={
                "tenant_id": execution.tenant_id,
                "correlation_id": execution.correlation_id,
                "step_id": execution.step_id,
                "agent_id": self.registration.agent_id,
                "receipt_count": len(accepted_receipts),
            },
        )
        return {
            "context_found": raw_content[: max(512, budget.max_output_tokens * 4)],
            "search_results": [],  # Receipts, not invented search-result records.
            "tool_receipts": accepted_receipts,
            "harness": "deepagents",
            "prompt_contract_id": self.registration.prompt_contract_id,
            "prompt_version": self.registration.prompt_version,
        }
