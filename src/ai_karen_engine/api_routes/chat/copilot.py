import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    EmergencyFallbackResponse,
    runtime_response_http_status,
    serialize_runtime_response,
)
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.utils.chat_helpers import (
    is_production_env as _is_production_env,
)
from ai_karen_engine.utils.chat_helpers import (
    json_safe as _json_safe,
)
from ai_karen_engine.utils.chat_helpers import (
    normalize_session_id as _normalize_session_id,
)
from ai_karen_engine.utils.chat_helpers import (
    resolve_user_context as _resolve_user_context,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["copilot"])


def get_chat_runtime_service():
    """Return the singleton authoritative chat runtime service."""
    return get_chat_runtime()


async def _get_chat_orchestrator():
    """Return the canonical chat orchestrator via the runtime service."""
    return await get_chat_runtime_service().get_orchestrator()


class SuggestedAction(BaseModel):
    type: str = Field(
        ..., examples=["add_task", "pin_memory", "open_doc", "export_note"]
    )
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    confidence: float = Field(0.8, ge=0.0, le=1.0)
    description: Optional[str] = None


class AssistRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
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
        description="Optional per-request override: streaming_first, auto, non_streaming. If not provided, uses admin default.",
    )


class AssistResponse(BaseModel):
    answer: str
    structured_content: Dict[str, Any] = Field(default_factory=dict)
    actions: List[SuggestedAction] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: str


def _build_chat_execution_request_from_assist_request(
    *,
    request: "AssistRequest",
    user: Dict[str, Any],
    conversation_id: str,
    correlation_id: str,
    response_id: str,
    stream: bool = False,
) -> ChatExecutionRequest:
    """Construct a canonical ChatExecutionRequest from an AssistRequest.

    Identity (user_id, tenant_id, roles, permissions) is taken only from
    the server-side ``user`` dependency; ``request.user_id`` is intentionally
    not trusted for execution.
    """
    preferred_provider = (
        request.preferred_provider or request.preferred_llm_provider
    )
    messages = [{"role": "user", "content": request.message}]

    return ChatExecutionRequest(
        messages=messages,
        context=ChatExecutionContext(
            user_id=user["user_id"],
            tenant_id=str(user.get("tenant_id") or "default"),
            session_id=request.session_id,
            conversation_id=conversation_id,
            request_id=response_id,
            correlation_id=correlation_id,
            roles=list(user.get("roles") or []),
            permissions=list(user.get("permissions") or []),
        ),
        preferred_provider=preferred_provider,
        preferred_model=request.preferred_model,
        stream=stream,
        metadata={
            "surface": "copilot",
            "top_k": request.top_k,
            "context": _json_safe(request.context or {}),
            "preferred_llm_provider": request.preferred_llm_provider,
            "preferred_provider": request.preferred_provider,
            "preferred_model": request.preferred_model,
        },
    )


class StartActionRequest(BaseModel):
    action: str = Field(
        ..., description="Registered action/predictor name, e.g. routing.select"
    )
    payload: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)


class StartActionResponse(BaseModel):
    status: str
    output: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: str


def get_correlation_id(request: Request) -> str:
    return request.headers.get("X-Correlation-Id", "")


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
    )


def _get_predictor_registry():
    """Return the predictor registry with graceful fallback."""

    try:
        from ai_karen_engine.core.cortex.predictors import (
            predictor_registry as registry,
        )

        return registry
    except Exception:
        return {}


def _get_audit_logger():
    """Lazily import the audit logger to avoid heavy startup costs."""

    try:
        from ai_karen_engine.services.audit.audit_logger import (
            get_audit_logger as _getter,
        )

        return _getter()
    except Exception:
        return None


class _AuditLoggerProtocol:
    async def log_event(self, *args: Any, **kwargs: Any) -> Any: ...


async def _log_audit_event(**kwargs: Any) -> None:
    """Best-effort audit logging with compatibility for partial shims."""
    try:
        audit_logger = _get_audit_logger()
        if audit_logger is not None and hasattr(audit_logger, "log_audit_event"):
            audit_logger.log_audit_event(**kwargs)
    except Exception:
        pass


