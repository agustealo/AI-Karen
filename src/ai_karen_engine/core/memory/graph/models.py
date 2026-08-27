from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MemoryEventNode:
    event_id: str
    user_id: str
    tenant_id: str
    conversation_id: str | None = None
    memory_type: str | None = None
    created_at: float | None = None
    importance: float | None = None
    source: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime | None = None
    recorded_at: datetime | None = None


@dataclass(slots=True)
class EntityNode:
    entity_id: str
    text: str
    type: str | None = None
    normalized: str | None = None


@dataclass(slots=True)
class AssertionNode:
    assertion_id: str
    user_id: str
    tenant_id: str
    text: str
    confidence: float | None = None
    polarity: str | None = None
    created_at: float | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime | None = None
    recorded_at: datetime | None = None
    lifecycle_state: str = "active"
    supersedes: str | None = None


@dataclass(slots=True)
class GraphEdge:
    from_id: str
    to_id: str
    relationship: str
    tenant_id: str
    user_id: str | None = None
    conversation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    observed_at: datetime | None = None
    recorded_at: datetime | None = None
    confidence: float = 1.0
    weight: float = 1.0
    salience: float = 0.5
    lifecycle_state: str = "active"
    source_memory_id: str | None = None
    source_event_id: str | None = None
    schema_version: int = 1
