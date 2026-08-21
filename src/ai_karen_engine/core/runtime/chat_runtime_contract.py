from __future__ import annotations

import uuid
from dataclasses import dataclass, field
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
    actual_provider: Optional[str] = None
    actual_model: Optional[str] = None
    runtime_engine: Optional[str] = None
    response_source: Optional[str] = None

    fallback_level: int = 0
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
            "actual_provider": self.actual_provider,
            "actual_model": self.actual_model,
            "runtime_engine": self.runtime_engine,
            "response_source": self.response_source,
            "fallback_level": self.fallback_level,
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
