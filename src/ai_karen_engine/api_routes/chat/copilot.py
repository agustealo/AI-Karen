import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, StreamingResponse

from ai_karen_engine.config.config_manager import (
    get_chat_response_mode,
    get_chat_streaming_transport,
)
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    DegradedCapabilities,
    DegradedResponse,
    EmergencyFallbackResponse,
    get_chat_runtime_control_plane,
    runtime_response_http_status,
    serialize_runtime_response,
)
from ai_karen_engine.core.runtime.degraded_mode import generate_degraded_mode_response
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.utils.chat_helpers import (
    extract_stream_text as _extract_stream_text,
)
from ai_karen_engine.utils.chat_helpers import (
    finalize_user_visible_text as _finalize_user_visible_text,
)
from ai_karen_engine.utils.chat_helpers import (
    is_production_env as _is_production_env,
)
from ai_karen_engine.utils.chat_helpers import (
    json_safe as _json_safe,
)
from ai_karen_engine.utils.chat_helpers import (
    normalize_processing_status as _normalize_processing_status,
)
from ai_karen_engine.utils.chat_helpers import (
    normalize_session_id as _normalize_session_id,
)
from ai_karen_engine.utils.chat_helpers import (
    resolve_user_context as _resolve_user_context,
)


def _finalize_runtime_payload_text(
    payload: Dict[str, Any], user_message: str
) -> Dict[str, Any]:
    """Apply final user-visible cleanup to runtime payload text fields."""
    updated = dict(payload or {})
    candidate_keys = ("answer", "message", "response", "final", "content")
    for key in candidate_keys:
        value = updated.get(key)
        if isinstance(value, str) and value.strip():
            updated[key] = _finalize_user_visible_text(value, user_message)
    return updated


