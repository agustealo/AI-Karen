"""
Cognitive Memory Types for AI-Karen

Extends the base memory types with 12 cognitive memory systems:
1. WorkingMemory: current mental workspace
2. EpisodicMemory: specific interactions and experiences
3. SemanticMemory: durable facts and generalized knowledge
4. AutobiographicalMemory: Karen-user history and meaningful shared events
5. PreferenceMemory: likes, dislikes, styles, recurring choices
6. ProceduralMemory: successful ways of doing things
7. ProspectiveMemory: intentions, commitments, unfinished work
8. RelationalMemory: people, projects, objects and how they connect
9. TemporalMemory: when something was true and for how long
10. SalienceMemory: importance, surprise, emotional relevance, consequences
11. BeliefMemory: claims with confidence and evidence
12. MetaMemory: what Karen knows, doubts, forgot, or needs to verify

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ===================================
# COGNITIVE MEMORY TYPE ENUM
# ===================================
from enum import Enum
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.contracts import (
    MemoryClaim,
    ProspectiveMemory,
    RecallScoreComponents,
    RelationshipModel,
    SalienceScore,
    SelfModel,
    UserModel,
)

from .base import (
    MemoryEntry,
    MemoryNamespace,
    MemoryPriority,
    MemoryStatus,
    MemoryVisibility,
)
from .base import (
    MemoryType as BaseMemoryType,
)


class CognitiveMemoryType(str, Enum):
    """12 cognitive memory systems."""
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    AUTOBIOGRAPHICAL = "autobiographical"
    PREFERENCE = "preference"
    PROCEDURAL = "procedural"
    PROSPECTIVE = "prospective"
    RELATIONAL = "relational"
    TEMPORAL = "temporal"
    SALIENCE = "salience"
    BELIEF = "belief"
    META = "meta"


# ===================================
# COGNITIVE MEMORY ENTRY
# ===================================

@dataclass
class CognitiveMemoryEntry:
    """
    Extended memory entry with cognitive metadata.
    """
    base_entry: MemoryEntry
    cognitive_type: CognitiveMemoryType = CognitiveMemoryType.EPISODIC
    salience: SalienceScore | None = None
    claim: MemoryClaim | None = None
    associations: list[str] = field(default_factory=list)  # IDs of associated memories
    activation: float = 0.0  # Current activation level (for spreading activation)
    repetition_count: int = 0
    last_activation: datetime | None = None
    temporal_valid_from: datetime | None = None
    temporal_valid_until: datetime | None = None
    is_consolidated: bool = False
    consolidation_source: str | None = None  # ID of episode that consolidated this
    prospective: ProspectiveMemory | None = None
    self_model: SelfModel | None = None
    user_model: UserModel | None = None
    relationship: RelationshipModel | None = None
    meta_knowledge: dict[str, Any] | None = None  # What Karen knows about this memory


# ===================================
# MEMORY CONTEXT
# ===================================

@dataclass
class MemoryContext:
    """
    Context for memory operations.
    """
    tenant_id: str
    user_id: str
    conversation_id: str | None = None
    session_id: str | None = None
    current_goals: list[str] = field(default_factory=list)
    active_intentions: list[ProspectiveMemory] = field(default_factory=list)
    relationship_context: RelationshipModel | None = None
    user_context: UserModel | None = None
    self_context: SelfModel | None = None


# ===================================
# ASSOCIATIVE ACTIVATION
# ===================================

@dataclass
class AssociativeActivation:
    """
    Result of spreading activation from a query.
    """
    source_concept: str
    activated_memories: list[str] = field(default_factory=list)  # Memory IDs
    activation_strengths: dict[str, float] = field(default_factory=dict)
    propagation_depth: int = 0
    total_activation: float = 0.0


# ===================================
# REFLECTION CANDIDATE
# ===================================

@dataclass
class ReflectionCandidate:
    """
    Candidate insight derived from reflection.
    """
    source_episodes: list[str] = field(default_factory=list)
    candidate_claim: MemoryClaim | None = None
    evidence_count: int = 0
    confidence: float = 0.0
    promotion_status: str = "pending"  # pending, promoted, deferred, rejected
    rejection_reason: str | None = None
