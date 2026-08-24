from typing import (
    Dict,
    Any,
    List,
    Optional,
    TypedDict,
    cast,
)
from langchain_core.messages import BaseMessage
from ai_karen_engine.core.model_runtime.runtime_contracts import (
    ProviderRouteDecision,
    ProviderExecutionResult,
)


class LangGraphOrchestrationState(TypedDict):
    """Typed state for orchestration graph"""

    # Input/Output
    messages: List[BaseMessage]
    user_id: str
    session_id: str
    tenant_id: Optional[str]

    # Authentication & Authorization
    auth_status: Optional[str]  # "authenticated", "failed", "pending"
    user_permissions: Optional[Dict[str, Any]]
    auth_context: Optional[Dict[str, Any]]
    user_profile: Optional[Dict[str, Any]]

    # Safety & Guardrails
    safety_status: Optional[str]  # "safe", "unsafe", "review_required"
    safety_flags: Optional[List[str]]
    safety_evaluation: Optional[Dict[str, Any]]

    # Memory & Context
    memory_context: Optional[Dict[str, Any]]
    context_sources: Optional[Dict[str, Any]]
    saved_contexts: Optional[List[Dict[str, Any]]]
    conversation_history: Optional[List[Dict[str, Any]]]

    # Intent & Planning
    detected_intent: Optional[str]
    intent_confidence: Optional[float]
    execution_plan: Optional[Dict[str, Any]]
    intent_analysis: Optional[Dict[str, Any]]
    reasoning_hints: Optional[Dict[str, Any]]
    reasoning_result: Optional[Dict[str, Any]]
    reasoning_metadata: Optional[Dict[str, Any]]

    # Routing & Execution
    selected_provider: Optional[str]
    selected_model: Optional[str]
    routing_reason: Optional[str]
    route_decision: Optional[ProviderRouteDecision]
    execution_result: Optional[ProviderExecutionResult]
    tool_calls: Optional[List[Dict[str, Any]]]
    tool_results: Optional[List[Dict[str, Any]]]
    tool_execution_metadata: Optional[Dict[str, Any]]

    # Response Generation
    response: Optional[str]
    response_metadata: Optional[Dict[str, Any]]
    llm_response: Optional[str]
    llm_metadata: Optional[Dict[str, Any]]

    # Salvaged from Legacy ChatOrchestrator
    structured_content: Optional[Dict[str, Any]]
    actions: Optional[List[Dict[str, Any]]]
    telemetry: Optional[Dict[str, Any]]
    formatting_payload: Optional[Dict[str, Any]]
    formatted_response: Optional[str]

    # Human-in-the-loop
    requires_approval: Optional[bool]
    approval_status: Optional[str]  # "pending", "approved", "rejected"
    approval_reason: Optional[str]

    # Error Handling
    errors: List[str]
    warnings: List[str]

    # Streaming Support
    streaming_enabled: Optional[bool]
    stream_chunks: Optional[List[str]]
    request_config: Optional[Dict[str, Any]]

    # Medusa Extensions
    agent_trace: Optional[List[str]]
    medusa_status: Optional[str]
    runtime_policy: Optional[Dict[str, Any]]

    # Degraded Mode Support
    degraded_mode: bool
    degradation_reasons: List[str]
    fallbacks_applied: List[str]

    # File Upload Support
    uploaded_files: Optional[List[Dict[str, Any]]]
    file_context: Optional[Dict[str, Any]]


def create_initial_state(
    messages: List[BaseMessage],
    user_id: str,
    session_id: str,
    config: Optional[Dict[str, Any]] = None,
) -> LangGraphOrchestrationState:
    """Centralized factory for creating initial state"""
    runtime_config = config or {}
    return {
        "messages": messages,
        "user_id": user_id,
        "session_id": session_id,
        "tenant_id": None,
        "auth_status": None,
        "user_permissions": None,
        "auth_context": cast(Dict[str, Any], runtime_config.get("auth_context") or {}),
        "user_profile": None,
        "safety_status": None,
        "safety_flags": None,
        "safety_evaluation": None,
        "memory_context": None,
        "context_sources": None,
        "saved_contexts": None,
        "conversation_history": None,
        "detected_intent": None,
        "intent_confidence": None,
        "execution_plan": None,
        "intent_analysis": None,
        "reasoning_hints": None,
        "reasoning_result": None,
        "reasoning_metadata": None,
        "selected_provider": None,
        "selected_model": None,
        "routing_reason": None,
        "route_decision": None,
        "execution_result": None,
        "tool_calls": None,
        "tool_results": None,
        "tool_execution_metadata": None,
        "response": None,
        "response_metadata": None,
        "llm_response": None,
        "llm_metadata": None,
        "requires_approval": None,
        "approval_status": None,
        "approval_reason": None,
        "errors": [],
        "warnings": [],
        "streaming_enabled": bool(runtime_config.get("streaming_enabled", False)),
        "stream_chunks": None,
        "request_config": runtime_config,
        # Degraded mode fields
        "degraded_mode": False,
        "degradation_reasons": [],
        "fallbacks_applied": [],
        # File upload fields
        "uploaded_files": None,
        "file_context": None,
        # Other salvaged fields
        "structured_content": None,
        "actions": None,
        "telemetry": None,
        "formatting_payload": None,
        "formatted_response": None,
        "agent_trace": None,
        "medusa_status": None,
        "runtime_policy": runtime_config.get("runtime_policy"),
    }


def create_streaming_initial_state(
    messages: List[BaseMessage],
    user_id: str,
    session_id: str,
    config: Optional[Dict[str, Any]] = None,
) -> LangGraphOrchestrationState:
    """Factory for streaming initial state (sets streaming_enabled=True)"""
    state = create_initial_state(messages, user_id, session_id, config)
    state["streaming_enabled"] = True
    state["stream_chunks"] = []
    return state


def merge_state_error(
    state: LangGraphOrchestrationState, error: str
) -> LangGraphOrchestrationState:
    """Append error to state"""
    state.setdefault("errors", []).append(error)
    return state


def append_warning(
    state: LangGraphOrchestrationState, warning: str
) -> LangGraphOrchestrationState:
    """Append warning to state"""
    state.setdefault("warnings", []).append(warning)
    return state


def append_agent_trace(
    state: LangGraphOrchestrationState, trace: str
) -> LangGraphOrchestrationState:
    """Append agent trace"""
    state.setdefault("agent_trace", []).append(trace)
    return state
