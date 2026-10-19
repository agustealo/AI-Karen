from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

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

_RICH_RESULT_KEYS = (
    "structured_content",
    "actions",
    "citations",
    "sources",
    "attachments",
    "artifacts",
)


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
        conversation_id = ctx.require_conversation_id()
        config = self._build_config(request, ctx, conversation_id, decision, plan)

        if self._use_deepagents(request, decision, plan):
            result = await self._run_deepagents(request, decision, plan, config)
            return result

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
        conversation_id = ctx.require_conversation_id()
        config = self._build_config(request, ctx, conversation_id, decision, plan)

        if self._use_deepagents(request, decision, plan):
            # Subscribe to the existing per-request Medusa event emitter. This
            # is a transport projection, not another execution scheduler.
            events: asyncio.Queue[Any] = asyncio.Queue(maxsize=256)
            dropped_event = False

            def receive_event(event: Any) -> None:
                nonlocal dropped_event
                try:
                    events.put_nowait(event)
                except asyncio.QueueFull:
                    dropped_event = True

            run_task = asyncio.create_task(
                self._run_deepagents(
                    request, decision, plan, config, event_sink=receive_event
                )
            )
            try:
                yield _SharedChatStreamChunk(
                    type="status",
                    content="Authorized agent run started.",
                    correlation_id=ctx.correlation_id,
                    metadata={"execution_engine": "deepagents", "status": "running"},
                )
                while True:
                    if run_task.done():
                        # Do not race a permanently completed task against a
                        # newly scheduled queue-get. Drain observed events
                        # before reporting the terminal response.
                        while not events.empty():
                            chunk = self._project_medusa_event(
                                events.get_nowait(),
                                correlation_id=ctx.correlation_id,
                            )
                            if chunk is not None:
                                yield chunk
                        break
                    next_event = asyncio.create_task(events.get())
                    try:
                        ready, _ = await asyncio.wait(
                            {next_event, run_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if next_event in ready:
                            chunk = self._project_medusa_event(
                                next_event.result(),
                                correlation_id=ctx.correlation_id,
                            )
                            if chunk is not None:
                                yield chunk
                    finally:
                        if not next_event.done():
                            next_event.cancel()
                            await asyncio.gather(next_event, return_exceptions=True)

                if dropped_event:
                    raise RuntimeError("Medusa agent progress event stream overflow")
                content, metadata = await run_task
                yield _SharedChatStreamChunk(
                    type="content",
                    content=content,
                    correlation_id=ctx.correlation_id,
                    metadata=metadata,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "deepagents_primary_execution_failed",
                    extra={"correlation_id": ctx.correlation_id,
                           "tenant_id": ctx.tenant_id},
                )
                yield _SharedChatStreamChunk(
                    type="error",
                    content="The authorized agent run could not be completed.",
                    correlation_id=ctx.correlation_id,
                    metadata={"error_code": "AGENT_EXECUTION_FAILED"},
                )
            finally:
                if not run_task.done():
                    run_task.cancel()
                    await asyncio.gather(run_task, return_exceptions=True)
            return

        orchestrator = await self._get_orchestrator()
        async for chunk in orchestrator.stream_process(
            messages=self._to_langchain(request.messages),
            user_id=ctx.user_id,
            session_id=conversation_id,
            config=config,
        ):
            for activity_chunk in self._extract_agent_activity_chunks(
                chunk,
                correlation_id=ctx.correlation_id,
            ):
                yield activity_chunk

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

    @staticmethod
    def _project_medusa_event(
        event: Any, *, correlation_id: str
    ) -> Optional[_SharedChatStreamChunk]:
        """Allowlist actual Medusa events for the existing Karen UI contract.

        The emitter may carry internal data, including tool inputs, which must
        not cross this transport boundary. Identity mismatches are dropped.
        """
        if getattr(event, "correlation_id", None) != correlation_id:
            return None
        event_type = getattr(event, "type", "")
        kind = str(getattr(event_type, "value", event_type))
        raw = getattr(event, "metadata", None)
        metadata = raw if isinstance(raw, dict) else {}
        step_id = metadata.get("step_id")
        agent_id = getattr(event, "agent_id", None)
        if not isinstance(step_id, str) or not 1 <= len(step_id) <= 128:
            return None
        if not isinstance(agent_id, str) or not 1 <= len(agent_id) <= 128:
            return None
        status_by_type = {
            "agent_started": ("agent_step_started", "running"),
            "agent_completed": ("agent_step_completed", "completed"),
            "agent_failed": ("agent_step_failed", "failed"),
        }
        if kind in status_by_type:
            event_name, status = status_by_type[kind]
            return _SharedChatStreamChunk(
                type="agent_step",
                content=f"Agent step {status}.",
                correlation_id=correlation_id,
                metadata={
                    "event_type": event_name,
                    "step_id": step_id,
                    "agent_id": agent_id,
                    "status": status,
                    "execution_topology": "multi_agent",
                    "execution_engine": "deepagents",
                },
            )
        tool_phase = {
            "tool_call_started": "started",
            "tool_call_completed": "completed",
            "tool_call_failed": "failed",
        }.get(kind)
        if tool_phase is None:
            return None
        tool_name = metadata.get("tool")
        tool_id = metadata.get("tool_call_id")
        if not isinstance(tool_name, str) or not 1 <= len(tool_name) <= 128:
            return None
        if not isinstance(tool_id, str) or not 1 <= len(tool_id) <= 128:
            return None
        return _SharedChatStreamChunk(
            type="tool",
            content="",
            correlation_id=correlation_id,
            metadata={
                "tool_name": tool_name,
                "tool_call_id": tool_id,
                "phase": tool_phase,
                "step_id": step_id,
                "agent_id": agent_id,
                "execution_topology": "multi_agent",
                "execution_engine": "deepagents",
            },
        )

    @staticmethod
    def _use_deepagents(
        request: ChatExecutionRequest,
        decision: Optional[ExecutionDecision],
        plan: Optional[AuthorizedExecutionPlan],
    ) -> bool:
        """Agent-first execution: custom LangGraph only for explicit workflows.

        The runtime, never the frontend, chooses the execution engine.
        While the tool-call-capable provider integration is being validated,
        the Deep Agents path is opt-in and fails closed when not ready.
        """
        from ai_karen_engine.config.agent_medusa import (
            get_agent_medusa_runtime_settings,
        )
        if not get_agent_medusa_runtime_settings().deepagents_research_enabled:
            return False
        if decision is None or plan is None:
            return False
        if getattr(plan.topology, "value", plan.topology) != "multi_agent":
            return False
        if not decision.requires_agent_delegation:
            return False
        if decision.workflow_id or plan.workflow_id:
            return False  # Explicit custom graph stays in LangGraph.
        return bool(request.messages and request.context.user_id and
                    request.context.tenant_id and request.context.session_id)

    async def _run_deepagents(
        self,
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        config: Dict[str, Any],
        *,
        event_sink: Optional[Callable[[Any], None]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Use Medusa's existing run manager directly, not a second graph owner."""
        from ai_karen_engine.agent_medusa.contracts.runtime_request import RuntimeRequest
        from ai_karen_engine.agent_medusa.contracts.runtime_response import ResponseStatus
        from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import (
            MedusaCoordinator,
        )

        ctx = request.context
        if not plan.matches_execution_scope(
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            policy_decision_id=plan.policy_decision_id,
        ):
            raise PermissionError("Deep Agents execution scope mismatch")
        req_config = config["request_config"]
        requirements = config.get("execution_requirements")
        if not isinstance(requirements, dict) or not requirements.get("requires_agent_delegation"):
            raise PermissionError("Deep Agents requires CORTEX delegation")
        query = next(
            (str(item.get("content") or "") for item in reversed(request.messages)
             if item.get("role") == "user"),
            "",
        )
        if not query.strip():
            raise ValueError("Deep Agents requires a user task")

        from ai_karen_engine.agent_medusa.registry_factory import (
            get_implementation_factory,
        )
        from ai_karen_engine.core.model_runtime.structured_tool_chat_model import (
            build_medusa_deepagents_model,
        )
        # The canonical runtime registers the only trusted model constructor.
        # The factory resolves provider/model through ModelManager on each run.
        get_implementation_factory().register_deepagents_model_factory(
            build_medusa_deepagents_model
        )
        agent_request = RuntimeRequest(
            query=query,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            request_id=req_config["request_id"],
            context={
                "execution_context": ctx,
                "preferred_provider": request.preferred_provider,
                "preferred_model": request.preferred_model,
            },
            authorized_plan=_serialize_plan(plan),
            execution_requirements=requirements,
        )
        coordinator = MedusaCoordinator()
        if event_sink is not None:
            coordinator.attach_sink(event_sink)
        result = await coordinator.handle_request(agent_request)
        if result.status not in {ResponseStatus.SUCCESS, ResponseStatus.PARTIAL,
                                 ResponseStatus.DEGRADED}:
            raise RuntimeError("Authorized Medusa agent execution failed")
        if not isinstance(result.content, str) or not result.content.strip():
            raise RuntimeError("Authorized Medusa agent returned no content")
        return result.content, {
            "execution_engine": "deepagents",
            "response_source": result.metadata.get("response_source", "agent"),
            "actual_provider": result.metadata.get("actual_provider"),
            "actual_model": result.metadata.get("actual_model"),
            "runtime_engine": result.metadata.get("runtime_engine"),
            "execution_topology": "multi_agent",
            "agent_status": result.status.value,
            "degraded_mode": result.status == ResponseStatus.DEGRADED,
            "correlation_id": ctx.correlation_id,
        }

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
            "session_id": ctx.session_id,
            "conversation_id": conversation_id,
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
            "session_id": ctx.session_id,
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
                "requires_agent_delegation": decision.requires_agent_delegation,
                "requires_parallel_execution": decision.requires_parallel_execution,
                "topology_signals": {
                    "preferred": (
                        decision.topology.value
                        if hasattr(decision.topology, "value")
                        else str(decision.topology)
                    )
                },
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
                    "execution_topology": execution_requirements["topology_signals"]["preferred"],
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
                "session_id": ctx.session_id,
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
            "session_id": ctx.session_id,
            "conversation_id": conversation_id,
            "tenant_id": ctx.tenant_id,
            "auth_context": auth_context,
            "runtime_policy": serialized_plan,
            "execution_requirements": execution_requirements,
            "request_config": request_config,
        }

    def _to_langchain(self, messages: List[Dict[str, Any]]) -> List["BaseMessage"]:
        # LangChain is a specialist workflow dependency. Import it only when
        # Runtime has explicitly selected graph-required execution so direct
        # chat/evidence paths remain independent of the graph stack.
        from langchain_core.messages import (
            AIMessage,
            BaseMessage,
            HumanMessage,
            SystemMessage,
        )

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
        """Preserve declared user-facing result fields across the graph boundary."""
        formatted = state.get("formatted_response")
        if formatted is not None:
            if hasattr(formatted, "data"):
                data = getattr(formatted, "data") or {}
                metadata = dict(getattr(formatted, "metadata") or {})
                text = str(data.get("response") or data.get("content") or "")
                return text, self._merge_rich_result(metadata, data, state)
            if isinstance(formatted, dict):
                data = formatted.get("data") or {}
                metadata = dict(formatted.get("metadata") or {})
                text = str(data.get("response") or data.get("content") or "")
                return text, self._merge_rich_result(metadata, data, state)
        return self._extract_from_raw(state)

    def _extract_from_raw(self, state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        text = str(state.get("response") or state.get("llm_response") or "")
        metadata = dict(state.get("response_metadata") or {})
        return text, self._merge_rich_result(metadata, state, state)

    @staticmethod
    def _merge_rich_result(
        metadata: Dict[str, Any],
        primary: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Forward only the public rich-result contract, never graph internals."""
        merged = dict(metadata)
        for key in _RICH_RESULT_KEYS:
            value = primary.get(key)
            if value is None:
                value = state.get(key)
            if value is None:
                continue
            if key == "structured_content":
                merged[key] = dict(value) if isinstance(value, dict) else {}
            else:
                merged[key] = list(value) if isinstance(value, list) else []
        return merged

    def _extract_agent_activity_chunks(
        self,
        chunk: Any,
        *,
        correlation_id: str,
    ) -> List[_SharedChatStreamChunk]:
        """Project canonical Medusa plan truth into the shared chat stream.

        LangGraph yields node-state updates. Medusa owns execution and records the
        terminal plan; this adapter only translates those already-authoritative
        step results into transport events. It does not invent agent selection,
        authorization, or execution state.
        """

        if not isinstance(chunk, dict):
            return []

        projected: List[_SharedChatStreamChunk] = []
        for state_update in chunk.values():
            if not isinstance(state_update, dict):
                continue
            metadata = state_update.get("response_metadata")
            if not isinstance(metadata, dict):
                continue
            if metadata.get("execution_topology") != "multi_agent":
                continue
            plan = metadata.get("plan")
            if not isinstance(plan, dict):
                continue
            steps = plan.get("steps")
            if not isinstance(steps, list):
                continue

            for step in steps:
                if not isinstance(step, dict):
                    continue
                status = str(step.get("status") or "pending").strip().lower()
                event_type = {
                    "completed": "agent_step_completed",
                    "failed": "agent_step_failed",
                    "skipped": "agent_step_skipped",
                    "running": "agent_step_started",
                    "pending": "agent_step_started",
                }.get(status, "agent_step_completed")
                step_id = str(step.get("id") or "").strip()
                agent_id = str(step.get("agent_specialist") or "").strip()
                description = str(step.get("description") or "").strip()
                projected.append(
                    _SharedChatStreamChunk(
                        type="agent_step",
                        content=description,
                        correlation_id=correlation_id,
                        metadata={
                            "event_type": event_type,
                            "step_id": step_id,
                            "agent_id": agent_id,
                            "status": status,
                            "required_tools": list(step.get("required_tools") or []),
                            "required_plugins": list(step.get("required_plugins") or []),
                            "degradation_metadata": step.get("degradation_metadata"),
                            "policy_decision_id": metadata.get("policy_decision_id"),
                            "execution_topology": "multi_agent",
                        },
                    )
                )
        return projected

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
        "authorized_user_id": plan.authorized_user_id,
        "authorized_tenant_id": plan.authorized_tenant_id,
        "authorized_session_id": plan.authorized_session_id,
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
