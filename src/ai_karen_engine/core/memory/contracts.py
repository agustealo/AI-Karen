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
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# ===================================
# MEMORY CLAIM
# ===================================

class ClaimStatus(str, Enum):
    """Epistemic lifecycle state of a memory claim.

    Tracks the certainty and validity status of a claim as it moves
    through Karen's cognitive memory pipeline.

    OBSERVED       - directly captured from interaction
    INFERRED       - derived by Karen's reasoning
    USER_ASSERTED  - explicitly stated by the user
    VERIFIED       - confirmed by evidence or user
    DISPUTED       - conflicting claims exist
    SUPERSEDED     - replaced by a newer, more accurate claim
    STALE          - outdated (not yet retracted)
    RETRACTED      - explicitly withdrawn
    """
    OBSERVED = "observed"
    INFERRED = "inferred"
    USER_ASSERTED = "user_asserted"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    STALE = "stale"
    RETRACTED = "retracted"


MemoryLifecycleState = ClaimStatus


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
    provenance: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    asserted_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_confirmed: datetime | None = None
    contradiction_refs: list[str] = field(default_factory=list)
    supersedes: str | None = None
    status: ClaimStatus = ClaimStatus.OBSERVED
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid(self, at: datetime | None = None) -> bool:
        """Check if claim is valid at given time."""
        check_time = at or datetime.now(tz=timezone.utc)
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


MemorySalience = SalienceScore


# ===================================
# SELF MODEL
# ===================================

@dataclass
class SelfModel:
    """
    Karen's governed model of itself.

    This provides continuity without pretending consciousness.
    """
    identity: dict[str, Any] = field(default_factory=dict)
    stable_principles: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    capability_limits: dict[str, str] = field(default_factory=dict)
    role_relationships: dict[str, str] = field(default_factory=dict)
    learned_strategies: list[str] = field(default_factory=list)
    current_commitments: list[str] = field(default_factory=list)
    active_goals: list[str] = field(default_factory=list)
    confidence: float = 1.0
    significant_decisions: list[dict[str, Any]] = field(default_factory=list)


# ===================================
# USER MODEL
# ===================================

@dataclass
class UserModel:
    """
    Karen's model of the user.

    Evidence-backed: no one-event canon.
    """
    explicit_preferences: dict[str, Any] = field(default_factory=dict)
    inferred_preferences: dict[str, float] = field(default_factory=dict)
    communication_patterns: dict[str, Any] = field(default_factory=dict)
    projects: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    relationships: dict[str, Any] = field(default_factory=dict)
    routines: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    evolving_beliefs: list[MemoryClaim] = field(default_factory=list)


# ===================================
# RELATIONSHIP MODEL
# ===================================

@dataclass
class RelationshipModel:
    """
    Karen↔User relationship model.

    Tracks shared history and relationship-specific context.
    """
    shared_projects: list[str] = field(default_factory=list)
    past_decisions: list[dict[str, Any]] = field(default_factory=list)
    interaction_style: dict[str, Any] = field(default_factory=dict)
    trust_relevant_facts: list[str] = field(default_factory=list)
    unresolved_threads: list[str] = field(default_factory=list)
    interaction_history: list[dict[str, Any]] = field(default_factory=list)


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
    trigger: dict[str, Any] = field(default_factory=dict)
    status: str = "open"  # open, completed, cancelled
    priority: str = "medium"  # low, medium, high, critical
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_from: str | None = None  # conversation_id or source
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ===================================
# MEMORY LIFECYCLE STATE
# ===================================

class MemoryProcessingStage(str, Enum):
    """Stages in the memory processing pipeline.

    These describe the sequence of cognitive operations Karen's brain
    performs on a memory claim, from initial encoding to eventual forgetting.
    """
    ENCODE = "encode"
    ASSOCIATE = "associate"
    CONSOLIDATE = "consolidate"
    RECALL = "recall"
    RECONSOLIDATE = "reconsolidate"
    DECAY = "decay"
    FORGET = "forget"


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
