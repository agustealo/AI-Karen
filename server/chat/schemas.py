"""
Pydantic schemas for the production chat system API.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List, Union, Literal
from pydantic import BaseModel, Field, validator
from enum import Enum


class MessageRole(str, Enum):
    """Message role enum for chat messages."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ProviderType(str, Enum):
    """Provider type enum for LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    LOCAL = "local"


class StreamingStatus(str, Enum):
    """Streaming status enum for messages."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# Base schemas
class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class MessageMetadata(BaseSchema):
    """Metadata for chat messages."""
    token_count: Optional[int] = None
    processing_time_ms: Optional[int] = None
    provider_id: Optional[str] = None
    model_used: Optional[str] = None
    parent_message_id: Optional[str] = None
    is_streaming: Optional[bool] = False
    streaming_completed_at: Optional[datetime] = None


class ConversationMetadata(BaseSchema):
    """Metadata for chat conversations."""
    provider_id: Optional[str] = None
    model_used: Optional[str] = None
    user_settings: Optional[Dict[str, Any]] = {}
    ui_context: Optional[Dict[str, Any]] = {}
    ai_insights: Optional[Dict[str, Any]] = {}


class ProviderConfig(BaseSchema):
    """Configuration for LLM providers."""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(
        2048,
        ge=1,
        description="Requested output tokens. Provider/model caps are enforced later.",
    )
    timeout_seconds: Optional[int] = Field(30, ge=1, le=300)
    enabled: bool = True
    priority: int = 0


class SessionMetadata(BaseSchema):
    """Metadata for chat sessions."""
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    device_fingerprint: Optional[str] = None
    geolocation: Optional[Dict[str, Any]] = {}


class AttachmentMetadata(BaseSchema):
    """Metadata for message attachments."""
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    processing_status: Optional[str] = None


# Request schemas
class CreateConversationRequest(BaseSchema):
    """Request schema for creating a new conversation."""
    title: Optional[str] = None
    provider_id: Optional[str] = None
    metadata: Optional[ConversationMetadata] = None


class SendMessageRequest(BaseSchema):
    """Request schema for sending a message."""
    content: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str = Field(..., min_length=1)
    role: MessageRole = MessageRole.USER
    provider_id: Optional[str] = None
    options: Optional[Dict[str, Any]] = {}
    stream: bool = False
    attachments: Optional[List[str]] = []


class UpdateConversationRequest(BaseSchema):
    """Request schema for updating a conversation."""
    title: Optional[str] = None
    metadata: Optional[ConversationMetadata] = None
    is_archived: Optional[bool] = None


class ConfigureProviderRequest(BaseSchema):
    """Request schema for configuring a provider."""
    config: ProviderConfig
    is_active: Optional[bool] = None
    priority: Optional[int] = None


class StreamMessageRequest(BaseSchema):
    """Request schema for streaming a message."""
    content: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str = Field(..., min_length=1)
    role: MessageRole = MessageRole.USER
    provider_id: Optional[str] = None
    options: Optional[Dict[str, Any]] = {}
    session_token: Optional[str] = None


# Response schemas
class MessageResponse(BaseSchema):
    """Response schema for chat messages."""
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    created_at: datetime
    updated_at: datetime
    provider_id: Optional[str] = None
    model_used: Optional[str] = None
    token_count: Optional[int] = None
    processing_time_ms: Optional[int] = None
    metadata: MessageMetadata
    parent_message_id: Optional[str] = None
    is_streaming: bool = False
    streaming_completed_at: Optional[datetime] = None
    attachments: Optional[List["AttachmentResponse"]] = []


class ConversationResponse(BaseSchema):
    """Response schema for chat conversations."""
    id: str
    user_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    provider_id: Optional[str] = None
    model_used: Optional[str] = None
    message_count: int
    metadata: ConversationMetadata
    is_archived: bool
    messages: Optional[List[MessageResponse]] = []


class ProviderResponse(BaseSchema):
    """Response schema for LLM providers."""
    id: str
    user_id: str
    provider_id: str
    provider_name: str
    config: ProviderConfig
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime


class SessionResponse(BaseSchema):
    """Response schema for chat sessions."""
    id: str
    conversation_id: str
    user_id: str
    session_token: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    last_activity_at: datetime
    metadata: SessionMetadata


class AttachmentResponse(BaseSchema):
    """Response schema for message attachments."""
    id: str
    message_id: str
    filename: str
    file_path: str
    mime_type: str
    file_size: int
    created_at: datetime
    metadata: AttachmentMetadata


class StreamChunkResponse(BaseSchema):
    """Response schema for streaming chunks."""
    content: str
    role: MessageRole
    provider: str
    is_complete: bool = False
    metadata: Optional[Dict[str, Any]] = None


class StreamResponse(BaseSchema):
    """Response schema for streaming responses."""
    session_token: Optional[str] = None
    chunks: List[StreamChunkResponse]
    metadata: Optional[Dict[str, Any]] = None


# List and pagination schemas
class ConversationListResponse(BaseSchema):
    """Response schema for conversation lists."""
    conversations: List[ConversationResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool


class MessageListResponse(BaseSchema):
    """Response schema for message lists."""
    messages: List[MessageResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool


class ProviderListResponse(BaseSchema):
    """Response schema for provider lists."""
    providers: List[ProviderResponse]
    total: int


# Error response schemas
class ErrorResponse(BaseSchema):
    """Standard error response schema."""
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ValidationErrorResponse(ErrorResponse):
    """Validation error response schema."""
    field: Optional[str] = None
    value: Optional[Any] = None


# Success response schemas
class SuccessResponse(BaseSchema):
    """Standard success response schema."""
    success: bool = True
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Health check schemas
class HealthCheckResponse(BaseSchema):
    """Health check response schema."""
    status: str
    timestamp: datetime
    version: str
    database: Optional[Dict[str, Any]] = None
    providers: Optional[Dict[str, Any]] = None


# Configuration schemas
class ChatSettings(BaseSchema):
    """Chat settings configuration."""
    default_provider: Optional[str] = None
    max_conversations: Optional[int] = Field(100, ge=1, le=1000)
    max_messages_per_conversation: Optional[int] = Field(1000, ge=1, le=10000)
    enable_streaming: bool = True
    enable_attachments: bool = True
    max_attachment_size_mb: Optional[int] = Field(10, ge=1, le=100)
    allowed_mime_types: Optional[List[str]] = []


class UserPreferences(BaseSchema):
    """User preferences for chat."""
    theme: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    notifications: Optional[Dict[str, Any]] = {}
    accessibility: Optional[Dict[str, Any]] = {}


# Search and filtering schemas
class SearchRequest(BaseSchema):
    """Request schema for searching conversations."""
    query: str = Field(..., min_length=1, max_length=100)
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)
    sort_by: Optional[str] = "updated_at"
    sort_order: Optional[str] = "desc"
    filters: Optional[Dict[str, Any]] = {}


class SearchResponse(BaseSchema):
    """Response schema for search results."""
    results: List[ConversationResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
    has_prev: bool
    query: str