def _build_degraded_sse_events(
    payload: Dict[str, Any], 
    correlation_id: str,
    requested_provider: Optional[str] = None,
    requested_model: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Build client-compatible SSE events for degraded/fallback payloads."""
    text = _extract_stream_text(payload)
    status = _normalize_processing_status(
        payload.get("mode") or payload.get("status"),
        "degraded",
    )
    status_message = _PROCESSING_STATUS_MESSAGES.get(
        status, f"Karen is {status.replace('_', ' ')}..."
    )
    
    # Build LLM metadata block for transparency
    llm_metadata = payload.get("llm") or {}
    if not isinstance(llm_metadata, dict):
        llm_metadata = {}
    
    llm_metadata.update({
        "requested_provider": requested_provider or llm_metadata.get("requested_provider"),
        "requested_model": requested_model or llm_metadata.get("requested_model"),
        "actual_provider": llm_metadata.get("actual_provider"), # User instruction: none for emergency static
        "actual_model": llm_metadata.get("actual_model"), # User instruction: none for emergency static
        "is_degraded": True,
        "fallback_level": llm_metadata.get("fallback_level") or 99,
        "response_source": llm_metadata.get("response_source") or "emergency_static",
        "provider_attempts": llm_metadata.get("provider_attempts", [])
    })

    metadata = {
        **payload,
        "status": status,
        "status_message": status_message,
        "degraded_mode": True,
        "llm": llm_metadata
    }
    events: List[Dict[str, Any]] = [
        {
            "type": "status",
            "content": status_message,
            "correlation_id": correlation_id,
            "metadata": metadata,
        }
    ]
    if text:
        events.append(
            {
                "type": "content",
                "content": text,
                "correlation_id": correlation_id,
                "metadata": metadata,
            }
        )
    events.append(
        {
            "type": "complete",
            "content": "",
            "correlation_id": correlation_id,
            "metadata": metadata,
        }
    )
    return events


async def _build_live_degraded_payload(
    user_message: str,
    degraded: Optional[DegradedResponse],
    correlation_id: str,
) -> Dict[str, Any]:
    """Build a degraded fallback payload with live content when possible."""
    payload: Dict[str, Any] = {}
    if degraded is not None:
        payload = serialize_runtime_response(degraded) or {}

    live_response = await generate_degraded_mode_response(user_message)
    if isinstance(live_response, dict):
        payload.update(live_response)

    payload["correlation_id"] = correlation_id
    payload.setdefault("degraded_mode", True)
    payload.setdefault("mode", "degraded")
    return payload


async def _build_router_fallback_assist_payload(*, request: "AssistRequest", correlation_id: str, conversation_id: str, start_time: float, request_config_metadata: Dict[str, Any], actual_mode: str, transport: str, failure: Exception, streaming_enabled: bool = False) -> Optional[Dict[str, Any]]:
    return {
        "answer": str(failure),
        "structured_content": {},
        "actions": [],
        "metadata": {
            "correlation_id": correlation_id,
            "conversation_id": conversation_id,
            "degraded_mode": True,
            "mode": actual_mode or "degraded",
            "response_source": "unavailable",
            "fallback_level": 1,
            **request_config_metadata,
        },
    }


def _build_router_fallback_sse_events(payload: Dict[str, Any], correlation_id: str) -> List[Dict[str, Any]]:
    return [
        {"type": "content", "content": payload.get("answer", ""), "correlation_id": correlation_id},
        {"type": "complete", "content": "", "correlation_id": correlation_id},
    ]


logger = logging.getLogger(__name__)

# Create router without prefix for automatic discovery alignment
router = APIRouter(tags=["copilot"])


def _resolve_actual_response_mode(
    request_response_mode: Optional[str],
    request_stream: Optional[bool],
) -> tuple[str, str, bool]:
    """Resolve the actual response mode, transport, and should_stream flag.

    Returns:
        (actual_mode, transport, should_stream)
        - actual_mode: "streaming_first", "auto", or "non_streaming"
        - transport: "sse" or "json"
        - should_stream: True if endpoint should stream, False otherwise
    """
    # Get admin default
    admin_mode = get_chat_response_mode() or "streaming_first"

    # Resolve per-request override
    if request_response_mode:
        mode = request_response_mode.lower()
        if mode in ("streaming_first", "auto", "non_streaming"):
            resolved_mode = mode
        else:
            logger.warning(
                f"Invalid response_mode '{request_response_mode}', using admin default '{admin_mode}'"
            )
            resolved_mode = admin_mode
    elif request_stream is not None:
        # Legacy compatibility: stream=true → streaming_first
        resolved_mode = "streaming_first" if request_stream else "non_streaming"
    else:
        resolved_mode = admin_mode

    # Determine if streaming should be used
    if resolved_mode == "non_streaming":
        return "non_streaming", "json", False
    elif resolved_mode == "streaming_first":
        return "streaming_first", get_chat_streaming_transport() or "sse", True
    else:  # auto
        return "auto", get_chat_streaming_transport() or "sse", True


def _build_request_config_metadata(
    requested_mode: str,
    actual_mode: str,
    transport: str,
    should_stream: bool,
    preferred_provider: Optional[str] = None,
    preferred_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Build request config metadata for responses."""
    return {
        "requested_response_mode": requested_mode,
        "actual_response_mode": actual_mode,
        "transport": transport,
        "should_stream": should_stream,
        "preferred_llm_provider": preferred_provider,
        "preferred_provider": preferred_provider,
        "preferred_model": preferred_model,
    }


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
    request_config_metadata: Optional[Dict[str, Any]] = None,
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
            tenant_id=str(user.get("tenant_id") or request.org_id or "default"),
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
            "preferred_lln_provider": request.preferred_lln_provider,
            "preferred_provider": request.preferred_provider,
            "preferred_model": request.preferred_model,
            **(request_config_metadata or {}),
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
            "metadata": metadata or {},
            "correlation_id": correlation_id,
        },
    )


