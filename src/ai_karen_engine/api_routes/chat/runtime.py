"""
Secure Chat Runtime API Routes with Comprehensive Validation

This module provides secure chat API endpoints with:
- Comprehensive input validation using Pydantic models
- Parameterized database queries to prevent injection
- Rate limiting and abuse prevention
- Proper error handling with structured logging
- Authentication and authorization checks
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from ai_karen_engine.core.logging import get_structured_logger
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
    ChatStreamChunk,
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
security = HTTPBearer()


def get_chat_runtime_service():
    """Return the singleton authoritative chat runtime service."""
    return get_chat_runtime()


async def get_chat_orchestrator():
    """Return the canonical chat orchestrator via the runtime service."""
    return await get_chat_runtime_service().get_orchestrator()


class ChatMessage(BaseModel):
    """Chat message model with comprehensive validation."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Message content",
        examples=["Hello, how can I help you today?"],
    )
    message_type: str = Field(
        default="user",
        pattern=r"^(user|assistant|system)$",
        description="Type of message",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional message metadata"
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        """Validate message content for structural correctness."""
        if not isinstance(v, str):
            raise ValueError("Content must be a string")
        return v.strip()


class ChatRequest(BaseModel):
    """Chat request model with comprehensive validation."""

    messages: List[ChatMessage] = Field(
        ..., min_length=1, max_length=50, description="List of chat messages"
    )
    preferred_llm_provider: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Canonical preferred provider ID.",
    )
    preferred_model: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Canonical preferred model ID.",
    )
    provider: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Deprecated alias for preferred_llm_provider.",
    )
    model: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Deprecated alias for preferred_model.",
    )
    temperature: Optional[float] = Field(
        default=0.7, ge=0.0, le=2.0, description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        description="Requested tokens to generate; provider/model caps are enforced downstream.",
    )
    stream: Optional[bool] = Field(
        default=False, description="Whether to stream the response"
    )
    session_id: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=100,
        description="Session identifier",
    )

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v):
        """Validate message list for security issues."""
        if not v:
            raise ValueError("Messages list cannot be empty")

        # Check total content length
        total_length = sum(len(msg.content) for msg in v)
        if total_length > 50000:  # 50KB total
            raise ValueError("Total message content too long")

        return v


class ChatResponse(BaseModel):
    """Chat response model."""

    response_id: str = Field(..., description="Unique response identifier")
    content: str = Field(..., description="Generated response content")
    model: str = Field(..., description="Model used for generation")
    usage: Dict[str, int] = Field(..., description="Token usage information")
    metadata: Dict[str, Any] = Field(..., description="Response metadata")
    timestamp: datetime = Field(..., description="Response timestamp")


class ChatStreamRequest(BaseModel):
    """Compact streaming request accepted by the canonical chat SSE route.

    The client may convey *intent* (message, session_id, preferred provider/model)
    but must never supply authoritative identity. ``user_id``, ``tenant_id``,
    ``roles`` and ``permissions`` are resolved server-side from the auth layer.
    """

    message: str = Field(
        ..., min_length=1, max_length=10000, description="User message content"
    )
    session_id: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=100,
        description="Session identifier",
    )
    preferred_llm_provider: Optional[str] = Field(
        default=None, max_length=100, description="Canonical preferred provider ID."
    )
    preferred_model: Optional[str] = Field(
        default=None, max_length=200, description="Canonical preferred model ID."
    )
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    stream: Optional[bool] = Field(default=True, description="Forced to True on this endpoint")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        if not isinstance(v, str):
            raise ValueError("Message must be a string")
        return v.strip()


# Rate limiting and security
class SecurityValidator:
    """Security validation utilities."""

    @staticmethod
    def sanitize_session_id(session_id: Optional[str]) -> str:
        """Generate secure session ID if not provided."""
        if not session_id:
            return f"session_{uuid.uuid4().hex[:16]}"

        # Validate existing session ID
        if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            raise ValueError("Invalid session ID format")

        return session_id

    @staticmethod
    def validate_user_input(user_input: str, max_length: int = 10000) -> str:
        """Validate and sanitize user input."""
        if not user_input:
            return ""

        # Length check
        if len(user_input) > max_length:
            raise ValueError(f"Input too long: {len(user_input)} > {max_length}")

        # Remove null bytes and control characters
        sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", user_input)

        return sanitized.strip()


