"""
FastAPI routes for conversation management.

The route layer is intentionally thin: it validates authenticated scope,
delegates durable conversation state to ConversationRuntimeGateway, translates
service failures to API errors, and never fabricates conversation state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationRuntimeGateway,
    ConversationSnapshot,
    get_conversation_runtime_gateway,
)
from ai_karen_engine.core.services.dependencies import (
    bypass_user_context_func,
    get_current_tenant_id,
)
from ai_karen_engine.database.conversation_manager import MessageRole
from ai_karen_engine.services.error_response_schemas import (
    WebAPIErrorCode,
    create_generic_error_response,
    create_service_error_response,
    get_http_status_for_error_code,
)
from ai_karen_engine.services.memory.conversation_service import (
    ConversationPriority,
    UISource,
)
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Depends, HTTPException, Query = import_fastapi(
    "APIRouter", "Depends", "HTTPException", "Query"
)
BaseModel, Field = import_pydantic("BaseModel", "Field")

logger = get_logger(__name__)
router = APIRouter(tags=["conversations"])


def _require_user_id(user_ctx: Dict[str, Any]) -> str:
    """Extract an authenticated user id and fail closed when it is absent."""
    user_id = user_ctx.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise HTTPException(status_code=401, detail="Missing authenticated user id")
    return user_id.strip()


def _raise_not_found(*, message: str, user_message: str, details: Dict[str, Any]) -> None:
    error_response = create_generic_error_response(
        error_code=WebAPIErrorCode.NOT_FOUND,
        message=message,
        user_message=user_message,
        details=details,
    )
    raise HTTPException(
        status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
        detail=error_response.model_dump(mode="json"),
    )


def _raise_service_error(*, error: Exception, user_message: str) -> None:
    error_response = create_service_error_response(
        service_name="conversation",
        error=error,
        error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
        user_message=user_message,
    )
    raise HTTPException(
        status_code=get_http_status_for_error_code(WebAPIErrorCode.INTERNAL_SERVER_ERROR),
        detail=error_response.model_dump(mode="json"),
    )


class CreateConversationRequest(BaseModel):
    """Request model for creating a conversation."""

    session_id: str = Field(..., description="Session ID")
    ui_source: UISource = Field(..., description="Source UI (web, desktop, api, ag_ui)")
    title: Optional[str] = Field(None, description="Conversation title")
    initial_message: Optional[str] = Field(None, description="Initial user message")
    user_settings: Optional[Dict[str, Any]] = Field(None, description="User settings")
    ui_context: Optional[Dict[str, Any]] = Field(None, description="UI context data")
    tags: Optional[List[str]] = Field(None, description="Initial tags")
    priority: ConversationPriority = Field(
        ConversationPriority.NORMAL, description="Conversation priority"
    )


class AddMessageRequest(BaseModel):
    """Request model for adding a message."""

    role: MessageRole = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    ui_source: UISource = Field(..., description="Source UI (web, desktop, api, ag_ui)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Message metadata")
    ai_confidence: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="AI confidence score"
    )
    processing_time_ms: Optional[int] = Field(
        None, description="Processing time in milliseconds"
    )
    tokens_used: Optional[int] = Field(None, description="Tokens used")
    model_used: Optional[str] = Field(None, description="Model used for generation")


class UpdateConversationRequest(BaseModel):
    """Request model for mutating conversation metadata owned by this user."""

    title: Optional[str] = Field(None, description="New title")
    is_active: Optional[bool] = Field(None, description="Active status")


class UpdateUIContextRequest(BaseModel):
    ui_context: Dict[str, Any] = Field(..., description="UI context data")


class AddTagsRequest(BaseModel):
    tags: List[str] = Field(..., description="Tags to add")


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    metadata: Dict[str, Any]
    function_call: Optional[Dict[str, Any]]
    function_response: Optional[Dict[str, Any]]
    ui_source: Optional[str]
    ai_confidence: Optional[float]
    processing_time_ms: Optional[int]
    tokens_used: Optional[int]
    model_used: Optional[str]
    user_feedback: Optional[str]
    edited: bool
    edit_history: List[Dict[str, Any]]


class ConversationResponse(BaseModel):
    id: str
    user_id: str
    title: Optional[str]
    messages: List[MessageResponse]
    metadata: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str
    message_count: int
    last_message_at: Optional[str]
    session_id: Optional[str]
    ui_context: Dict[str, Any]
    ai_insights: Dict[str, Any]
    user_settings: Dict[str, Any]
    summary: Optional[str]
    tags: List[str]
    last_ai_response_id: Optional[str]
    status: str
    priority: str
    context_memories: List[Dict[str, Any]]
    proactive_suggestions: List[str]


class CreateConversationResponse(BaseModel):
    conversation: ConversationResponse
    success: bool
    message: str


class AddMessageResponse(BaseModel):
    message: MessageResponse
    success: bool


class ConversationListResponse(BaseModel):
    conversations: List[ConversationResponse]
    total_count: int
    has_more: bool





def _canonical_message_to_response(message: Any) -> MessageResponse:
    metadata = dict(getattr(message, "metadata", {}) or {})
    return MessageResponse(
        id=str(message.id),
        role=str(message.role),
        content=str(message.content),
        timestamp=message.created_at.isoformat(),
        metadata=metadata,
        function_call=metadata.get("function_call"),
        function_response=metadata.get("function_response"),
        ui_source=metadata.get("ui_source"),
        ai_confidence=metadata.get("ai_confidence"),
        processing_time_ms=metadata.get("processing_time_ms"),
        tokens_used=metadata.get("tokens_used"),
        model_used=metadata.get("model_used"),
        user_feedback=metadata.get("user_feedback"),
        edited=bool(metadata.get("edited", False)),
        edit_history=list(metadata.get("edit_history", [])),
    )


def _canonical_snapshot_to_response(
    snapshot: ConversationSnapshot,
) -> ConversationResponse:
    conversation = snapshot.conversation
    metadata = dict(conversation.metadata or {})
    messages = [_canonical_message_to_response(message) for message in snapshot.messages]
    last_message_at = (
        snapshot.messages[-1].created_at.isoformat() if snapshot.messages else None
    )
    return ConversationResponse(
        id=str(conversation.id),
        user_id=str(conversation.user_id),
        title=conversation.title,
        messages=messages,
        metadata=metadata,
        is_active=bool(conversation.is_active),
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        message_count=len(messages),
        last_message_at=last_message_at,
        session_id=metadata.get("session_id"),
        ui_context=dict(metadata.get("ui_context", {}) or {}),
        ai_insights=dict(metadata.get("ai_insights", {}) or {}),
        user_settings=dict(metadata.get("user_settings", {}) or {}),
        summary=conversation.summary,
        tags=list(conversation.tags or []),
        last_ai_response_id=metadata.get("last_ai_response_id"),
        status="active" if conversation.is_active else "inactive",
        priority=str(metadata.get("priority", "normal")),
        context_memories=[],
        proactive_suggestions=[],
    )


def _conversation_api_context(
    *,
    tenant_id: str,
    user_id: str,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> ChatExecutionContext:
    request_id = str(uuid.uuid4())
    return ChatExecutionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        correlation_id=request_id,
    )



# Static GET routes must be registered before /{conversation_id}.
@router.get("/health")
async def health_check() -> Dict[str, str]:
    return {
        "status": "healthy",
        "service": "conversation",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/by-session/{session_id}", response_model=ConversationResponse)
async def get_conversation_by_session(
    session_id: str,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Retrieve canonical durable conversation state by runtime session identifier."""
    try:
        user_id = _require_user_id(user_ctx)
        snapshot = await conversation_gateway.get_owned_snapshot_by_session(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
        )
        return _canonical_snapshot_to_response(snapshot)
    except HTTPException:
        raise
    except (PermissionError, RuntimeError) as error:
        if str(error) in {"conversation_user_mismatch", "conversation_not_found"}:
            _raise_not_found(
                message="Conversation not found",
                user_message="No conversation exists for the requested session.",
                details={"session_id": session_id},
            )
        _raise_service_error(
            error=error,
            user_message="Failed to get conversation. Please try again.",
        )
    except Exception as error:
        logger.exception("Failed to get conversation by session", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to get conversation. Please try again.",
        )

