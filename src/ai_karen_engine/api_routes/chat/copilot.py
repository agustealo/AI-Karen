"""Copilot transport adapters for canonical AI KAREN execution.

Copilot is an ingress surface only. Chat generation delegates to ``ChatRuntime``;
identity is server-owned; tenant scope is never synthesized; authorization
failures fail closed. Predictor action dispatch remains a compatibility surface
until action execution is moved behind the runtime action authority.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

from ai_karen_engine.api_routes.chat.execution_identity import (
    build_chat_execution_context,
    can_execute_copilot_action,
    require_execution_identity,
)
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionRequest,
    ChatExecutionStatus,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    EmergencyFallbackResponse,
    runtime_response_http_status,
    serialize_runtime_response,
)
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.utils.chat_helpers import json_safe as _json_safe
from ai_karen_engine.utils.chat_helpers import normalize_session_id as _normalize_session_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["copilot"])


def _is_placeholder_response(content: str) -> bool:
    """Check if a response string is a degraded shim or placeholder response."""
    if not content or not isinstance(content, str):
        return True
    lowered = content.lower()
    degraded_indicators = [
        "operating with limited capabilities",
        "degraded mode",
        "placeholder response",
        "fallback response",
    ]
    for indicator in degraded_indicators:
        if indicator in lowered:
            return True
    return False


def _sanitize_user_visible_text(content: str) -> str:
    """Strip internal analysis scaffold or reasoning markers from user-facing output."""
    if not content or not isinstance(content, str):
        return ""
    if "\n===\n" in content:
        content = content.split("\n===\n")[0]
    elif "\n===" in content:
        content = content.split("\n===")[0]
    elif "===" in content:
        content = content.split("===")[0]
    return content.strip()


class SuggestedAction(BaseModel):
    type: str = Field(
        ...,
        examples=["add_task", "pin_memory", "open_doc", "export_note"],
    )
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    description: Optional[str] = None


class AssistRequest(BaseModel):
    """Copilot assist request.

    ``user_id`` and ``org_id`` remain accepted for wire compatibility but are
    never trusted as execution identity. Authentication middleware owns user and
    tenant scope.
    """

    user_id: Optional[str] = Field(default=None, min_length=1)
    org_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=8000)
    top_k: int = Field(6, ge=1, le=50)
    context: Dict[str, Any] = Field(default_factory=dict)
    preferred_llm_provider: Optional[str] = None
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    session_id: Optional[str] = None
    response_mode: Optional[str] = Field(
        default=None,
        description=(
            "Optional compatibility hint: streaming_first, auto, or non_streaming. "
            "Execution authority remains in ChatRuntime."
        ),
    )


class AssistResponse(BaseModel):
    answer: str
    structured_content: Dict[str, Any] = Field(default_factory=dict)
    actions: List[SuggestedAction] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: str


class StartActionRequest(BaseModel):
    action: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Registered action/predictor name, e.g. routing.select",
    )
    payload: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)


class StartActionResponse(BaseModel):
    status: str
    output: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: str


def get_chat_runtime_service():
    """Return the singleton authoritative chat runtime service."""

    return get_chat_runtime()


async def _get_chat_orchestrator():
    """Compatibility health adapter for callers that inspect the orchestrator."""

    return await get_chat_runtime_service().get_orchestrator()


def get_correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-Id", "")


def _get_predictor_registry():
    """Return the existing CORTEX predictor registry without inventing handlers."""

    try:
        from ai_karen_engine.core.cortex.predictors import predictor_registry

        return predictor_registry
    except Exception:
        logger.exception("CORTEX predictor registry unavailable")
        return {}


def _get_audit_logger():
    try:
        from ai_karen_engine.services.audit.audit_logger import get_audit_logger

        return get_audit_logger()
    except Exception:
        logger.debug("Audit logger unavailable", exc_info=True)
        return None


async def _log_audit_event(**kwargs: Any) -> None:
    """Emit an audit event without allowing audit failure to mask the action result."""

    audit_logger = _get_audit_logger()
    if audit_logger is None or not hasattr(audit_logger, "log_audit_event"):
        return
    try:
        result = audit_logger.log_audit_event(**kwargs)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.warning("Copilot audit event failed", exc_info=True)


def _assist_response_json(
    *,
    answer: str,
    structured_content: Optional[Dict[str, Any]] = None,
    actions: Optional[List[SuggestedAction]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    correlation_id: str,
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "answer": answer,
            "structured_content": structured_content or {},
            "actions": [action.model_dump() for action in (actions or [])],
            "metadata": _json_safe(metadata or {}),
            "correlation_id": correlation_id,
        },
        headers={"X-Correlation-Id": correlation_id},
    )


def _build_chat_execution_request_from_assist_request(
    *,
    request: AssistRequest,
    user: Dict[str, Any],
    conversation_id: str,
    correlation_id: str,
    response_id: str,
    stream: bool,
) -> ChatExecutionRequest:
    """Adapt Copilot input into the canonical runtime request."""

    require_execution_identity(user)
    session_id = str(request.session_id or conversation_id).strip() or conversation_id
    preferred_provider = request.preferred_provider or request.preferred_llm_provider

    return ChatExecutionRequest(
        messages=[{"role": "user", "content": request.message.strip()}],
        context=build_chat_execution_context(
            user=user,
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=response_id,
            correlation_id=correlation_id,
        ),
        preferred_provider=preferred_provider,
        preferred_model=request.preferred_model,
        stream=stream,
        metadata={
            "surface": "copilot",
            "top_k": request.top_k,
            "context": _json_safe(request.context or {}),
            "response_mode": request.response_mode,
            "compatibility_user_id_present": bool(request.user_id),
            "compatibility_org_id_present": bool(request.org_id),
        },
    )


def _action_output(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {"result": dumped}
    return {"result": value}


async def _execute_copilot_action(
    *,
    req: StartActionRequest,
    user_ctx: Dict[str, Any],
    correlation_id: str,
) -> StartActionResponse:
    user_id, tenant_id = require_execution_identity(user_ctx)
    if not can_execute_copilot_action(user_ctx):
        await _log_audit_event(
            event_type="copilot.action.denied",
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=user_ctx.get("session_id"),
            correlation_id=correlation_id,
            details={"action": req.action},
            surface="copilot",
            success=False,
        )
        raise HTTPException(
            status_code=403,
            detail="Copilot action permission required",
        )

    registry = _get_predictor_registry()
    handler_getter = getattr(registry, "get", None)
    handler = handler_getter(req.action) if callable(handler_getter) else None
    if handler is None:
        available = sorted(registry.keys()) if hasattr(registry, "keys") else []
        raise HTTPException(
            status_code=404,
            detail={"message": "Unknown Copilot action", "available": available},
        )

    await _log_audit_event(
        event_type="copilot.action.started",
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=user_ctx.get("session_id"),
        correlation_id=correlation_id,
        details={"action": req.action, "payload_keys": sorted(req.payload.keys())},
        surface="copilot",
    )

    try:
        result = handler(user_ctx, req.payload, req.context)
        if inspect.isawaitable(result):
            result = await result
        output = _action_output(result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Copilot action execution failed",
            extra={
                "correlation_id": correlation_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "action": req.action,
                "error_type": type(exc).__name__,
            },
        )
        await _log_audit_event(
            event_type="copilot.action.failed",
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=user_ctx.get("session_id"),
            correlation_id=correlation_id,
            details={"action": req.action, "error_type": type(exc).__name__},
            surface="copilot",
            success=False,
        )
        raise HTTPException(
            status_code=500,
            detail="Copilot action execution failed",
        ) from exc

    await _log_audit_event(
        event_type="copilot.action.completed",
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=user_ctx.get("session_id"),
        correlation_id=correlation_id,
        details={"action": req.action, "success": True},
        surface="copilot",
    )
    return StartActionResponse(
        status="ok",
        output=output,
        correlation_id=correlation_id,
    )


@router.get("/health")
async def copilot_health() -> Dict[str, Any]:
    registry = _get_predictor_registry()
    registered = sorted(registry.keys()) if hasattr(registry, "keys") else []
    return {
        "status": "ok",
        "registered_actions": registered,
        "runtime_authority": "ChatRuntime",
        "timestamp": int(time.time()),
    }


@router.post("/start", response_model=StartActionResponse)
async def copilot_start_action(
    req: StartActionRequest,
    http_request: Request,
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
) -> StartActionResponse:
    correlation_id = get_correlation_id(http_request) or str(uuid.uuid4())
    return await _execute_copilot_action(
        req=req,
        user_ctx=user_ctx,
        correlation_id=correlation_id,
    )


@router.get("/start", response_model=StartActionResponse)
async def copilot_start_action_get(
    action: str,
    http_request: Request,
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
) -> StartActionResponse:
    """Compatibility GET adapter with the same fail-closed authorization path."""

    correlation_id = get_correlation_id(http_request) or str(uuid.uuid4())
    return await _execute_copilot_action(
        req=StartActionRequest(action=action),
        user_ctx=user_ctx,
        correlation_id=correlation_id,
    )


@router.post("/assist", response_model=AssistResponse)
async def copilot_assist(
    request: AssistRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    correlation_id = get_correlation_id(http_request) or str(uuid.uuid4())
    response_id = str(uuid.uuid4())
    require_execution_identity(user)

    conversation_id = _normalize_session_id(request.session_id) or str(uuid.uuid4())
    chat_request = _build_chat_execution_request_from_assist_request(
        request=request,
        user=user,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        response_id=response_id,
        stream=False,
    )

    logger.info(
        "Copilot assist request received",
        extra={
            "correlation_id": correlation_id,
            "user_id": user.get("user_id"),
            "tenant_id": user.get("tenant_id"),
            "message_length": len(request.message),
        },
    )

    try:
        result = await get_chat_runtime().execute(chat_request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Copilot assist runtime call failed",
            extra={
                "correlation_id": correlation_id,
                "error_type": type(exc).__name__,
            },
        )
        emergency = EmergencyFallbackResponse()
        payload = serialize_runtime_response(emergency) or {}
        payload["correlation_id"] = correlation_id
        return JSONResponse(
            status_code=runtime_response_http_status(emergency) or 503,
            content=payload,
            headers={"X-Correlation-Id": correlation_id},
        )

    if result.status == ChatExecutionStatus.GATE and result.gate_response is not None:
        gate = result.gate_response
        payload = serialize_runtime_response(gate) or {}
        payload["correlation_id"] = correlation_id
        return JSONResponse(
            status_code=runtime_response_http_status(gate) or 503,
            content=payload,
            headers={"X-Correlation-Id": correlation_id},
        )

    metadata = _json_safe(result.metadata.to_dict())
    metadata["llm"] = {
        "requested_provider": metadata.get("requested_provider"),
        "requested_model": metadata.get("requested_model"),
        "actual_provider": metadata.get("actual_provider"),
        "actual_model": metadata.get("actual_model"),
        "runtime_engine": metadata.get("runtime_engine"),
        "response_source": metadata.get("response_source"),
        "fallback_level": metadata.get("fallback_level", 0),
        "degraded_mode": metadata.get("degraded_mode", False),
        "used_fallback": metadata.get("used_fallback", False),
        "correlation_id": metadata.get("correlation_id") or correlation_id,
    }

    action_models: List[SuggestedAction] = []
    for action in result.actions or []:
        if not isinstance(action, dict):
            continue
        params_value = action.get("params")
        params = (
            params_value
            if isinstance(params_value, dict)
            else {
                key: value
                for key, value in action.items()
                if key not in {"type", "confidence", "description"}
            }
        )
        action_models.append(
            SuggestedAction(
                type=str(action.get("type", "unknown")),
                params=params,
                confidence=float(action.get("confidence", 0.8)),
                description=action.get("description"),
            )
        )

    return _assist_response_json(
        answer=result.answer,
        structured_content=_json_safe(result.structured_content or {}),
        actions=action_models,
        metadata=metadata,
        correlation_id=correlation_id,
    )


@router.post("/assist/stream")
async def copilot_assist_stream(
    request: AssistRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> StreamingResponse:
    correlation_id = get_correlation_id(http_request) or str(uuid.uuid4())
    response_id = str(uuid.uuid4())
    require_execution_identity(user)

    conversation_id = _normalize_session_id(request.session_id) or str(uuid.uuid4())
    chat_request = _build_chat_execution_request_from_assist_request(
        request=request,
        user=user,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        response_id=response_id,
        stream=True,
    )

    async def generate_stream():
        try:
            async for chunk in get_chat_runtime().execute_stream(chat_request):
                yield f"data: {json.dumps(chunk.to_sse_payload())}\n\n"
        except Exception as exc:
            logger.exception(
                "Copilot assist stream failed",
                extra={
                    "correlation_id": correlation_id,
                    "error_type": type(exc).__name__,
                },
            )
            yield "data: " + json.dumps(
                {
                    "type": "error",
                    "content": "Unable to complete the response.",
                    "correlation_id": correlation_id,
                    "metadata": {"error_code": "COPILOT_STREAM_FAILED"},
                }
            ) + "\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Correlation-Id": correlation_id,
            "X-Response-Id": response_id,
        },
    )


__all__ = [
    "AssistRequest",
    "AssistResponse",
    "StartActionRequest",
    "StartActionResponse",
    "_build_chat_execution_request_from_assist_request",
    "copilot_assist",
    "copilot_assist_stream",
    "copilot_start_action",
    "router",
]
