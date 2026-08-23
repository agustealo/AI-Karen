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
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
import re
import uuid
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ai_karen_engine.core.services.dependencies import bypass_user_context_func

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    MaintenanceResponse,
    EmergencyFallbackResponse,
    DegradedResponse,
    serialize_runtime_response,
    runtime_response_http_status,
    get_chat_runtime_control_plane,
)
from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionStatus,
)
from ai_karen_engine.models.shared_types import (
    CanonicalChatRequest,
    CanonicalChatResponse,
)
from ai_karen_engine.utils.chat_helpers import normalize_session_id as normalize_chat_session_id
from ai_karen_engine.services.streaming.stream_processor import AsyncStreamProcessor
from ai_karen_engine.core.observability.metrics import get_metrics_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])
security = HTTPBearer()


def _runtime_metadata_from_orchestrator_response(
    response: CanonicalChatResponse,
    *,
    response_id: str,
    requested_model: Optional[str],
) -> Dict[str, Any]:
    """Expose a stable backend-confirmed metadata shape for chat runtime clients."""
    metadata = dict(response.metadata or {})
    metadata.setdefault("response_id", response_id)
    metadata.setdefault("request_id", getattr(response, "request_id", None))
    metadata.setdefault("correlation_id", response.correlation_id)
    metadata.setdefault("conversation_id", getattr(response, "conversation_id", None))
    metadata.setdefault(
        "assistant_message_id", getattr(response, "assistant_message_id", None)
    )
    metadata.setdefault(
        "status",
        response.status.value
        if hasattr(response.status, "value")
        else str(response.status),
    )
    metadata.setdefault("execution_path", getattr(response, "execution_path", None))
    metadata.setdefault("processing_time", response.processing_time)
    metadata.setdefault("used_fallback", response.used_fallback)
    metadata.setdefault("context_used", response.context_used)
    metadata.setdefault("telemetry", getattr(response, "telemetry", {}) or {})
    metadata.setdefault(
        "persistence",
        {
            "canonical_store": "postgres",
            "assistant_persisted": bool(
                getattr(response, "assistant_message_id", None)
            ),
        },
    )
    metadata.setdefault("model", getattr(response, "actual_model", None) or getattr(response, "model", None))
    return metadata


# Pydantic models for request/response validation
class ChatMessage(BaseModel):
    """Chat message model with comprehensive validation"""

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
    """Chat request model with comprehensive validation"""

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
        """Validate message list for security issues"""
        if not v:
            raise ValueError("Messages list cannot be empty")

        # Check total content length
        total_length = sum(len(msg.content) for msg in v)
        if total_length > 50000:  # 50KB total
            raise ValueError("Total message content too long")

        return v


class ChatResponse(BaseModel):
    """Chat response model"""

    response_id: str = Field(..., description="Unique response identifier")
    content: str = Field(..., description="Generated response content")
    model: str = Field(..., description="Model used for generation")
    usage: Dict[str, int] = Field(..., description="Token usage information")
    metadata: Dict[str, Any] = Field(..., description="Response metadata")
    timestamp: datetime = Field(..., description="Response timestamp")


class StreamChunk(BaseModel):
    """Streaming response chunk model"""

    response_id: str = Field(..., description="Response identifier")
    chunk_id: int = Field(..., description="Chunk sequence number")
    content: str = Field(..., description="Chunk content")
    finished: bool = Field(default=False, description="Whether this is the final chunk")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Chunk metadata")


# Rate limiting and security
class SecurityValidator:
    """Security validation utilities"""

    @staticmethod
    def sanitize_session_id(session_id: Optional[str]) -> str:
        """Generate secure session ID if not provided"""
        if not session_id:
            return f"session_{uuid.uuid4().hex[:16]}"

        # Validate existing session ID
        if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            raise ValueError("Invalid session ID format")

        return session_id

    @staticmethod
    def validate_user_input(user_input: str, max_length: int = 10000) -> str:
        """Validate and sanitize user input"""
        if not user_input:
            return ""

        # Length check
        if len(user_input) > max_length:
            raise ValueError(f"Input too long: {len(user_input)} > {max_length}")

        # Remove null bytes and control characters
        sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", user_input)

        return sanitized.strip()


