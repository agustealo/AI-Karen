from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ChatExecutionMode(str, Enum):
    """Authoritative runtime mode for a single chat execution.

    The control plane owns system availability; the runtime reports the mode
    it resolved for this specific request.
    """

    NORMAL = "normal"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    EMERGENCY = "emergency"
    GRAPH = "graph"


class ChatExecutionStatus(str, Enum):
    """Terminal status of a chat execution attempt."""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"
    GATE = "gate"


class ChatStreamEventType(str, Enum):
    """Canonical, transport-agnostic event types emitted by ChatRuntime.execute_stream.

    Every transport (SSE, WebSocket, CopilotKit, HTTP) serializes the same
    semantics via ``ChatStreamChunk.type`` using this enum so the frontend
    only needs one normalizer.
    """

    STATUS = "status"
    CONTENT = "content"
    TOOL = "tool"
    CITATION = "citation"
    APPROVAL = "approval"
    WARNING = "warning"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class ChatExecutionContext:
    """Stable request/tenant/session identity for one chat execution.

    This is the single identity carrier that must propagate from ingress
    through provider, memory, plugin, and persistence.
    """

    user_id: str
    tenant_id: str = "default"
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)


@dataclass
class ChatExecutionRequest:
    """Canonical input contract for the chat runtime.

    Every transport (HTTP, WebSocket, CopilotKit, future internal paths)
    normalizes its external shape into this object before delegating to
    ``ChatRuntime.execute``.
    """

    messages: List[Dict[str, Any]]
    context: ChatExecutionContext
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatRuntimeMetadata:
    """Single normalizer for the user-facing chat response metadata contract.

    One schema, one place. Required fields from the runtime authority audit.
    """

    correlation_id: str
    latency_ms: float = 0.0

    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None
    requested_target: Optional[str] = None
    actual_provider: Optional[str] = None
    actual_model: Optional[str] = None
    actual_target: Optional[str] = None
    runtime_engine: Optional[str] = None
    protocol: Optional[str] = None
    locality: Optional[str] = None
    response_source: Optional[str] = None

    fallback_level: int = 0
    fallback_reason: Optional[str] = None
    degraded_mode: bool = False
    degradation_reason: Optional[str] = None

    mode: str = "normal"
    used_fallback: bool = False
    context_used: bool = False

    # Stable backend-confirmed identifiers surfaced to clients.
    response_id: Optional[str] = None
    conversation_id: Optional[str] = None
    assistant_message_id: Optional[str] = None

    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Render the canonical metadata plus any extension fields."""
        base: Dict[str, Any] = {
            "correlation_id": self.correlation_id,
            "latency_ms": self.latency_ms,
            "requested_provider": self.requested_provider,
            "requested_model": self.requested_model,
            "requested_target": self.requested_target,
            "actual_provider": self.actual_provider,
            "actual_model": self.actual_model,
            "actual_target": self.actual_target,
            "runtime_engine": self.runtime_engine,
            "protocol": self.protocol,
            "locality": self.locality,
            "response_source": self.response_source,
            "fallback_level": self.fallback_level,
            "fallback_reason": self.fallback_reason,
            "degraded_mode": self.degraded_mode,
            "degradation_reason": self.degradation_reason,
            "mode": self.mode,
            "used_fallback": self.used_fallback,
            "context_used": self.context_used,
            "response_id": self.response_id,
            "conversation_id": self.conversation_id,
            "assistant_message_id": self.assistant_message_id,
        }
        base.update(self.extra)
        return base


@dataclass
class ChatExecutionResult:
    """Canonical output contract for the chat runtime.

    When ``status`` is ``GATE`` the ``gate_response`` carries the control
    plane decision (maintenance / degraded / emergency) and the transport
    must serialize it instead of a normal answer.
    """

    answer: str
    metadata: ChatRuntimeMetadata
    structured_content: Dict[str, Any] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    status: ChatExecutionStatus = ChatExecutionStatus.OK
    gate_response: Optional[Any] = None

    citations: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)


try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field


class ChatStreamChunk(BaseModel):
    """Granular output chunk for streaming responses."""

    model_config = ConfigDict(protected_namespaces=())

    type: ChatStreamEventType = Field(
        ..., description="Event type. Canonical values live in ChatStreamEventType."
    )
    content: str = Field("", description="The text fragment or status update")
    correlation_id: str = Field(..., description="Request tracking identifier")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional chunk metadata")

    event_id: Optional[str] = Field(
        None, description="Unique identifier for this chunk/event"
    )
    sequence: Optional[int] = Field(
        None, description="Monotonically increasing chunk sequence number"
    )
    request_id: Optional[str] = Field(
        None, description="Identifies the originating request"
    )
    response_id: Optional[str] = Field(
        None, description="Identifies the runtime response"
    )
    conversation_id: Optional[str] = Field(
        None, description="Conversation context identifier"
    )
    timestamp: Optional[datetime] = Field(
        None, description="When this chunk was emitted"
    )

    def to_sse_payload(self) -> Dict[str, Any]:
        """Serialize to a transport-agnostic dict suitable for SSE data lines."""
        return {
            "type": self.type.value if isinstance(self.type, ChatStreamEventType) else self.type,
            "content": self.content,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "request_id": self.request_id,
            "response_id": self.response_id,
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class CanonicalChatRequest(BaseModel):
    """Input payload for the canonical chat orchestration runtime."""
    model_config = ConfigDict(protected_namespaces=())

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Stable request identifier")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Cross-service correlation identifier")
    tenant_id: Optional[str] = Field(None, description="Tenant identifier when available")
    message: str = Field(..., description="The user's message content")
    user_id: str = Field(..., description="Unique user identifier")
    org_id: Optional[str] = Field(None, description="Organization or Tenant ID")
    conversation_id: str = Field(..., description="Active conversation context ID")
    session_id: Optional[str] = Field(None, description="Optional session tracking ID")
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Stable user message identifier")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="Associated file or media links")
    include_context: bool = Field(True, description="Whether to perform RAG recall")
    metadata: Dict[str, Any] = Field(default_factory=list, description="Additional request-specific metadata")
    streaming: bool = Field(False, description="Whether to return a stream generator")
    stream: bool = Field(False, description="Alias for streaming")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Request creation timestamp")


class CanonicalChatResponse(BaseModel):
    """Terminal output from the canonical orchestration runtime."""
    model_config = ConfigDict(protected_namespaces=())

    request_id: Optional[str] = Field(None, description="Source request identifier")
    response: str = Field(..., description="The final generated response")
    correlation_id: str = Field(..., description="Request tracking identifier")
    conversation_id: Optional[str] = Field(None, description="Conversation identifier")
    assistant_message_id: Optional[str] = Field(None, description="Persisted assistant message identifier")
    processing_time: float = Field(..., description="Total execution time in seconds")
    status: ChatExecutionStatus = Field(..., description="Terminal processing state")
    used_fallback: bool = Field(False, description="Whether a fallback model was used")
    context_used: bool = Field(False, description="Whether RAG context was utilized")
    execution_path: Optional[str] = Field(None, description="Execution path selected by the orchestrator")
    structured_content: Dict[str, Any] = Field(default_factory=dict, description="Rich JSON output or application state")
    actions: List[Dict[str, Any]] = Field(default_factory=list, description="Suggested or triggered automation actions")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Detailed execution and model metadata")
    telemetry: Dict[str, Any] = Field(default_factory=dict, description="Telemetry payload for frontend/runtime inspection")
    error: Optional[str] = Field(None, description="Error message if failed")
    error_type: Optional[ErrorType] = Field(None, description="Error classification")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Response creation timestamp")
