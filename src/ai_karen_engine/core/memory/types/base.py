"""
Unified Memory Types for AI-Karen

This module provides unified types that consolidate:
- MemoryEntry (from neuro_vault)
- RecallItem (from recalls)
- Memory types from existing memory system

Aligns with research papers:
- HippoRAG: Hippocampal-inspired memory classification
- LongMem: Long-term memory architecture
- Think-in-Memory: Memory with reasoning integration

Author: AI-Karen Core Team
Version: 1.0.0 (Unified Architecture)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    """Tri-partite durable memory classification."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryNamespace(str, Enum):
    """Memory tier/duration classification."""

    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    PERSISTENT = "persistent"
    EPHEMERAL = "ephemeral"


class ArtifactType(str, Enum):
    """Artifact classification for downstream EchoCore export."""

    EPISODIC_EVENT = "episodic_event"
    LONG_TERM_FACT = "long_term_fact"
    USER_PREFERENCE = "user_preference"
    PROJECT_MEMORY = "project_memory"
    TRAINING_CANDIDATE = "training_candidate"
    ARCHIVAL_RECORD = "archival_record"
    SHADOW_SIGNAL = "shadow_signal"
    METADATA_SIGNAL = "metadata_signal"


class ArtifactSourceTier(str, Enum):
    """Source tier for promoted artifacts."""

    STM = "stm"
    EPISODIC = "episodic"
    LTM = "ltm"


class ArtifactPrivacyTag(str, Enum):
    """Privacy tags attached to runtime-exported artifacts."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"
    NO_TRAINING = "no_training"
    NO_EXPORT = "no_export"


class ArtifactTrainingEligibility(str, Enum):
    """Training eligibility state for runtime artifacts."""

    ELIGIBLE = "eligible"
    REVIEW = "review"
    INELIGIBLE = "ineligible"


class MemoryStatus(str, Enum):
    """Memory lifecycle status."""

    ACTIVE = "active"
    CONSOLIDATING = "consolidating"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    PENDING = "pending"


class MemoryPriority(str, Enum):
    """Memory priority for retrieval and consolidation."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MINIMAL = "minimal"


class MemoryVisibility(str, Enum):
    """Memory visibility/access control."""

    PUBLIC = "public"
    PRIVATE = "private"
    SHARED = "shared"
    SYSTEM = "system"


class RecallType(str, Enum):
    """Recall category compatible with the legacy recall system."""

    MESSAGE = "message"
    FACT = "fact"
    TASK = "task"
    INTENT = "intent"
    PROFILE = "profile"
    CONTEXT = "context"
    DOCUMENT = "document"
    SIGNAL = "signal"
    EVENT = "event"
    EMBEDDING = "embedding"


class ImportanceLevel(Enum):
    """Importance scoring levels (1-10 scale)."""

    CRITICAL = 10
    VERY_HIGH = 9
    HIGH = 8
    ABOVE_AVERAGE = 7
    AVERAGE = 6
    BELOW_AVERAGE = 5
    LOW = 4
    VERY_LOW = 3
    MINIMAL = 2
    NEGLIGIBLE = 1


EmbeddingVector = list[float]
ArtifactImportanceScore = float
ArtifactRetentionScore = float
RecallNamespace = MemoryNamespace
RecallPriority = MemoryPriority
RecallStatus = MemoryStatus
RecallVisibility = MemoryVisibility
JSONLike = dict[str, Any] | list[Any] | str | int | float | bool | None


@dataclass
class MemoryMetadata:
    """Metadata for memory entries."""

    tenant_id: str
    user_id: str
    conversation_id: str | None = None
    session_id: str | None = None
    source: str = "user"
    created_by: str | None = None
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    related_memories: list[str] = field(default_factory=list)
    custom: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeMemoryArtifact:
    """Normalized artifact exported from runtime memory to EchoCore."""

    artifact_id: str
    artifact_type: ArtifactType
    source_tier: ArtifactSourceTier
    user_id: str
    tenant_id: str | None
    session_id: str | None
    thread_id: str | None
    content: dict[str, Any]
    importance_score: ArtifactImportanceScore = 0.0
    retention_score: ArtifactRetentionScore = 0.0
    privacy_tags: list[ArtifactPrivacyTag] = field(default_factory=list)
    training_eligibility: ArtifactTrainingEligibility = ArtifactTrainingEligibility.REVIEW
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryEntry:
    """Single source of truth for memory entries."""

    id: str
    content: str
    embedding: EmbeddingVector | None = None
    memory_type: MemoryType = MemoryType.EPISODIC
    namespace: MemoryNamespace = MemoryNamespace.LONG_TERM
    status: MemoryStatus = MemoryStatus.ACTIVE
    priority: MemoryPriority = MemoryPriority.MEDIUM
    visibility: MemoryVisibility = MemoryVisibility.PRIVATE
    timestamp: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime | None = None
    access_count: int = 0
    expires_at: datetime | None = None
    ttl_seconds: float | None = None
    importance: float = 5.0
    confidence: float = 1.0
    relevance: float = 0.0
    quality: float = 1.0
    metadata: MemoryMetadata | None = None
    summary: str | None = None
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    version: int = 1
    parent_id: str | None = None

    def __post_init__(self):
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
        if isinstance(self.updated_at, str):
            self.updated_at = datetime.fromisoformat(self.updated_at)
        if self.expires_at is None and self.ttl_seconds is not None:
            self.expires_at = self.created_at + timedelta(seconds=self.ttl_seconds)
        self.importance = max(1.0, min(10.0, self.importance))
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.relevance = max(0.0, min(1.0, self.relevance))
        self.quality = max(0.0, min(1.0, self.quality))

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(tz=timezone.utc) > self.expires_at

    def update_access(self) -> None:
        self.last_accessed = datetime.now(tz=timezone.utc)
        self.access_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "embedding": self.embedding,
            "memory_type": self.memory_type.value,
            "namespace": self.namespace.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "visibility": self.visibility.value,
            "timestamp": self.timestamp.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "access_count": self.access_count,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "ttl_seconds": self.ttl_seconds,
            "importance": self.importance,
            "confidence": self.confidence,
            "relevance": self.relevance,
            "quality": self.quality,
            "metadata": self.metadata.__dict__ if self.metadata else None,
            "summary": self.summary,
            "keywords": self.keywords,
            "entities": self.entities,
            "version": self.version,
            "parent_id": self.parent_id,
        }