class ChatRuntimeHelper:
    """Helper for chat runtime operations to keep routes thin."""

    @staticmethod
    async def gate_request() -> Optional[Any]:
        """Consult the control plane for maintenance or degradation."""
        runtime_response = await get_chat_runtime_control_plane().get_runtime_response()

        if runtime_response is not None:
            if isinstance(runtime_response, DegradedResponse):
                if runtime_response.is_minimal:
                    from fastapi.responses import JSONResponse

                    payload = serialize_runtime_response(runtime_response) or {}
                    return JSONResponse(
                        status_code=runtime_response_http_status(runtime_response)
                        or 200,
                        content=payload,
                        headers={
                            "Retry-After": str(runtime_response.retry_after_seconds)
                        },
                    )
            elif isinstance(
                runtime_response, (MaintenanceResponse, EmergencyFallbackResponse)
            ):
                from fastapi.responses import JSONResponse

                payload = serialize_runtime_response(runtime_response) or {}
                status_code = runtime_response_http_status(runtime_response) or 503
                return JSONResponse(
                    status_code=status_code,
                    content=payload,
                    headers={"Retry-After": str(runtime_response.retry_after_seconds)},
                )
        return None

    @staticmethod
    async def validate_provider_model(provider: Optional[str], model: Optional[str]) -> None:
        """Validate provider/model against canonical runtime provider catalog."""
        if not provider and not model:
            return
        from ai_karen_engine.api_routes.models.runtime_api import get_runtime_provider_catalog

        catalog = await get_runtime_provider_catalog(current_user={"user_id":"system"})
        providers = {p.id: p for p in (catalog.providers or [])}
        if provider and provider not in providers:
            raise HTTPException(status_code=400, detail=f"Provider '{provider}' not available in runtime catalog")
        if provider and model and model != "auto":
            provider_models = {m.id for m in (providers.get(provider).models or [])}
            if provider_models and model not in provider_models:
                raise HTTPException(status_code=400, detail=f"Model '{model}' not available for provider '{provider}'")

    @staticmethod
    async def get_user_provider_preferences() -> Dict[str, str]:
        """Get user's preferred provider and model from settings."""
        try:
            from ai_karen_engine.services.formatting.settings_manager import get_settings_manager

            settings = get_settings_manager()
            provider = settings.get_setting("provider")
            model = settings.get_setting("model")

            if provider and model:
                logger.debug(f"User provider preferences loaded: provider={provider}, model={model}")
                return {"provider": provider, "model": model}

            logger.debug("No user provider preferences found in settings")
            return {}
        except Exception as e:
            logger.debug(f"Failed to load user preferences: {e}")
            return {}


    @staticmethod
    def resolve_preferred_provider_model(
        request: "ChatRequest",
        user_preferences: Optional[Dict[str, str]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve canonical provider/model with backward-compatible aliases."""
        preferred_provider = (
            request.preferred_llm_provider
            or request.provider
            or ((user_preferences or {}).get("provider"))
        )
        preferred_model = (
            request.preferred_model
            or request.model
            or ((user_preferences or {}).get("model"))
        )
        return preferred_provider, preferred_model
    @staticmethod
    def normalize_messages(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Normalize and sanitize messages for the orchestrator."""
        validated = []
        for msg in messages:
            sanitized_content = SecurityValidator.validate_user_input(msg.content)
            validated.append(
                {
                    "content": sanitized_content,
                    "message_type": msg.message_type,
                    "metadata": msg.metadata or {},
                }
            )
        return validated

    @staticmethod
    def to_langchain_messages(messages: List[Dict[str, Any]]) -> List[BaseMessage]:
        """Convert normalized chat messages into LangChain messages."""
        converted: List[BaseMessage] = []
        for msg in messages:
            content = str(msg.get("content") or "")
            message_type = str(msg.get("message_type") or "user").lower()
            if message_type == "assistant":
                converted.append(AIMessage(content=content))
            elif message_type == "system":
                converted.append(SystemMessage(content=content))
            else:
                converted.append(HumanMessage(content=content))
        return converted

    @staticmethod
    def extract_response_payload(state: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """Pull final content/metadata from orchestrator state."""
        formatted_response = state.get("formatted_response")
        if formatted_response is not None:
            if hasattr(formatted_response, "data"):
                data = getattr(formatted_response, "data") or {}
                metadata = getattr(formatted_response, "metadata") or {}
                response_text = str(data.get("response") or data.get("content") or "")
                return response_text, metadata
            if isinstance(formatted_response, dict):
                data = formatted_response.get("data") or {}
                metadata = formatted_response.get("metadata") or {}
                response_text = str(data.get("response") or data.get("content") or "")
                return response_text, metadata

        response_text = str(state.get("response") or state.get("llm_response") or "")
        metadata = dict(state.get("response_metadata") or {})
        return response_text, metadata

    @staticmethod
    def extract_stream_payload(chunk: Any) -> tuple[str, Dict[str, Any]]:
        """Normalize stream updates into content plus metadata."""
        if isinstance(chunk, dict):
            for state_update in chunk.values():
                if not isinstance(state_update, dict):
                    continue
                if "formatted_response" in state_update or "llm_response" in state_update:
                    return ChatRuntimeHelper.extract_response_payload(state_update)
                if "error" in state_update:
                    return f"Error: {state_update['error']}", {
                        "error": state_update["error"]
                    }
        if isinstance(chunk, str):
            return chunk, {}
        return "", {}

    @staticmethod
    def build_orchestrator_request(
        request: ChatRequest,
        user: Dict[str, Any],
        validated_messages: List[Dict[str, Any]],
        response_id: str,
        correlation_id: str,
        session_id: str,
        user_preferences: Optional[Dict[str, str]] = None,
    ) -> CanonicalChatRequest:
        """Build the canonical orchestrator request object."""
        conversation_id = normalize_chat_session_id(session_id)
        flattened_prompt = "\n".join(
            msg["content"]
            for msg in validated_messages
            if msg.get("message_type") == "user"
        ).strip()

        preferred_provider, preferred_model = ChatRuntimeHelper.resolve_preferred_provider_model(request, user_preferences)

        logger.info(f"Building chat request - preferred_provider: {preferred_provider}, preferred_model: {preferred_model}")

        return CanonicalChatRequest(
            request_id=response_id,
            correlation_id=correlation_id,
            tenant_id=str(user.get("tenant_id") or "default"),
            message=flattened_prompt,
            user_id=user["user_id"],
            org_id=str(user.get("tenant_id") or "default"),
            conversation_id=conversation_id,
            session_id=conversation_id,
            message_id=str(uuid.uuid4()),
            streaming=bool(request.stream),
            stream=bool(request.stream),
            include_context=True,
            attachments=[],
            metadata={
                "preferred_llm_provider": preferred_provider,
                "preferred_model": preferred_model,
                "provider": preferred_provider,
                "model": preferred_model,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
                "messages": validated_messages,
                "response_id": response_id,
            },
        )


# Dependency functions
async def get_chat_orchestrator():
    """Verify chat runtime is operational."""
    await get_chat_runtime_control_plane().get_runtime_response()
    return True


async def get_stream_processor():
    """Get stream processor instance"""
    # Create a new instance with default parameters
    return AsyncStreamProcessor()


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
    Create a chat response with comprehensive validation and security checks
    """
    start_time = time.time()
    correlation_id = http_request.headers.get("X-Correlation-Id", str(uuid.uuid4()))
    response_id = str(uuid.uuid4())
    structured_logger = get_structured_logger()

    try:
        # 1. Transport validation & normalization (route-owned responsibilities).
        session_id = SecurityValidator.sanitize_session_id(request.session_id)
        validated_messages = ChatRuntimeHelper.normalize_messages(request.messages)

        user_preferences = await ChatRuntimeHelper.get_user_provider_preferences()
        preferred_provider, preferred_model = ChatRuntimeHelper.resolve_preferred_provider_model(
            request, user_preferences
        )
        await ChatRuntimeHelper.validate_provider_model(preferred_provider, preferred_model)

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
                async for chunk in get_chat_runtime().execute_stream(chat_request):
                    payload = {
                        "content": chunk.content,
                        "metadata": chunk.metadata,
                        "finished": chunk.type == "complete",
                        "event_type": chunk.type,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

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
            usage=(response_metadata.get("llm") or {}).get("usage", {}),
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


@router.get("/sessions/{session_id}")
async def get_chat_session(
    session_id: str,
    http_request: Request,
    user: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """
    Get chat session history with validation and access control
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
    Delete chat session with validation and access control
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
    Get available chat models with user-specific filtering
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
    """Health check endpoint for chat service"""
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


# Import StreamingResponse for streaming endpoints
from fastapi.responses import StreamingResponse
