"""Canonical HTTP/SSE ingress for AI KAREN chat execution.

This module owns transport validation and response translation only. Provider
selection, fallback policy, memory, prompt assembly, persistence, and execution
remain authoritative in ChatRuntime.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ai_karen_engine.core.logging import get_structured_logger
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.ag_ui_event_projection import AGUIEventProjection
from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
    ChatStreamChunk,
    ChatStreamEventType,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    runtime_response_http_status,
    serialize_runtime_response,
)
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.services.approvals import (
    ApprovalNotFoundError,
    ApprovalScopeError,
    ApprovalStateError,
    get_approval_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    """Validated chat message accepted by the HTTP ingress."""

    content: str = Field(..., min_length=1, max_length=10000)
    message_type: str = Field(default="user", pattern=r"^(user|assistant|system)$")
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return value.strip()


class ChatRequest(BaseModel):
    """Validated non-streaming or streaming chat request."""

    messages: List[ChatMessage] = Field(..., min_length=1, max_length=50)
    preferred_llm_provider: Optional[str] = Field(default=None, max_length=100)
    preferred_model: Optional[str] = Field(default=None, max_length=200)
    provider: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Deprecated compatibility alias for preferred_llm_provider.",
    )
    model: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Deprecated compatibility alias for preferred_model.",
    )
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    approval_id: Optional[str] = Field(default=None, max_length=64)
    stream: bool = False
    session_id: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=100,
    )
    conversation_id: Optional[str] = Field(default=None, max_length=100)
    timezone: Optional[str] = Field(default=None, max_length=100)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_+\-/]+", normalized):
            raise ValueError("Invalid timezone format")
        return normalized

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, messages: List[ChatMessage]) -> List[ChatMessage]:
        if sum(len(message.content) for message in messages) > 50000:
            raise ValueError("Total message content too long")
        return messages


class ChatResponse(BaseModel):
    """HTTP chat response envelope."""

    response_id: str
    content: str
    model: str
    usage: Dict[str, int]
    metadata: Dict[str, Any]
    structured_content: Dict[str, Any] = Field(default_factory=dict)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime


class ChatStreamRequest(BaseModel):
    """Compact request accepted by the canonical chat SSE route."""

    message: str = Field(..., min_length=1, max_length=10000)
    # Provisional same-session user turns only. Durable history still comes
    # exclusively from the conversation repository in the runtime.
    recent_user_messages: List[str] = Field(default_factory=list, max_length=12)
    workspace_run_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    session_id: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=100,
    )
    conversation_id: Optional[str] = Field(default=None, max_length=100)

    preferred_llm_provider: Optional[str] = Field(default=None, max_length=100)
    preferred_model: Optional[str] = Field(default=None, max_length=200)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    approval_id: Optional[str] = Field(default=None, max_length=64)
    timezone: Optional[str] = Field(default=None, max_length=100)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_+\-/]+", normalized):
            raise ValueError("Invalid timezone format")
        return normalized

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return value.strip()

    @field_validator("recent_user_messages")
    @classmethod
    def validate_recent_user_messages(cls, values: List[str]) -> List[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 500 for value in normalized):
            raise ValueError("Recent user messages must contain 1-500 characters")
        return normalized



class AGUIRunRequest(BaseModel):
    """Restricted AG-UI RunAgentInput ingress.

    The caller may provide a thread identity and its current user turn.
    Backend-owned history, tools, model selection, policy, and state are never
    accepted as authority from this transport.
    """

    threadId: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    runId: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    messages: List[Dict[str, Any]] = Field(..., min_length=1, max_length=50)
    tools: List[Dict[str, Any]] = Field(default_factory=list)
    context: List[Dict[str, Any]] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)
    forwardedProps: Dict[str, Any] = Field(default_factory=dict)

    def latest_user_message(self) -> str:
        last = self.messages[-1]
        if last.get("role") != "user":
            raise ValueError("AG-UI run must end with a user message")
        content = last.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "text":
                    raise ValueError("AG-UI multimodal messages are not yet supported")
                value = part.get("text")
                if not isinstance(value, str):
                    raise ValueError("Invalid AG-UI text message part")
                parts.append(value)
            text = "".join(parts)
        else:
            raise ValueError("AG-UI user message must contain text")
        if not 1 <= len(text.strip()) <= 10000:
            raise ValueError("AG-UI user message must contain 1-10000 characters")
        return text.strip()


class SecurityValidator:
    """Transport-level input validation helpers."""

    @staticmethod
    def sanitize_session_id(session_id: Optional[str]) -> str:
        if not session_id:
            return f"session_{uuid.uuid4().hex[:16]}"
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", session_id):
            raise ValueError("Invalid session ID format")
        return session_id

    @staticmethod
    def validate_user_input(user_input: str, max_length: int = 10000) -> str:
        if len(user_input) > max_length:
            raise ValueError(f"Input too long: {len(user_input)} > {max_length}")
        sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", user_input)
        return sanitized.strip()


def _require_execution_identity(user: Dict[str, Any]) -> Tuple[str, str]:
    """Resolve authenticated user and tenant scope without synthesizing either."""
    user_id = str(user.get("user_id") or "").strip()
    tenant_id = str(user.get("tenant_id") or "").strip()

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authenticated user identity is incomplete",
        )
    if not tenant_id:
        raise HTTPException(
            status_code=401,
            detail="Authenticated tenant context is required",
        )
    return user_id, tenant_id


def _normalize_messages(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
    return [
        {
            "role": message.message_type,
            "content": SecurityValidator.validate_user_input(message.content),
        }
        for message in messages
    ]


def _execution_context(
    *,
    user: Dict[str, Any],
    session_id: str,
    conversation_id: Optional[str],
    request_id: str,
    correlation_id: str,
) -> ChatExecutionContext:
    user_id, tenant_id = _require_execution_identity(user)
    return ChatExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        correlation_id=correlation_id,
        roles=list(user.get("roles") or []),
        permissions=list(user.get("permissions") or []),
        authenticated_user=UserData.ensure(user),
    )


def _stream_execution_request(
    *,
    request: ChatStreamRequest,
    user: Dict[str, Any],
    session_id: str,
    correlation_id: str,
    response_id: str,
) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[
            {
                "role": "user",
                "content": SecurityValidator.validate_user_input(request.message),
            }
        ],
        context=_execution_context(
            user=user,
            session_id=session_id,
            conversation_id=request.conversation_id,
            request_id=response_id,
            correlation_id=correlation_id,
        ),
        preferred_provider=request.preferred_llm_provider,
        preferred_model=request.preferred_model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=True,
        metadata={
            "transport": "sse",
            "ingress_recent_user_messages": [
                SecurityValidator.validate_user_input(value, max_length=500)
                for value in request.recent_user_messages
            ],
            **({"user_timezone": request.timezone} if request.timezone else {}),
            **({"approval_id": request.approval_id} if request.approval_id else {}),
        },
    )


async def _verified_workspace_run_reference(
    *, run_id: str, user: Dict[str, Any],
) -> Dict[str, Any]:
    """Resolve a chat work reference from the canonical owner-checked Medusa record.

    This is context evidence, never an execution capability or approval.
    """
    from ai_karen_engine.api_routes.agents.runtime import (
        get_my_run_context, get_run_control_plane,
    )
    return await get_my_run_context(
        run_id,
        current_user=UserData.ensure(user),
        control_plane=get_run_control_plane(),
    )


async def _sse(runtime_request: ChatExecutionRequest):
    """Transport-only framing and fail-closed terminal integrity.

    Runtime owns execution and model truth. Ingress emits an immediate,
    authenticated transport comment before potentially slow context and model
    preparation, then transparently forwards every runtime event. A graceful
    runtime return without a terminal event cannot become silent HTTP 200.
    """
    correlation_id = runtime_request.context.correlation_id
    terminal_seen = False

    # SSE comment flushes headers/first bytes without pretending the model
    # advanced. The browser ignores comments, so its shorter progress-status
    # silence timeout is not activated during provider warmup.
    yield ": stream_connected\n\n"

    try:
        async for chunk in get_chat_runtime().execute_stream(runtime_request):
            if chunk.type in (ChatStreamEventType.COMPLETE, ChatStreamEventType.ERROR):
                terminal_seen = True
            yield f"data: {json.dumps(chunk.to_sse_payload())}\n\n"
    except Exception as exc:
        logger.exception(
            "Chat SSE runtime failed",
            extra={
                "correlation_id": correlation_id,
                "error_type": type(exc).__name__,
            },
        )
        error_event = ChatStreamChunk(
            type=ChatStreamEventType.ERROR,
            content="Chat streaming failed before completion.",
            correlation_id=correlation_id,
            metadata={
                "error_code": "CHAT_STREAM_RUNTIME_EXCEPTION",
                "error_type": type(exc).__name__,
                "correlation_id": correlation_id,
            },
        )
        yield f"data: {json.dumps(error_event.to_sse_payload())}\n\n"
        terminal_seen = True

    if not terminal_seen:
        logger.error(
            "Chat runtime returned without terminal SSE event",
            extra={"correlation_id": correlation_id, "error_code": "CHAT_SSE_MISSING_TERMINAL"},
        )
        error_event = ChatStreamChunk(
            type=ChatStreamEventType.ERROR,
            content="The chat runtime stopped before completing its response.",
            correlation_id=correlation_id,
            metadata={
                "error_code": "CHAT_SSE_MISSING_TERMINAL",
                "error_type": "MissingTerminalEvent",
                "correlation_id": correlation_id,
            },
        )
        yield f"data: {json.dumps(error_event.to_sse_payload())}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/chat", response_model=ChatResponse)
async def create_chat_response(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Validate HTTP input and delegate all chat execution to ChatRuntime."""
    del background_tasks
    start_time = time.time()
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    response_id = str(uuid.uuid4())
    structured_logger = get_structured_logger()
    session_id = "unknown"

    try:
        user_id, _ = _require_execution_identity(user)
        session_id = SecurityValidator.sanitize_session_id(request.session_id)
        preferred_provider = request.preferred_llm_provider or request.provider
        preferred_model = request.preferred_model or request.model

        runtime_request = ChatExecutionRequest(
            messages=_normalize_messages(request.messages),
            context=_execution_context(
                user=user,
                session_id=session_id,
                conversation_id=request.conversation_id,
                request_id=response_id,
                correlation_id=correlation_id,
            ),
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=request.stream,
            metadata={
                "transport": "http",
                **({"user_timezone": request.timezone} if request.timezone else {}),
                **({"approval_id": request.approval_id} if request.approval_id else {}),
            },
        )

        structured_logger.log_event(
            event="chat_request_started",
            user_id=user_id,
            details={
                "method": "POST",
                "endpoint": "/api/chat",
                "correlation_id": correlation_id,
                "message_count": len(runtime_request.messages),
                "preferred_llm_provider": preferred_provider,
                "preferred_model": preferred_model,
                "stream": request.stream,
                "session_id": session_id,
            },
        )

        if request.stream:
            return StreamingResponse(
                _sse(runtime_request),
                media_type="text/event-stream",
                headers={
                    "X-Correlation-Id": correlation_id,
                    "X-Response-Id": response_id,
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        result = await get_chat_runtime().execute(runtime_request)

        if result.status == ChatExecutionStatus.GATE and result.gate_response is not None:
            gate = result.gate_response
            payload = serialize_runtime_response(gate) or {}
            status_code = runtime_response_http_status(gate) or 503
            headers: Dict[str, str] = {}
            retry_after = getattr(gate, "retry_after_seconds", None)
            if retry_after is not None:
                headers["Retry-After"] = str(retry_after)
            return JSONResponse(status_code=status_code, content=payload, headers=headers)

        response_metadata = result.metadata.to_dict()
        actual_model = response_metadata.get("actual_model") or "unknown"
        processing_time = time.time() - start_time

        structured_logger.log_response(
            status_code=200,
            endpoint="/api/chat",
            user_id=user_id,
            correlation_id=correlation_id,
            response_data={
                "response_id": response_id,
                "model": actual_model,
                "processing_time": processing_time,
            },
        )

        llm_metadata = response_metadata.get("llm")
        usage = (
            llm_metadata.get("usage", {})
            if isinstance(llm_metadata, dict)
            else {}
        )
        return ChatResponse(
            response_id=response_id,
            content=result.answer,
            model=actual_model,
            usage=usage,
            metadata=response_metadata,
            structured_content=result.structured_content,
            actions=result.actions,
            citations=result.citations,
            sources=result.sources,
            attachments=result.attachments,
            artifacts=result.artifacts,
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except ValueError as exc:
        structured_logger.log_error(
            error=str(exc),
            endpoint="/api/chat",
            user_id=str(user.get("user_id") or "unknown"),
            correlation_id=correlation_id,
            context="validation_error",
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chat/stream")
async def stream_chat_response(
    request: ChatStreamRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Validate SSE input and delegate streaming execution to ChatRuntime."""
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    response_id = str(uuid.uuid4())
    structured_logger = get_structured_logger()

    try:
        user_id, _ = _require_execution_identity(user)
        session_id = SecurityValidator.sanitize_session_id(request.session_id)
        runtime_request = _stream_execution_request(
            request=request,
            user=user,
            session_id=session_id,
            correlation_id=correlation_id,
            response_id=response_id,
        )
        if request.workspace_run_id:
            verified = await _verified_workspace_run_reference(
                run_id=request.workspace_run_id, user=user,
            )
            runtime_request.metadata["verified_workspace_run"] = verified
        conversation_id = runtime_request.context.conversation_id or session_id

        structured_logger.log_event(
            event="chat_stream_started",
            user_id=user_id,
            details={
                "endpoint": "/api/chat/stream",
                "correlation_id": correlation_id,
                "response_id": response_id,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "preferred_provider": runtime_request.preferred_provider,
                "preferred_model": runtime_request.preferred_model,
            },
        )

        return StreamingResponse(
            _sse(runtime_request),
            media_type="text/event-stream",
            headers={
                "X-Correlation-Id": correlation_id,
                "X-Response-Id": response_id,
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    except HTTPException:
        raise
    except ValueError as exc:
        structured_logger.log_error(
            error=str(exc),
            endpoint="/api/chat/stream",
            user_id=str(user.get("user_id") or "unknown"),
            correlation_id=correlation_id,
            context="validation_error",
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc



async def _ag_ui_sse(
    runtime_request: ChatExecutionRequest, *, thread_id: str, run_id: str
):
    """Translate the same authorized runtime stream into AG-UI event framing."""
    projection = AGUIEventProjection(thread_id=thread_id, run_id=run_id)
    yield ": stream_connected\n\n"
    yield f"data: {json.dumps(projection.begin())}\n\n"

    try:
        async for chunk in get_chat_runtime().execute_stream(runtime_request):
            for event in projection.project(chunk):
                yield f"data: {json.dumps(event)}\n\n"
            if projection.terminal:
                break
    except Exception as exc:
        logger.exception(
            "AG-UI runtime projection failed",
            extra={
                "correlation_id": runtime_request.context.correlation_id,
                "error_type": type(exc).__name__,
            },
        )
        error_chunk = ChatStreamChunk(
            type=ChatStreamEventType.ERROR,
            content="Chat streaming failed before completion.",
            correlation_id=runtime_request.context.correlation_id,
            metadata={"error_code": "CHAT_STREAM_RUNTIME_EXCEPTION"},
        )
        for event in projection.project(error_chunk):
            yield f"data: {json.dumps(event)}\n\n"

    for event in projection.fail_incomplete():
        yield f"data: {json.dumps(event)}\n\n"


@router.post("/chat/ag-ui")
async def stream_ag_ui_chat(
    request: AGUIRunRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """AG-UI-compatible wire adapter; never a second chat execution path."""
    if not get_runtime_settings().features.enable_ag_ui_bridge:
        raise HTTPException(status_code=404, detail="AG-UI bridge is disabled")
    # AG-UI may carry only a bounded resource lookup hint. Never trust the
    # client-supplied context, tools, or state as authorization.
    workspace_ref = request.forwardedProps.get("workspace_run_id")
    if request.forwardedProps and (
        set(request.forwardedProps) != {"workspace_run_id"}
        or not isinstance(workspace_ref, str)
        or not 1 <= len(workspace_ref) <= 128
    ):
        raise HTTPException(status_code=422, detail="Unsupported workspace context")
    # Reject ungoverned client-provided tools, shared state and context.
    if request.tools or request.state or request.context:
        raise HTTPException(
            status_code=422,
            detail="Client-supplied tools, state and context are not supported by Karen",
        )
    try:
        user_id, _tenant_id = _require_execution_identity(user)
        current_text = request.latest_user_message()
        correlation_id = http_request.headers.get("X-Correlation-Id") or str(uuid.uuid4())
        response_id = str(uuid.uuid4())
        # Assistant-ui's canonical threadId is Karen's already-persisted
        # conversation UUID. Resolve its owner and actual runtime session
        # using the SAME runtime gateway as existing conversation ingress.
        # A foreign or missing thread must never silently create a new one.
        session_id = SecurityValidator.sanitize_session_id(request.threadId)
        conversation_id = None
        try:
            uuid.UUID(request.threadId)
        except (TypeError, ValueError):
            # Backward compatibility for historical opaque AG-UI session ids.
            # The canonical scoped runtime generates its tenant-isolated id.
            pass
        else:
            from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
                get_conversation_runtime_gateway,
            )
            lookup_context = _execution_context(
                user=user,
                session_id=session_id,
                conversation_id=request.threadId,
                request_id=response_id,
                correlation_id=correlation_id,
            )
            try:
                owned = await get_conversation_runtime_gateway().get_owned_snapshot(
                    lookup_context, message_limit=0,
                )
            except (PermissionError, RuntimeError, ValueError) as exc:
                raise HTTPException(
                    status_code=404, detail="Conversation is unavailable",
                ) from exc
            conversation_id = str(owned.conversation.id)
            session_id = SecurityValidator.sanitize_session_id(
                str(owned.conversation.session_id)
            )
        canonical_request = _stream_execution_request(
            request=ChatStreamRequest(
                message=current_text,
                session_id=session_id,
                conversation_id=conversation_id,
                workspace_run_id=workspace_ref,
            ),
            user=user,
            session_id=session_id,
            correlation_id=correlation_id,
            response_id=response_id,
        )
        if workspace_ref:
            canonical_request.metadata["verified_workspace_run"] = (
                await _verified_workspace_run_reference(run_id=workspace_ref, user=user)
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    get_structured_logger().log_event(
        event="chat_stream_started",
        user_id=user_id,
        details={
            "endpoint": "/api/chat/ag-ui",
            "correlation_id": correlation_id,
            "response_id": response_id,
            # Caller-issued AG-UI run correlation is not a durable ledger ID.
            "ag_ui_transport_run_id": request.runId,
            "conversation_id": canonical_request.context.conversation_id,
            "transport": "ag-ui",
        },
    )
    return StreamingResponse(
        _ag_ui_sse(
            canonical_request,
            thread_id=request.threadId,
            run_id=request.runId,
        ),
        media_type="text/event-stream",
        headers={
            "X-Correlation-Id": correlation_id,
            "X-Response-Id": response_id,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/chat/approvals/{approval_id}/resume")
async def resume_approved_chat(
    approval_id: str,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Resume an approved request through the canonical streaming runtime."""
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    response_id = str(uuid.uuid4())
    principal = UserData.ensure(user)

    try:
        runtime_request = await get_approval_service().build_resume_request(
            approval_id,
            user=principal,
            request_id=response_id,
            correlation_id=correlation_id,
            fresh_permissions=list(user.get("permissions") or []),
            stream=True,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ApprovalScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return StreamingResponse(
        _sse(runtime_request),
        media_type="text/event-stream",
        headers={
            "X-Correlation-Id": correlation_id,
            "X-Response-Id": response_id,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/models")
async def get_available_models(
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Delegate user-scoped model discovery to the canonical runtime orchestrator."""
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    structured_logger = get_structured_logger()

    try:
        user_id, _ = _require_execution_identity(user)
        orchestrator = await get_chat_runtime().get_orchestrator()
        get_models = getattr(orchestrator, "get_available_models", None)
        if not callable(get_models):
            raise HTTPException(status_code=501, detail="Model listing not supported")

        models = await get_models(user_context=user)
        structured_logger.log_event(
            event="chat_models_listed",
            user_id=user_id,
            details={"correlation_id": correlation_id, "count": len(models)},
        )
        return {"models": models, "count": len(models)}

    except HTTPException:
        raise
    except Exception as exc:
        structured_logger.log_error(
            error="Unable to list available models",
            endpoint="/api/models",
            user_id=str(user.get("user_id") or "unknown"),
            correlation_id=correlation_id,
            context="model_listing_error",
        )
        raise HTTPException(status_code=500, detail="Unable to list available models") from exc
