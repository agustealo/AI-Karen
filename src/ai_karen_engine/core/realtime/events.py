"""Versioned Realtime Event Envelope for KAREN Supabase integration.

Defines the canonical event contract shared between backend and UI.
No Supabase SDK imports here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    CONVERSATION_MESSAGE_CREATED = "conversation.message.created.v1"
    CONVERSATION_UPDATED = "conversation.updated.v1"

    EXECUTION_STARTED = "execution.started.v1"
    EXECUTION_PROGRESS = "execution.progress.v1"
    EXECUTION_COMPLETED = "execution.completed.v1"
    EXECUTION_FAILED = "execution.failed.v1"

    ARTIFACT_UPLOAD_STARTED = "artifact.upload.started.v1"
    ARTIFACT_AVAILABLE = "artifact.available.v1"
    ARTIFACT_FAILED = "artifact.failed.v1"
    ARTIFACT_DELETED = "artifact.deleted.v1"

    NOTIFICATION_CREATED = "notification.created.v1"

    PROVIDER_DEGRADED = "provider.degraded.v1"
    PROVIDER_RECOVERED = "provider.recovered.v1"


@dataclass(frozen=True)
class RealtimeEvent:
    """Canonical realtime event envelope.

    Required properties:
        event_id, event_type, version, tenant_id, resource_id,
        correlation_id, occurred_at, payload
    """

    event_id: uuid.UUID = field(default_factory=uuid.uuid4)
    event_type: str = ""
    version: int = 1
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    resource_id: uuid.UUID = field(default_factory=uuid.uuid4)
    correlation_id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_type:
            raise ValueError("event_type is required")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("occurred_at must be datetime")


@dataclass(frozen=True)
class EventValidationResult:
    """Result of validating an inbound event."""

    valid: bool
    event: Optional[RealtimeEvent] = None
    reason: Optional[str] = None


def validate_event(data: Dict[str, Any]) -> EventValidationResult:
    """Validate raw event dict into a RealtimeEvent.

    Returns EventValidationResult with either the parsed event or rejection reason.
    """
    try:
        event = RealtimeEvent(
            event_id=uuid.UUID(str(data["event_id"])),
            event_type=str(data["event_type"]),
            version=int(data.get("version", 1)),
            tenant_id=uuid.UUID(str(data["tenant_id"])),
            resource_id=uuid.UUID(str(data["resource_id"])),
            correlation_id=uuid.UUID(str(data["correlation_id"])),
            occurred_at=_parse_occurred_at(data.get("occurred_at")),
            payload=_safe_dict(data.get("payload", {})),
        )
        return EventValidationResult(valid=True, event=event)
    except (KeyError, ValueError, TypeError) as exc:
        return EventValidationResult(valid=False, reason=str(exc))


def _parse_occurred_at(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def is_safe_payload(payload: Dict[str, Any]) -> bool:
    """Reject payloads that contain forbidden sensitive fields."""
    forbidden = {
        "system_prompt",
        "private_reasoning",
        "provider_credentials",
        "internal_policy",
        "raw_authorization_state",
        "secret_metadata",
    }
    return not any(key in payload for key in forbidden)