def _normalize_runtime_truth_metadata(
    *,
    metadata: Optional[Dict[str, Any]],
    request: AssistRequest,
    final_state: Optional[Dict[str, Any]],
    correlation_id: str,
    conversation_id: str,
    start_time: Optional[float],
    request_config_metadata: Dict[str, Any],
    streaming_enabled: bool,
    transport: str,
    actual_response_mode: str,
) -> Dict[str, Any]:
    """Normalize requested-vs-actual provider truth for all copilot responses."""
    normalized: Dict[str, Any] = _json_safe(metadata or {})
    state = final_state or {}
    state_llm = state.get("llm_metadata") or {}
    exec_result = state.get("execution_result")
    route_decision = state.get("route_decision")
    
    # Priority: 1. Real execution result object, 2. Existing metadata, 3. State metadata
    llm = dict(normalized.get("llm") or state_llm or {})

    requested_provider = (
        (exec_result.requested_provider if exec_result else None)
        or (route_decision.requested_provider if route_decision else None)
        or llm.get("requested_provider")
        or normalized.get("requested_provider")
        or request.preferred_llm_provider
    )
    requested_model = (
        (exec_result.requested_model if exec_result else None)
        or (route_decision.requested_model if route_decision else None)
        or llm.get("requested_model")
        or normalized.get("requested_model")
        or request.preferred_model
    )
    actual_provider = (
        (exec_result.actual_provider if exec_result else None)
        or llm.get("actual_provider")
        or normalized.get("actual_provider")
        or llm.get("provider")
        or normalized.get("provider")
    )
    actual_model = (
        (exec_result.actual_model if exec_result else None)
        or llm.get("actual_model")
        or normalized.get("actual_model")
        or llm.get("model_id")
        or llm.get("model_name")
        or normalized.get("model")
    )

    fallback_level = (
        (exec_result.fallback_level if exec_result else None)
        or llm.get("fallback_level")
        or normalized.get("fallback_level")
    )
    if fallback_level is None:
        fallback_level = 0

    if (not requested_provider or str(requested_provider).lower() == "unknown") and actual_provider not in {"", "unknown", None}:
        fallback_level = max(1, int(fallback_level))
        normalized.setdefault("degraded_mode", True)
        normalized.setdefault("degradation_type", "provider_unknown")
        normalized.setdefault("degradation_reason", "Requested provider was missing at ingress; runtime resolved or fell back.")

    response_source = (
        (exec_result.response_source if exec_result else None)
        or llm.get("response_source")
        or normalized.get("response_source")
        or llm.get("source")
        or ("emergency_static" if actual_provider is None else "live_model")
    )

    provider_attempts = (
        (exec_result.provider_attempts if exec_result else None)
        or llm.get("provider_attempts")
        or normalized.get("provider_attempts")
        or []
    )
    
    selected_provider = (
        (exec_result.selected_provider if exec_result else None)
        or (route_decision.selected_provider if route_decision else None)
        or llm.get("selected_provider")
        or "unknown"
    )
    
    selected_model = (
        (exec_result.selected_model if exec_result else None)
        or (route_decision.selected_model if route_decision else None)
        or llm.get("selected_model")
        or "unknown"
    )

    def _robust_normalize(val: Any, is_model: bool = False) -> str:
        s = str(val or "").strip().lower().replace("-", "_")
        if not s:
            return ""
        if is_model:
            # Handle path separators like in the frontend
            return s.split("/")[-1].split(":")[-1].split(".")[0]
        # Handle provider aliases (remove builtin_ prefix for comparison)
        return s.replace("builtin_", "")

    requested_provider_norm = _robust_normalize(requested_provider)
    actual_provider_norm = _robust_normalize(actual_provider)
    
    provider_changed = bool(
        requested_provider_norm
        and actual_provider_norm
        and requested_provider_norm != actual_provider_norm
    )
    
    # Models are only "changed" if requested was not "auto" and they don't match
    requested_model_norm = _robust_normalize(requested_model, is_model=True)
    actual_model_norm = _robust_normalize(actual_model, is_model=True)
    
    model_changed = bool(
        requested_model_norm
        and actual_model_norm
        and requested_model_norm != "auto"
        and requested_model_norm != actual_model_norm
    )
    
    # Determine if the response source represents a healthy live execution
    is_healthy_source = (
        response_source == "live_model" or 
        response_source == "provider_runtime" or
        str(response_source).endswith("_engine") or 
        response_source == "intelligent_router"
    )
    
    degraded_mode = bool(
        (exec_result.degraded_mode if exec_result else None)
        or llm.get("degraded_mode")
        or llm.get("is_degraded")
        or normalized.get("degraded_mode")
        or provider_changed
        or model_changed
        or not is_healthy_source
    )
    
    # If it's a successful direct engine response, it's not degraded
    if is_healthy_source and not provider_changed and not model_changed:
        degraded_mode = False
        
    fallback_level = (
        (exec_result.fallback_level if exec_result else None)
        or llm.get("fallback_level")
        or normalized.get("fallback_level")
    )
    if fallback_level is None:
        fallback_level = 1 if provider_changed else (99 if response_source == "emergency_static" else 0)

    runtime_engine = (
        (exec_result.runtime_engine if exec_result else None)
        or llm.get("runtime_engine")
        or normalized.get("runtime_engine")
        or ("none" if not actual_provider else str(actual_provider).replace("builtin_", ""))
    )
    
    latency_ms = (
        (exec_result.latency_ms if exec_result else None)
        or normalized.get("latency_ms")
    )
    if latency_ms is None and start_time is not None:
        latency_ms = (time.time() - start_time) * 1000

    llm.update(
        {
            "requested_provider": requested_provider,
            "requested_model": requested_model,
            "selected_provider": selected_provider,
            "selected_model": selected_model,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
            "provider": actual_provider,
            "model_id": actual_model,
            "model_name": llm.get("model_name") or actual_model,
            "runtime_engine": runtime_engine,
            "response_source": response_source,
            "source": llm.get("source") or response_source,
            "provider_health": llm.get("provider_health", normalized.get("provider_health", {})),
            "provider_error": (exec_result.degradation_reason if exec_result else None) or llm.get("provider_error", normalized.get("provider_error")),
            "fallback_level": fallback_level,
            "degraded_mode": degraded_mode,
            "is_degraded": degraded_mode,
            "used_fallback": bool(llm.get("used_fallback") or provider_changed or degraded_mode),
            "degradation_type": (exec_result.degradation_type if exec_result else None) or llm.get("degradation_type") or normalized.get("degradation_type"),
            "degradation_reason": (exec_result.degradation_reason if exec_result else None) 
            or llm.get("degradation_reason")
            or normalized.get("degradation_reason")
            or ("requested_provider_unavailable" if provider_changed else None),
            "streaming_enabled": streaming_enabled,
            "actual_response_mode": actual_response_mode,
            "transport": transport,
            "latency_ms": latency_ms,
            "correlation_id": (exec_result.correlation_id if exec_result else None) or correlation_id,
            "provider_attempts": provider_attempts,
        }
    )

    normalized.update(request_config_metadata)
    normalized.update(
        {
            "llm": llm,
            "requested_provider": requested_provider,
            "requested_model": requested_model,
            "selected_provider": selected_provider,
            "selected_model": selected_model,
            "actual_provider": actual_provider,
            "actual_model": actual_model,
            "runtime_engine": runtime_engine,
            "response_source": response_source,
            "provider_health": llm.get("provider_health", {}),
            "provider_error": llm.get("provider_error"),
            "fallback_level": fallback_level,
            "degraded_mode": degraded_mode,
            "degradation_type": llm.get("degradation_type"),
            "degradation_reason": llm.get("degradation_reason"),
            "streaming_enabled": streaming_enabled,
            "actual_response_mode": actual_response_mode,
            "transport": transport,
            "latency_ms": latency_ms,
            "correlation_id": llm.get("correlation_id") or correlation_id,
            "conversation_id": conversation_id,
            "status": normalized.get("status", "success"),
            "provider_attempts": provider_attempts,
        }
    )
    return normalized


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