@dataclass
class MemoryQuery:
    """Unified memory query structure with explicit session scope."""

    text: str | None = None
    embedding: EmbeddingVector | None = None
    memory_types: list[MemoryType] | None = None
    namespaces: list[MemoryNamespace] | None = None
    statuses: list[MemoryStatus] | None = None
    tags_any: list[str] | None = None
    tags_all: list[str] | None = None
    keywords: list[str] | None = None
    since: datetime | None = None
    until: datetime | None = None
    recency_boost: float = 0.0
    min_importance: float | None = None
    min_confidence: float | None = None
    min_quality: float | None = None
    top_k: int = 10
    offset: int = 0
    include_expired: bool = False
    tenant_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    rerank: bool = False
    diversity_weight: float = 0.0


@dataclass
class MemoryQueryResult:
    """Result of a memory query."""

    memories: list[MemoryEntry]
    total_found: int
    query_time_ms: float
    query: MemoryQuery
    strategy_used: str | None = None
    by_type: dict[MemoryType, int] = field(default_factory=dict)
    by_namespace: dict[MemoryNamespace, int] = field(default_factory=dict)
    avg_relevance: float = 0.0
    truncated: bool = False


def make_memory_id(prefix: str = "mem") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def decay_score(
    base_score: float,
    age_seconds: float,
    decay_lambda: float = 0.0001,
) -> float:
    import math

    return base_score * math.exp(-decay_lambda * age_seconds)


def ttl_to_expires(ttl_seconds: float) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(seconds=ttl_seconds)


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_memory_entry(
    content: str,
    *,
    memory_type: MemoryType = MemoryType.EPISODIC,
    namespace: MemoryNamespace = MemoryNamespace.LONG_TERM,
    importance: float = 5.0,
    tenant_id: str = "",
    user_id: str = "system",
    **kwargs,
) -> MemoryEntry:
    """Create a scoped memory entry; implicit/default tenants are forbidden."""

    resolved_tenant = str(tenant_id or "").strip()
    if not resolved_tenant or resolved_tenant == "default":
        raise ValueError("create_memory_entry requires explicit non-default tenant_id")
    metadata = MemoryMetadata(
        tenant_id=resolved_tenant,
        user_id=user_id,
    )
    return MemoryEntry(
        id=make_memory_id(),
        content=content,
        memory_type=memory_type,
        namespace=namespace,
        importance=importance,
        metadata=metadata,
        **kwargs,
    )


DEFAULT_DECAY_LAMBDA = 0.0001
DEFAULT_TOP_K = 10
DEFAULT_IMPORTANCE = 5.0
DEFAULT_CONFIDENCE = 1.0
MAX_CONTENT_LENGTH = 10000
MAX_EMBEDDING_DIM = 4096
MAX_TAGS = 50
MAX_KEYWORDS = 100
TTL_EPHEMERAL = 3600
TTL_SHORT_TERM = 86400
TTL_LONG_TERM = 2592000
TTL_PERSISTENT = None


__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_DECAY_LAMBDA",
    "DEFAULT_IMPORTANCE",
    "DEFAULT_TOP_K",
    "MAX_CONTENT_LENGTH",
    "MAX_EMBEDDING_DIM",
    "MAX_KEYWORDS",
    "MAX_TAGS",
    "TTL_EPHEMERAL",
    "TTL_LONG_TERM",
    "TTL_PERSISTENT",
    "TTL_SHORT_TERM",
    "ArtifactImportanceScore",
    "ArtifactPrivacyTag",
    "ArtifactRetentionScore",
    "ArtifactSourceTier",
    "ArtifactTrainingEligibility",
    "ArtifactType",
    "EmbeddingVector",
    "ImportanceLevel",
    "JSONLike",
    "MemoryEntry",
    "MemoryMetadata",
    "MemoryNamespace",
    "MemoryPriority",
    "MemoryQuery",
    "MemoryQueryResult",
    "MemoryStatus",
    "MemoryType",
    "MemoryVisibility",
    "RecallNamespace",
    "RecallPriority",
    "RecallStatus",
    "RecallType",
    "RecallVisibility",
    "RuntimeMemoryArtifact",
    "clamp",
    "create_memory_entry",
    "decay_score",
    "make_memory_id",
    "now_utc",
    "ttl_to_expires",
]
