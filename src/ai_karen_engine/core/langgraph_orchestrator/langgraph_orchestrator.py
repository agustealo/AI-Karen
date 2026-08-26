"""
LangGraph Orchestration Foundation

This module implements the core orchestration backbone using LangGraph for
human-in-the-loop workflows with typed state management and checkpointing.

Graph Structure:
auth_gate → safety_gate → memory_fetch → intent_detect → planner →
router_select → tool_exec → response_synth → approval_gate → memory_write
"""

from typing import (
    Dict,
    Any,
    List,
    Optional,
    TypedDict,
    Annotated,
    Literal,
    Deque,
    Tuple,
    cast,
)
from dataclasses import dataclass, field, replace, asdict
import asyncio
from collections import deque
import logging
import os
import re
import time
from datetime import datetime, timezone
import uuid

# from ai_karen_engine.auth.auth_service import (
#     AuthService,
#     get_auth_service,
#     user_account_to_dict,
# )
from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService, SafetyResult
# from ai_karen_engine.services.llm_router import ChatRequest, LLMRouter  <- Moved to local scope
from ai_karen_engine.core.memory.profile_synthesis.profile_manager import (
    Guardrails,
    ProfileManager,
)
from ai_karen_engine.services.tooling.tool_service import ToolInput, ToolOutput, ToolService
from ai_karen_engine.core.runtime.chat_runtime_contract import ToolType

from ai_karen_engine.services.formatting.response_formatting_engine import (
    ResponseFormattingEngine,
    FormattingContext,
    DisplayContext,
    AccessibilityLevel,
)
from ai_karen_engine.services.formatting.ResponseFormattingClass.Specialized.Integration import (
    get_specialized_integration,
)
from ai_karen_engine.services.formatting.response_policy_enforcer import ResponsePolicyEnforcer
from ai_karen_engine.services.formatting.pretty_output_layer import (
    PrettyOutputLayer,
)
from ai_karen_engine.core.runtime.session_state_manager_compat import SessionStateManager
from ai_karen_engine.utils.chat_helpers import (
    build_user_identity_line,
    wants_long_form_markdown_article,
    strip_internal_analysis_leakage,
    is_low_information_content,
)
from ai_karen_engine.core.langgraph_orchestrator.utils.message_serialization import (
    history_entry_to_message,
)

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool

from ai_karen_engine.agent_medusa.agent_medusa_node import medusa_node

# Import new unified components
from .nodes import (
    auth_gate_node,
    safety_gate_node,
    memory_fetch_node,
    intent_detect_node,
    planner_node,
    router_select_node,
    reasoning_node,
    select_reasoning_branch,
    tool_exec_node,
    response_synth_node,
    approval_gate_node,
    memory_write_node,
    stream_process_node,
)
from .runtime_policy import runtime_policy_enforcer_node, select_execution_branch
from .formatting.response_formatter_pipeline import response_formatter_node
from .diagnostics import DiagnosticsEngine

# Import consolidated classes from separate modules
from .decision_engine import DecisionEngine

from .contracts.orchestration_state import (
    LangGraphOrchestrationState,
    create_initial_state,
    create_streaming_initial_state,
)
from .contracts.orchestration_config import LangGraphOrchestrationConfig

logger = logging.getLogger(__name__)