def _ensure_routing_actions_registered() -> None:
    """Ensure routing actions are registered for the /start endpoint."""
    try:
        import ai_karen_engine.routing.actions  # noqa: F401  — registers routing.* handlers in predictor registry
    except Exception:
        # Best-effort; if not present, action registry may be empty until lazily imported elsewhere
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
    _ensure_routing_actions_registered()
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
        # Try late registration of routing actions, then re-check
        try:
            import ai_karen_engine.routing.actions  # noqa: F401  — late-registers routing.* handlers in predictor registry
        except Exception:
            pass
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
    _ensure_routing_actions_registered()
    return await copilot_start_action(http_request=http_request)


@router.post("/assist")
async def copilot_assist(
    request: AssistRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Copilot assist endpoint normalized through the canonical chat runtime."""
    start_time = time.time()
    correlation_id = get_correlation_id(http_request) or f"copilot_{int(time.time())}"

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

    actual_mode, transport, _ = _resolve_actual_response_mode(
        request.response_mode,
        None,
    )
    request_config_metadata = _build_request_config_metadata(
        requested_mode=request.response_mode or get_chat_response_mode(),
        actual_mode=actual_mode,
        transport=transport,
        should_stream=False,
        preferred_provider=request.preferred_llm_provider,
        preferred_model=request.preferred_model,
    )

    try:
        control_response = await get_chat_runtime_control_plane().get_runtime_response(
            user_id=user["user_id"],
            message=request.message,
            session_id=request.session_id,
            correlation_id=correlation_id,
        )

        if control_response is not None:
            if isinstance(control_response, EmergencyFallbackResponse):
                payload = serialize_runtime_response(control_response) or {}
                payload["correlation_id"] = correlation_id
                status_code = runtime_response_http_status(control_response) or 503
                return JSONResponse(
                    status_code=status_code,
                    content=payload,
                    headers={"X-Correlation-Id": correlation_id},
                )
            if isinstance(control_response, DegradedResponse):
                payload = await _build_live_degraded_payload(
                    request.message, control_response, correlation_id
                )
                payload = _finalize_runtime_payload_text(payload, request.message)
                payload["correlation_id"] = correlation_id
                return _assist_response_json(
                    answer=str(
                        payload.get("final")
                        or payload.get("message")
                        or payload.get("response")
                        or payload.get("answer")
                        or ""
                    ).strip()
                    or control_response.message,
                    structured_content={},
                    actions=[],
                    metadata={
                        "runtime": serialize_runtime_response(control_response) or {},
                        "mode": "degraded",
                        "degraded_mode": True,
                        "capabilities": vars(control_response.capabilities)
                        if control_response.capabilities
                        else {},
                        "is_minimal": getattr(control_response, "is_minimal", True),
                        "retry_after_seconds": getattr(control_response, "retry_after_seconds", 30),
                        "system_status_code": getattr(control_response, "system_status_code", 503),
                        "support_hint": getattr(control_response, "support_hint", ""),
                        "llm": {
                            "provider": None,
                            "model_name": None,
                            "source": "runtime_control_plane",
                            "is_degraded": True,
                            "fallback_level": "degraded",
                            "failure_reason": control_response.message,
                        },
                    },
                    correlation_id=correlation_id,
                    status_code=runtime_response_http_status(control_response) or 200,
                )

        chat_request = _build_chat_execution_request_from_assist_request(
            request=request,
            user=user,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            response_id=str(uuid.uuid4()),
            request_config_metadata=request_config_metadata,
        )

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

        runtime_meta = result.metadata.to_dict()
        copilot_metadata = _normalize_runtime_truth_metadata(
            metadata={"llm": runtime_meta, **runtime_meta},
            request=request,
            final_state=None,
            correlation_id=correlation_id,
            conversation_id=conversation_id,
            start_time=start_time,
            request_config_metadata=request_config_metadata,
            streaming_enabled=False,
            transport="json",
            actual_response_mode=actual_mode,
        )

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
            metadata=copilot_metadata,
            correlation_id=correlation_id,
            status_code=200,
        )

    except Exception as e:
        logger.exception(
            "Copilot assist orchestration failed: %s",
            e,
            extra={"correlation_id": correlation_id},
        )
        fallback_payload = await _build_router_fallback_assist_payload(
            request=request,
            correlation_id=correlation_id,
            conversation_id=conversation_id,
            start_time=start_time,
            request_config_metadata=request_config_metadata,
            actual_mode=actual_mode,
            transport="json",
            failure=e,
        )
        if fallback_payload is not None:
            return _assist_response_json(
                answer=fallback_payload["answer"],
                structured_content=fallback_payload["structured_content"],
                actions=[],
                metadata=fallback_payload["metadata"],
                correlation_id=correlation_id,
                status_code=200,
            )

        fallback = EmergencyFallbackResponse()
        payload = serialize_runtime_response(fallback) or {}
        payload["correlation_id"] = correlation_id
        return JSONResponse(
            status_code=200,
            content=payload,
            headers={"X-Correlation-Id": correlation_id},
        )


_PROCESSING_STATUS_MESSAGES = {
    "initializing": "Karen is initializing the request pipeline...",
    "processing": "Karen is analyzing your message...",
    "extracting_context": "Karen is retrieving relevant context and memories...",
    "generating_response": "Karen is generating a response...",
    "streaming": "Karen is composing the response...",
    "executing_tools": "Karen is executing tools and integrations...",
    "recording_memory": "Karen is recording insights from this conversation...",
    "post_processing": "Karen is finalizing the response...",
    "completed": "Response complete.",
    "degraded": "Karen is running in degraded mode...",
    "failed": "Processing failed. Retrying or falling back...",
    "cancelled": "Request was cancelled.",
    "retrying": "Retrying with an alternative provider...",
}


@router.post("/assist/stream")
async def copilot_assist_stream(
    request: AssistRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Streaming copilot assist endpoint normalized through the canonical chat runtime."""
    correlation_id = (
        get_correlation_id(http_request) or f"copilot_stream_{int(time.time())}"
    )
    start_time = time.time()

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

    actual_mode, transport, should_stream = _resolve_actual_response_mode(
        request.response_mode, None
    )
    requested_provider = request.preferred_provider or request.preferred_llm_provider
    requested_model = request.preferred_model

    request_config_metadata = _build_request_config_metadata(
        requested_mode=request.response_mode or get_chat_response_mode(),
        actual_mode=actual_mode,
        transport=transport,
        should_stream=True,
        preferred_provider=requested_provider,
        preferred_model=requested_model,
    )

    async def stream_control_plane_fallback(
        degraded: Optional[DegradedResponse],
        fallback_payload: Optional[Dict[str, Any]],
    ):
        events: List[Dict[str, Any]] = []
        if fallback_payload is not None:
            events = _build_router_fallback_sse_events(fallback_payload, correlation_id)
        elif degraded is not None:
            live_payload = await _build_live_degraded_payload(
                request.message, degraded, correlation_id
            )
            events = _build_degraded_sse_events(
                live_payload,
                correlation_id,
                requested_provider=requested_provider,
                requested_model=requested_model,
            )
        else:
            emergency_payload = serialize_runtime_response(
                EmergencyFallbackResponse()
            ) or {}
            emergency_payload["correlation_id"] = correlation_id
            events = _build_degraded_sse_events(
                emergency_payload,
                correlation_id,
                requested_provider=requested_provider,
                requested_model=requested_model,
            )
        for event in events:
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    try:
        control_response = await get_chat_runtime_control_plane().get_runtime_response(
            user_id=user["user_id"],
            message=request.message,
            session_id=request.session_id,
            correlation_id=correlation_id,
        )

        if control_response is not None:
            if isinstance(control_response, EmergencyFallbackResponse):
                payload = serialize_runtime_response(control_response) or {}
                payload["correlation_id"] = correlation_id

                async def stream_emergency():
                    for event in _build_degraded_sse_events(
                        payload,
                        correlation_id,
                        requested_provider=requested_provider,
                        requested_model=requested_model,
                    ):
                        yield f"data: {json.dumps(event)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    stream_emergency(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Correlation-Id": correlation_id,
                    },
                )

            if isinstance(control_response, DegradedResponse):
                degraded_continuation_response = control_response

        runtime_plane = await get_chat_runtime_control_plane()
        runtime_status = runtime_plane.get_status()
        if runtime_status.get("mode") != "normal":
            fallback_payload = await _build_router_fallback_assist_payload(
                request=request,
                correlation_id=correlation_id,
                conversation_id=conversation_id,
                start_time=start_time,
                request_config_metadata=request_config_metadata,
                actual_mode=actual_mode,
                transport="sse",
                failure=RuntimeError(
                    f"runtime_mode_{runtime_status.get('mode', 'unknown')}"
                ),
                streaming_enabled=True,
            )
            return StreamingResponse(
                stream_control_plane_fallback(
                    degraded_continuation_response, fallback_payload
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Correlation-Id": correlation_id,
                },
            )

        chat_request = _build_chat_execution_request_from_assist_request(
            request=request,
            user=user,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            response_id=str(uuid.uuid4()),
            stream=True,
            request_config_metadata=request_config_metadata,
        )

        async def generate_stream():
            initial_payload = {
                "type": "status",
                "content": _PROCESSING_STATUS_MESSAGES.get(
                    "initializing",
                    "Karen is initializing the request pipeline...",
                ),
                "correlation_id": correlation_id,
                "metadata": {
                    "status": "initializing",
                    "status_message": _PROCESSING_STATUS_MESSAGES.get(
                        "initializing",
                        "Karen is initializing the request pipeline...",
                    ),
                    **request_config_metadata,
                },
            }
            yield f"data: {json.dumps(initial_payload)}\n\n"

            selection_payload = {
                "type": "status",
                "content": "Selecting provider...",
                "correlation_id": correlation_id,
                "metadata": {
                    "status": "provider_selection",
                    "requested_provider": requested_provider,
                    "requested_model": requested_model,
                    **request_config_metadata,
                },
            }
            yield f"data: {json.dumps(selection_payload)}\n\n"

            last_metadata: Dict[str, Any] = {}
            final_content = ""
            fallback_status_emitted = False

            try:
                async for chunk in get_chat_runtime().execute_stream(chat_request):
                    metadata = dict(chunk.metadata or {})
                    metadata = _normalize_runtime_truth_metadata(
                        metadata=metadata,
                        request=request,
                        final_state=None,
                        correlation_id=correlation_id,
                        conversation_id=conversation_id,
                        start_time=start_time,
                        request_config_metadata=request_config_metadata,
                        streaming_enabled=True,
                        transport=transport,
                        actual_response_mode=actual_mode,
                    )
                    last_metadata = metadata
                    llm_metadata = metadata.get("llm") or {}
                    actual_provider = llm_metadata.get("actual_provider")
                    if (
                        not fallback_status_emitted
                        and requested_provider
                        and actual_provider
                        and str(requested_provider).lower() != str(actual_provider).lower()
                    ):
                        failure_payload = {
                            "type": "status",
                            "content": "Requested provider unavailable; trying fallback.",
                            "correlation_id": correlation_id,
                            "metadata": {
                                **metadata,
                                "status": "provider_failed",
                                "fallback_next": actual_provider,
                            },
                        }
                        yield f"data: {json.dumps(failure_payload)}\n\n"
                        selected_payload = {
                            "type": "status",
                            "content": f"Fallback provider selected: {actual_provider}",
                            "correlation_id": correlation_id,
                            "metadata": {
                                **metadata,
                                "status": "fallback_provider_selected",
                            },
                        }
                        yield f"data: {json.dumps(selected_payload)}\n\n"
                        fallback_status_emitted = True

                    event_type = chunk.type
                    if event_type == "error":
                        payload_type = "error"
                    elif event_type == "complete":
                        payload_type = "complete"
                    elif metadata.get("status") and not chunk.content:
                        payload_type = "status"
                    else:
                        payload_type = "content"

                    if chunk.content:
                        final_content += chunk.content

                    yield f"data: {json.dumps({'type': payload_type, 'content': chunk.content, 'correlation_id': correlation_id, 'metadata': metadata})}\n\n"

                complete_metadata = _normalize_runtime_truth_metadata(
                    metadata=last_metadata,
                    request=request,
                    final_state=None,
                    correlation_id=correlation_id,
                    conversation_id=conversation_id,
                    start_time=start_time,
                    request_config_metadata=request_config_metadata,
                    streaming_enabled=True,
                    transport=transport,
                    actual_response_mode=actual_mode,
                )
                complete_payload = {
                    "type": "complete",
                    "content": "",
                    "correlation_id": correlation_id,
                    "metadata": {
                        **complete_metadata,
                        "status": "completed",
                        "content_length": len(final_content),
                    },
                }
                yield f"data: {json.dumps(complete_payload)}\n\n"
                yield "data: [DONE]\n\n"

            except Exception as stream_error:
                logger.error(
                    "Streaming error in copilot assist: %s",
                    stream_error,
                    extra={"correlation_id": correlation_id},
                )

                fallback_payload = await _build_router_fallback_assist_payload(
                    request=request,
                    correlation_id=correlation_id,
                    conversation_id=conversation_id,
                    start_time=start_time,
                    request_config_metadata=request_config_metadata,
                    actual_mode=actual_mode,
                    transport="sse",
                    failure=stream_error,
                    streaming_enabled=True,
                )
                if fallback_payload is not None:
                    for event in _build_router_fallback_sse_events(
                        fallback_payload, correlation_id
                    ):
                        yield f"data: {json.dumps(event)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                if degraded_continuation_response is not None:
                    degraded_payload = await _build_live_degraded_payload(
                        request.message,
                        degraded_continuation_response,
                        correlation_id,
                    )
                    for event in _build_degraded_sse_events(
                        degraded_payload,
                        correlation_id,
                        requested_provider=requested_provider,
                        requested_model=requested_model,
                    ):
                        yield f"data: {json.dumps(event)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                error_payload = {
                    "type": "error",
                    "content": "Streaming error: " + str(stream_error),
                    "correlation_id": correlation_id,
                    "metadata": {"error_type": "stream_error"},
                }
                yield f"data: {json.dumps(error_payload)}\n\n"
                yield "data: [DONE]\n\n"
                return

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Correlation-Id": correlation_id,
            },
        )

    except Exception as runtime_exc:
        logger.error(
            "Runtime control plane error: %s",
            runtime_exc,
            extra={"correlation_id": correlation_id},
        )
        degraded_continuation_response = DegradedResponse(
            mode="degraded",
            message="I'm currently experiencing some technical difficulties and can only provide limited responses. I'm Karen - your AI assistant. While I'm in degraded mode, I may not be able to answer complex questions fully, but I'll do my best to help with simple requests. For the best experience, please try again later when the system is fully operational.",
            capabilities=DegradedCapabilities(
                memory_available=False,
                tools_available=True,
                plugins_available=True,
                external_providers_available=True,
                streaming_supported=False,
                local_model_available=False,
                description="Degraded mode active - runtime control plane unavailable",
            ),
            is_minimal=True,
            retry_after_seconds=30,
            system_status_code=503,
            support_hint="Please try again in a few moments",
        )

        return StreamingResponse(
            stream_control_plane_fallback(
                degraded_continuation_response, None
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Correlation-Id": correlation_id,
            },
        )


__all__ = ["router"]
