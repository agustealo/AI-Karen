"""
FastAPI routes for conversation management.

The route layer is intentionally thin: it validates authenticated scope,
delegates durable state operations to ConversationService, translates service
failures to API errors, and never fabricates conversation state.
"""

from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.services.dependencies import (
    bypass_user_context_func,
    get_conversation_service,
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
    ConversationService,
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


def _get_total_conversations_from_stats(stats: Any, fallback: int) -> int:
    """Read total conversation count from dict or model-like stats."""
    if isinstance(stats, dict):
        value = stats.get("total_conversations", fallback)
    else:
        value = getattr(stats, "total_conversations", fallback)

    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


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


class BuildContextRequest(BaseModel):
    """Request model for building conversation context."""

    current_message: str = Field(..., description="Current message for context")
    include_memories: bool = Field(True, description="Include memory context")
    include_insights: bool = Field(True, description="Include AI insights")


class UpdateUIContextRequest(BaseModel):
    ui_context: Dict[str, Any] = Field(..., description="UI context data")


class UpdateAIInsightsRequest(BaseModel):
    ai_insights: Dict[str, Any] = Field(..., description="AI insights data")


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


class ContextResponse(BaseModel):
    conversation_summary: Dict[str, Any]
    recent_messages: List[Dict[str, Any]]
    relevant_memories: Dict[str, List[Dict[str, Any]]]
    ai_insights: Dict[str, Any]
    user_preferences: Dict[str, Any]
    ai_insights_context: Dict[str, Any]
    conversation_patterns: Dict[str, Any]
    context_metadata: Dict[str, Any]


class ConversationListResponse(BaseModel):
    conversations: List[ConversationResponse]
    total_count: int
    has_more: bool


class AnalyticsResponse(BaseModel):
    total_conversations: int
    active_conversations: int
    recent_conversations_7d: int
    total_messages: int
    avg_messages_per_conversation: float
    conversations_by_ui_source: Dict[str, int]
    conversations_by_priority: Dict[str, int]
    conversations_with_tags: int
    average_tags_per_conversation: float
    conversations_with_summaries: int
    most_common_tags: Dict[str, int]
    web_ui_metrics: Dict[str, Any]
    metrics: Dict[str, Any]


get_current_tenant = get_current_tenant_id


def _convert_conversation_to_response(conversation: Any) -> ConversationResponse:
    conversation_dict = conversation.to_dict()
    messages = [
        MessageResponse(
            id=str(msg_data["id"]),
            role=str(msg_data["role"]),
            content=str(msg_data["content"]),
            timestamp=str(msg_data["timestamp"]),
            metadata=msg_data.get("metadata", {}),
            function_call=msg_data.get("function_call"),
            function_response=msg_data.get("function_response"),
            ui_source=msg_data.get("ui_source"),
            ai_confidence=msg_data.get("ai_confidence"),
            processing_time_ms=msg_data.get("processing_time_ms"),
            tokens_used=msg_data.get("tokens_used"),
            model_used=msg_data.get("model_used"),
            user_feedback=msg_data.get("user_feedback"),
            edited=bool(msg_data.get("edited", False)),
            edit_history=msg_data.get("edit_history", []),
        )
        for msg_data in conversation_dict["messages"]
    ]

    return ConversationResponse(
        id=str(conversation_dict["id"]),
        user_id=str(conversation_dict["user_id"]),
        title=conversation_dict.get("title"),
        messages=messages,
        metadata=conversation_dict.get("metadata", {}),
        is_active=bool(conversation_dict.get("is_active", True)),
        created_at=str(conversation_dict["created_at"]),
        updated_at=str(conversation_dict["updated_at"]),
        message_count=int(conversation_dict.get("message_count", 0)),
        last_message_at=conversation_dict.get("last_message_at"),
        session_id=conversation_dict.get("session_id"),
        ui_context=conversation_dict.get("ui_context", {}),
        ai_insights=conversation_dict.get("ai_insights", {}),
        user_settings=conversation_dict.get("user_settings", {}),
        summary=conversation_dict.get("summary"),
        tags=conversation_dict.get("tags", []),
        last_ai_response_id=conversation_dict.get("last_ai_response_id"),
        status=str(conversation_dict.get("status", "active")),
        priority=str(conversation_dict.get("priority", "normal")),
        context_memories=conversation_dict.get("context_memories", []),
        proactive_suggestions=conversation_dict.get("proactive_suggestions", []),
    )


# Static GET routes must be registered before /{conversation_id}.
@router.get("/health")
async def health_check() -> Dict[str, str]:
    return {
        "status": "healthy",
        "service": "conversation",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    time_range_start: Optional[datetime] = Query(None, description="Start of time range"),
    time_range_end: Optional[datetime] = Query(None, description="End of time range"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        authenticated_user_id = _require_user_id(user_ctx)
        time_range = (
            (time_range_start, time_range_end)
            if time_range_start and time_range_end
            else None
        )
        target_user_id = user_id or authenticated_user_id
        analytics = await conversation_service.get_conversation_analytics(
            tenant_id=tenant_id,
            user_id=target_user_id,
            time_range=time_range,
        )
        return AnalyticsResponse(**analytics)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to get conversation analytics", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to get conversation analytics. Please try again.",
        )


@router.get("/stats")
async def get_conversation_stats(
    tenant_id: str = Depends(get_current_tenant),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
    conversation_service: ConversationService = Depends(get_conversation_service),
):
    try:
        user_id = _require_user_id(user_ctx)
        stats = await conversation_service.base_manager.get_conversation_stats(
            tenant_id,
            user_id,
        )
        return {
            "base_stats": stats,
            "web_ui_metrics": conversation_service.get_metrics(),
            "tenant_id": tenant_id,
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to get conversation stats", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to get conversation statistics. Please try again.",
        )


@router.get("/by-session/{session_id}", response_model=ConversationResponse)
async def get_conversation_by_session(
    session_id: str,
    include_context: bool = Query(True, description="Include context data"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Retrieve durable conversation state by session identifier."""
    try:
        user_id = _require_user_id(user_ctx)
        conversation = await conversation_service.get_web_ui_conversation_by_session(
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            include_context=include_context,
        )
        if not conversation:
            _raise_not_found(
                message="Conversation not found",
                user_message="No conversation exists for the requested session.",
                details={"session_id": session_id},
            )
        return _convert_conversation_to_response(conversation)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to get conversation by session", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to get conversation. Please try again.",
        )


@router.get("/ensure-session/{session_id}", response_model=ConversationResponse)
async def ensure_session_conversation_get(
    session_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Compatibility alias for clients still using GET during session ensure."""
    return await ensure_session_conversation(
        session_id=session_id,
        conversation_service=conversation_service,
        tenant_id=tenant_id,
        user_ctx=user_ctx,
    )


@router.get("")
async def list_conversations(
    active_only: bool = Query(True, description="Only return active conversations"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of conversations"),
    offset: int = Query(0, ge=0, description="Number of conversations to skip"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        base_manager = conversation_service.base_manager
        params = inspect.signature(base_manager.list_conversations).parameters

        if "active_only" in params:
            conversations = await base_manager.list_conversations(
                tenant_id=tenant_id,
                user_id=user_id,
                active_only=active_only,
                limit=limit,
                offset=offset,
            )
        else:
            from ai_karen_engine.chat.conversation_models import (
                ConversationFilters as _ConversationFilters,
                ConversationStatus as _ConversationStatus,
            )

            filters: Optional[Any] = None
            if active_only:
                filters = _ConversationFilters(status=_ConversationStatus.ACTIVE)
            enhanced_list_conversations = cast(Any, base_manager.list_conversations)
            conversations = await enhanced_list_conversations(
                tenant_id=tenant_id,
                user_id=user_id,
                filters=filters,
                limit=limit,
                offset=offset,
            )

        web_ui_conversations: List[ConversationResponse] = []
        for conversation in conversations:
            web_ui_data = await conversation_service._get_web_ui_conversation_data(
                tenant_id, conversation.id
            )
            web_ui_conversation = await conversation_service._convert_to_web_ui_conversation(
                conversation,
                web_ui_data.get("session_id"),
                web_ui_data.get("ui_context", {}),
                web_ui_data.get("user_settings", {}),
                web_ui_data.get("tags", []),
                ConversationPriority.from_any(web_ui_data.get("priority", "normal")),
                web_ui_data.get("summary"),
                web_ui_data.get("last_ai_response_id"),
            )
            web_ui_conversations.append(
                _convert_conversation_to_response(web_ui_conversation)
            )

        stats = await conversation_service.base_manager.get_conversation_stats(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        total_count = _get_total_conversations_from_stats(
            stats,
            len(web_ui_conversations),
        )
        return ConversationListResponse(
            conversations=web_ui_conversations,
            total_count=total_count,
            has_more=len(web_ui_conversations) == limit,
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
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        conversation = await conversation_service.create_web_ui_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=request.session_id,
            ui_source=request.ui_source,
            title=request.title,
            initial_message=request.initial_message,
            user_settings=request.user_settings,
            ui_context=request.ui_context,
            tags=request.tags,
            priority=request.priority,
        )
        if not conversation:
            raise RuntimeError("Conversation service returned no conversation")
        return CreateConversationResponse(
            conversation=_convert_conversation_to_response(conversation),
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
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Return the durable session conversation, creating it when absent."""
    try:
        user_id = _require_user_id(user_ctx)
        existing_conversation = (
            await conversation_service.get_web_ui_conversation_by_session(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                include_context=False,
            )
        )
        if existing_conversation:
            return _convert_conversation_to_response(existing_conversation)

        new_conversation = await conversation_service.create_web_ui_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            ui_source=UISource.WEB,
            title="New Conversation",
            initial_message=None,
            user_settings={},
            ui_context={},
            tags=["new-session"],
            priority=ConversationPriority.NORMAL,
        )
        if not new_conversation:
            raise RuntimeError("Conversation service returned no conversation")
        return _convert_conversation_to_response(new_conversation)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to ensure session conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to ensure conversation exists. Please try again.",
        )


@router.post("/cleanup-inactive")
async def cleanup_inactive_conversations(
    days_inactive: int = Query(30, ge=1, description="Days of inactivity threshold"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        count = await conversation_service.base_manager.cleanup_inactive_conversations(
            tenant_id=tenant_id,
            days_inactive=days_inactive,
        )
        return {
            "success": True,
            "inactive_count": count,
            "message": f"Marked {count} conversations as inactive",
        }
    except Exception as error:
        logger.exception("Failed to cleanup conversations", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to cleanup conversations. Please try again.",
        )


@router.post("/update-session-activity/{session_id}")
async def update_session_activity(
    session_id: str,
    activity_data: Optional[Dict[str, Any]] = None,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Update activity only after proving the session belongs to this tenant/user."""
    try:
        user_id = _require_user_id(user_ctx)
        conversation = await conversation_service.get_web_ui_conversation_by_session(
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            include_context=False,
        )
        if not conversation:
            _raise_not_found(
                message="Conversation not found",
                user_message="No conversation exists for the requested session.",
                details={"session_id": session_id},
            )

        success = await conversation_service.update_session_activity(
            session_id=session_id,
            activity_data=activity_data,
        )
        if not success:
            raise RuntimeError("Conversation service failed to update session activity")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to update session activity", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update session activity. Please try again.",
        )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    include_context: bool = Query(True, description="Include context data"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    try:
        user_id = _require_user_id(user_ctx)
        conversation = await conversation_service.get_web_ui_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            include_context=include_context,
            user_id=user_id,
        )
        if not conversation:
            _raise_not_found(
                message="Conversation not found",
                user_message="The requested conversation could not be found.",
                details={"conversation_id": conversation_id},
            )
        return _convert_conversation_to_response(conversation)
    except HTTPException:
        raise
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
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        message = await conversation_service.add_web_ui_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=request.role,
            content=request.content,
            ui_source=request.ui_source,
            metadata=request.metadata,
            ai_confidence=request.ai_confidence,
            processing_time_ms=request.processing_time_ms,
            tokens_used=request.tokens_used,
            model_used=request.model_used,
        )
        if not message:
            raise RuntimeError("Conversation service returned no message")

        message_dict = message.to_dict()
        return AddMessageResponse(
            message=MessageResponse(
                id=str(message_dict["id"]),
                role=str(message_dict["role"]),
                content=str(message_dict["content"]),
                timestamp=str(message_dict["timestamp"]),
                metadata=message_dict.get("metadata", {}),
                function_call=message_dict.get("function_call"),
                function_response=message_dict.get("function_response"),
                ui_source=message_dict.get("ui_source"),
                ai_confidence=message_dict.get("ai_confidence"),
                processing_time_ms=message_dict.get("processing_time_ms"),
                tokens_used=message_dict.get("tokens_used"),
                model_used=message_dict.get("model_used"),
                user_feedback=message_dict.get("user_feedback"),
                edited=bool(message_dict.get("edited", False)),
                edit_history=message_dict.get("edit_history", []),
            ),
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


@router.post("/{conversation_id}/context", response_model=ContextResponse)
async def build_context(
    conversation_id: str,
    request: BuildContextRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        context = await conversation_service.build_conversation_context(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            current_message=request.current_message,
            include_memories=request.include_memories,
            include_insights=request.include_insights,
        )
        return ContextResponse(**context)
    except Exception as error:
        logger.exception("Failed to build context", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to build conversation context. Please try again.",
        )


@router.put("/{conversation_id}/ui-context")
async def update_ui_context(
    conversation_id: str,
    request: UpdateUIContextRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        success = await conversation_service.update_conversation_ui_context(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            ui_context=request.ui_context,
        )
        if not success:
            _raise_not_found(
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
        return {"success": True, "message": "UI context updated successfully"}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to update UI context", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update UI context. Please try again.",
        )


@router.put("/{conversation_id}/ai-insights")
async def update_ai_insights(
    conversation_id: str,
    request: UpdateAIInsightsRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        success = await conversation_service.update_conversation_ai_insights(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            ai_insights=request.ai_insights,
        )
        if not success:
            _raise_not_found(
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
        return {"success": True, "message": "AI insights updated successfully"}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to update AI insights", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update AI insights. Please try again.",
        )


@router.post("/{conversation_id}/tags")
async def add_tags(
    conversation_id: str,
    request: AddTagsRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        success = await conversation_service.add_conversation_tags(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            tags=request.tags,
        )
        if not success:
            _raise_not_found(
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
        return {
            "success": True,
            "message": f"Added {len(request.tags)} tags to conversation",
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to add conversation tags", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to add tags to conversation. Please try again.",
        )


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    title: Optional[str] = Query(None, description="New title"),
    is_active: Optional[bool] = Query(None, description="Active status"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        success = await conversation_service.base_manager.update_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            title=title,
            is_active=is_active,
        )
        if not success:
            _raise_not_found(
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
        return {"success": True, "message": "Conversation updated successfully"}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to update conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to update conversation. Please try again.",
        )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    try:
        success = await conversation_service.delete_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        if not success:
            _raise_not_found(
                message="Conversation not found or deletion failed",
                user_message="The requested conversation could not be found or deleted.",
                details={"conversation_id": conversation_id},
            )
        return {"success": True, "message": "Conversation deleted successfully"}
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to delete conversation", error=str(error))
        _raise_service_error(
            error=error,
            user_message="Failed to delete conversation. Please try again.",
        )
