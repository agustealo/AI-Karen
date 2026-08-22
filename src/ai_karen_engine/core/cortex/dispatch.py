"""CORTEX decision layer.

CORTEX owns pre-runtime intelligence only:
- intent normalization
- predictor scoring
- KIRE reasoning preparation
- routing decisioning
- RBAC pre-checks

It does not execute tools, memory writes, LangGraph nodes, or plugins.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.cortex.contracts import (
    CorrelationIdFactory,
    CortexOutput,
    ExecutionMode,
    IntentSignal,
    KireSignal,
    OrchestrationInput,
    PredictorSignal,
    ReasoningDepth,
    ReasoningRequest,
    RouteFamily,
    RoutingDecision,
    RuntimeRequest,
    UserContext,
)
from ai_karen_engine.core.cortex.kire_signal_producer import KireSignalProducer
from ai_karen_engine.core.cortex.errors import CortexDispatchError
from ai_karen_engine.core.cortex.intent import resolve_intent as resolve_base_intent
from ai_karen_engine.core.cortex.routing_intents import (
    extract_routing_parameters,
    resolve_capability_decision,
    resolve_routing_intent as resolve_intent,
)

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)

try:
    from ai_karen_engine.core.cortex.rbac_validator import (
        PermissionDeniedError,
        RBACValidationError,
        validate_plugin_permission,
    )

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
    logger.warning("[CORTEX] RBAC validator not available; routing permission checks disabled")


def _build_runtime_request(
    user_ctx: Dict[str, Any],
    query: str,
    context: Optional[Dict[str, Any]] = None,
) -> RuntimeRequest:
    context = dict(context or {})
    user = UserContext(
        user_id=str(user_ctx.get("user_id", "anonymous")),
        tenant_id=user_ctx.get("tenant_id"),
        roles=list(user_ctx.get("roles", [])),
        session_id=context.get("session_id") or user_ctx.get("session_id"),
        thread_id=context.get("thread_id") or user_ctx.get("thread_id"),
    )
    return RuntimeRequest(message=query, user=user, metadata=context)


def _classify_predictors(intent: str, query: str, context: Dict[str, Any]) -> PredictorSignal:
    q = query.lower()
    route_hint = extract_routing_parameters(query)

    tool_likelihood = 0.0
    if route_hint.get("requested_provider") or route_hint.get("requested_model"):
        tool_likelihood += 0.15
    if any(token in q for token in ("tool", "execute", "run", "call", "plugin")):
        tool_likelihood += 0.5
    if any(token in q for token in ("memory", "remember", "recall", "context")):
        tool_likelihood += 0.2

    complexity = 0.1
    if any(token in q for token in ("plan", "step", "multi-step", "workflow", "design", "architecture")):
        complexity += 0.5
    if intent.startswith("routing.") or intent.startswith("reasoning."):
        complexity += 0.3

    ambiguity = 0.1
    if len(query.split()) < 5:
        ambiguity += 0.4
    if "?" not in query and len(query.split()) < 8:
        ambiguity += 0.2

    memory_relevance = 0.0
    if any(token in q for token in ("previous", "again", "that", "this", "memory", "remember")):
        memory_relevance += 0.3
    if context.get("memory_hint"):
        memory_relevance += 0.3

    multi_step = 0.0
    if complexity > 0.5:
        multi_step += 0.4
    if any(token in q for token in ("and then", "after", "before", "first", "next")):
        multi_step += 0.4

    degraded_risk = 0.0
    if any(token in q for token in ("error", "fail", "degraded", "fallback", "unavailable")):
        degraded_risk += 0.5

    return PredictorSignal(
        ambiguity_score=min(1.0, ambiguity),
        complexity_score=min(1.0, complexity),
        tool_likelihood=min(1.0, tool_likelihood),
        memory_relevance=min(1.0, memory_relevance),
        multi_step_likelihood=min(1.0, multi_step),
        degraded_risk=min(1.0, degraded_risk),
    )


def _infer_route_family(intent: str, predictors: PredictorSignal) -> RouteFamily:
    if intent.startswith("routing.") or intent.startswith("admin"):
        return RouteFamily.ADMIN
    if intent.startswith("memory"):
        return RouteFamily.MEMORY
    if intent.startswith("reasoning") or predictors.complexity_score >= 0.7:
        return RouteFamily.REASONING
    if predictors.tool_likelihood >= 0.5:
        return RouteFamily.TOOL
    if "search" in intent:
        return RouteFamily.SEARCH
    return RouteFamily.CHAT


def _build_kire_signal(
    intent: str,
    predictors: PredictorSignal,
    route_family: RouteFamily,
) -> KireSignal:
    return KireSignalProducer.produce(
        intent=IntentSignal(primary_intent=intent),
        predictors=predictors,
        route_family=route_family,
    )


def _build_routing_decision(
    intent: str,
    predictors: PredictorSignal,
    kire: KireSignal,
    route_family: RouteFamily,
) -> RoutingDecision:
    execution_mode = (
        ExecutionMode.DEGRADED
        if predictors.degraded_risk >= 0.7
        else ExecutionMode.LANGGRAPH
    )
    target_graph = "default_reasoning_graph" if route_family == RouteFamily.REASONING else "default_chat_graph"
    return RoutingDecision(
        route_family=route_family,
        execution_mode=execution_mode,
        target_graph=target_graph,
        target_service="kro_orchestrator" if route_family == RouteFamily.REASONING else None,
        target_plugin=None,
        target_agent=None,
        allow_reasoning=kire.requires_reasoning,
        allow_tools=kire.should_use_tools,
        allow_memory_read=True,
        allow_memory_write=True,
        require_approval_gate=kire.should_use_tools or route_family == RouteFamily.ADMIN,
    )


def _build_cortex_output(
    *,
    intent: IntentSignal,
    predictors: PredictorSignal,
    kire: KireSignal,
    routing: RoutingDecision,
    runtime_request: RuntimeRequest,
) -> CortexOutput:
    correlation_id = CorrelationIdFactory().create(runtime_request)
    return CortexOutput(
        intent=intent,
        predictors=predictors,
        kire=kire,
        routing=routing,
        correlation_id=correlation_id,
        audit_tags=[
            f"intent:{intent.primary_intent}",
            f"route:{routing.route_family.value}",
            f"mode:{routing.execution_mode.value}",
            f"reasoning:{kire.reasoning_depth.value}",
        ],
    )


def build_orchestration_input(
    request: RuntimeRequest,
    cortex: CortexOutput,
) -> OrchestrationInput:
    """Construct the LangGraph runtime entry contract."""
    return OrchestrationInput(
        message=request.message,
        user=request.user,
        metadata=dict(request.metadata),
        cortex=cortex,
    )


def build_reasoning_request(
    request: RuntimeRequest,
    cortex: CortexOutput,
    *,
    memory_context: Optional[Dict[str, Any]] = None,
    tool_context: Optional[Dict[str, Any]] = None,
) -> ReasoningRequest:
    """Construct the KRO entry contract."""
    return ReasoningRequest(
        message=request.message,
        user=request.user,
        memory_context=dict(memory_context or {}),
        tool_context=dict(tool_context or {}),
        intent=cortex.intent,
        predictors=cortex.predictors,
        kire=cortex.kire,
        metadata=dict(request.metadata),
    )


async def evaluate_cortex(
    user_ctx: Dict[str, Any],
    query: str,
    mode: str = "auto",
    context: Optional[Dict[str, Any]] = None,
    trace: Optional[List[Dict[str, Any]]] = None,
) -> CortexOutput:
    """Build a Cortex output contract without executing runtime actions."""
    if trace is None:
        trace = []
    runtime_request = _build_runtime_request(user_ctx, query, context)

    intent, intent_meta = resolve_intent(query, user_ctx)
    if intent == "unknown":
        fallback_intent, fallback_meta = resolve_base_intent(query, user_ctx)
        if fallback_intent != "unknown":
            intent, intent_meta = fallback_intent, fallback_meta

    trace.append({"stage": "intent_resolved", "intent": intent, "meta": intent_meta})
    capability_decision = resolve_capability_decision(
        query,
        confidence=float(intent_meta.get("confidence", 0.6)),
    )
    trace.append({"stage": "capability_resolved", "decision": capability_decision.to_dict()})

    predictors = _classify_predictors(intent, query, dict(context or {}))
    trace.append({"stage": "predictors_scored", "predictors": asdict(predictors)})

    route_family = _infer_route_family(intent, predictors)
    kire = _build_kire_signal(intent, predictors, route_family)
    routing = _build_routing_decision(intent, predictors, kire, route_family)
    trace.append(
        {
            "stage": "routing_decided",
            "route_family": route_family.value,
            "execution_mode": routing.execution_mode.value,
        }
    )

    if RBAC_AVAILABLE:
        try:
            await validate_plugin_permission(
                user_ctx,
                routing.target_plugin or routing.target_service or intent,
            )
            trace.append({"stage": "rbac_validated", "route_family": route_family.value})
        except PermissionDeniedError as pde:
            trace.append({"stage": "rbac_denied", "error": str(pde)})
            raise CortexDispatchError(str(pde)) from pde
        except RBACValidationError as rve:
            trace.append({"stage": "rbac_error", "error": str(rve)})
            raise CortexDispatchError(str(rve)) from rve

    cortex = _build_cortex_output(
        intent=IntentSignal(
            primary_intent=intent,
            subtype=capability_decision.subtype,
            secondary_intents=list(intent_meta.get("secondary_intents", [])),
            entities=list(intent_meta.get("entities", [])),
            confidence=float(intent_meta.get("confidence", 0.6)),
            category=str(intent_meta.get("category", "general")),
            requested_modality=str(intent_meta.get("requested_modality", "text")),
            requires_chat_capable_model=capability_decision.requires_chat_capable_model,
        ),
        predictors=predictors,
        kire=kire,
        routing=routing,
        runtime_request=runtime_request,
    )

    trace.append({"stage": "cortex_output_built", "correlation_id": cortex.correlation_id})
    return cortex


def _normalize(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


async def dispatch(
    user_ctx: Dict[str, Any],
    query: str,
    mode: str = "auto",
    context: Optional[Dict[str, Any]] = None,
    memory_enabled: bool = True,
    plugin_enabled: bool = True,
    predictor_enabled: bool = True,
    trace: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Backward-compatible wrapper that returns a serialized Cortex decision package."""
    if trace is None:
        trace = []
    try:
        cortex = await evaluate_cortex(
            user_ctx=user_ctx,
            query=query,
            mode=mode,
            context=context,
            trace=trace,
        )

        return {
            "intent": cortex.intent.primary_intent,
            "confidence": cortex.intent.confidence,
            "capability_decision": _normalize(resolve_capability_decision(query, confidence=cortex.intent.confidence).to_dict()),
            "route_family": cortex.routing.route_family.value,
            "execution_mode": cortex.routing.execution_mode.value,
            "requires_reasoning": cortex.kire.requires_reasoning,
            "cortex": _normalize(asdict(cortex)),
            "trace": trace,
        }

    except Exception as ex:
        trace.append({"stage": "dispatch_error", "error": str(ex)})
        raise CortexDispatchError(f"CORTEX dispatch failed: {ex}") from ex


__all__ = [
    "build_orchestration_input",
    "build_reasoning_request",
    "dispatch",
    "evaluate_cortex",
    "CortexDispatchError",
]
