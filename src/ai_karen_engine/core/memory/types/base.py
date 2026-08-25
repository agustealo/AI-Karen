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
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# ===================================
# ENUMS AND CLASSIFICATIONS
# ===================================

class MemoryType(str, Enum):
    """
    Tri-partite memory classification (HippoRAG-inspired).

    Based on neuroscience principles and memory research:
    - Episodic: Time-stamped experiences and interactions
    - Semantic: Distilled facts and knowledge
    - Procedural: Tool usage patterns and workflows
    """
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryNamespace(str, Enum):
    """
    Memory tier/duration classification.

    Maps to:
    - RecallNamespace from recalls module
    - Memory tiers from research papers
    """
    SHORT_TERM = "short_term"      # Working memory (<1 hour)
    LONG_TERM = "long_term"        # Persistent memory (days to months)
    PERSISTENT = "persistent"      # Never expires (facts, critical knowledge)
    EPHEMERAL = "ephemeral"        # Temporary (current session only)


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
    ACTIVE = "active"              # Currently accessible
    CONSOLIDATING = "consolidating"  # Being promoted (episodic → semantic)
    ARCHIVED = "archived"          # Soft-deleted, retained for audit
    EXPIRED = "expired"            # Hard-deleted after retention period
    PENDING = "pending"            # Not yet committed


class MemoryPriority(str, Enum):
    """
    Memory priority for retrieval and consolidation.

    Maps to RecallPriority from recalls module.
    """
    CRITICAL = "critical"   # 9-10 importance
    HIGH = "high"           # 7-8 importance
    MEDIUM = "medium"       # 4-6 importance
    LOW = "low"             # 2-3 importance
    MINIMAL = "minimal"     # 0-1 importance


class MemoryVisibility(str, Enum):
    """
    Memory visibility/access control.

    Maps to RecallVisibility from recalls module.
    """
    PUBLIC = "public"       # Accessible to all users
    PRIVATE = "private"     # User-specific
    SHARED = "shared"       # Shared with specific users/groups
    SYSTEM = "system"       # System-level memories


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


# ===================================
# TYPE ALIASES
# ===================================

# Embedding vector (typically 384, 768, or 1536 dimensions)
EmbeddingVector = List[float]
ArtifactImportanceScore = float
ArtifactRetentionScore = float

# Legacy recall aliases used by the migration layer.
RecallNamespace = MemoryNamespace
RecallPriority = MemoryPriority
RecallStatus = MemoryStatus
RecallVisibility = MemoryVisibility

# JSON-like metadata
JSONLike = Union[Dict[str, Any], List[Any], str, int, float, bool, None]


# ===================================
# METADATA STRUCTURES
# ===================================

@dataclass
class MemoryMetadata:
    """
    Metadata for memory entries.

    Unified structure combining metadata from all memory systems.
    """
    # Tenant/User identification
    tenant_id: str
    user_id: str
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None

    # Source and provenance
    source: str = "user"  # user|ai|system|tool|consolidation
    created_by: Optional[str] = None  # Agent/process that created this

    # Classification
    tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)

    # Context and relationships
    context: Dict[str, Any] = field(default_factory=dict)
    related_memories: List[str] = field(default_factory=list)  # IDs of related memories

    # Additional metadata
    custom: Dict[str, Any] = field(default_factory=dict)  # Extensible custom fields


@dataclass
class RuntimeMemoryArtifact:
    """Normalized artifact exported from runtime memory to EchoCore."""
    artifact_id: str
    artifact_type: ArtifactType
    source_tier: ArtifactSourceTier
    user_id: str
    tenant_id: Optional[str]
    session_id: Optional[str]
    thread_id: Optional[str]
    content: Dict[str, Any]
    importance_score: ArtifactImportanceScore = 0.0
    retention_score: ArtifactRetentionScore = 0.0
    privacy_tags: List[ArtifactPrivacyTag] = field(default_factory=list)
    training_eligibility: ArtifactTrainingEligibility = ArtifactTrainingEligibility.REVIEW
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===================================
# CORE MEMORY ENTRY
# ===================================