@router.get("/health")
async def copilot_health():
    """Lightweight health check for copilot routes to verify wiring.

    Returns minimal info without invoking heavy dependencies.
    """
    try:
        registry = _get_predictor_registry()
        if hasattr(registry, "keys"):
            registered = list(registry.keys())
        else:
            registered = []
    except Exception:
        registered = []

    return {
        "status": "ok",
        "registered_actions": registered,
        "timestamp": int(time.time()),
    }


@router.post("/start", response_model=StartActionResponse)
async def copilot_start_action(
    http_request: Request,
    # In dev/bypass we allow anonymous; compute context inside to avoid hard 401
    user_ctx: Optional[Dict[str, Any]] = None,
):
    """Generic CopilotKit action starter. Routes to predictor-registered actions."""
    correlation_id = (
        http_request.headers.get("X-Correlation-Id") or f"copilot_{int(time.time())}"
    )

    # Parse request body manually
    try:
        body = await http_request.json()
        req = StartActionRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")

    # Resolve user context: prefer provided; otherwise permissive in dev/bypass
    if user_ctx is None:
        auth_mode = os.getenv("AUTH_MODE", "hybrid").lower()
        allow_public = os.getenv("ALLOW_PUBLIC_COPILOT", "false").lower() in (
            "1",
            "true",
            "yes",
        )
        if not _is_production_env() and (allow_public or auth_mode == "bypass"):
            user_ctx = {
                "user_id": "anonymous",
                "roles": ["admin"],
                "scopes": ["chat:write"],
            }
        else:
            try:
                # Try to resolve real context if available
                user_ctx = await _resolve_user_context(http_request)
            except Exception:
                # If strict mode, deny
                raise HTTPException(status_code=401, detail="Unauthorized")
            if user_ctx is None:
                raise HTTPException(status_code=401, detail="Unauthorized")

    # RBAC: basic scope check; allow admin or chat:write by default
    try:
        allow_public = os.getenv("ALLOW_PUBLIC_COPILOT", "false").lower() in (
            "1",
            "true",
            "yes",
        )
        if not allow_public:
            # Simple role checking - admin or user role required
            user_roles = user_ctx.get("roles", [])
            if not any(role in user_roles for role in ["admin", "user"]):
                raise HTTPException(
                    status_code=403,
                    detail="Insufficient permissions - user or admin role required",
                )
    except Exception:
        # If RBAC service not configured, proceed in permissive mode
        pass

    # Audit: action started
    await _log_audit_event(
        event_type="copilot.action.started",
        user_id=user_ctx.get("user_id"),
        session_id=user_ctx.get("session_id"),
        correlation_id=correlation_id,
        details={"action": req.action, "payload_keys": list(req.payload.keys())},
        surface="copilot",
    )

    # Dispatch to predictor registry
    registry = _get_predictor_registry()
    handler_getter = getattr(registry, "get", lambda *_: None)
    handler = handler_getter(req.action)
    if handler is None:
        available = []
        try:
            registry = _get_predictor_registry()
            available = list(registry.keys()) if hasattr(registry, "keys") else []
        except Exception:
            available = []
        raise HTTPException(
            status_code=404,
            detail=f"Unknown action: {req.action}. Available: {available}",
        )

    try:
        import inspect

        # Normalize user context and pass payload/context
        args = (user_ctx, req.payload, req.context)
        if inspect.iscoroutinefunction(handler):
            output = await handler(*args)
        else:
            output = handler(*args)

        # Audit: action completed
        await _log_audit_event(
            event_type="copilot.action.completed",
            user_id=user_ctx.get("user_id"),
            session_id=user_ctx.get("session_id"),
            correlation_id=correlation_id,
            details={"action": req.action, "success": True},
            surface="copilot",
        )

        return StartActionResponse(
            status="ok", output=output or {}, correlation_id=correlation_id
        )
    except Exception as e:
        # Audit: action failed
        await _log_audit_event(
            event_type="copilot.action.failed",
            user_id=user_ctx.get("user_id"),
            session_id=user_ctx.get("session_id"),
            correlation_id=correlation_id,
            details={"action": req.action, "error": str(e)},
            surface="copilot",
            success=False,
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Action failed: {e}")


# Convenience GET endpoint for clients that mistakenly use GET
@router.get("/start", response_model=StartActionResponse)
async def copilot_start_action_get(action: str, http_request: Request):
    """Shallow wrapper that maps GET to the same start action handler.

    Accepts `action` as a query param and calls the POST handler with empty payload/context.
    Keeps legacy or misconfigured clients working without 404s.
    """
    return await copilot_start_action(http_request=http_request)


@router.post("/assist")
async def copilot_assist(
    request: AssistRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Copilot assist endpoint normalized through the canonical chat runtime.

    AssistRequest → ChatExecutionRequest → ChatRuntime.execute → serialize result.
    All identity (user_id, tenant_id, roles, permissions) is server-owned.
    """
    correlation_id = get_correlation_id(http_request) or f"copilot_{int(time.time())}"
    response_id = str(uuid.uuid4())

    logger.info(
        "Copilot assist request received",
        extra={
            "correlation_id": correlation_id,
            "user_id": user.get("user_id"),
            "message_length": len(request.message),
        },
    )

    conversation_id = _normalize_session_id(request.session_id)
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    chat_request = _build_chat_execution_request_from_assist_request(
        request=request,
        user=user,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        response_id=response_id,
        stream=False,
    )

    try:
        result = await get_chat_runtime().execute(chat_request)

        if result.status == ChatExecutionStatus.GATE and result.gate_response is not None:
            gate = result.gate_response
            payload = serialize_runtime_response(gate) or {}
            status_code = runtime_response_http_status(gate) or 503
            return JSONResponse(
                status_code=status_code,
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
            "is_degraded": metadata.get("degraded_mode", False),
            "used_fallback": metadata.get("used_fallback", False),
            "correlation_id": metadata.get("correlation_id"),
        }

        action_models: List[SuggestedAction] = []
        for action in result.actions or []:
            if not isinstance(action, dict):
                continue
            params_value = action.get("params")
            if isinstance(params_value, dict):
                params = params_value
            else:
                params = {
                    k: v
                    for k, v in action.items()
                    if k not in {"type", "confidence", "description"}
                } or {}
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
            status_code=200,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Copilot assist failed: %s",
            e,
            extra={"correlation_id": correlation_id},
        )
        emergency = EmergencyFallbackResponse()
        payload = serialize_runtime_response(emergency) or {}
        payload["correlation_id"] = correlation_id
        return JSONResponse(
            status_code=200,
            content=payload,
            headers={"X-Correlation-Id": correlation_id},
        )


@router.post("/assist/stream")
async def copilot_assist_stream(
    request: AssistRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Streaming copilot assist endpoint normalized through the canonical chat runtime.

    AssistRequest → ChatExecutionRequest → ChatRuntime.execute_stream → serialize
    canonical ChatStreamChunk events. No provider/fallback inference at the transport.
    """
    correlation_id = (
        get_correlation_id(http_request) or f"copilot_stream_{int(time.time())}"
    )
    response_id = str(uuid.uuid4())

    logger.info(
        "Copilot assist stream request received",
        extra={
            "correlation_id": correlation_id,
            "user_id": user.get("user_id"),
            "message_length": len(request.message),
        },
    )

    conversation_id = _normalize_session_id(request.session_id)
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    chat_request = _build_chat_execution_request_from_assist_request(
        request=request,
        user=user,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        response_id=response_id,
        stream=True,
    )

    async def generate_stream():
        async for chunk in get_chat_runtime().execute_stream(chat_request):
            yield f"data: {json.dumps(chunk.to_sse_payload())}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Correlation-Id": correlation_id,
        },
    )


__all__ = ["router"]
