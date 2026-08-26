"""Cognitive memory contracts for AI-Karen.

Memory owns the canonical claim lifecycle and cognitive memory semantics.
Concrete persistence remains outside Core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ai_karen_engine.core.contracts.values import JsonMap, JsonValue


class ClaimStatus(str, Enum):
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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class MemoryClaim:
    subject: str
    predicate: str
    object: JsonValue
    tenant_id: str
    user_id: str | None = None
    confidence: float = 0.5
    provenance: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    asserted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("memory claim tenant_id must be explicit and non-default")
        self.asserted_at = _utc(self.asserted_at)
        for name in (
            "event_time",
            "valid_from",
            "valid_until",
            "last_confirmed",
            "superseded_at",
            "deleted_at",
        ):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, _utc(value))
        self.confidence = max(0.0, min(1.0, self.confidence))

    def is_valid(self, at: datetime | None = None) -> bool:
        check_time = _utc(at or datetime.now(timezone.utc))
        if self.valid_from and check_time < self.valid_from:
            return False
        if self.valid_until and check_time > self.valid_until:
            return False
        return self.status not in {
            ClaimStatus.SUPERSEDED,
            ClaimStatus.RETRACTED,
            ClaimStatus.STALE,
        }

    def effective_confidence(self) -> float:
        return max(0.0, min(1.0, self.confidence - 0.1 * len(self.contradiction_refs)))


@dataclass
class SalienceScore:
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
            (
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
            )
        )


MemorySalience = SalienceScore


@dataclass
class SelfModel:
    identity: JsonMap = field(default_factory=dict)
    stable_principles: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    capability_limits: dict[str, str] = field(default_factory=dict)
    role_relationships: dict[str, str] = field(default_factory=dict)
    learned_strategies: list[str] = field(default_factory=list)
    current_commitments: list[str] = field(default_factory=list)
    active_goals: list[str] = field(default_factory=list)
    confidence: float = 1.0
    significant_decisions: list[JsonMap] = field(default_factory=list)


@dataclass
class UserModel:
    explicit_preferences: JsonMap = field(default_factory=dict)
    inferred_preferences: dict[str, float] = field(default_factory=dict)
    communication_patterns: JsonMap = field(default_factory=dict)
    projects: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    relationships: JsonMap = field(default_factory=dict)
    routines: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    decisions: list[JsonMap] = field(default_factory=list)
    evolving_beliefs: list[MemoryClaim] = field(default_factory=list)


@dataclass
class RelationshipModel:
    shared_projects: list[str] = field(default_factory=list)
    past_decisions: list[JsonMap] = field(default_factory=list)
    interaction_style: JsonMap = field(default_factory=dict)
    trust_relevant_facts: list[str] = field(default_factory=list)
    unresolved_threads: list[str] = field(default_factory=list)
    interaction_history: list[JsonMap] = field(default_factory=list)


@dataclass
class ProspectiveMemory:
    intention: str
    tenant_id: str
    user_id: str | None = None
    trigger: JsonMap = field(default_factory=dict)
    status: str = "open"
    priority: str = "medium"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_from: str | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("prospective memory tenant_id must be explicit and non-default")


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
            (
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
            )
        )
        return max(
            0.0,
            positive - self.contradiction_penalty - self.staleness - self.interference,
        )


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
]
