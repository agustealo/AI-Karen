"""Authenticated real-time transport adapters for AI KAREN.

This module owns WebSocket/SSE/NDJSON transport only. All chat generation,
provider selection, fallback, memory, prompt assembly, policy, persistence, and
telemetry remain authoritative in :class:`ChatRuntime`.

The historical ``AsyncStreamProcessor`` inference path is intentionally not
referenced here. Legacy stream-management URLs remain as honest ``410 Gone``
compatibility boundaries instead of silently producing simulated model output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ai_karen_engine.api_routes.chat.execution_identity import (
    build_chat_execution_context,
    require_execution_identity,
)
from ai_karen_engine.auth.auth_service import get_auth_service, user_account_to_dict
from ai_karen_engine.auth.cookie_manager import get_cookie_manager
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    DegradedResponse,
    EmergencyFallbackResponse,
    MaintenanceResponse,
    get_chat_runtime_control_plane,
    serialize_runtime_response,
)
from ai_karen_engine.core.security.auth_config import auth_config
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.services.streaming.websocket_gateway import WebSocketGateway
from ai_karen_engine.utils.chat_helpers import (
    normalize_session_id as normalize_chat_session_id,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class StreamChatRequest(BaseModel):
    """Compatibility streaming request normalized into ``ChatExecutionRequest``.

    ``user_id`` is accepted only for backward wire compatibility and is ignored.
    The authenticated principal is always resolved server-side.
    """

    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: Optional[str] = Field(default=None, max_length=200)
    user_id: Optional[str] = Field(default=None, max_length=200)
    session_id: Optional[str] = Field(default=None, max_length=100)
    stream_type: str = Field("sse", pattern=r"^(sse|http)$")
    include_context: bool = True
    preferred_llm_provider: Optional[str] = Field(default=None, max_length=100)
    preferred_model: Optional[str] = Field(default=None, max_length=200)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WebSocketStatsResponse(BaseModel):
    total_connections: int
    authenticated_connections: int
    unique_users: int
    active_conversations: int
    typing_users: int
    online_users: int
    queue_stats: Dict[str, Any]


def get_runtime_service():
    return get_chat_runtime()


async def get_websocket_gateway(
    runtime_service=Depends(get_runtime_service),
) -> WebSocketGateway:
    """Resolve the existing transport gateway without creating execution authority."""

    orchestrator = await runtime_service.get_orchestrator()
    return WebSocketGateway(orchestrator)


def _normalize_session_id(value: Optional[str]) -> str:
    if value is None or not str(value).strip():
        return f"session_{uuid.uuid4().hex[:16]}"
    session_id = str(value).strip()
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    return session_id


def _is_admin(user: Dict[str, Any]) -> bool:
    return "admin" in {
        str(role).strip().lower() for role in (user.get("roles") or [])
    }


def _require_admin(user: Dict[str, Any]) -> tuple[str, str]:
    identity = require_execution_identity(user)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return identity


def _require_self_or_admin(user: Dict[str, Any], target_user_id: str) -> tuple[str, str]:
    user_id, tenant_id = require_execution_identity(user)
    if user_id != str(target_user_id) and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Cross-user access denied")
    return user_id, tenant_id


def _extract_websocket_token(websocket: WebSocket) -> Optional[str]:
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token

    try:
        configured_cookie = get_cookie_manager().config.session_cookie
    except Exception:
        configured_cookie = "kari_session"

    for cookie_name in (
        configured_cookie,
        "kari_session",
        "session_token",
        "access_token",
    ):
        token = websocket.cookies.get(cookie_name)
        if token:
            return token
    return None


async def get_current_user_websocket(websocket: WebSocket) -> Dict[str, Any]:
    """Authenticate a WebSocket through the canonical authentication authority."""

    if auth_config.should_bypass_auth():
        user = dict(auth_config.get_dev_user_context())
        require_execution_identity(user)
        return user

    token = _extract_websocket_token(websocket)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        service = await get_auth_service()
        account = await service.validate_token(token)
    except Exception as exc:
        logger.warning(
            "WebSocket authentication service failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable",
        ) from exc

    if account is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = user_account_to_dict(account)
    require_execution_identity(user)
    return user


def _build_stream_request(
    *,
    request: StreamChatRequest,
    user: Dict[str, Any],
    correlation_id: str,
    response_id: str,
    transport: str,
) -> ChatExecutionRequest:
    require_execution_identity(user)
    session_id = _normalize_session_id(request.session_id)
    conversation_id = (
        str(request.conversation_id or "").strip()
        or normalize_chat_session_id(session_id)
    )
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": request.message.strip()}],
        context=build_chat_execution_context(
            user=user,
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=response_id,
            correlation_id=correlation_id,
        ),
        preferred_provider=request.preferred_llm_provider,
        preferred_model=request.preferred_model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=True,
        metadata={
            "transport": transport,
            "include_context": request.include_context,
            "compatibility_user_id_present": bool(request.user_id),
            "client_metadata": dict(request.metadata or {}),
        },
    )


async def _sse_chunks(runtime_request: ChatExecutionRequest):
    async for chunk in get_chat_runtime().execute_stream(runtime_request):
        yield f"data: {json.dumps(chunk.to_sse_payload())}\n\n"
    yield "data: [DONE]\n\n"


async def _ndjson_chunks(runtime_request: ChatExecutionRequest):
    async for chunk in get_chat_runtime().execute_stream(runtime_request):
        yield json.dumps(chunk.to_sse_payload()) + "\n"
    yield json.dumps({"type": "done"}) + "\n"


def _retired_stream_control(session_id: Optional[str] = None) -> JSONResponse:
    payload: Dict[str, Any] = {
        "detail": "Legacy stream session control has been retired",
        "canonical_stream_endpoint": "/api/stream",
        "runtime_authority": "ChatRuntime",
    }
    if session_id:
        payload["session_id"] = session_id
    return JSONResponse(status_code=410, content=payload)


@router.websocket("/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    current_user: Dict[str, Any] = Depends(get_current_user_websocket),
):
    """Bidirectional chat transport backed only by ``ChatRuntime.execute_stream``."""

    user_id, tenant_id = require_execution_identity(current_user)
    runtime_response = await get_chat_runtime_control_plane().get_runtime_response(
        user_context=current_user
    )
    if runtime_response is not None:
        await websocket.accept()
        payload: Dict[str, Any] = {"type": "runtime_mode"}
        if isinstance(
            runtime_response,
            (MaintenanceResponse, EmergencyFallbackResponse, DegradedResponse),
        ):
            payload.update(serialize_runtime_response(runtime_response) or {})
        await websocket.send_text(json.dumps(payload))
        await websocket.close(code=1013)
        return

    await websocket.accept()
    connection_id = str(uuid.uuid4())
    session_id = f"ws_{connection_id.replace('-', '')[:24]}"
    conversation_id = normalize_chat_session_id(session_id)

    logger.info(
        "WebSocket chat connected",
        extra={
            "connection_id": connection_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
        },
    )

    try:
        while True:
            try:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "Invalid JSON payload.",
                                "metadata": {"error_code": "INVALID_JSON"},
                            }
                        )
                    )
                    continue

                user_message = str(message.get("message") or "").strip()
                if not user_message:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "A non-empty message is required.",
                                "metadata": {"error_code": "EMPTY_MESSAGE"},
                            }
                        )
                    )
                    continue
                if len(user_message) > 10000:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "Message is too long.",
                                "metadata": {"error_code": "MESSAGE_TOO_LONG"},
                            }
                        )
                    )
                    continue

                correlation_id = str(uuid.uuid4())
                request_id = str(uuid.uuid4())
                runtime_request = ChatExecutionRequest(
                    messages=[{"role": "user", "content": user_message}],
                    context=build_chat_execution_context(
                        user=current_user,
                        session_id=session_id,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        correlation_id=correlation_id,
                    ),
                    preferred_provider=(
                        str(message.get("preferred_llm_provider") or "").strip() or None
                    ),
                    preferred_model=(
                        str(message.get("preferred_model") or "").strip() or None
                    ),
                    stream=True,
                    metadata={"transport": "websocket"},
                )

                async for chunk in get_chat_runtime().execute_stream(runtime_request):
                    await websocket.send_text(json.dumps(chunk.to_sse_payload()))

            except WebSocketDisconnect:
                raise
            except Exception as exc:
                logger.exception(
                    "WebSocket chat execution failed",
                    extra={
                        "connection_id": connection_id,
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                        "error_type": type(exc).__name__,
                    },
                )
                try:
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "Unable to complete the response.",
                                "metadata": {"error_code": "WEBSOCKET_CHAT_FAILED"},
                            }
                        )
                    )
                except Exception:
                    break
    except WebSocketDisconnect as exc:
        logger.info(
            "WebSocket chat disconnected",
            extra={"connection_id": connection_id, "code": exc.code},
        )


@router.post("/stream/sse")
async def stream_chat_sse(
    request: StreamChatRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> StreamingResponse:
    """Legacy SSE URL adapted directly to canonical ``ChatRuntime`` streaming."""

    correlation_id = http_request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    response_id = str(uuid.uuid4())
    runtime_request = _build_stream_request(
        request=request,
        user=user,
        correlation_id=correlation_id,
        response_id=response_id,
        transport="legacy_sse_compat",
    )
    return StreamingResponse(
        _sse_chunks(runtime_request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Correlation-Id": correlation_id,
            "X-Response-Id": response_id,
            "Link": '</api/stream>; rel="successor-version"',
        },
    )


@router.post("/stream/http")
async def stream_chat_http(
    request: StreamChatRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> StreamingResponse:
    """Legacy NDJSON URL adapted directly to canonical ``ChatRuntime`` streaming."""

    correlation_id = http_request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
    response_id = str(uuid.uuid4())
    runtime_request = _build_stream_request(
        request=request,
        user=user,
        correlation_id=correlation_id,
        response_id=response_id,
        transport="legacy_http_stream_compat",
    )
    return StreamingResponse(
        _ndjson_chunks(runtime_request),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Correlation-Id": correlation_id,
            "X-Response-Id": response_id,
            "Link": '</api/stream>; rel="successor-version"',
        },
    )


@router.get("/stream/{session_id}/status")
async def get_stream_status(
    session_id: str,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    require_execution_identity(user)
    return _retired_stream_control(session_id)


@router.post("/stream/{session_id}/pause")
async def pause_stream(
    session_id: str,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    require_execution_identity(user)
    return _retired_stream_control(session_id)


@router.post("/stream/{session_id}/resume")
async def resume_stream(
    session_id: str,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    require_execution_identity(user)
    return _retired_stream_control(session_id)


@router.post("/stream/{session_id}/cancel")
async def cancel_stream(
    session_id: str,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    require_execution_identity(user)
    return _retired_stream_control(session_id)


@router.post("/stream/{session_id}/recover")
async def recover_stream(
    session_id: str,
    from_sequence: Optional[int] = Query(None),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    del from_sequence
    require_execution_identity(user)
    return _retired_stream_control(session_id)


@router.websocket("/models/events")
async def websocket_model_events_endpoint(
    websocket: WebSocket,
    current_user: Dict[str, Any] = Depends(get_current_user_websocket),
):
    """Authenticated admin transport for model-operation events."""

    _require_admin(current_user)
    from ai_karen_engine.event_bus import get_event_bus

    event_bus = get_event_bus()
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=200)

    async def handle_model_event(event_data: Dict[str, Any]) -> None:
        message = {
            "type": "model_event",
            "event": event_data.get("event_type"),
            "data": event_data.get("payload", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("Dropping model event for slow WebSocket consumer")

    event_bus.subscribe("model_orchestrator", handle_model_event)
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    await websocket.send_text(
        json.dumps(
            {
                "type": "connection_established",
                "connection_id": connection_id,
                "subscribed_events": ["model_orchestrator"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    )

    async def sender() -> None:
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event))

    sender_task = asyncio.create_task(sender())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({"type": "error", "message": "Invalid JSON format"})
                )
                continue
            if message.get("type") == "ping":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "pong",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        await asyncio.gather(sender_task, return_exceptions=True)


@router.get("/models/events/sse")
async def model_events_sse(
    http_request: Request,
    job_id: Optional[str] = Query(None, description="Specific job ID to track"),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> StreamingResponse:
    """Authenticated admin SSE transport for model-operation events."""

    _require_admin(user)

    async def event_generator():
        from ai_karen_engine.event_bus import get_event_bus

        event_bus = get_event_bus()
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=200)

        async def handle_event(event_data: Dict[str, Any]) -> None:
            payload = event_data.get("payload", {}) or {}
            if job_id and payload.get("job_id") != job_id:
                return
            message = {
                "type": "model_event",
                "event": event_data.get("event_type"),
                "data": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Dropping model event for slow SSE consumer")

        event_bus.subscribe("model_orchestrator", handle_event)
        yield "event: connected\ndata: {}\n\n"

        last_heartbeat = asyncio.get_running_loop().time()
        while not await http_request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"event: model_event\ndata: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                pass

            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= 30.0:
                heartbeat = {
                    "type": "heartbeat",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"
                last_heartbeat = now

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/stats", response_model=WebSocketStatsResponse)
async def get_websocket_stats(
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    _require_admin(user)
    return WebSocketStatsResponse(**gateway.get_connection_stats())


@router.get("/stream/metrics")
async def get_stream_metrics(
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    _require_admin(user)
    return _retired_stream_control()


@router.get("/stream/active")
async def list_active_streams(
    user: Dict[str, Any] = Depends(bypass_user_context_func),
) -> JSONResponse:
    _require_admin(user)
    return _retired_stream_control()


@router.get("/presence/{user_id}")
async def get_user_presence(
    user_id: str,
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    _require_self_or_admin(user, user_id)
    presence = gateway.presence_manager.get_presence(user_id)
    return {"user_id": user_id, "presence": presence}


@router.get("/presence/online")
async def get_online_users(
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    _require_admin(user)
    online_users = gateway.presence_manager.get_online_users()
    return {"online_users": online_users, "count": len(online_users)}


@router.get("/typing/{conversation_id}")
async def get_typing_users(
    conversation_id: str,
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    require_execution_identity(user)
    typing_users = gateway.typing_manager.get_typing_users(conversation_id)
    return {
        "conversation_id": conversation_id,
        "typing_users": typing_users,
        "count": len(typing_users),
    }


@router.get("/queue/{user_id}")
async def get_queued_messages(
    user_id: str,
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    _require_self_or_admin(user, user_id)
    queued_messages = await gateway.message_queue.get_queued_messages(user_id)
    return {
        "user_id": user_id,
        "queued_messages": [
            {
                "message_id": msg.message.message_id,
                "type": msg.message.type.value,
                "content": msg.message.data,
                "queued_at": msg.queued_at.isoformat(),
                "expires_at": msg.expires_at.isoformat() if msg.expires_at else None,
                "delivery_attempts": msg.delivery_attempts,
            }
            for msg in queued_messages
        ],
        "count": len(queued_messages),
    }


@router.delete("/queue/{user_id}")
async def clear_queued_messages(
    user_id: str,
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    _require_self_or_admin(user, user_id)
    await gateway.message_queue.clear_queued_messages(user_id)
    return {"success": True, "user_id": user_id}


@router.get("/connections/{user_id}")
async def get_user_connections(
    user_id: str,
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    _require_self_or_admin(user, user_id)
    connections = gateway.get_user_connections(user_id)
    return {"user_id": user_id, "connections": connections, "count": len(connections)}


@router.get("/connections/conversation/{conversation_id}")
async def get_conversation_connections(
    conversation_id: str,
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    _require_admin(user)
    connections = gateway.get_conversation_connections(conversation_id)
    return {
        "conversation_id": conversation_id,
        "connections": connections,
        "count": len(connections),
    }


@router.get("/health")
async def websocket_health_check(
    gateway: WebSocketGateway = Depends(get_websocket_gateway),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    require_execution_identity(user)
    try:
        stats = gateway.get_connection_stats()
        return {
            "status": "healthy",
            "runtime_authority": "ChatRuntime",
            "legacy_stream_processor": "retired",
            "websocket_gateway": {
                "status": "running",
                "connections": stats.get("total_connections", 0),
                "authenticated_users": stats.get("unique_users", 0),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.exception(
            "WebSocket health check failed",
            extra={"error_type": type(exc).__name__},
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "runtime_authority": "ChatRuntime",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


__all__ = [
    "StreamChatRequest",
    "get_current_user_websocket",
    "router",
    "stream_chat_http",
    "stream_chat_sse",
    "websocket_chat_endpoint",
]
