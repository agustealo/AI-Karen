"""
Web UI specific type definitions for API compatibility.

This module provides Pydantic models that match the TypeScript interfaces
used in the web UI, ensuring seamless integration between frontend and backend.
"""

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum


class FileType(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    CODE = "code"
    OTHER = "other"


class UISource(str, Enum):
    WEB = "web"
    DESKTOP = "desktop"
    API = "api"
    AG_UI = "ag_ui"
    COPILOTKIT = "copilotkit"


# Chat Processing Models


class ChatProcessRequest(BaseModel):
    """Request format expected by web UI for chat processing."""

    message: str = Field(..., description="User message")
    conversation_history: List[Dict[str, Any]] = Field(
        default_factory=list, description="Conversation history"
    )
    relevant_memories: List[Dict[str, Any]] = Field(
        default_factory=list, description="Relevant memories"
    )
    user_settings: Dict[str, Any] = Field(
        default_factory=dict, description="User settings"
    )
    user_id: Optional[str] = Field(None, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "Message cannot be empty or contain only whitespace"
            )
        if len(v) > 10_000:
            raise ValueError("Message is too long (maximum 10,000 characters)")
        return v

    @field_validator("conversation_history")
    @classmethod
    def validate_conversation_history(
        cls, v: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        for i, msg in enumerate(v):
            if not isinstance(msg, dict):
                raise ValueError(
                    f"conversation_history[{i}] must be an object"
                )
            if "role" not in msg or "content" not in msg:
                raise ValueError(
                    f"conversation_history[{i}] must include 'role' and 'content'"
                )
        return v

    @field_validator("user_settings")
    @classmethod
    def validate_user_settings(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise TypeError("User settings must be an object")
        return v


class ChatProcessResponse(BaseModel):
    """Response format expected by web UI for chat processing."""

    finalResponse: str = Field(
        ..., description="Final response to user (camelCase for JS compatibility)"
    )
    acknowledgement: Optional[str] = Field(
        None, description="Initial acknowledgement message"
    )
    ai_data_for_final_response: Optional[Dict[str, Any]] = Field(
        None, description="AI metadata"
    )
    suggested_new_facts: Optional[List[str]] = Field(
        None, description="Suggested facts to remember"
    )
    proactive_suggestion: Optional[str] = Field(
        None, description="Proactive suggestion"
    )
    summary_was_generated: Optional[bool] = Field(
        None, description="Whether summary was generated"
    )
    widget: Optional[str] = Field(
        None, description="Optional widget tag for rich UI rendering"
    )


# Memory Models
class WebUIMemoryQuery(BaseModel):
    """Memory query format expected by web UI with enhanced validation."""

    text: str = Field(..., min_length=1, max_length=1000, description="Query text")
    user_id: Optional[str] = Field(None, max_length=100, description="User ID")
    session_id: Optional[str] = Field(None, max_length=100, description="Session ID")
    tags: Optional[List[str]] = Field(None, description="Filter by tags")
    metadata_filter: Optional[Dict[str, Any]] = Field(
        None, description="Metadata filter"
    )
    time_range: Optional[List[datetime]] = Field(
        None, description="Time range [start, end]"
    )
    top_k: Optional[int] = Field(
        5, ge=1, le=100, description="Maximum number of results"
    )
    similarity_threshold: Optional[float] = Field(
        0.7, ge=0.0, le=1.0, description="Similarity threshold"
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Query text cannot be empty or contain only whitespace")

        cleaned_text = " ".join(v.strip().split())

        if len(cleaned_text) < 1:
            raise ValueError(
                "Query text must contain at least 1 character after cleaning"
            )

        return cleaned_text

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v

        if len(v) > 20:
            raise ValueError("Maximum 20 tags allowed")

        validated_tags = []
        for tag in v:
            if not isinstance(tag, str):
                raise ValueError("All tags must be strings")

            cleaned_tag = tag.strip().lower()
            if not cleaned_tag:
                continue

            if len(cleaned_tag) > 50:
                raise ValueError("Tag length cannot exceed 50 characters")

            if cleaned_tag not in validated_tags:
                validated_tags.append(cleaned_tag)

        return validated_tags if validated_tags else None

    @field_validator("time_range")
    @classmethod
    def validate_time_range(
        cls, v: Optional[List[datetime]]
    ) -> Optional[List[datetime]]:
        if v is None:
            return v

        if not isinstance(v, list) or len(v) != 2:
            raise ValueError(
                "Time range must be a list with exactly 2 datetime elements [start, end]"
            )

        start_time, end_time = v

        if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
            raise ValueError("Time range elements must be datetime objects")

        if start_time >= end_time:
            raise ValueError("Start time must be before end time")

        time_diff = end_time - start_time
        if time_diff.days > 365:
            raise ValueError("Time range cannot exceed 365 days")

        return v

    @field_validator("metadata_filter")
    @classmethod
    def validate_metadata_filter(
        cls, v: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if v is None:
            return v

        if not isinstance(v, dict):
            raise ValueError("Metadata filter must be a dictionary")

        if len(v) > 10:
            raise ValueError("Maximum 10 metadata filter keys allowed")

        for key, value in v.items():
            if not isinstance(key, str):
                raise ValueError("Metadata filter keys must be strings")

            if len(key) > 100:
                raise ValueError(
                    "Metadata filter key length cannot exceed 100 characters"
                )

            if not isinstance(value, (str, int, float, bool, type(None))):
                if isinstance(value, (list, dict)):
                    try:
                        import json
                        json.dumps(value)
                    except (TypeError, ValueError):
                        raise ValueError(
                            f"Metadata filter value for key '{key}' must be JSON serializable"
                        )
                else:
                    raise ValueError(
                        f"Metadata filter value for key '{key}' must be a basic type (str, int, float, bool, None, list, dict)"
                    )

        return v


class WebUIMemoryEntry(BaseModel):
    """Memory entry format expected by web UI with JavaScript compatibility."""

    id: str = Field(..., description="Memory ID")
    content: str = Field(..., description="Memory content")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Memory metadata"
    )
    timestamp: int = Field(
        ..., description="Unix timestamp in milliseconds for JS compatibility"
    )
    similarity_score: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Similarity score"
    )
    tags: List[str] = Field(default_factory=list, description="Memory tags")
    user_id: Optional[str] = Field(None, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Timestamp cannot be negative")

        min_timestamp = 946684800000
        max_timestamp = 4102444800000

        if v < min_timestamp or v > max_timestamp:
            raise ValueError("Timestamp must be between year 2000 and 2100")

        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Memory content cannot be empty")

        return v.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        if not v:
            return []

        cleaned_tags = []
        for tag in v:
            if isinstance(tag, str) and tag.strip():
                cleaned_tag = tag.strip().lower()
                if cleaned_tag not in cleaned_tags:
                    cleaned_tags.append(cleaned_tag)

        return cleaned_tags

    @field_validator("similarity_score")
    @classmethod
    def validate_similarity_score(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v

        if not isinstance(v, (int, float)):
            raise ValueError("Similarity score must be a number")

        if not (0.0 <= v <= 1.0):
            raise ValueError("Similarity score must be between 0.0 and 1.0")

        return float(v)


class WebUIMemoryQueryResponse(BaseModel):
    """Memory query response format expected by web UI with metadata."""

    memories: List[WebUIMemoryEntry] = Field(
        default_factory=list, description="Memory entries"
    )
    total_count: int = Field(0, ge=0, description="Total number of memories found")
    query_time_ms: float = Field(
        0.0, ge=0.0, description="Query execution time in milliseconds"
    )

    @field_validator("memories")
    @classmethod
    def validate_memories(cls, v: List[WebUIMemoryEntry]) -> List[WebUIMemoryEntry]:
        if v is None:
            return []

        if not isinstance(v, list):
            raise ValueError("Memories must be a list")

        return v

    @field_validator("total_count")
    @classmethod
    def validate_total_count(cls, v: int) -> int:
        if not isinstance(v, int):
            raise ValueError("Total count must be an integer")

        if v < 0:
            raise ValueError("Total count cannot be negative")

        return v

    @field_validator("query_time_ms")
    @classmethod
    def validate_query_time_ms(cls, v: float) -> float:
        if not isinstance(v, (int, float)):
            raise ValueError("Query time must be a number")

        if v < 0:
            raise ValueError("Query time cannot be negative")

        return round(float(v), 2)


class WebUIMemoryStoreRequest(BaseModel):
    """Memory store request format expected by web UI."""

    content: str = Field(..., description="Memory content")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Memory metadata")
    tags: Optional[List[str]] = Field(None, description="Memory tags")
    user_id: Optional[str] = Field(None, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")


class WebUIMemoryStoreResponse(BaseModel):
    """Memory store response format expected by web UI."""

    success: bool = Field(..., description="Whether storage was successful")
    memory_id: Optional[str] = Field(None, description="ID of stored memory")
    message: str = Field(..., description="Status message")


# Plugin Models
class WebUIPluginInfo(BaseModel):
    """Plugin information format expected by web UI."""

    name: str = Field(..., description="Plugin name")
    description: str = Field(..., description="Plugin description")
    category: str = Field(..., description="Plugin category")
    enabled: bool = Field(..., description="Whether plugin is enabled")
    version: Optional[str] = Field(None, description="Plugin version")


class WebUIPluginExecuteRequest(BaseModel):
    """Plugin execution request format expected by web UI."""

    plugin_name: str = Field(..., description="Name of plugin to execute")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Plugin parameters"
    )
    user_id: Optional[str] = Field(None, description="User ID")
    session_id: Optional[str] = Field(None, description="Session ID")


class WebUIPluginExecuteResponse(BaseModel):
    """Plugin execution response format expected by web UI."""

    success: bool = Field(..., description="Whether execution was successful")
    result: Optional[Dict[str, Any]] = Field(
        None, description="Plugin execution result"
    )
    error: Optional[str] = Field(None, description="Error message if execution failed")
    execution_time_ms: Optional[float] = Field(
        None, description="Execution time in milliseconds"
    )


# Analytics Models
class WebUISystemMetrics(BaseModel):
    """System metrics format expected by web UI."""

    cpu_usage: float = Field(..., description="CPU usage percentage")
    memory_usage: float = Field(..., description="Memory usage percentage")
    disk_usage: float = Field(..., description="Disk usage percentage")
    active_sessions: int = Field(..., description="Number of active sessions")
    total_requests: int = Field(..., description="Total number of requests")
    error_rate: float = Field(..., description="Error rate percentage")


class WebUIUsageAnalytics(BaseModel):
    """Usage analytics format expected by web UI."""

    total_conversations: int = Field(..., description="Total number of conversations")
    total_messages: int = Field(..., description="Total number of messages")
    average_session_duration: float = Field(
        ..., description="Average session duration in minutes"
    )
    most_used_features: List[Dict[str, Any]] = Field(
        default_factory=list, description="Most used features"
    )
    user_activity: Dict[str, Any] = Field(
        default_factory=dict, description="User activity data"
    )


# Health Check Models
class WebUIHealthCheck(BaseModel):
    """Health check response format expected by web UI."""

    status: str = Field(..., description="Overall health status")
    services: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, description="Individual service status"
    )
    timestamp: str = Field(..., description="Health check timestamp")
    uptime: float = Field(..., description="System uptime in seconds")