@router.get("/ensure-session/{session_id}", response_model=ConversationResponse)
async def ensure_session_conversation_get(
    session_id: str,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Compatibility alias for clients still using GET during session ensure."""
    return await ensure_session_conversation(
        session_id=session_id,
        conversation_gateway=conversation_gateway,
        tenant_id=tenant_id,
        user_ctx=user_ctx,
    )


@router.get("")
async def list_conversations(
    active_only: bool = Query(True, description="Only return active conversations"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of conversations"),
    offset: int = Query(0, ge=0, description="Number of conversations to skip"),
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        context = _conversation_api_context(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        snapshots = await conversation_gateway.list_owned_snapshots(
            context,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )
        total_count = await conversation_gateway.count_owned_conversations(
            context,
            active_only=active_only,
        )
        return ConversationListResponse(
            conversations=[
                _canonical_snapshot_to_response(snapshot) for snapshot in snapshots
            ],
            total_count=total_count,
            has_more=offset + len(snapshots) < total_count,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to list conversations", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to list conversations. Please try again.",
        )

@router.post("/create", response_model=CreateConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Compatibility create surface backed only by canonical conversation storage."""
    try:
        user_id = _require_user_id(user_ctx)
        context = _conversation_api_context(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=request.session_id,
        )
        snapshot = await conversation_gateway.ensure_session_snapshot(
            context,
            title=request.title or "New Conversation",
        )
        context = _conversation_api_context(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=request.session_id,
            conversation_id=str(snapshot.conversation.id),
        )
        await conversation_gateway.update_conversation_metadata(
            context,
            metadata_updates={
                "ui_source": request.ui_source.value,
                "session_id": request.session_id,
                "user_settings": request.user_settings or {},
                "ui_context": request.ui_context or {},
                "priority": request.priority.value,
            },
            tags_to_add=request.tags or [],
        )
        if request.initial_message:
            await conversation_gateway.append_message(
                context,
                role=MessageRole.USER.value,
                content=request.initial_message,
                metadata={"ui_source": request.ui_source.value},
            )
        snapshot = await conversation_gateway.get_owned_snapshot(context)
        return CreateConversationResponse(
            conversation=_canonical_snapshot_to_response(snapshot),
            success=True,
            message="Conversation created successfully",
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to create conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to create conversation. Please try again.",
        )

@router.post("/ensure-session/{session_id}", response_model=ConversationResponse)
async def ensure_session_conversation(
    session_id: str,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Return the canonical durable session conversation, creating it when absent."""
    try:
        user_id = _require_user_id(user_ctx)
        snapshot = await conversation_gateway.ensure_session_snapshot(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            ),
            title="New Conversation",
        )
        return _canonical_snapshot_to_response(snapshot)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to ensure session conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to ensure conversation exists. Please try again.",
        )


@router.post("/update-session-activity/{session_id}")
async def update_session_activity(
    session_id: str,
    activity_data: Optional[Dict[str, Any]] = None,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Touch activity only on the authenticated user's canonical session conversation."""
    try:
        user_id = _require_user_id(user_ctx)
        await conversation_gateway.touch_session_conversation(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
        )
        return {"success": True}
    except HTTPException:
        raise
    except (PermissionError, RuntimeError) as error:
        if str(error) in {"conversation_user_mismatch", "conversation_not_found"}:
            _raise_not_found(
                message="Conversation not found",
                user_message="No conversation exists for the requested session.",
                details={"session_id": session_id},
            )
        _raise_service_error(
            error=error,
            user_message="Failed to update session activity. Please try again.",
        )
    except Exception as error:
        logger.exception("Failed to update session activity", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update session activity. Please try again.",
        )

@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    include_context: bool = Query(True, description="Compatibility flag; transcript is canonical"),
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        snapshot = await conversation_gateway.get_owned_snapshot(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        )
        return _canonical_snapshot_to_response(snapshot)
    except HTTPException:
        raise
    except (PermissionError, RuntimeError) as error:
        if str(error) in {"conversation_user_mismatch", "conversation_not_found"}:
            _raise_not_found(
                message="Conversation not found",
                user_message="The requested conversation could not be found.",
                details={"conversation_id": conversation_id},
            )
        _raise_service_error(
            error=error,
            user_message="Failed to get conversation. Please try again.",
        )
    except Exception as error:
        logger.exception("Failed to get conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to get conversation. Please try again.",
        )

@router.post("/{conversation_id}/messages", response_model=AddMessageResponse)
async def add_message(
    conversation_id: str,
    request: AddMessageRequest,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Append a durable transcript message without invoking semantic memory."""
    try:
        user_id = _require_user_id(user_ctx)
        metadata = {
            **dict(request.metadata or {}),
            "ui_source": str(request.ui_source.value),
            "ai_confidence": request.ai_confidence,
            "processing_time_ms": request.processing_time_ms,
            "tokens_used": request.tokens_used,
            "model_used": request.model_used,
        }
        message = await conversation_gateway.append_message(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            ),
            role=str(request.role.value),
            content=request.content,
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
        return AddMessageResponse(
            message=_canonical_message_to_response(message),
            success=True,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to add message", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to add message to conversation. Please try again.",
        )


@router.put("/{conversation_id}/ui-context")
async def update_ui_context(
    conversation_id: str,
    request: UpdateUIContextRequest,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        await conversation_gateway.update_conversation_metadata(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            ),
            metadata_updates={"ui_context": request.ui_context},
        )
        return {"success": True, "message": "UI context updated successfully"}
    except HTTPException:
        raise
    except (PermissionError, RuntimeError) as error:
        if str(error) in {"conversation_user_mismatch", "conversation_not_found"}:
            _raise_not_found(
                message="Conversation not found or update denied",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
        _raise_service_error(
            error=error,
            user_message="Failed to update UI context. Please try again.",
        )
    except Exception as error:
        logger.exception("Failed to update UI context", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update UI context. Please try again.",
        )

@router.post("/{conversation_id}/tags")
async def add_tags(
    conversation_id: str,
    request: AddTagsRequest,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        await conversation_gateway.update_conversation_metadata(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            ),
            tags_to_add=request.tags,
        )
        return {
            "success": True,
            "message": f"Added {len(request.tags)} tags to conversation",
        }
    except HTTPException:
        raise
    except (PermissionError, RuntimeError) as error:
        if str(error) in {"conversation_user_mismatch", "conversation_not_found"}:
            _raise_not_found(
                message="Conversation not found or update denied",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
        _raise_service_error(
            error=error,
            user_message="Failed to add tags to conversation. Please try again.",
        )
    except Exception as error:
        logger.exception("Failed to add conversation tags", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to add tags to conversation. Please try again.",
        )

@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    request: UpdateConversationRequest,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        await conversation_gateway.update_conversation(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            ),
            title=request.title,
            is_active=request.is_active,
        )
        return {"success": True, "message": "Conversation updated successfully"}
    except HTTPException:
        raise
    except (PermissionError, RuntimeError) as error:
        if str(error) in {"conversation_user_mismatch", "conversation_not_found"}:
            _raise_not_found(
                message="Conversation not found or update denied",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
        logger.exception("Failed to update conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update conversation. Please try again.",
        )
    except Exception as error:
        logger.exception("Failed to update conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update conversation. Please try again.",
        )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    conversation_gateway: ConversationRuntimeGateway = Depends(
        get_conversation_runtime_gateway
    ),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        await conversation_gateway.delete_conversation(
            _conversation_api_context(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        )
        return {"success": True, "message": "Conversation deleted successfully"}
    except HTTPException:
        raise
    except (PermissionError, RuntimeError) as error:
        if str(error) in {"conversation_user_mismatch", "conversation_not_found"}:
            _raise_not_found(
                message="Conversation not found or deletion denied",
                user_message="The requested conversation could not be found or deleted.",
                details={"conversation_id": conversation_id},
            )
        logger.exception("Failed to delete conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to delete conversation. Please try again.",
        )
    except Exception as error:
        logger.exception("Failed to delete conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to delete conversation. Please try again.",
        )
