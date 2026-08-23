"""
FastAPI routes for enhanced conversation management with web UI integration.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, cast
import inspect

from ai_karen_engine.core.services.dependencies import (
    get_conversation_service,
    get_current_tenant_id,
    bypass_user_context_func,
)
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.database.conversation_manager import MessageRole, normalize_user_id
from ai_karen_engine.services.error_response_schemas import (
    WebAPIErrorCode,
    create_generic_error_response,
    create_service_error_response,
    get_http_status_for_error_code,
)
from ai_karen_engine.services.memory.conversation_service import (
    ConversationPriority,
    UISource,
    ConversationService,
)
from ai_karen_engine.utils.dependency_checks import import_fastapi, import_pydantic

APIRouter, Depends, HTTPException, Query = import_fastapi(
    "APIRouter", "Depends", "HTTPException", "Query"
)
BaseModel, Field = import_pydantic("BaseModel", "Field")

# from ai_karen_engine.database.client import get_db_client  # Not needed with dependency injection
# Temporarily disable auth imports for web UI integration

logger = get_logger(__name__)

# Create router without prefix for automatic discovery alignment
router = APIRouter(tags=["conversations"])


def _require_user_id(user_ctx: Dict[str, Any]) -> str:
    """Extract the authenticated user id as a non-empty string."""
    user_id = user_ctx.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Missing authenticated user id")
    return user_id


def _get_total_conversations_from_stats(
    stats: Any,
    fallback: int,
) -> int:
    """Read total conversation count from either dict or model-like stats."""
    if isinstance(stats, dict):
        value = stats.get("total_conversations", fallback)
    else:
        value = getattr(stats, "total_conversations", fallback)

    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# Request/Response Models
class CreateConversationRequest(BaseModel):
    """Request model for creating conversation."""

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
    """Request model for adding message."""

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
    """Request model for updating UI context."""

    ui_context: Dict[str, Any] = Field(..., description="UI context data")


class UpdateAIInsightsRequest(BaseModel):
    """Request model for updating AI insights."""

    ai_insights: Dict[str, Any] = Field(..., description="AI insights data")


class AddTagsRequest(BaseModel):
    """Request model for adding tags."""

    tags: List[str] = Field(..., description="Tags to add")


class MessageResponse(BaseModel):
    """Response model for messages."""

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
    """Response model for conversations."""

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
    """Response model for creating conversation."""

    conversation: ConversationResponse
    success: bool
    message: str


class AddMessageResponse(BaseModel):
    """Response model for adding message."""

    message: MessageResponse
    success: bool


class ContextResponse(BaseModel):
    """Response model for conversation context."""

    conversation_summary: Dict[str, Any]
    recent_messages: List[Dict[str, Any]]
    relevant_memories: Dict[str, List[Dict[str, Any]]]
    ai_insights: Dict[str, Any]
    user_preferences: Dict[str, Any]
    ai_insights_context: Dict[str, Any]
    conversation_patterns: Dict[str, Any]
    context_metadata: Dict[str, Any]


class ConversationListResponse(BaseModel):
    """Response model for conversation list."""

    conversations: List[ConversationResponse]
    total_count: int
    has_more: bool


class AnalyticsResponse(BaseModel):
    """Response model for conversation analytics."""

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


# Alias core dependencies for convenience
get_current_tenant = get_current_tenant_id


def _convert_conversation_to_response(conversation) -> ConversationResponse:
    """Convert conversation to response model."""
    conversation_dict = conversation.to_dict()

    # Convert messages
    messages = []
    for msg_data in conversation_dict["messages"]:
        messages.append(
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
        )

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


@router.post("/create", response_model=CreateConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Create a new conversation with web UI features."""
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
            error_response = create_service_error_response(
                service_name="conversation",
                error=Exception("Failed to create conversation"),
                error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
                user_message="Failed to create conversation. Please try again.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(
                    WebAPIErrorCode.INTERNAL_SERVER_ERROR
                ),
                detail=error_response.model_dump(mode="json"),
            )

        return CreateConversationResponse(
            conversation=_convert_conversation_to_response(conversation),
            success=True,
            message="Conversation created successfully",
        )

    except Exception as e:
        logger.exception("Failed to create conversation", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to create conversation. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    include_context: bool = Query(True, description="Include context data"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Get conversation by ID with web UI features."""
    try:
        # DEBUG: Log service availability
        logger.info(
            f"🔍 DEBUG: Getting conversation {conversation_id} with service: {type(conversation_service).__name__}"
        )
        logger.info(f"🔍 DEBUG: Service registry status: {conversation_service}")

        conversation = await conversation_service.get_web_ui_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            include_context=include_context,
            user_id=user_ctx.get("user_id"),
        )

        logger.info(f"🔍 DEBUG: Successfully retrieved conversation {conversation_id}")

        if not conversation:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Conversation not found",
                user_message="The requested conversation could not be found.",
                details={"conversation_id": conversation_id},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return _convert_conversation_to_response(conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get conversation", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get conversation. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/by-session/{session_id}", response_model=ConversationResponse)
async def get_conversation_by_session(
    session_id: str,
    include_context: bool = Query(True, description="Include context data"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Retrieve a conversation using its session identifier."""

    try:
        # DEBUG: Log session lookup details
        logger.info(
            "🔍 DEBUG: Attempting to retrieve conversation by session ID: %s",
            session_id,
        )
        logger.info("🔍 DEBUG: Tenant ID: %s", tenant_id)
        logger.info("🔍 DEBUG: User context: %s", user_ctx)
        logger.info(
            "🔍 DEBUG: Conversation service type: %s",
            type(conversation_service).__name__,
        )

        conversation = await conversation_service.get_web_ui_conversation_by_session(
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_ctx.get("user_id"),
            include_context=include_context,
        )

        logger.info(
            "🔍 DEBUG: Conversation lookup result: %s", conversation is not None
        )

        if not conversation:
            logger.warning(
                "🔍 DEBUG: No conversation found for session ID: %s", session_id
            )
            logger.info(
                "🔍 DEBUG: This indicates a new session that hasn't been used to create a conversation yet"
            )

            # Instead of returning a 404, return an empty conversation response
            # This allows the frontend to handle new sessions gracefully
            empty_conversation = ConversationResponse(
                id="new-session",
                user_id=user_ctx.get("user_id", "anonymous"),
                title="New Conversation",
                messages=[],
                metadata={},
                is_active=True,
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                message_count=0,
                last_message_at=None,
                session_id=session_id,
                ui_context={},
                ai_insights={},
                user_settings={},
                summary=None,
                tags=[],
                last_ai_response_id=None,
                status="active",
                priority="normal",
                context_memories=[],
                proactive_suggestions=[],
            )

            logger.info("🔍 DEBUG: Returning empty conversation for new session")
            return empty_conversation

        logger.info(
            "🔍 DEBUG: Successfully retrieved conversation with %d messages",
            len(conversation.messages),
        )
        return _convert_conversation_to_response(conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "🔍 DEBUG: Failed to get conversation by session", error=str(e)
        )
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get conversation. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/{conversation_id}/messages", response_model=AddMessageResponse)
async def add_message(
    conversation_id: str,
    request: AddMessageRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Add a message to conversation with web UI features."""
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
            error_response = create_service_error_response(
                service_name="conversation",
                error=Exception("Failed to add message"),
                error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
                user_message="Failed to add message to conversation. Please try again.",
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(
                    WebAPIErrorCode.INTERNAL_SERVER_ERROR
                ),
                detail=error_response.model_dump(mode="json"),
            )

        message_dict = message.to_dict()
        message_response = MessageResponse(
            id=message_dict["id"],
            role=message_dict["role"],
            content=message_dict["content"],
            timestamp=message_dict["timestamp"],
            metadata=message_dict["metadata"],
            function_call=message_dict.get("function_call"),
            function_response=message_dict.get("function_response"),
            ui_source=message_dict.get("ui_source"),
            ai_confidence=message_dict.get("ai_confidence"),
            processing_time_ms=message_dict.get("processing_time_ms"),
            tokens_used=message_dict.get("tokens_used"),
            model_used=message_dict.get("model_used"),
            user_feedback=message_dict.get("user_feedback"),
            edited=message_dict.get("edited", False),
            edit_history=message_dict.get("edit_history", []),
        )

        return AddMessageResponse(message=message_response, success=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to add message", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to add message to conversation. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/{conversation_id}/context", response_model=ContextResponse)
async def build_context(
    conversation_id: str,
    request: BuildContextRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Build comprehensive conversation context."""
    try:
        context = await conversation_service.build_conversation_context(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            current_message=request.current_message,
            include_memories=request.include_memories,
            include_insights=request.include_insights,
        )

        return ContextResponse(**context)

    except Exception as e:
        logger.exception("Failed to build context", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to build conversation context. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.put("/{conversation_id}/ui-context")
async def update_ui_context(
    conversation_id: str,
    request: UpdateUIContextRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Update conversation UI context."""
    try:
        success = await conversation_service.update_conversation_ui_context(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            ui_context=request.ui_context,
        )

        if not success:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {"success": True, "message": "UI context updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update UI context", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to update UI context. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.put("/{conversation_id}/ai-insights")
async def update_ai_insights(
    conversation_id: str,
    request: UpdateAIInsightsRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Update conversation AI insights."""
    try:
        success = await conversation_service.update_conversation_ai_insights(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            ai_insights=request.ai_insights,
        )

        if not success:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {"success": True, "message": "AI insights updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update AI insights", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to update AI insights. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/{conversation_id}/tags")
async def add_tags(
    conversation_id: str,
    request: AddTagsRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Add tags to conversation."""
    try:
        success = await conversation_service.add_conversation_tags(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            tags=request.tags,
        )

        if not success:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {
            "success": True,
            "message": f"Added {len(request.tags)} tags to conversation",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to add tags", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to add tags to conversation. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
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
    """List conversations for current user."""
    logger.info(
        f"🔍 DEBUG: list_conversations called with active_only={active_only}, limit={limit}, offset={offset}"
    )
    logger.info(
        f"🔍 DEBUG: user_ctx keys: {list(user_ctx.keys()) if user_ctx else 'None'}"
    )
    try:
        user_id = _require_user_id(user_ctx)
        logger.info(f"🔍 DEBUG: user_id extracted: {user_id}")

        base_manager = conversation_service.base_manager
        sig = inspect.signature(base_manager.list_conversations)
        params = sig.parameters

        # The base ConversationManager accepts `active_only` directly.
        # The enhanced ConversationManager uses `filters: ConversationFilters`.
        # We must detect which variant is wired and call accordingly.
        if "active_only" in params:
            conversations = await base_manager.list_conversations(
                tenant_id=tenant_id,
                user_id=user_id,
                active_only=active_only,
                limit=limit,
                offset=offset,
            )
        else:
            # Enhanced manager – convert the boolean to ConversationFilters
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

        # Convert to web UI conversations
        web_ui_conversations = []
        for conv in conversations:
            # Get web UI data for each conversation
            web_ui_data = await conversation_service._get_web_ui_conversation_data(
                tenant_id, conv.id
            )

            web_ui_conv = await conversation_service._convert_to_web_ui_conversation(
                conv,
                web_ui_data.get("session_id"),
                web_ui_data.get("ui_context", {}),
                web_ui_data.get("user_settings", {}),
                web_ui_data.get("tags", []),
                ConversationPriority.from_any(web_ui_data.get("priority", "normal")),
                web_ui_data.get("summary"),
                web_ui_data.get("last_ai_response_id"),
            )

            web_ui_conversations.append(_convert_conversation_to_response(web_ui_conv))

        # Get global stats for total count
        stats = await conversation_service.base_manager.get_conversation_stats(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        total_count = _get_total_conversations_from_stats(
            stats,
            len(web_ui_conversations),
        )

        logger.info(
            f"🔍 DEBUG: About to return response with {len(web_ui_conversations)} conversations"
        )
        try:
            response = ConversationListResponse(
                conversations=web_ui_conversations,
                total_count=total_count,
                has_more=len(web_ui_conversations) == limit,
            )
            logger.info(f"🔍 DEBUG: Response created successfully: {response}")
            return response
        except Exception as validation_error:
            logger.error(
                f"🔍 DEBUG: Validation error creating response: {validation_error}"
            )
            logger.error(
                f"🔍 DEBUG: web_ui_conversations type: {type(web_ui_conversations)}"
            )
            logger.error(
                f"🔍 DEBUG: First conversation type: {type(web_ui_conversations[0]) if web_ui_conversations else 'None'}"
            )
            if web_ui_conversations:
                logger.error(f"🔍 DEBUG: First conversation: {web_ui_conversations[0]}")
                logger.error(
                    f"🔍 DEBUG: First conversation dict: {web_ui_conversations[0].dict() if hasattr(web_ui_conversations[0], 'dict') else 'No dict method'}"
                )
            raise

    except Exception as e:
        logger.exception(
            "❌ API: Failed to list conversations for user %s: %s",
            user_ctx.get("user_id"),
            str(e),
        )
        # Check if it's a validation error and provide more details
        if "Validation error" in str(e) or "pydantic" in str(e).lower():
            logger.error(f"🔍 DEBUG: Pydantic validation details: {e}")
            if "web_ui_conversations" in locals():
                logger.error(
                    f"🔍 DEBUG: web_ui_conversations length: {len(web_ui_conversations)}"
                )
                if web_ui_conversations:
                    for i, conv in enumerate(
                        web_ui_conversations[:3]
                    ):  # Check first 3 conversations
                        logger.error(f"🔍 DEBUG: Conversation {i}: {conv}")
                        logger.error(f"🔍 DEBUG: Conversation {i} type: {type(conv)}")
                        if hasattr(conv, "dict"):
                            logger.error(
                                f"🔍 DEBUG: Conversation {i} dict: {conv.dict()}"
                            )
                        elif hasattr(conv, "__dict__"):
                            logger.error(
                                f"🔍 DEBUG: Conversation {i} __dict__: {conv.__dict__}"
                            )
                        else:
                            logger.error(
                                f"🔍 DEBUG: Conversation {i} dir: {[attr for attr in dir(conv) if not attr.startswith('_')][:10]}"
                            )
            else:
                logger.error(
                    f"🔍 DEBUG: web_ui_conversations variable not available in locals()"
                )
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to list conversations. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.put("/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    title: Optional[str] = Query(None, description="New title"),
    is_active: Optional[bool] = Query(None, description="Active status"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Update conversation properties."""
    try:
        success = await conversation_service.base_manager.update_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            title=title,
            is_active=is_active,
        )

        if not success:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Conversation not found or update failed",
                user_message="The requested conversation could not be found or updated.",
                details={"conversation_id": conversation_id},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {"success": True, "message": "Conversation updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update conversation", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to update conversation. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Delete a conversation."""
    try:
        success = await conversation_service.delete_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )

        if not success:
            error_response = create_generic_error_response(
                error_code=WebAPIErrorCode.NOT_FOUND,
                message="Conversation not found or deletion failed",
                user_message="The requested conversation could not be found or deleted.",
                details={"conversation_id": conversation_id},
            )
            raise HTTPException(
                status_code=get_http_status_for_error_code(WebAPIErrorCode.NOT_FOUND),
                detail=error_response.model_dump(mode="json"),
            )

        return {"success": True, "message": "Conversation deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete conversation", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to delete conversation. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    time_range_start: Optional[datetime] = Query(
        None, description="Start of time range"
    ),
    time_range_end: Optional[datetime] = Query(None, description="End of time range"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Get conversation analytics for dashboard."""
    try:
        # Build time range tuple if provided
        time_range = None
        if time_range_start and time_range_end:
            time_range = (time_range_start, time_range_end)

        # Use current user if no user_id specified
        target_user_id = user_id or user_ctx.get("user_id")

        analytics = await conversation_service.get_conversation_analytics(
            tenant_id=tenant_id,
            user_id=target_user_id,
            time_range=time_range,
        )

        return AnalyticsResponse(**analytics)

    except Exception as e:
        logger.exception("Failed to get analytics", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get conversation analytics. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/stats")
async def get_conversation_stats(
    tenant_id: str = Depends(get_current_tenant),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
    conversation_service: ConversationService = Depends(get_conversation_service),
):
    """Get basic conversation statistics."""
    try:
        stats = await conversation_service.base_manager.get_conversation_stats(
            tenant_id,
            user_ctx.get("user_id"),
        )
        web_ui_metrics = conversation_service.get_metrics()

        return {
            "base_stats": stats,
            "web_ui_metrics": web_ui_metrics,
            "tenant_id": tenant_id,
        }

    except Exception as e:
        logger.exception("Failed to get stats", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to get conversation statistics. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.post("/cleanup-inactive")
async def cleanup_inactive_conversations(
    days_inactive: int = Query(30, ge=1, description="Days of inactivity threshold"),
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Mark old conversations as inactive."""
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

    except Exception as e:
        logger.exception("Failed to cleanup conversations", error=str(e))
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to cleanup conversations. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check for conversation service."""
    return {
        "status": "healthy",
        "service": "conversation",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/ensure-session/{session_id}")
async def ensure_session_conversation(
    session_id: str,
    conversation_service: ConversationService = Depends(get_conversation_service),
    tenant_id: str = Depends(get_current_tenant_id),
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
):
    """Ensure a conversation record exists for the given session ID. Creates one if it doesn't exist."""

    try:
        logger.info(
            "🔍 DEBUG: Ensuring conversation exists for session ID: %s", session_id
        )

        # First, try to get existing conversation
        existing_conversation = (
            await conversation_service.get_web_ui_conversation_by_session(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_ctx.get("user_id"),
                include_context=False,
            )
        )

        if existing_conversation:
            logger.info(
                "🔍 DEBUG: Existing conversation found for session: %s", session_id
            )
            return _convert_conversation_to_response(existing_conversation)

        # Create new conversation for this session
        logger.info("🔍 DEBUG: Creating new conversation for session: %s", session_id)

        try:
            new_conversation = await conversation_service.create_web_ui_conversation(
                tenant_id=tenant_id,
                user_id=user_ctx.get("user_id", "anonymous"),
                session_id=session_id,
                ui_source=UISource.WEB,
                title="New Conversation",
                initial_message=None,
                user_settings={},
                ui_context={},
                tags=["new-session"],
                priority=ConversationPriority.NORMAL,
            )
        except Exception as create_err:
            logger.exception(
                "❌ API: create_web_ui_conversation raised for session %s: %s",
                session_id,
                create_err,
            )
            logger.warning(
                "🔍 DEBUG: Falling back to empty session bootstrap for %s", session_id
            )
            return ConversationResponse(
                id="new-session",
                user_id=user_ctx.get("user_id", "anonymous"),
                title="New Conversation",
                messages=[],
                metadata={},
                is_active=True,
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat(),
                message_count=0,
                last_message_at=None,
                session_id=session_id,
                ui_context={},
                ai_insights={},
                user_settings={},
                summary=None,
                tags=[],
                last_ai_response_id=None,
                status="active",
                priority="normal",
                context_memories=[],
                proactive_suggestions=[],
            )

        if not new_conversation:
            logger.error("❌ API: Service returned None for session: %s", session_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to create conversation record (service returned None).",
            )

        logger.info(
            "🔍 DEBUG: Successfully created new conversation for session: %s",
            session_id,
        )
        return _convert_conversation_to_response(new_conversation)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "❌ API: Failed to ensure session conversation for session %s: %s",
            session_id,
            str(e),
        )
        error_response = create_service_error_response(
            service_name="conversation",
            error=e,
            error_code=WebAPIErrorCode.INTERNAL_SERVER_ERROR,
            user_message="Failed to ensure conversation exists. Please try again.",
        )
        raise HTTPException(
            status_code=get_http_status_for_error_code(
                WebAPIErrorCode.INTERNAL_SERVER_ERROR
            ),
            detail=error_response.model_dump(mode="json"),
        )


@router.get("/ensure-session/{session_id}")
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


@router.post("/update-session-activity/{session_id}")
async def update_session_activity(
    session_id: str,
    activity_data: Optional[Dict[str, Any]] = None,
    conversation_service: ConversationService = Depends(get_conversation_service),
):
    """Update session activity timestamp and data."""
    try:
        success = await conversation_service.update_session_activity(
            session_id=session_id,
            activity_data=activity_data,
        )
        return {"success": success}
    except Exception as e:
        logger.exception("Failed to update session activity", error=str(e))
        return {"success": False, "error": str(e)}
