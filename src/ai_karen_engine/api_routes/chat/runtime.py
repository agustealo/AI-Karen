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
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    runtime_response_http_status,
    serialize_runtime_response,
)
from ai_karen_engine.core.services.dependencies import bypass_user_context_func
from ai_karen_engine.utils.chat_helpers import (
    normalize_session_id as normalize_chat_session_id,
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
    stream: bool = False
    session_id: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=100,
    )

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
    timestamp: datetime


class ChatStreamRequest(BaseModel):
    """Compact request accepted by the canonical chat SSE route."""

    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=100,
    )
    preferred_llm_provider: Optional[str] = Field(default=None, max_length=100)
    preferred_model: Optional[str] = Field(default=None, max_length=200)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return value.strip()


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
    request_id: str,
    correlation_id: str,
) -> ChatExecutionContext:
    user_id, tenant_id = _require_execution_identity(user)
    return ChatExecutionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation_id=normalize_chat_session_id(session_id),
        request_id=request_id,
        correlation_id=correlation_id,
        roles=list(user.get("roles") or []),
        permissions=list(user.get("permissions") or []),
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
            request_id=response_id,
            correlation_id=correlation_id,
        ),
        preferred_provider=request.preferred_llm_provider,
        preferred_model=request.preferred_model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=True,
        metadata={"transport": "sse"},
    )


async def _sse(runtime_request: ChatExecutionRequest):
    async for chunk in get_chat_runtime().execute_stream(runtime_request):
        yield f"data: {json.dumps(chunk.to_sse_payload())}\n\n"
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
                request_id=response_id,
                correlation_id=correlation_id,
            ),
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=request.stream,
            metadata={"transport": "http"},
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
    except Exception as exc:
        structured_logger.log_error(
            error=str(exc),
            endpoint="/api/chat",
            user_id=str(user.get("user_id") or "unknown"),
            correlation_id=correlation_id,
            context="unexpected_error",
            details={"session_id": session_id},
        )
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/stream")
async def stream_chat_response(
    request: ChatStreamRequest,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Validate SSE input and delegate streaming execution to ChatRuntime."""
    start_time = time.time()
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
        conversation_id = runtime_request.context.conversation_id or session_id

        structured_logger.log_event(
            event="chat_stream_started",
            user_id=user_id,
            details={
                "endpoint": "/api/stream",
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
            endpoint="/api/stream",
            user_id=str(user.get("user_id") or "unknown"),
            correlation_id=correlation_id,
            context="validation_error",
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        structured_logger.log_error(
            error=str(exc),
            endpoint="/api/stream",
            user_id=str(user.get("user_id") or "unknown"),
            correlation_id=correlation_id,
            context="unexpected_error",
            details={"duration_ms": (time.time() - start_time) * 1000.0},
        )
        raise HTTPException(status_code=500, detail="Internal server error") from exc


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
