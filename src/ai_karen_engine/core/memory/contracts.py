"""Cognitive memory contracts for AI-Karen.

Memory owns the canonical claim lifecycle, temporal validity, and durable
cognitive memory semantics. Concrete persistence, vector stores, caches, and
provider implementations remain outside Core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ClaimStatus(str, Enum):
    """Canonical epistemic lifecycle shared by memory and belief reasoning."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    USER_ASSERTED = "user_asserted"
    SUPPORTED = "supported"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    STALE = "stale"
    RETRACTED = "retracted"
    UNKNOWN = "unknown"


MemoryLifecycleState = ClaimStatus


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class MemoryClaim:
    """A durable memory claim with provenance, confidence, and temporal truth."""

    subject: str
    predicate: str
    object: Any
    confidence: float = 0.5
    provenance: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    asserted_at: datetime = field(default_factory=utc_now)
    observed_at: datetime | None = None
    event_time: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_confirmed: datetime | None = None
    superseded_at: datetime | None = None
    deleted_at: datetime | None = None
    contradiction_refs: list[str] = field(default_factory=list)
    supersedes: str | None = None
    status: ClaimStatus = ClaimStatus.OBSERVED
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
        for name in (
            "asserted_at",
            "observed_at",
            "event_time",
            "valid_from",
            "valid_until",
            "last_confirmed",
            "superseded_at",
            "deleted_at",
        ):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                setattr(self, name, value.replace(tzinfo=timezone.utc))

    def is_valid(self, at: datetime | None = None) -> bool:
        check_time = at or utc_now()
        if check_time.tzinfo is None:
            check_time = check_time.replace(tzinfo=timezone.utc)
        if self.deleted_at is not None:
            return False
        if self.valid_from and check_time < self.valid_from:
            return False
        if self.valid_until and check_time > self.valid_until:
            return False
        return self.status not in {
            ClaimStatus.SUPERSEDED,
            ClaimStatus.RETRACTED,
            ClaimStatus.STALE,
            ClaimStatus.CONTRADICTED,
        }

    def effective_confidence(self) -> float:
        penalty = 0.1 * len(self.contradiction_refs)
        return max(0.0, self.confidence - penalty)


@dataclass
class SalienceScore:
    """Multi-dimensional memory salience score."""

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
        return sum(
            [
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
            ]
        )


MemorySalience = SalienceScore


@dataclass
class SelfModel:
    """Karen's governed self-model without consciousness claims."""

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


@dataclass
class UserModel:
    """Evidence-backed user model; one event never silently becomes canon."""

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


@dataclass
class RelationshipModel:
    """Karen-user relationship continuity with evidence-backed shared history."""

    shared_projects: list[str] = field(default_factory=list)
    past_decisions: list[dict[str, Any]] = field(default_factory=list)
    interaction_style: dict[str, Any] = field(default_factory=dict)
    trust_relevant_facts: list[str] = field(default_factory=list)
    unresolved_threads: list[str] = field(default_factory=list)
    interaction_history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProspectiveMemory:
    """Future intention or commitment; scheduling remains Platform-owned."""

    intention: str
    trigger: dict[str, Any] = field(default_factory=dict)
    status: str = "open"
    priority: str = "medium"
    created_at: datetime = field(default_factory=utc_now)
    created_from: str | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryProcessingStage(str, Enum):
    ENCODE = "encode"
    ASSOCIATE = "associate"
    CONSOLIDATE = "consolidate"
    RECALL = "recall"
    RECONSOLIDATE = "reconsolidate"
    DECAY = "decay"
    FORGET = "forget"


@dataclass
class RecallScoreComponents:
    """Components of multi-factor NeuroRecall ranking."""

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
        positive = sum(
            [
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
            ]
        )
        negative = self.contradiction_penalty + self.staleness + self.interference
        return max(0.0, positive - negative)


__all__ = [
    "ClaimStatus",
    "MemoryClaim",
    "MemoryLifecycleState",
    "MemoryProcessingStage",
    "MemorySalience",
    "ProspectiveMemory",
    "RecallScoreComponents",
    "RelationshipModel",
    "SalienceScore",
    "SelfModel",
    "UserModel",
    "utc_now",
]