@dataclass
class MemoryEntry:
    """
    Unified Memory Entry.

    Consolidates:
    - MemoryEntry from neuro_vault
    - RecallItem from recalls
    - Memory types from existing memory system

    This is the single source of truth for all memory entries.
    """
    # === Core Identity ===
    id: str
    content: str  # Main text content
    embedding: Optional[EmbeddingVector] = None

    # === Classification ===
    memory_type: MemoryType = MemoryType.EPISODIC
    namespace: MemoryNamespace = MemoryNamespace.LONG_TERM
    status: MemoryStatus = MemoryStatus.ACTIVE
    priority: MemoryPriority = MemoryPriority.MEDIUM
    visibility: MemoryVisibility = MemoryVisibility.PRIVATE

    # === Temporal Information ===
    timestamp: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: Optional[datetime] = None
    access_count: int = 0

    # === Lifecycle Management ===
    expires_at: Optional[datetime] = None
    ttl_seconds: Optional[float] = None  # Time-to-live in seconds

    # === Scoring and Relevance ===
    importance: float = 5.0      # 1-10 scale
    confidence: float = 1.0      # 0-1 scale (certainty of content)
    relevance: float = 0.0       # Query-specific relevance (computed during retrieval)
    quality: float = 1.0         # 0-1 scale (quality of memory)

    # === Metadata ===
    metadata: Optional[MemoryMetadata] = None

    # === Optional Fields ===
    summary: Optional[str] = None  # Brief summary of content
    keywords: List[str] = field(default_factory=list)  # Extracted keywords
    entities: List[str] = field(default_factory=list)  # Named entities

    # === Version Control ===
    version: int = 1
    parent_id: Optional[str] = None  # For memory updates/consolidation

    def __post_init__(self):
        """Validate and normalize fields after initialization."""
        # Ensure timestamps are datetime objects
        if isinstance(self.timestamp, str):
            self.timestamp = datetime.fromisoformat(self.timestamp)
        if isinstance(self.created_at, str):
            self.created_at = datetime.fromisoformat(self.created_at)
        if isinstance(self.updated_at, str):
            self.updated_at = datetime.fromisoformat(self.updated_at)

        # Compute expires_at from ttl_seconds if not set
        if self.expires_at is None and self.ttl_seconds is not None:
            self.expires_at = self.created_at + timedelta(seconds=self.ttl_seconds)

        # Clamp scores to valid ranges
        self.importance = max(1.0, min(10.0, self.importance))
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.relevance = max(0.0, min(1.0, self.relevance))
        self.quality = max(0.0, min(1.0, self.quality))

    def is_expired(self) -> bool:
        """Check if memory has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def update_access(self) -> None:
        """Update access tracking."""
        self.last_accessed = datetime.utcnow()
        self.access_count += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
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


# ===================================
# QUERY STRUCTURES
# ===================================

@dataclass
class MemoryQuery:
    """
    Unified memory query structure.

    Consolidates query types from all memory systems.
    """
    # === Query Content ===
    text: Optional[str] = None  # Text query
    embedding: Optional[EmbeddingVector] = None  # Vector query

    # === Filters ===
    memory_types: Optional[List[MemoryType]] = None
    namespaces: Optional[List[MemoryNamespace]] = None
    statuses: Optional[List[MemoryStatus]] = None

    # === Tags and Keywords ===
    tags_any: Optional[List[str]] = None  # Match any tag
    tags_all: Optional[List[str]] = None  # Match all tags
    keywords: Optional[List[str]] = None

    # === Temporal Filters ===
    since: Optional[datetime] = None  # Memories after this time
    until: Optional[datetime] = None  # Memories before this time
    recency_boost: float = 0.0  # Boost for recent memories (0-1)

    # === Scoring Filters ===
    min_importance: Optional[float] = None
    min_confidence: Optional[float] = None
    min_quality: Optional[float] = None

    # === Retrieval Parameters ===
    top_k: int = 10  # Number of results to return
    offset: int = 0  # Pagination offset
    include_expired: bool = False  # Include expired memories

    # === User/Tenant Scope ===
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None

    # === Advanced Options ===
    rerank: bool = False  # Apply reranking
    diversity_weight: float = 0.0  # 0-1, higher = more diverse results


@dataclass
class MemoryQueryResult:
    """
    Result of a memory query.

    Includes retrieved memories and metadata about the query.
    """
    memories: List[MemoryEntry]
    total_found: int  # Total matches (before pagination)
    query_time_ms: float  # Query execution time

    # === Query Metadata ===
    query: MemoryQuery
    strategy_used: Optional[str] = None  # E.g., "hybrid", "semantic", "temporal"

    # === Statistics ===
    by_type: Dict[MemoryType, int] = field(default_factory=dict)
    by_namespace: Dict[MemoryNamespace, int] = field(default_factory=dict)
    avg_relevance: float = 0.0
    truncated: bool = False  # True if results were limited


# ===================================
# HELPER FUNCTIONS
# ===================================

def make_memory_id(prefix: str = "mem") -> str:
    """Generate a unique memory ID."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to range."""
    return max(min_val, min(max_val, value))


