"""
FastAPI routes for LangGraph/AI flow orchestration.

Boundary contract:
- This router is a thin API ingress for explicit AI flow operations.
- Normal user chat should use the canonical chat runtime route, not this router.
- LangGraph is used here for deep/structured flows only.
- Provider routing, prompt construction, memory recall, tool execution, and fallback
  policy must remain inside runtime/orchestrator services, not inside routes.
"""

# Import pydantic with fallback to stub for type checking

from __future__ import annotations

import asyncio
import hashlib
import inspect
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

if TYPE_CHECKING:
    from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from pydantic import (
        BaseModel,
        ConfigDict,
        Field,
        field_validator,
    )
except ImportError:  # pragma: no cover - runtime fallback for pydantic_stub envs
    from ai_karen_engine.pydantic_stub import (
        BaseModel,
        ConfigDict,
        Field,
        field_validator,
    )

from ai_karen_engine.core.langgraph_orchestrator import (
    LangGraphOrchestrator as AIOrchestrator,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.services.dependencies import (
    get_langgraph_orchestrator_service,
)
from ai_karen_engine.models.shared_types import FlowType
from ai_karen_engine.models.web_api_error_responses import (
    WebAPIErrorCode,
    create_service_error_response,
    get_http_status_for_error_code,
)
from ai_karen_engine.utils.flow_helpers import build_flow_input, format_flow_response

router = APIRouter(prefix="/ai", tags=["ai-orchestrator"])
logger = get_logger(__name__)

MAX_PROMPT_LENGTH = 10_000
MAX_HISTORY_ITEMS = 200
MAX_BATCH_SIZE = 50
FLOW_STATUS_TTL_SECONDS = 3_600


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _safe_request_id(request: Request | None = None) -> str:
    if request is None:
        return str(uuid.uuid4())

    for header_name in ("x-request-id", "x-correlation-id", "traceparent"):
        header_value = request.headers.get(header_name)
        if header_value:
            return header_value[:128]

    return str(uuid.uuid4())


def _safe_correlation_id(request: Request | None = None) -> str:
    if request is None:
        return str(uuid.uuid4())

    header_value = request.headers.get("x-correlation-id")
    if header_value:
        return header_value[:128]

    request_id = request.headers.get("x-request-id")
    if request_id:
        return request_id[:128]

    return str(uuid.uuid4())


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _normalize_prompt(value: str) -> str:
    if value is None:
        raise ValueError("Prompt is required")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Prompt cannot be empty or whitespace only")

    if len(cleaned) > MAX_PROMPT_LENGTH:
        raise ValueError(f"Prompt cannot exceed {MAX_PROMPT_LENGTH} characters")

    return cleaned


def _normalize_context(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not value:
        return {}

    return dict(value)


def _get_actor_user_id(request_body_user_id: Optional[str], http_request: Request) -> str:
    """
    Temporary compatibility resolver.

    Replace with canonical auth dependency when the route is wired to the central
    auth/session context. Do not use this to authorize privileged actions.
    """
    if request_body_user_id and request_body_user_id.strip():
        return request_body_user_id.strip()

    header_user = http_request.headers.get("x-user-id")
    if header_user and header_user.strip():
        return header_user.strip()[:128]

    return "anonymous"


def _get_actor_tenant_id(context: Mapping[str, Any], http_request: Request) -> Optional[str]:
    header_tenant = http_request.headers.get("x-tenant-id")
    if header_tenant and header_tenant.strip():
        return header_tenant.strip()[:128]

    tenant_from_context = context.get("tenant_id")
    if isinstance(tenant_from_context, str) and tenant_from_context.strip():
        return tenant_from_context.strip()[:128]

    return None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _public_error(
    *,
    service_name: str,
    error: Exception,
    error_code: WebAPIErrorCode,
    user_message: str,
    correlation_id: str,
) -> HTTPException:
    error_response = create_service_error_response(
        service_name=service_name,
        error=error,
        error_code=error_code,
        user_message=user_message,
    )

    detail = error_response.model_dump(mode="json")
    if isinstance(detail, dict):
        detail.setdefault("correlation_id", correlation_id)

    return HTTPException(
        status_code=get_http_status_for_error_code(error_code),
        detail=detail,
    )


def _model_dump(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return {}


def _set_extra_field(model: Any, key: str, value: Any) -> None:
    try:
        setattr(model, key, value)
    except Exception:
        pass


class _PromptValidatedModel(BaseModel):
    """Base model with prompt validation if field_validator is available."""
    model_config = ConfigDict(extra="forbid")

    if field_validator is not None:
        # Only add the validator if field_validator is available
        _validate_prompt = field_validator("prompt")(_normalize_prompt)


class ProcessFlowRequest(_PromptValidatedModel):
    """Request model for processing explicit AI flows."""

    flow_type: FlowType = Field(..., description="Type of flow to process")
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    user_settings: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class DecideActionRequest(_PromptValidatedModel):
    """Request model for decision-only flow."""

    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    user_settings: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class ConversationProcessingRequest(_PromptValidatedModel):
    """
    Legacy/deep conversation flow request.

    Normal chat should prefer the canonical chat runtime endpoints. This endpoint
    remains for explicit LangGraph conversation-processing flows.
    """

    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    user_settings: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    include_memories: bool = True
    include_insights: bool = True
    llm_preferences: Optional[Dict[str, str]] = None
    stream_response: bool = False
    max_tokens: Optional[int] = Field(
        None,
        ge=1,
        description="Requested tokens to generate; provider/model caps are enforced downstream.",
    )
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)


class FlowResponse(BaseModel):
    """Response model for AI flow processing."""

    model_config = ConfigDict(extra="allow")

    response: str = Field(..., description="Generated response text")
    requires_plugin: bool = False
    plugin_to_execute: Optional[str] = None
    plugin_parameters: Optional[Dict[str, Any]] = None
    memory_to_store: Optional[Dict[str, Any]] = None
    suggested_actions: Optional[List[str]] = None
    ai_data: Optional[Dict[str, Any]] = None
    proactive_suggestion: Optional[str] = None
    processing_time_ms: Optional[int] = None
    model_used: Optional[str] = None
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    token_usage: Optional[Dict[str, int]] = None
    fallback_chain_used: Optional[List[str]] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    runtime_metadata: Optional[Dict[str, Any]] = None


class AvailableFlowsResponse(BaseModel):
    flows: List[Dict[str, Any]]
    total_count: int
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None


class FlowMetricsResponse(BaseModel):
    total_flows_processed: int
    flows_by_type: Dict[str, int]
    average_processing_time: float
    success_rate: float
    error_rate: float
    recent_activity: List[Dict[str, Any]]
    model_performance: Optional[Dict[str, Any]] = None
    cache_hit_rate: Optional[float] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None


class BatchProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: List[ProcessFlowRequest] = Field(
        ...,
        min_items=1,
        max_items=MAX_BATCH_SIZE,
        description="Batch of flow requests",
    )
    parallel: bool = False
    fail_fast: bool = False


class BatchProcessResponse(BaseModel):
    results: List[FlowResponse]
    errors: List[Dict[str, Any]]
    total_processed: int
    total_succeeded: int
    total_failed: int
    total_processing_time_ms: int
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None


class CancelFlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: str = Field(..., min_length=1, max_length=256)
    session_id: Optional[str] = None


class FlowStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStatusResponse(BaseModel):
    flow_id: str
    status: FlowStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[FlowResponse] = None
    error: Optional[str] = None
    progress: Optional[float] = Field(None, ge=0.0, le=1.0)
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None


# Compatibility-only local status cache.
# Production tracking belongs in the runtime/job service with Redis/Postgres TTL.
_flow_status_store: Dict[str, FlowStatusResponse] = {}


def _create_flow_id(prompt: str, request_id: str) -> str:
    return f"flow_{int(_utc_now().timestamp() * 1000)}_{_hash_prompt(prompt)}_{request_id[:8]}"


def _cleanup_old_flow_status() -> None:
    now = _utc_now()
    expired: List[str] = []

    for flow_id, flow_status in _flow_status_store.items():
        completed_at = flow_status.completed_at
        if completed_at is None:
            continue

        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)

        if (now - completed_at).total_seconds() > FLOW_STATUS_TTL_SECONDS:
            expired.append(flow_id)

    for flow_id in expired:
        _flow_status_store.pop(flow_id, None)


def _build_common_context(
    *,
    request_context: Optional[Dict[str, Any]],
    http_request: Request,
    request_id: str,
    correlation_id: str,
    user_id: str,
    tenant_id: Optional[str],
) -> Dict[str, Any]:
    context = _normalize_context(request_context)
    context.update(
        {
            "request_id": request_id,
            "correlation_id": correlation_id,
            "user_id": user_id,
        }
    )

    if tenant_id:
        context["tenant_id"] = tenant_id

    return context


def _build_flow_input_from_request(
    *,
    request_body: ProcessFlowRequest | DecideActionRequest | ConversationProcessingRequest,
    http_request: Request,
    request_id: str,
    correlation_id: str,
    extra_context: Optional[Dict[str, Any]] = None,
):
    context = _normalize_context(request_body.context)
    if extra_context:
        context.update(extra_context)

    user_id = _get_actor_user_id(getattr(request_body, "user_id", None), http_request)
    tenant_id = _get_actor_tenant_id(context, http_request)

    context = _build_common_context(
        request_context=context,
        http_request=http_request,
        request_id=request_id,
        correlation_id=correlation_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )

    return build_flow_input(
        prompt=_normalize_prompt(request_body.prompt),
        conversation_history=list(request_body.conversation_history or [])[:MAX_HISTORY_ITEMS],
        user_settings=dict(request_body.user_settings or {}),
        context=context,
        session_id=request_body.session_id,
        user_id=user_id,
    )


def _apply_legacy_user_settings(flow_input: Any, user_settings: Mapping[str, Any]) -> None:
    personality_tone = user_settings.get("personality_tone")
    personality_verbosity = user_settings.get("personality_verbosity")
    memory_depth = user_settings.get("memory_depth")

    tone_mapping = {
        "friendly": "friendly",
        "professional": "formal",
        "casual": "friendly",
        "neutral": "neutral",
        "formal": "formal",
        "humorous": "humorous",
    }

    depth_mapping = {
        "minimal": "short",
        "medium": "medium",
        "comprehensive": "long",
        "short": "short",
        "long": "long",
    }

    if personality_tone:
        _set_extra_field(
            flow_input,
            "personality_tone",
            tone_mapping.get(str(personality_tone), personality_tone),
        )

    if personality_verbosity:
        _set_extra_field(flow_input, "personality_verbosity", personality_verbosity)

    if memory_depth:
        _set_extra_field(
            flow_input,
            "memory_depth",
            depth_mapping.get(str(memory_depth), memory_depth),
        )


def _build_flow_response(
    *,
    result: Any,
    processing_time_ms: int,
    request_id: str,
    correlation_id: str,
) -> FlowResponse:
    payload = format_flow_response(result, processing_time_ms)
    response = FlowResponse(**payload)

    response.request_id = request_id
    response.correlation_id = correlation_id

    if hasattr(result, "token_usage") and getattr(result, "token_usage"):
        response.token_usage = getattr(result, "token_usage")

    if hasattr(result, "fallback_chain") and getattr(result, "fallback_chain"):
        response.fallback_chain_used = getattr(result, "fallback_chain")

    if hasattr(result, "runtime_metadata") and getattr(result, "runtime_metadata"):
        response.runtime_metadata = getattr(result, "runtime_metadata")

    return response


@router.post("/process-flow", response_model=FlowResponse, status_code=status.HTTP_200_OK)
async def process_flow(
    http_request: Request,
    request: ProcessFlowRequest,
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Process an explicit AI flow through the LangGraph/deep-flow orchestrator."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)
    flow_id = _create_flow_id(request.prompt, request_id)

    _flow_status_store[flow_id] = FlowStatusResponse(
        flow_id=flow_id,
        status=FlowStatus.PROCESSING,
        started_at=_utc_now(),
        progress=0.0,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    try:
        flow_input = _build_flow_input_from_request(
            request_body=request,
            http_request=http_request,
            request_id=request_id,
            correlation_id=correlation_id,
        )

        _flow_status_store[flow_id].progress = 0.35

        start_time = _utc_now()
        result = await langgraph_orchestrator.process_flow(request.flow_type, flow_input)
        processing_time_ms = int((_utc_now() - start_time).total_seconds() * 1000)

        response = _build_flow_response(
            result=result,
            processing_time_ms=processing_time_ms,
            request_id=request_id,
            correlation_id=correlation_id,
        )

        _flow_status_store[flow_id].status = FlowStatus.COMPLETED
        _flow_status_store[flow_id].completed_at = _utc_now()
        _flow_status_store[flow_id].progress = 1.0
        _flow_status_store[flow_id].result = response
        _cleanup_old_flow_status()

        return response

    except Exception as exc:
        logger.exception(
            "Failed to process AI flow",
            error=str(exc),
            flow_id=flow_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

        flow_status = _flow_status_store.get(flow_id)
        if flow_status:
            flow_status.status = FlowStatus.FAILED
            flow_status.completed_at = _utc_now()
            flow_status.error = "AI flow processing failed"

        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to process AI flow. Please try again.",
            correlation_id=correlation_id,
        )


@router.post("/decide-action", response_model=FlowResponse)
async def decide_action(
    http_request: Request,
    request: DecideActionRequest,
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Run the decision-only flow."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        flow_input = _build_flow_input_from_request(
            request_body=request,
            http_request=http_request,
            request_id=request_id,
            correlation_id=correlation_id,
        )

        start_time = _utc_now()
        result = await langgraph_orchestrator.decide_action(flow_input)
        processing_time_ms = int((_utc_now() - start_time).total_seconds() * 1000)

        return _build_flow_response(
            result=result,
            processing_time_ms=processing_time_ms,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    except Exception as exc:
        logger.exception(
            "Failed to process decide action",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to process decision action. Please try again.",
            correlation_id=correlation_id,
        )


@router.head("/conversation-processing")
async def conversation_processing_head() -> Response:
    """Compatibility HEAD endpoint for conversation-processing availability checks."""
    return Response(status_code=status.HTTP_200_OK)


@router.post("/conversation-processing", response_model=FlowResponse)
async def conversation_processing(
    http_request: Request,
    request: ConversationProcessingRequest,
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """
    Process a legacy/deep conversation flow.

    Normal chat should go through the canonical chat runtime. This endpoint remains
    for explicit LangGraph conversation-processing callers.
    """
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        extra_context: Dict[str, Any] = {
            "include_memories": request.include_memories,
            "include_insights": request.include_insights,
            "stream_response": request.stream_response,
            "route_scope": "langgraph_conversation_processing",
        }

        if request.llm_preferences:
            extra_context["llm_preferences"] = dict(request.llm_preferences)

        if request.max_tokens is not None:
            extra_context["max_tokens"] = request.max_tokens

        if request.temperature is not None:
            extra_context["temperature"] = request.temperature

        flow_input = _build_flow_input_from_request(
            request_body=request,
            http_request=http_request,
            request_id=request_id,
            correlation_id=correlation_id,
            extra_context=extra_context,
        )

        _apply_legacy_user_settings(flow_input, request.user_settings or {})

        start_time = _utc_now()
        result = await langgraph_orchestrator.conversation_processing_flow(flow_input)
        processing_time_ms = int((_utc_now() - start_time).total_seconds() * 1000)

        return _build_flow_response(
            result=result,
            processing_time_ms=processing_time_ms,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    except Exception as exc:
        logger.exception(
            "Failed to process conversation flow",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to process conversation. Please try again.",
            correlation_id=correlation_id,
        )


@router.get("/flows", response_model=AvailableFlowsResponse)
async def get_available_flows(
    http_request: Request,
    flow_type_filter: Optional[FlowType] = Query(None, description="Filter by flow type"),
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Get available explicit AI flow types."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        flows: List[Dict[str, Any]] = []

        for flow_type in FlowType:
            if flow_type_filter and flow_type != flow_type_filter:
                continue

            flows.append(
                {
                    "type": flow_type.value,
                    "name": flow_type.value.replace("_", " ").title(),
                    "description": _get_flow_description(flow_type),
                    "parameters": _get_flow_parameters(flow_type),
                    "is_enabled": await _is_flow_enabled(langgraph_orchestrator, flow_type),
                    "estimated_time_ms": _get_estimated_processing_time(flow_type),
                }
            )

        return AvailableFlowsResponse(
            flows=flows,
            total_count=len(flows),
            request_id=request_id,
            correlation_id=correlation_id,
        )

    except Exception as exc:
        logger.exception(
            "Failed to get available flows",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to get available AI flows. Please try again.",
            correlation_id=correlation_id,
        )


@router.get("/metrics", response_model=FlowMetricsResponse)
async def get_flow_metrics(
    http_request: Request,
    time_range_hours: int = Query(24, ge=1, le=168),
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Get AI flow metrics."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        metrics = await _maybe_await(
            langgraph_orchestrator.get_metrics(time_range_hours=time_range_hours)
        )

        return FlowMetricsResponse(
            total_flows_processed=metrics.get("total_flows_processed", 0),
            flows_by_type=metrics.get("flows_by_type", {}),
            average_processing_time=metrics.get("average_processing_time", 0.0),
            success_rate=metrics.get("success_rate", 0.0),
            error_rate=metrics.get("error_rate", 0.0),
            recent_activity=metrics.get("recent_activity", []),
            model_performance=metrics.get("model_performance"),
            cache_hit_rate=metrics.get("cache_hit_rate"),
            request_id=request_id,
            correlation_id=correlation_id,
        )

    except Exception as exc:
        logger.exception(
            "Failed to get AI flow metrics",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to get AI orchestrator metrics. Please try again.",
            correlation_id=correlation_id,
        )


@router.post("/batch-process", response_model=BatchProcessResponse)
async def batch_process_flows(
    http_request: Request,
    request: BatchProcessRequest,
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Process multiple explicit flow requests."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)
    start_time = _utc_now()

    results: List[FlowResponse] = []
    errors: List[Dict[str, Any]] = []

    async def run_single(index: int, req: ProcessFlowRequest) -> FlowResponse:
        return await _process_single_flow(
            request=req,
            orchestrator=langgraph_orchestrator,
            http_request=http_request,
            request_id=f"{request_id}:{index}",
            correlation_id=correlation_id,
        )

    try:
        if request.parallel:
            tasks = [run_single(index, req) for index, req in enumerate(request.requests)]
            batch_results = await asyncio.gather(*tasks, return_exceptions=not request.fail_fast)

            for index, item in enumerate(batch_results):
                if isinstance(item, Exception):
                    errors.append({"index": index, "error": "Flow processing failed"})
                    if request.fail_fast:
                        raise item
                else:
                    results.append(item)
        else:
            for index, req in enumerate(request.requests):
                try:
                    results.append(await run_single(index, req))
                except Exception as exc:
                    errors.append({"index": index, "error": "Flow processing failed"})
                    if request.fail_fast:
                        raise exc

        total_time_ms = int((_utc_now() - start_time).total_seconds() * 1000)

        return BatchProcessResponse(
            results=results,
            errors=errors,
            total_processed=len(request.requests),
            total_succeeded=len(results),
            total_failed=len(errors),
            total_processing_time_ms=total_time_ms,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    except Exception as exc:
        logger.exception(
            "Batch processing failed",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Batch processing failed. Please try again.",
            correlation_id=correlation_id,
        )


@router.get("/flow-status/{flow_id}", response_model=FlowStatusResponse)
async def get_flow_status(flow_id: str):
    """
    Get compatibility status for a flow execution.

    Production status should be migrated to runtime/job persistence with TTL.
    """
    _cleanup_old_flow_status()

    flow_status = _flow_status_store.get(flow_id)
    if not flow_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found")

    return flow_status


@router.post("/cancel-flow")
async def cancel_flow(
    http_request: Request,
    request: CancelFlowRequest,
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Cancel a running flow if the orchestrator supports cancellation."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        flow_status = _flow_status_store.get(request.flow_id)
        if not flow_status:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found")

        if flow_status.status not in {FlowStatus.PENDING, FlowStatus.PROCESSING}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Flow cannot be cancelled in its current state",
            )

        if not hasattr(langgraph_orchestrator, "cancel_flow"):
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Flow cancellation is not supported by this orchestrator",
            )

        cancelled = await langgraph_orchestrator.cancel_flow(request.flow_id, request.session_id)

        if not cancelled:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel flow",
            )

        flow_status.status = FlowStatus.CANCELLED
        flow_status.completed_at = _utc_now()
        flow_status.progress = 1.0

        return {
            "status": "cancelled",
            "flow_id": request.flow_id,
            "request_id": request_id,
            "correlation_id": correlation_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to cancel flow",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to cancel flow. Please try again.",
            correlation_id=correlation_id,
        )


async def _generate_starter_prompts(assistant_type: Optional[str] = None) -> Dict[str, Any]:
    starter_prompts_by_type = {
        "general": [
            "Search the internet for the latest AI model runtime news",
            "Summarize my recent conversation",
            "Help me organize my next task",
            "What can you help me with?",
            "Show me my recent conversations",
        ],
        "personal_assistant": [
            "Set a reminder for tomorrow at 9 AM",
            "What's on my calendar today?",
            "Create a shopping list",
            "Search the internet for current traffic conditions",
            "Help me plan my week",
        ],
        "coding": [
            "Help me debug this Python function",
            "Explain this algorithm",
            "Generate a React component",
            "Optimize this SQL query",
            "Write unit tests for this class",
        ],
        "research": [
            "Search the internet for the latest vLLM CUDA guidance",
            "Run a deep research pass on local-first AI runtimes",
            "Find current documentation for FastAPI streaming",
            "Compare recent model-serving options",
        ],
    }

    normalized_type = (assistant_type or "general").strip().lower()
    prompts = starter_prompts_by_type.get(normalized_type, starter_prompts_by_type["general"])

    return {
        "prompts": prompts,
        "assistant_type": normalized_type,
        "timestamp": _iso_now(),
    }


@router.get("/generate-starter")
async def generate_starter_prompts_get(
    assistant_type: Optional[str] = Query(None, description="Type of assistant"),
):
    """Generate starter prompts for the web UI."""
    return await _generate_starter_prompts(assistant_type)


@router.post("/generate-starter")
async def generate_starter_prompts_post(body: Optional[Dict[str, Any]] = None):
    """Generate starter prompts for the web UI."""
    assistant_type = None
    if body:
        assistant_type = body.get("assistant_type") or body.get("assistantType")
    return await _generate_starter_prompts(assistant_type)


@router.get("/health")
async def health_check(
    http_request: Request,
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Health check for the LangGraph/deep-flow orchestrator."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        if hasattr(langgraph_orchestrator, "health_check"):
            health_result = await langgraph_orchestrator.health_check()
            if isinstance(health_result, dict):
                health_result.setdefault("request_id", request_id)
                health_result.setdefault("correlation_id", correlation_id)
            return health_result

        if hasattr(langgraph_orchestrator, "test_connectivity"):
            connected = await langgraph_orchestrator.test_connectivity()
        else:
            connected = True

        return {
            "status": "healthy" if connected else "degraded",
            "service": "langgraph_orchestrator",
            "timestamp": _iso_now(),
            "components": {
                "llm_providers": await _check_llm_providers(langgraph_orchestrator),
                "memory_store": await _check_memory_store(langgraph_orchestrator),
                "plugin_system": await _check_plugin_system(langgraph_orchestrator),
            },
            "request_id": request_id,
            "correlation_id": correlation_id,
        }

    except Exception as exc:
        logger.exception(
            "AI orchestrator health check failed",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return {
            "status": "unhealthy",
            "service": "langgraph_orchestrator",
            "timestamp": _iso_now(),
            "error": "health_check_failed",
            "request_id": request_id,
            "correlation_id": correlation_id,
        }


@router.get("/models")
async def get_available_models(
    http_request: Request,
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """
    Get models exposed by the LangGraph orchestrator compatibility surface.

    Provider/model registry remains the canonical owner for model availability.
    """
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        if not hasattr(langgraph_orchestrator, "get_available_models"):
            return {
                "models": [],
                "default_model": None,
                "status": "not_supported",
                "timestamp": _iso_now(),
                "request_id": request_id,
                "correlation_id": correlation_id,
            }

        models = await _maybe_await(langgraph_orchestrator.get_available_models())
        default_model = None
        if hasattr(langgraph_orchestrator, "get_default_model"):
            default_model = await _maybe_await(langgraph_orchestrator.get_default_model())

        return {
            "models": models,
            "default_model": default_model,
            "timestamp": _iso_now(),
            "request_id": request_id,
            "correlation_id": correlation_id,
        }

    except Exception as exc:
        logger.exception(
            "Failed to get available models",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to get available models. Please try again.",
            correlation_id=correlation_id,
        )


@router.post("/clear-cache")
async def clear_cache(
    http_request: Request,
    cache_type: Optional[str] = Query(None, description="Type of cache to clear"),
    langgraph_orchestrator: AIOrchestrator = Depends(get_langgraph_orchestrator_service),
):
    """Clear orchestrator cache if supported."""
    request_id = _safe_request_id(http_request)
    correlation_id = _safe_correlation_id(http_request)

    try:
        cache_type_value = (cache_type or "all").strip().lower()
        if cache_type_value not in {"model", "memory", "flow", "all"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cache_type must be one of: model, memory, flow, all",
            )

        if not hasattr(langgraph_orchestrator, "clear_cache"):
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Cache clearing is not supported by this orchestrator",
            )

        result = await langgraph_orchestrator.clear_cache(cache_type_value)

        return {
            "status": "success",
            "cache_type_cleared": cache_type_value,
            "details": result,
            "request_id": request_id,
            "correlation_id": correlation_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to clear orchestrator cache",
            error=str(exc),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        raise _public_error(
            service_name="langgraph_orchestrator",
            error=exc,
            error_code=WebAPIErrorCode.AI_ORCHESTRATOR_ERROR,
            user_message="Failed to clear cache. Please try again.",
            correlation_id=correlation_id,
        )


async def _process_single_flow(
    *,
    request: ProcessFlowRequest,
    orchestrator: AIOrchestrator,
    http_request: Request,
    request_id: str,
    correlation_id: str,
) -> FlowResponse:
    flow_input = _build_flow_input_from_request(
        request_body=request,
        http_request=http_request,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    start_time = _utc_now()
    result = await orchestrator.process_flow(request.flow_type, flow_input)
    processing_time_ms = int((_utc_now() - start_time).total_seconds() * 1000)

    return _build_flow_response(
        result=result,
        processing_time_ms=processing_time_ms,
        request_id=request_id,
        correlation_id=correlation_id,
    )


async def _is_flow_enabled(orchestrator: AIOrchestrator, flow_type: FlowType) -> bool:
    if hasattr(orchestrator, "is_flow_enabled"):
        return bool(await _maybe_await(orchestrator.is_flow_enabled(flow_type)))
    return True


def _get_estimated_processing_time(flow_type: FlowType) -> int:
    estimates = {
        FlowType.DECIDE_ACTION: 500,
        FlowType.CONVERSATION_PROCESSING: 1_500,
        FlowType.CONVERSATION_SUMMARY: 800,
        FlowType.GENERATE_FINAL_RESPONSE: 300,
    }
    return estimates.get(flow_type, 1_000)


async def _check_llm_providers(orchestrator: AIOrchestrator) -> Dict[str, Any]:
    if hasattr(orchestrator, "check_llm_providers"):
        return await _maybe_await(orchestrator.check_llm_providers())
    return {"status": "unknown", "reason": "not_supported"}


async def _check_memory_store(orchestrator: AIOrchestrator) -> Dict[str, Any]:
    if hasattr(orchestrator, "check_memory_store"):
        return await _maybe_await(orchestrator.check_memory_store())
    return {"status": "unknown", "reason": "not_supported"}


async def _check_plugin_system(orchestrator: AIOrchestrator) -> Dict[str, Any]:
    if hasattr(orchestrator, "check_plugin_system"):
        return await _maybe_await(orchestrator.check_plugin_system())
    return {"status": "unknown", "reason": "not_supported"}


def _get_flow_description(flow_type: FlowType) -> str:
    descriptions = {
        FlowType.DECIDE_ACTION: (
            "Analyzes user input and decides what action to take, including "
            "tool/plugin execution eligibility."
        ),
        FlowType.CONVERSATION_PROCESSING: (
            "Runs explicit LangGraph conversation-processing with memory/context options. "
            "Normal chat should use the canonical chat runtime."
        ),
        FlowType.CONVERSATION_SUMMARY: "Generates summaries of conversation history.",
        FlowType.GENERATE_FINAL_RESPONSE: "Produces the final response payload for delivery.",
    }
    return descriptions.get(flow_type, "AI processing flow")


def _get_flow_parameters(flow_type: FlowType) -> Dict[str, Any]:
    base_params: Dict[str, Any] = {
        "prompt": {
            "type": "string",
            "required": True,
            "description": "User input prompt",
            "max_length": MAX_PROMPT_LENGTH,
        },
        "conversation_history": {
            "type": "array",
            "required": False,
            "description": "Previous conversation messages",
            "max_items": MAX_HISTORY_ITEMS,
        },
        "user_settings": {
            "type": "object",
            "required": False,
            "description": "User preferences and settings",
        },
        "context": {
            "type": "object",
            "required": False,
            "description": "Additional context data",
        },
        "session_id": {
            "type": "string",
            "required": False,
            "description": "Session identifier",
        },
        "user_id": {
            "type": "string",
            "required": False,
            "description": "User identifier. Prefer authenticated session context.",
        },
    }

    if flow_type == FlowType.CONVERSATION_PROCESSING:
        base_params.update(
            {
                "include_memories": {
                    "type": "boolean",
                    "required": False,
                    "description": "Include memory integration",
                    "default": True,
                },
                "include_insights": {
                    "type": "boolean",
                    "required": False,
                    "description": "Include AI insights",
                    "default": True,
                },
                "stream_response": {
                    "type": "boolean",
                    "required": False,
                    "description": "Stream response if supported",
                    "default": False,
                },
                "max_tokens": {
                    "type": "integer",
                    "required": False,
                    "minimum": 1,
                    "maximum": 4096,
                },
                "temperature": {
                    "type": "number",
                    "required": False,
                    "minimum": 0.0,
                    "maximum": 2.0,
                },
            }
        )

    elif flow_type == FlowType.GENERATE_FINAL_RESPONSE:
        base_params.update(
            {
                "response_style": {
                    "type": "string",
                    "required": False,
                    "description": "Preferred response style or format",
                    "enum": ["concise", "detailed", "step_by_step", "bullet_points"],
                }
            }
        )

    return base_params