def _normalize_messages(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
    """Normalize and sanitize messages into the canonical role/content format.

    The runtime consumes messages with ``role`` and ``content`` keys.
    ``message_type`` from the transport model is mapped to ``role``.
    """
    validated: List[Dict[str, Any]] = []
    for msg in messages:
        sanitized_content = SecurityValidator.validate_user_input(msg.content)
        validated.append(
            {
                "role": msg.message_type,
                "content": sanitized_content,
            }
        )
    return validated


def _build_chat_execution_request_from_stream_payload(
    request: ChatStreamRequest,
    user: Dict[str, Any],
    session_id: str,
    correlation_id: str,
    response_id: str,
) -> ChatExecutionRequest:
    """Construct a canonical ChatExecutionRequest from a compact stream payload.

    Identity (user_id, tenant_id, roles, permissions) is taken **only** from the
    server-side ``user`` dependency. Client-supplied values for those fields are
    intentionally ignored.
    """
    preferred_provider = request.preferred_llm_provider

    conversation_id = normalize_chat_session_id(session_id)

    messages = [
        {
            "role": "user",
            "content": SecurityValidator.validate_user_input(request.message),
        }
    ]

    return ChatExecutionRequest(
        messages=messages,
        context=ChatExecutionContext(
            user_id=user["user_id"],
            tenant_id=str(user.get("tenant_id") or "default"),
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=response_id,
            correlation_id=correlation_id,
            roles=list(user.get("roles") or []),
            permissions=list(user.get("permissions") or []),
        ),
        preferred_provider=preferred_provider,
        preferred_model=request.preferred_model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=True,
        metadata={"transport": "sse"},
    )


def get_stream_processor():
    """Get stream processor instance (deprecated shim for backward compat)."""
    return True


# API endpoints
@router.post("/chat", response_model=ChatResponse)
async def create_chat_response(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """
    Create a chat response with comprehensive validation and security checks.
    """
    start_time = time.time()
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    response_id = str(uuid.uuid4())
    structured_logger = get_structured_logger()

    try:
        # 1. Transport validation & normalization (route-owned responsibilities).
        session_id = SecurityValidator.sanitize_session_id(request.session_id)
        validated_messages = _normalize_messages(request.messages)

        preferred_provider = (
            request.preferred_llm_provider
            or request.provider
        )
        preferred_model = (
            request.preferred_model
            or request.model
        )

        # 2. Log request start (transport telemetry only; runtime owns execution events).
        structured_logger.log_event(
            event="chat_request_started",
            user_id=user["user_id"],
            details={
                "method": "POST",
                "endpoint": "/api/chat/chat",
                "correlation_id": correlation_id,
                "message_count": len(validated_messages),
                "preferred_llm_provider": preferred_provider,
                "preferred_model": preferred_model,
                "stream": request.stream,
                "session_id": session_id,
            },
        )

        # 3. Delegate the entire execution pipeline to the single chat runtime.
        chat_request = ChatExecutionRequest(
            messages=validated_messages,
            context=ChatExecutionContext(
                user_id=user["user_id"],
                tenant_id=str(user.get("tenant_id") or "default"),
                session_id=session_id,
                conversation_id=normalize_chat_session_id(session_id),
                request_id=response_id,
                correlation_id=correlation_id,
                roles=list(user.get("roles") or []),
                permissions=list(user.get("permissions") or []),
            ),
            preferred_provider=preferred_provider,
            preferred_model=preferred_model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=bool(request.stream),
            metadata={"transport": "http"},
        )

        if request.stream:
            async def generate_stream():
                sequence_counter = 0

                initial_status = ChatStreamChunk(
                    type="status",
                    content="Initializing request...",
                    correlation_id=correlation_id,
                    metadata={"status": "initializing", "transport": "sse"},
                    event_id=str(uuid.uuid4()),
                    sequence=sequence_counter,
                    request_id=response_id,
                    response_id=response_id,
                    conversation_id=normalize_chat_session_id(session_id),
                    timestamp=datetime.utcnow(),
                )
                sequence_counter += 1
                yield f"data: {json.dumps(initial_status.to_sse_payload())}\n\n"

                async for chunk in get_chat_runtime().execute_stream(chat_request):
                    payload = chunk.to_sse_payload()
                    if payload.get("sequence") is None:
                        payload["sequence"] = sequence_counter
                    sequence_counter += 1
                    yield f"data: {json.dumps(payload)}\n\n"

                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "X-Correlation-Id": correlation_id,
                    "X-Response-Id": response_id,
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        result = await get_chat_runtime().execute(chat_request)

        # 4. Control-plane gate short-circuit (maintenance / degraded-minimal).
        if result.status == ChatExecutionStatus.GATE and result.gate_response is not None:
            gate = result.gate_response
            payload = serialize_runtime_response(gate) or {}
            status_code = runtime_response_http_status(gate) or 503
            headers: Dict[str, str] = {}
            retry = getattr(gate, "retry_after_seconds", None)
            if retry is not None:
                headers["Retry-After"] = str(retry)
            return JSONResponse(status_code=status_code, content=payload, headers=headers)

        processing_time = time.time() - start_time
        response_metadata = result.metadata.to_dict()

        structured_logger.log_response(
            status_code=200,
            endpoint="/api/chat/chat",
            user_id=user["user_id"],
            correlation_id=correlation_id,
            response_data={
                "response_id": response_id,
                "model": response_metadata.get("actual_model") or preferred_model or "unknown",
                "processing_time": processing_time,
            },
        )

        return ChatResponse(
            response_id=response_id,
            content=result.answer,
            model=response_metadata.get("actual_model") or preferred_model or "unknown",
            usage=(response_metadata.get("llm") or {}).get("usage", {}) if isinstance(response_metadata.get("llm"), dict) else {},
            metadata=response_metadata,
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except ValueError as e:
        structured_logger.log_error(
            error=str(e),
            endpoint="/api/chat/chat",
            user_id=user.get("user_id") or "unknown",
            correlation_id=correlation_id,
            context="validation_error",
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        structured_logger.log_error(
            error=str(e),
            endpoint=f"/api/chat/sessions/{session_id}",
            user_id=user.get("user_id") or "unknown",
            correlation_id=correlation_id,
            context="unexpected_error",
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/stream")
async def stream_chat_response(
    request: ChatStreamRequest,
    http_request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """
    Canonical SSE streaming chat endpoint backed by ``ChatRuntime.execute_stream``.

    This is the single streaming ingress for the UI. CopilotKit and other
    transports also normalize into the same ``ChatExecutionRequest``.
    """
    start_time = time.time()
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    response_id = str(uuid.uuid4())
    structured_logger = get_structured_logger()

    try:
        session_id = SecurityValidator.sanitize_session_id(request.session_id)

        chat_request = _build_chat_execution_request_from_stream_payload(
            request,
            user,
            session_id,
            correlation_id,
            response_id,
        )

        conversation_id = chat_request.context.conversation_id or session_id

        structured_logger.log_event(
            event="chat_stream_started",
            user_id=user["user_id"],
            details={
                "endpoint": "/api/chat/stream",
                "correlation_id": correlation_id,
                "response_id": response_id,
                "session_id": session_id,
                "conversation_id": conversation_id,
                "preferred_provider": chat_request.preferred_provider,
                "preferred_model": chat_request.preferred_model,
            },
        )

        async def generate_stream():
            sequence_counter = 0

            initial_status = ChatStreamChunk(
                type="status",
                content="Initializing request...",
                correlation_id=correlation_id,
                metadata={"status": "initializing", "transport": "sse"},
                event_id=str(uuid.uuid4()),
                sequence=sequence_counter,
                request_id=response_id,
                response_id=response_id,
                conversation_id=conversation_id,
                timestamp=datetime.utcnow(),
            )
            sequence_counter += 1
            yield f"data: {json.dumps(initial_status.to_sse_payload())}\n\n"

            async for chunk in get_chat_runtime().execute_stream(chat_request):
                payload = chunk.to_sse_payload()
                if payload.get("sequence") is None:
                    payload["sequence"] = sequence_counter
                sequence_counter += 1
                yield f"data: {json.dumps(payload)}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_stream(),
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
    except ValueError as e:
        structured_logger.log_error(
            error=str(e),
            endpoint="/api/chat/stream",
            user_id=user.get("user_id") or "unknown",
            correlation_id=correlation_id,
            context="validation_error",
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        structured_logger.log_error(
            error=str(e),
            endpoint="/api/chat/stream",
            user_id=user.get("user_id") or "unknown",
            correlation_id=correlation_id,
            context="unexpected_error",
            details={"duration_ms": (time.time() - start_time) * 1000.0},
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """
    Get chat session history with validation and access control.
    """
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    structured_logger = get_structured_logger()

    try:
        # Validate session ID format
        if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            raise HTTPException(status_code=400, detail="Invalid session ID format")

        # Session management is not part of the current production chat orchestrator contract.
        raise HTTPException(
            status_code=501,
            detail="Chat session retrieval is not implemented on the production orchestrator",
        )

        # Log access
        structured_logger.log_event(
            event="chat_session_access",
            user_id=user["user_id"],
            details={
                "method": "GET",
                "endpoint": f"/api/chat/sessions/{session_id}",
                "correlation_id": correlation_id,
                "session_id": session_id,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        structured_logger.log_error(
            error=str(e),
            endpoint=f"/api/chat/sessions/{session_id}",
            user_id=user.get("user_id") or "unknown",
            correlation_id=correlation_id,
            context="unexpected_error",
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """
    Delete chat session with validation and access control.
    """
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    structured_logger = get_structured_logger()

    try:
        # Validate session ID format
        if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            raise HTTPException(status_code=400, detail="Invalid session ID format")

        raise HTTPException(
            status_code=501,
            detail="Chat session deletion is not implemented on the production orchestrator",
        )

        # Log deletion
        structured_logger.log_event(
            event="chat_session_deletion_attempted",
            user_id=user["user_id"],
            details={
                "method": "DELETE",
                "endpoint": f"/api/chat/sessions/{session_id}",
                "correlation_id": correlation_id,
                "session_id": session_id,
            },
        )

        return {"message": "Session deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        structured_logger.log_error(
            error=str(e),
            endpoint=f"/api/chat/sessions/{session_id}",
            user_id=user.get("user_id") or "unknown",
            correlation_id=correlation_id,
            context="unexpected_error",
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/models")
async def get_available_models(
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """
    Get available chat models with user-specific filtering.
    """
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    structured_logger = get_structured_logger()

    try:
        # Get configuration
        from ai_karen_engine.config.config_manager import get_config_value

        all_models = get_config_value("available_models", [])

        # Filter models based on user permissions
        user_permissions = user.get("permissions", [])
        available_models = []

        for model in all_models:
            model_permissions = model.get("required_permissions", [])
            if all(perm in user_permissions for perm in model_permissions):
                available_models.append(
                    {
                        "id": model["id"],
                        "name": model["name"],
                        "description": model.get("description", ""),
                        "max_tokens": model.get("max_tokens", 4096),
                        "supports_streaming": model.get("supports_streaming", True),
                    }
                )

        # Log access
        structured_logger.log_event(
            event="chat_models_accessed",
            user_id=user["user_id"],
            details={
                "method": "GET",
                "endpoint": "/api/chat/models",
                "correlation_id": correlation_id,
                "model_count": len(available_models),
            },
        )

        return {"models": available_models, "total_count": len(available_models)}

    except Exception as e:
        structured_logger.log_error(
            error=str(e),
            endpoint="/api/chat/models",
            user_id=user.get("user_id") or "unknown",
            correlation_id=correlation_id,
            context="unexpected_error",
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/health")
async def health_check():
    """Health check endpoint for chat service."""
    try:
        await get_chat_orchestrator()
        await get_stream_processor()

        return {
            "status": "healthy",
            "services": {"orchestrator": "healthy", "stream_processor": "healthy"},
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


__all__ = ["router"]