def decay_score(
    base_score: float,
    age_seconds: float,
    decay_lambda: float = 0.0001
) -> float:
    """
    Apply exponential decay to score based on age.

    Args:
        base_score: Original score (0-1)
        age_seconds: Age of memory in seconds
        decay_lambda: Decay rate (default: 0.0001 ~= half-life of ~2 hours)

    Returns:
        Decayed score
    """
    import math
    return base_score * math.exp(-decay_lambda * age_seconds)


def ttl_to_expires(ttl_seconds: float) -> datetime:
    """Convert TTL in seconds to expiration datetime."""
    return datetime.utcnow() + timedelta(seconds=ttl_seconds)


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.utcnow()


def create_memory_entry(
    content: str,
    *,
    memory_type: MemoryType = MemoryType.EPISODIC,
    namespace: MemoryNamespace = MemoryNamespace.LONG_TERM,
    importance: float = 5.0,
    tenant_id: str = "default",
    user_id: str = "system",
    **kwargs
) -> MemoryEntry:
    """
    Factory function to create a memory entry with defaults.

    Args:
        content: Memory content (required)
        memory_type: Type of memory
        namespace: Memory tier
        importance: Importance score (1-10)
        tenant_id: Tenant ID
        user_id: User ID
        **kwargs: Additional MemoryEntry fields

    Returns:
        MemoryEntry instance
    """
    metadata = MemoryMetadata(
        tenant_id=tenant_id,
        user_id=user_id,
    )

    return MemoryEntry(
        id=make_memory_id(),
        content=content,
        memory_type=memory_type,
        namespace=namespace,
        importance=importance,
        metadata=metadata,
        **kwargs
    )


# ===================================
# CONSTANTS
# ===================================

# Default values
DEFAULT_DECAY_LAMBDA = 0.0001  # ~2 hour half-life
DEFAULT_TOP_K = 10
DEFAULT_IMPORTANCE = 5.0
DEFAULT_CONFIDENCE = 1.0

# Limits
MAX_CONTENT_LENGTH = 10000  # characters
MAX_EMBEDDING_DIM = 4096
MAX_TAGS = 50
MAX_KEYWORDS = 100

# TTL presets (in seconds)
TTL_EPHEMERAL = 3600  # 1 hour
TTL_SHORT_TERM = 86400  # 1 day
TTL_LONG_TERM = 2592000  # 30 days
TTL_PERSISTENT = None  # Never expires


__all__ = [
    # Enums
    "MemoryType",
    "MemoryNamespace",
    "ArtifactType",
    "ArtifactSourceTier",
    "ArtifactPrivacyTag",
    "ArtifactTrainingEligibility",
    "MemoryStatus",
    "MemoryPriority",
    "MemoryVisibility",
    "ImportanceLevel",
    "RecallType",
    "RecallNamespace",
    "RecallPriority",
    "RecallStatus",
    "RecallVisibility",
    # Types
    "EmbeddingVector",
    "ArtifactImportanceScore",
    "ArtifactRetentionScore",
    "JSONLike",
    # Data structures
    "MemoryMetadata",
    "RuntimeMemoryArtifact",
    "MemoryEntry",
    "MemoryQuery",
    "MemoryQueryResult",
    # Helper functions
    "make_memory_id",
    "clamp",
    "decay_score",
    "ttl_to_expires",
    "now_utc",
    "create_memory_entry",
    # Constants
    "DEFAULT_DECAY_LAMBDA",
    "DEFAULT_TOP_K",
    "DEFAULT_IMPORTANCE",
    "DEFAULT_CONFIDENCE",
    "MAX_CONTENT_LENGTH",
    "MAX_EMBEDDING_DIM",
    "MAX_TAGS",
    "MAX_KEYWORDS",
    "TTL_EPHEMERAL",
    "TTL_SHORT_TERM",
    "TTL_LONG_TERM",
    "TTL_PERSISTENT",
]
