"""
Cognitive Memory Contracts for AI-Karen

This module defines the core contracts for Karen's cognitive memory architecture:
- MemoryClaim: beliefs with confidence, provenance, temporal validity, contradictions
- SelfModel: Karen's identity and stable properties
- UserModel: learned user knowledge
- RelationshipModel: Karen↔User relationship history
- ProspectiveMemory: intentions and commitments
- SalienceScore: importance, novelty, surprise, goal relevance

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# ===================================
# MEMORY CLAIM
# ===================================

class ClaimStatus(str, Enum):
    """Status of a memory claim."""
    OBSERVED = "observed"
    INFERRED = "inferred"
    USER_ASSERTED = "user_asserted"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    STALE = "stale"
    RETRACTED = "retracted"


@dataclass
class MemoryClaim:
    """
    A memory claim with full provenance and uncertainty tracking.

    This is the fundamental unit of durable belief in Karen's cognitive system.
    """
    subject: str
    predicate: str
    object: Any
    confidence: float = 0.5
    provenance: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    asserted_at: datetime = field(default_factory=datetime.utcnow)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    last_confirmed: Optional[datetime] = None
    contradiction_refs: List[str] = field(default_factory=list)
    supersedes: Optional[str] = None
    status: ClaimStatus = ClaimStatus.OBSERVED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_valid(self, at: Optional[datetime] = None) -> bool:
        """Check if claim is valid at given time."""
        check_time = at or datetime.utcnow()
        if self.valid_from and check_time < self.valid_from:
            return False
        if self.valid_until and check_time > self.valid_until:
            return False
        return self.status not in {ClaimStatus.SUPERSEDED, ClaimStatus.RETRACTED, ClaimStatus.STALE}

    def effective_confidence(self) -> float:
        """Calculate effective confidence considering contradictions."""
        base = self.confidence
        penalty = 0.1 * len(self.contradiction_refs)
        return max(0.0, base - penalty)


# ===================================
# SALIENCE SCORING
# ===================================

@dataclass
class SalienceScore:
    """
    Multi-dimensional salience score for memory importance.

    Combines:
    - novelty: how new/unexpected is this
    - surprise: deviation from expectations
    - user_emphasis: explicit "remember this" signals
    - goal_relevance: alignment with current goals
    - consequence: stakes of the information
    - repetition: how often seen
    - relationship_relevance: importance to relationship
    - decision_importance: impact on decisions
    - error_significance: failures/errors are more salient
    - success_significance: successes are more salient
    """
    novelty: float = 0.0
    surprise: float = 0.0
    user_emphasis: float = 0.0
    goal_relevance: float = 0.0
    consequence: float = 0.0
    repetition: float = 0.0
    relationship_relevance: float = 0.0
    decision_importance: float = 0.0
    error_significance: float = 0.0
    success_significance: float = 0.0

    def total(self) -> float:
        """Compute total salience score."""
        return sum([
            self.novelty,
            self.surprise,
            self.user_emphasis,
            self.goal_relevance,
            self.consequence,
            self.repetition,
            self.relationship_relevance,
            self.decision_importance,
            self.error_significance,
            self.success_significance,
        ])


# ===================================
# SELF MODEL
# ===================================

@dataclass
class SelfModel:
    """
    Karen's governed model of itself.

    This provides continuity without pretending consciousness.
    """
    identity: Dict[str, Any] = field(default_factory=dict)
    stable_principles: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    capability_limits: Dict[str, str] = field(default_factory=dict)
    role_relationships: Dict[str, str] = field(default_factory=dict)
    learned_strategies: List[str] = field(default_factory=list)
    current_commitments: List[str] = field(default_factory=list)
    active_goals: List[str] = field(default_factory=list)
    confidence: float = 1.0
    significant_decisions: List[Dict[str, Any]] = field(default_factory=list)


# ===================================
# USER MODEL
# ===================================

@dataclass
class UserModel:
    """
    Karen's model of the user.

    Evidence-backed: no one-event canon.
    """
    explicit_preferences: Dict[str, Any] = field(default_factory=dict)
    inferred_preferences: Dict[str, float] = field(default_factory=dict)
    communication_patterns: Dict[str, Any] = field(default_factory=dict)
    projects: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
    relationships: Dict[str, Any] = field(default_factory=dict)
    routines: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    evolving_beliefs: List[MemoryClaim] = field(default_factory=list)


# ===================================
# RELATIONSHIP MODEL
# ===================================

@dataclass
class RelationshipModel:
    """
    Karen↔User relationship model.

    Tracks shared history and relationship-specific context.
    """
    shared_projects: List[str] = field(default_factory=list)
    past_decisions: List[Dict[str, Any]] = field(default_factory=list)
    interaction_style: Dict[str, Any] = field(default_factory=dict)
    trust_relevant_facts: List[str] = field(default_factory=list)
    unresolved_threads: List[str] = field(default_factory=list)
    interaction_history: List[Dict[str, Any]] = field(default_factory=list)


# ===================================
# PROSPECTIVE MEMORY
# ===================================

@dataclass
class ProspectiveMemory:
    """
    Future intention or commitment.

    Distinct from scheduler infrastructure (cron = PLATFORM).
    This is cognitive: remembering that there is unfinished business.
    """
    intention: str
    trigger: Dict[str, Any] = field(default_factory=dict)
    status: str = "open"  # open, completed, cancelled
    priority: str = "medium"  # low, medium, high, critical
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_from: Optional[str] = None  # conversation_id or source
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===================================
# MEMORY LIFECYCLE STATE
# ===================================

class MemoryLifecycleState(str, Enum):
    """States in the memory lifecycle."""
    PERCEIVE = "perceive"
    ENCODE = "encode"
    SCORE_SALIENCE = "score_salience"
    ASSOCIATE = "associate"
    STORE_EPISODE = "store_episode"
    REPLAY_REFLECT = "replay_reflect"
    CONSOLIDATE = "consolidate"
    GENERALIZE = "generalize"
    RETRIEVE = "retrieve"
    RECONSOLIDATE = "reconsolidate"
    DECAY_SUPERSEDE_FORGET = "decay_supersede_forget"


# ===================================
# RECALL SCORE COMPONENTS
# ===================================

@dataclass
class RecallScoreComponents:
    """
    Components of the multi-factor recall score.

    RecallScore =
        semantic_similarity
      + associative_activation
      + temporal_relevance
      + salience
      + relationship_relevance
      + current_goal_relevance
      + repetition_strength
      + causal_relevance
      + unresolved_intention_relevance
      + explicit_user_priority
      - contradiction_penalty
      - staleness
      - interference
    """
    semantic_similarity: float = 0.0
    associative_activation: float = 0.0
    temporal_relevance: float = 0.0
    salience: float = 0.0
    relationship_relevance: float = 0.0
    current_goal_relevance: float = 0.0
    repetition_strength: float = 0.0
    causal_relevance: float = 0.0
    unresolved_intention_relevance: float = 0.0
    explicit_user_priority: float = 0.0
    contradiction_penalty: float = 0.0
    staleness: float = 0.0
    interference: float = 0.0

    def total(self) -> float:
        """Compute total recall score."""
        positive = sum([
            self.semantic_similarity,
            self.associative_activation,
            self.temporal_relevance,
            self.salience,
            self.relationship_relevance,
            self.current_goal_relevance,
            self.repetition_strength,
            self.causal_relevance,
            self.unresolved_intention_relevance,
            self.explicit_user_priority,
        ])
        negative = sum([
            self.contradiction_penalty,
            self.staleness,
            self.interference,
        ])
        return max(0.0, positive - negative)