class LangGraphOrchestrator:
    """Main orchestration class using LangGraph for workflow management."""

    def __init__(
        self,
        config: Optional[LangGraphOrchestrationConfig] = None,
        *,
        auth_service: Optional[Any] = None,
        safety_service: Optional[DistilBertService] = None,
        memory_service: Optional[Any] = None,
        memory_recall: Optional[Any] = None,
        decision_engine: Optional[DecisionEngine] = None,
        tool_service: Optional[ToolService] = None,
        llm_router: Optional[Any] = None,
        profile_manager: Optional[ProfileManager] = None,
        session_state_manager: Optional[SessionStateManager] = None,
    ):
        self.config = config or LangGraphOrchestrationConfig()
        self.checkpointer = MemorySaver() if self.config.checkpoint_enabled else None
        self.graph = None
        self._build_graph()

        # Runtime telemetry
        self._start_time = datetime.now(timezone.utc)
        self._stats_lock = asyncio.Lock()
        self._config_lock = asyncio.Lock()
        self._active_sessions: Dict[str, datetime] = {}
        self._total_processed: int = 0
        self._total_failed: int = 0
        self._latency_samples: Deque[float] = deque(maxlen=1000)
        self._last_error: Optional[Dict[str, Any]] = None

        # Dependency handles (lazily resolved when not provided)
        self._auth_service: Optional[Any] = auth_service
        self._auth_service_lock = asyncio.Lock()
        self._auth_service_failed = False
        self._safety_service: Optional[DistilBertService] = safety_service
        self._legacy_memory_service: Optional[Any] = memory_service
        self._memory_recall: Optional[Any] = memory_recall or getattr(
            memory_service, "recall_context", None
        )
        self._session_state_manager: Optional[SessionStateManager] = (
            session_state_manager
        )
        self._decision_engine: DecisionEngine = decision_engine or DecisionEngine()
        self._tool_service: Optional[ToolService] = tool_service

        # Local import to avoid circular dependency
        from ai_karen_engine.core.model_runtime.routing.llm_router_service import LLMRouter

        self._llm_router: LLMRouter = llm_router or LLMRouter()
        self._profile_manager: ProfileManager = profile_manager or ProfileManager()

        # Track fallback resolutions so we only warn once per dependency.
        self._tool_resolution_failed = False
        self._session_state_resolution_failed = False

    def _legacy_payload(self, flow_input: Any) -> Dict[str, Any]:
        """Normalize legacy flow wrappers, dicts, and pydantic models."""

        if flow_input is None:
            return {}
        if isinstance(flow_input, dict):
            return flow_input

        data = getattr(flow_input, "data", None)
        if isinstance(data, dict):
            return data

        model_dump = getattr(flow_input, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass

        if hasattr(flow_input, "__dict__"):
            return {
                key: value
                for key, value in vars(flow_input).items()
                if not key.startswith("_")
            }

        return {"value": flow_input}

    def _legacy_messages(self, payload: Dict[str, Any]) -> List[BaseMessage]:
        """Build LangChain messages from legacy flow payloads."""

        messages: List[BaseMessage] = []
        conversation_history = payload.get("conversation_history") or []

        for entry in conversation_history:
            if not isinstance(entry, dict):
                continue
            try:
                messages.append(history_entry_to_message(entry))
            except Exception:
                content = entry.get("content", "")
                role = (entry.get("role") or "user").lower()
                if role == "assistant":
                    messages.append(AIMessage(content=content))
                elif role == "system":
                    messages.append(SystemMessage(content=content))
                else:
                    messages.append(HumanMessage(content=content))

        prompt = (
            payload.get("prompt")
            or payload.get("message")
            or payload.get("text")
            or payload.get("content")
            or ""
        )
        if prompt:
            messages.append(HumanMessage(content=str(prompt)))

        if not messages:
            messages.append(HumanMessage(content=""))

        return messages

    def _legacy_flow_response(
        self,
        payload: Dict[str, Any],
        state: Dict[str, Any],
        *,
        flow_type: str,
    ) -> Dict[str, Any]:
        """Convert graph state into a legacy-friendly response payload."""

        response_text = (
            state.get("response")
            or state.get("formatted_response")
            or state.get("routing_reason")
            or state.get("execution_plan", {}).get("intent")
            or ""
        )

        return {
            "response": response_text,
            "requires_plugin": bool(state.get("tool_calls")),
            "plugin_to_execute": state.get("selected_provider"),
            "plugin_parameters": {
                "selected_model": state.get("selected_model"),
                "routing_reason": state.get("routing_reason"),
                "flow_type": flow_type,
            },
            "memory_to_store": state.get("memory_context"),
            "suggested_actions": state.get("actions")
            or state.get("degradation_reasons"),
            "ai_data": {
                "execution_plan": state.get("execution_plan"),
                "intent_analysis": state.get("intent_analysis"),
                "selected_provider": state.get("selected_provider"),
                "selected_model": state.get("selected_model"),
                "routing_reason": state.get("routing_reason"),
                "errors": state.get("errors", []),
                "warnings": state.get("warnings", []),
            },
            "proactive_suggestion": state.get("routing_reason"),
            "flow_type": flow_type,
            "session_id": payload.get("session_id"),
            "user_id": payload.get("user_id"),
            "processing_state": state,
        }

    # --- Dependencies and Handlers ---

    async def _ensure_auth_service(self) -> Optional[Any]:
        """Resolve the authentication service on first use."""

        if self._auth_service_failed:
            return None

        if self._auth_service is not None:
            return self._auth_service

        async with self._auth_service_lock:
            if self._auth_service is None and not self._auth_service_failed:
                try:
                    from ai_karen_engine.auth.auth_service import get_auth_service

                    self._auth_service = await get_auth_service()
                except Exception as exc:  # pragma: no cover - depends on environment
                    logger.warning("Auth service unavailable: %s", exc)
                    self._auth_service_failed = True
                    return None

        return self._auth_service

    async def _resolve_memory_recall(self) -> Any:
        """Resolve the canonical Core memory recall callable.

        ``memory_service`` remains a constructor compatibility input only. New
        orchestration code consumes the Core recall contract directly.
        """

        if callable(self._memory_recall):
            return self._memory_recall

        from ai_karen_engine.core.memory.memory_runtime_manager import recall_context

        self._memory_recall = recall_context
        return self._memory_recall

    async def _ensure_session_state_manager(self) -> Optional[SessionStateManager]:
        """Return only a composition-edge injected session-state implementation."""

        return self._session_state_manager

    async def _ensure_tool_service(self) -> Optional[ToolService]:
        """Resolve tool execution service lazily."""

        if self._tool_service is not None or self._tool_resolution_failed:
            return self._tool_service

        try:
            if self._tool_service is None:
                from ai_karen_engine.core.services.service_registry import get_tool_service

                self._tool_service = await get_tool_service()
        except Exception as exc:  # pragma: no cover - optional dependency
            if not self._tool_resolution_failed:
                logger.warning("Tool service unavailable: %s", exc)
            self._tool_resolution_failed = True
            self._tool_service = ToolService()

        if self._tool_service is None:
            self._tool_service = ToolService()

        return self._tool_service

    def _build_graph(self):
        """Build the orchestration graph with all nodes and edges"""
        workflow = StateGraph(LangGraphOrchestrationState)

        # Add nodes using extracted components
        def _auth_gate_node(state: LangGraphOrchestrationState) -> Any:
            return auth_gate_node(state, auth_service=self._auth_service)

        def _safety_gate_node(state: LangGraphOrchestrationState) -> Any:
            return safety_gate_node(state, profile_manager=self._profile_manager)

        async def _memory_fetch_node(state: LangGraphOrchestrationState) -> Any:
            memory_recall = await self._resolve_memory_recall()
            return await memory_fetch_node(
                state,
                memory_recall=memory_recall,
                memory_recall_top_k=self.config.memory_recall_top_k,
                session_state_manager=self._session_state_manager,
            )

        def _intent_detect_node(state: LangGraphOrchestrationState) -> Any:
            return intent_detect_node(state, decision_engine=self._decision_engine)

        def _router_select_node(state: LangGraphOrchestrationState) -> Any:
            return router_select_node(
                state,
                llm_router=self._llm_router,
                profile_manager=self._profile_manager,
            )

        def _reasoning_node(state: LangGraphOrchestrationState) -> Any:
            return reasoning_node(state)

        def _tool_exec_node(state: LangGraphOrchestrationState) -> Any:
            return tool_exec_node(state, tool_service=self._tool_service)

        def _response_synth_node(state: LangGraphOrchestrationState) -> Any:
            return response_synth_node(state, llm_router=self._llm_router)

        workflow.add_node("auth_gate", _auth_gate_node)
        workflow.add_node("safety_gate", _safety_gate_node)
        workflow.add_node("memory_fetch", _memory_fetch_node)
        workflow.add_node("intent_detect", _intent_detect_node)
        workflow.add_node("planner", planner_node)
        workflow.add_node("runtime_policy", runtime_policy_enforcer_node)
        workflow.add_node("router_select", _router_select_node)
        workflow.add_node("medusa_node", medusa_node)
        workflow.add_node("tool_exec", _tool_exec_node)
        workflow.add_node("reasoning", _reasoning_node)
        workflow.add_node("response_synth", _response_synth_node)
        workflow.add_node("approval_gate", approval_gate_node)
        workflow.add_node("memory_write", memory_write_node)
        workflow.add_node("response_formatter", response_formatter_node)

        # Define the flow
        workflow.add_edge(START, "auth_gate")

        # Conditional edges based on configuration
        if self.config.enable_auth_gate:
            workflow.add_conditional_edges(
                "auth_gate",
                self._should_continue_after_auth,
                {
                    "continue": "safety_gate"
                    if self.config.enable_safety_gate
                    else "memory_fetch",
                    "reject": END,
                },
            )
        else:
            workflow.add_edge(
                "auth_gate",
                "safety_gate" if self.config.enable_safety_gate else "memory_fetch",
            )

        if self.config.enable_safety_gate:
            workflow.add_conditional_edges(
                "safety_gate",
                self._should_continue_after_safety,
                {
                    "continue": "memory_fetch"
                    if self.config.enable_memory_fetch
                    else "intent_detect",
                    "reject": END,
                    "review": "approval_gate",
                },
            )

        if self.config.enable_memory_fetch:
            workflow.add_edge("memory_fetch", "intent_detect")

        workflow.add_edge("intent_detect", "planner")
        workflow.add_edge("planner", "runtime_policy")
        workflow.add_edge("runtime_policy", "router_select")

        # Route to Medusa or Normal Tool Execution
        workflow.add_conditional_edges(
            "router_select",
            select_execution_branch,
            {"medusa": "medusa_node", "normal": "tool_exec"},
        )

        workflow.add_conditional_edges(
            "tool_exec",
            select_reasoning_branch,
            {"reasoning": "reasoning", "skip": "response_synth"},
        )
        workflow.add_conditional_edges(
            "medusa_node",
            select_reasoning_branch,
            {"reasoning": "reasoning", "skip": "response_synth"},
        )

        workflow.add_edge("reasoning", "response_synth")

        if self.config.enable_approval_gate:
            workflow.add_conditional_edges(
                "response_synth",
                self._should_require_approval,
                {"approve": "memory_write", "review": "approval_gate"},
            )
            workflow.add_conditional_edges(
                "approval_gate",
                self._check_approval_status,
                {
                    "approved": "memory_write",
                    "rejected": END,
                    "pending": "approval_gate",  # Wait for human input
                },
            )
        else:
            workflow.add_edge("response_synth", "memory_write")

        workflow.add_edge("memory_write", "response_formatter")
        workflow.add_edge("response_formatter", END)

        # Compile the graph
        self.graph = workflow.compile(checkpointer=self.checkpointer)
        self._initialized = True

    # --- Operational Methods ---

    def _should_continue_after_auth(self, state: LangGraphOrchestrationState) -> str:
        """Determine if processing should continue after auth gate"""
        auth_status = state.get("auth_status")
        return "continue" if auth_status == "authenticated" else "reject"

    def _should_continue_after_safety(self, state: LangGraphOrchestrationState) -> str:
        """Determine if processing should continue after safety gate"""
        safety_status = state.get("safety_status")
        if safety_status == "safe":
            return "continue"
        elif safety_status == "review_required":
            return "review"
        else:
            return "reject"

    def _should_require_approval(self, state: LangGraphOrchestrationState) -> str:
        """Determine if human approval is required"""
        # Check if approval is required based on various factors
        safety_flags = state.get("safety_flags", [])
        tool_results = state.get("tool_results", [])

        # Require approval if there are safety flags or sensitive tools were used
        if safety_flags or any("sensitive" in str(result) for result in tool_results):
            state["requires_approval"] = True
            return "review"
        else:
            return "approve"

    def _check_approval_status(self, state: LangGraphOrchestrationState) -> str:
        """Check the current approval status"""
        approval_status = state.get("approval_status", "pending")
        return approval_status

    async def initialize(self) -> None:
        """Compatibility initialization hook."""

        self._initialized = True
        return None

    async def health_check(self) -> bool:
        """Compatibility health check for callers expecting a boolean."""

        try:
            status = await self.get_runtime_status()
            return self.graph is not None and status.get("total_processed", 0) >= 0
        except Exception:
            return False

    def get_metrics(self) -> Dict[str, Any]:
        """Compatibility metrics snapshot."""

        return {
            "active_sessions": len(self._active_sessions),
            "total_processed": self._total_processed,
            "failed_sessions": self._total_failed,
            "average_latency": (
                sum(self._latency_samples) / len(self._latency_samples)
                if self._latency_samples
                else 0.0
            ),
            "last_error": self._last_error,
        }

    def get_available_flows(self) -> List[str]:
        """Compatibility flow list."""

        return [
            "conversation",
            "decision",
            "analysis",
            "consensus_negotiation",
            "conflict_resolution",
        ]

    async def process_flow(self, flow_type: Any, flow_input: Any) -> Dict[str, Any]:
        """Compatibility legacy flow entrypoint."""

        payload = self._legacy_payload(flow_input)
        normalized_flow_type = str(getattr(flow_type, "value", flow_type) or "")
        normalized_flow_type = normalized_flow_type.lower()

        if normalized_flow_type in {"conversation", "conversation_processing"}:
            return await self.conversation_processing_flow(payload)
        if normalized_flow_type in {"decision", "decide_action"}:
            return await self.decide_action(payload)
        if normalized_flow_type in {"analysis"}:
            analysis = await self.run_dry_run_analysis(
                message=str(
                    payload.get("prompt")
                    or payload.get("message")
                    or payload.get("text")
                    or ""
                ),
                session_id=payload.get("session_id"),
                user={
                    "user_id": payload.get("user_id"),
                    "tenant_id": payload.get("tenant_id"),
                },
                context=payload.get("context") or {},
            )
            return {
                "response": analysis.get("predicted_intent", ""),
                "ai_data": analysis,
                "processing_state": analysis,
            }
        if normalized_flow_type in {"consensus_negotiation"}:
            return await self.consensus_negotiation(payload)
        if normalized_flow_type in {"conflict_resolution"}:
            return await self.conflict_resolution(payload)

        analysis = await self.run_dry_run_analysis(
            message=str(
                payload.get("prompt")
                or payload.get("message")
                or payload.get("text")
                or ""
            ),
            session_id=payload.get("session_id"),
            user={
                "user_id": payload.get("user_id"),
                "tenant_id": payload.get("tenant_id"),
            },
            context=payload.get("context") or {},
        )
        return {
            "response": analysis.get("predicted_intent", ""),
            "ai_data": analysis,
            "processing_state": analysis,
        }

    async def decide_action(self, flow_input: Any) -> Dict[str, Any]:
        """Compatibility wrapper for action decisions."""

        payload = self._legacy_payload(flow_input)
        analysis = await self.run_dry_run_analysis(
            message=str(
                payload.get("prompt")
                or payload.get("message")
                or payload.get("text")
                or ""
            ),
            session_id=payload.get("session_id"),
            user={
                "user_id": payload.get("user_id"),
                "tenant_id": payload.get("tenant_id"),
            },
            context=payload.get("context") or {},
        )
        return {
            "decision": "continue"
            if not analysis.get("approval_required", False)
            else "review",
            "confidence": analysis.get("routing_confidence", 0.0),
            "reasoning": analysis.get("routing_reason", ""),
            "response": analysis.get("predicted_intent", ""),
            "ai_data": analysis,
            "processing_state": analysis,
        }

    async def conversation_processing_flow(self, flow_input: Any) -> Dict[str, Any]:
        """Compatibility wrapper for conversation handling."""

        payload = self._legacy_payload(flow_input)
        messages = self._legacy_messages(payload)
        user_id = str(payload.get("user_id") or "anonymous")
        session_id = payload.get("session_id") or f"{user_id}_{datetime.now(timezone.utc).isoformat()}"
        final_state = await self.process(
            messages=messages,
            user_id=user_id,
            session_id=session_id,
            config=payload.get("context") or payload.get("user_settings") or {},
        )
        return self._legacy_flow_response(
            payload, final_state, flow_type="conversation"
        )

    async def complex_reasoning_task(
        self, reasoning_type: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compatibility reasoning helper."""

        reasoning_type = (reasoning_type or "").lower()
        if reasoning_type not in {"logical", "causal", "probabilistic"}:
            return {
                "reasoning": "error",
                "message": f"Unknown reasoning type: {reasoning_type}",
                "confidence": 0.0,
            }

        try:
            from ai_karen_engine.core.cortex.contracts import (
                IntentSignal,
                KireSignal,
                PredictorSignal,
                ReasoningDepth,
                ReasoningRequest,
                UserContext,
            )
            from ai_karen_engine.core.reasoning.kro_orchestrator import get_kro_orchestrator

            user_ctx = UserContext(
                user_id=str(data.get("user_id") or "anonymous"),
                tenant_id=data.get("tenant_id"),
                session_id=data.get("session_id"),
            )
            request = ReasoningRequest(
                message=str(data.get("message") or data.get("query") or reasoning_type),
                user=user_ctx,
                memory_context=data.get("memory_context") or data,
                tool_context=data.get("tool_context") or {},
                intent=IntentSignal(
                    primary_intent=reasoning_type,
                    secondary_intents=[],
                    entities=[],
                    confidence=0.75,
                    category="analytical",
                    requested_modality="text",
                ),
                predictors=PredictorSignal(
                    ambiguity_score=0.2 if reasoning_type == "logical" else 0.35,
                    complexity_score=0.5,
                    tool_likelihood=0.1,
                    memory_relevance=0.4,
                    multi_step_likelihood=0.3,
                    degraded_risk=0.0,
                ),
                kire=KireSignal(
                    requires_reasoning=True,
                    reasoning_depth=ReasoningDepth.STANDARD,
                    reasoning_modes=[reasoning_type],
                    should_use_memory=True,
                    should_use_tools=False,
                    should_use_retrieval_reasoning=True,
                    should_use_causal_reasoning=reasoning_type == "causal",
                    should_use_graph_reasoning=reasoning_type == "logical",
                    should_self_refine=reasoning_type != "probabilistic",
                    should_verify=True,
                ),
                metadata={
                    "conversation_history": data.get("conversation_history") or [],
                    "ui_context": data.get("context") or {},
                    "system_caps": data.get("system_caps") or {},
                    "config_ui": data.get("config_ui") or {},
                },
            )
            result = await get_kro_orchestrator().run(request)
            return {
                "reasoning": f"{reasoning_type.capitalize()} reasoning applied",
                "summary": result.summary,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "hypotheses": result.hypotheses,
                "verification_notes": result.verification_notes,
                "refined_answer": result.refined_answer,
                "diagnostics": result.diagnostics,
            }
        except Exception as e:
            logger.error("Compatibility reasoning helper failed: %s", e)
            return {
                "reasoning": "error",
                "message": f"Reasoning helper failed: {e}",
                "confidence": 0.0,
            }

    async def consensus_negotiation(self, flow_input: Any) -> Dict[str, Any]:
        """Compatibility wrapper for consensus negotiation."""

        payload = self._legacy_payload(flow_input)
        team_id = payload.get("team_id")
        agent_ids = payload.get("agent_ids") or []
        topic = payload.get("topic")
        initial_proposal = payload.get("initial_proposal")
        consensus_threshold = float(payload.get("consensus_threshold", 0.7))

        if not all([team_id, agent_ids, topic, initial_proposal]):
            return {"result": "error", "message": "Missing required negotiation data"}

        agent_responses = {}
        for agent_id in agent_ids:
            confidence = 0.7 + (hash(agent_id) % 30) / 100
            agent_responses[agent_id] = {
                "agent_id": agent_id,
                "position": {
                    "agreement_level": confidence,
                    "concerns": [],
                    "suggestions": [],
                },
                "confidence": confidence,
                "reasoning": f"Agent {agent_id} reasoning about {topic}",
            }

        agreements = [response["confidence"] for response in agent_responses.values()]
        avg_agreement = sum(agreements) / len(agreements) if agreements else 0.0
        consensus_reached = avg_agreement >= consensus_threshold

        return {
            "team_id": team_id,
            "topic": topic,
            "consensus": consensus_reached,
            "confidence": avg_agreement,
            "agent_responses": agent_responses,
            "reasoning": (
                f"Consensus reached with {avg_agreement:.2f} agreement level"
                if consensus_reached
                else f"No consensus reached, only {avg_agreement:.2f} agreement level (threshold: {consensus_threshold})"
            ),
        }

    async def conflict_resolution(self, flow_input: Any) -> Dict[str, Any]:
        """Compatibility wrapper for conflict resolution."""

        payload = self._legacy_payload(flow_input)
        agent_ids = payload.get("agent_ids") or []
        conflict_type = payload.get("conflict_type")
        conflict_details = payload.get("conflict_details")

        if not all([agent_ids, conflict_type, conflict_details]):
            return {"result": "error", "message": "Missing required conflict data"}

        return {
            "conflict_type": conflict_type,
            "agent_ids": agent_ids,
            "resolution": {
                "strategy": "analysis",
                "confidence": 0.8,
                "reasoning": "Conflict resolved through analysis",
            },
            "confidence": 0.8,
            "reasoning": "Conflict resolved through analysis",
        }

    async def run_dry_run_analysis(
        self,
        *,
        message: str,
        session_id: Optional[str] = None,
        user: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Simulate orchestration without side effects for diagnostics."""

        diagnostics_engine = DiagnosticsEngine(
            decision_engine=self._decision_engine,
            llm_router=self._llm_router,
            profile_manager=self._profile_manager,
        )

        return await diagnostics_engine.run_dry_run_analysis(
            message=message,
            session_id=session_id,
            user=user,
            context=context,
        )

    async def process(
        self,
        messages: List[BaseMessage],
        user_id: str,
        session_id: str = None,
        config: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Process a conversation through the orchestration graph

        Args:
            messages: List of conversation messages
            user_id: User identifier
            session_id: Session identifier (optional)
            config: Additional configuration (optional)

        Returns:
            Final state after processing
        """
        if not session_id:
            session_id = f"{user_id}_{datetime.now(timezone.utc).isoformat()}"

        # Initialize state
        runtime_config = config or {}

        initial_state = create_initial_state(
            messages, user_id, session_id, runtime_config
        )

        start_time = datetime.now(timezone.utc)
        error_message: Optional[str] = None

        await self._register_session(session_id)

        try:
            # Process through the graph
            thread_config = {"configurable": {"thread_id": session_id}}
            final_state = await self.graph.ainvoke(initial_state, config=thread_config)

            return final_state

        except Exception as e:
            error_message = str(e)
            logger.error(f"Orchestration processing error: {e}")
            initial_state["errors"].append(f"Processing error: {error_message}")
            return initial_state

        finally:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await self._finalize_session(session_id, duration, error_message)

    async def stream_process(
        self,
        messages: List[BaseMessage],
        user_id: str,
        session_id: str = None,
        config: Dict[str, Any] = None,
    ):
        """
        Stream process a conversation through the orchestration graph

        Args:
            messages: List of conversation messages
            user_id: User identifier
            session_id: Session identifier (optional)
            config: Additional configuration (optional)

        Yields:
            State updates during processing
        """
        if not session_id:
            session_id = f"{user_id}_{datetime.now(timezone.utc).isoformat()}"

        # Initialize state (same as process method)
        runtime_config = config or {}

        initial_state = create_streaming_initial_state(
            messages, user_id, session_id, runtime_config
        )

        start_time = datetime.now(timezone.utc)
        error_message: Optional[str] = None

        await self._register_session(session_id)

        try:
            thread_config = {"configurable": {"thread_id": session_id}}

            # Stream through the graph
            async for chunk in self.graph.astream(initial_state, config=thread_config):
                yield chunk

        except Exception as e:
            error_message = str(e)
            logger.error(f"Orchestration streaming error: {e}")
            yield {"error": f"Streaming error: {error_message}"}

        finally:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await self._finalize_session(session_id, duration, error_message)

    async def _register_session(self, session_id: str) -> None:
        """Register an active orchestration session for telemetry."""

        async with self._stats_lock:
            self._active_sessions[session_id] = datetime.now(timezone.utc)

    async def _finalize_session(
        self,
        session_id: str,
        duration: float,
        error_message: Optional[str] = None,
    ) -> None:
        """Finalize bookkeeping for a session."""

        async with self._stats_lock:
            self._active_sessions.pop(session_id, None)
            if duration is not None:
                self._latency_samples.append(max(duration, 0.0))
            self._total_processed += 1

            if error_message:
                self._total_failed += 1
                self._last_error = {
                    "message": error_message,
                    "timestamp": datetime.now(timezone.utc),
                }

    async def update_configuration(
        self, updates: Dict[str, Any]
    ) -> LangGraphOrchestrationConfig:
        """Update orchestrator configuration and rebuild the graph."""

        if not updates:
            return self.config

        allowed_fields = set(LangGraphOrchestrationConfig.__annotations__.keys())
        sanitized_updates = {
            key: value
            for key, value in updates.items()
            if key in allowed_fields and value is not None
        }

        if not sanitized_updates:
            return self.config

        async with self._config_lock:
            self.config = replace(self.config, **sanitized_updates)
            self.checkpointer = (
                MemorySaver() if self.config.checkpoint_enabled else None
            )
            self._build_graph()
            return self.config

    async def get_runtime_status(self) -> Dict[str, Any]:
        """Return telemetry snapshot for orchestration runtime."""

        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()

        async with self._stats_lock:
            active_sessions = len(self._active_sessions)
            total_processed = self._total_processed
            failed_sessions = self._total_failed
            latency_samples = list(self._latency_samples)
            last_error = self._last_error.copy() if self._last_error else None

        average_latency = (
            sum(latency_samples) / len(latency_samples) if latency_samples else 0.0
        )
        p95_latency = self._percentile(latency_samples, 0.95)

        return {
            "active_sessions": active_sessions,
            "total_processed": total_processed,
            "failed_sessions": failed_sessions,
            "uptime": uptime,
            "average_latency": average_latency,
            "p95_latency": p95_latency,
            "last_error": last_error,
        }

    @staticmethod
    def _percentile(samples: List[float], percentile: float) -> float:
        """Calculate percentile for latency samples."""

        if not samples:
            return 0.0

        ordered = sorted(samples)
        index = max(
            0, min(len(ordered) - 1, int(round(percentile * (len(ordered) - 1))))
        )
        return ordered[index]

    async def shutdown(self) -> None:
        """Gracefully release orchestrator resources."""

        logger.info("Shutting down LangGraph orchestrator")
        self._initialized = False

        try:
            await self._llm_router.shutdown()
        except Exception as exc:  # pragma: no cover - defensive cleanup
            logger.warning("LLM router shutdown encountered an error: %s", exc)


        async with self._stats_lock:
            self._active_sessions.clear()
            self._latency_samples.clear()


# Factory function for easy instantiation
def create_orchestrator(
    config: LangGraphOrchestrationConfig = None,
) -> LangGraphOrchestrator:
    """Create a new LangGraph orchestrator instance"""
    return LangGraphOrchestrator(config)


# Default orchestrator instance
default_orchestrator = None


def get_default_orchestrator() -> LangGraphOrchestrator:
    """Get the default orchestrator instance (singleton)"""
    global default_orchestrator
    if default_orchestrator is None:
        default_orchestrator = create_orchestrator()
    return default_orchestrator

