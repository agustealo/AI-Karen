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
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.contracts import (
    MemoryClaim,
    ProspectiveMemory,
    RecallScoreComponents,
    SalienceScore,
    SelfModel,
    UserModel,
    RelationshipModel,
)
from ai_karen_engine.core.memory.types import (
    MemoryEntry,
    MemoryType as BaseMemoryType,
    MemoryStatus,
    MemoryPriority,
    MemoryVisibility,
    MemoryNamespace,
)


# ===================================
# COGNITIVE MEMORY TYPE ENUM
# ===================================

from enum import Enum


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
    salience: Optional[SalienceScore] = None
    claim: Optional[MemoryClaim] = None
    associations: List[str] = field(default_factory=list)  # IDs of associated memories
    activation: float = 0.0  # Current activation level (for spreading activation)
    repetition_count: int = 0
    last_activation: Optional[datetime] = None
    temporal_valid_from: Optional[datetime] = None
    temporal_valid_until: Optional[datetime] = None
    is_consolidated: bool = False
    consolidation_source: Optional[str] = None  # ID of episode that consolidated this
    prospective: Optional[ProspectiveMemory] = None
    self_model: Optional[SelfModel] = None
    user_model: Optional[UserModel] = None
    relationship: Optional[RelationshipModel] = None
    meta_knowledge: Optional[Dict[str, Any]] = None  # What Karen knows about this memory


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
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None
    current_goals: List[str] = field(default_factory=list)
    active_intentions: List[ProspectiveMemory] = field(default_factory=list)
    relationship_context: Optional[RelationshipModel] = None
    user_context: Optional[UserModel] = None
    self_context: Optional[SelfModel] = None


# ===================================
# ASSOCIATIVE ACTIVATION
# ===================================

@dataclass
class AssociativeActivation:
    """
    Result of spreading activation from a query.
    """
    source_concept: str
    activated_memories: List[str] = field(default_factory=list)  # Memory IDs
    activation_strengths: Dict[str, float] = field(default_factory=dict)
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
    source_episodes: List[str] = field(default_factory=list)
    candidate_claim: Optional[MemoryClaim] = None
    evidence_count: int = 0
    confidence: float = 0.0
    promotion_status: str = "pending"  # pending, promoted, deferred, rejected
    rejection_reason: Optional[str] = None
