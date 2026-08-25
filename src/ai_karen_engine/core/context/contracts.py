from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContextKind(str, Enum):
    USER_PREFERENCE = "user_preference"
    MEMORY = "memory"
    GOAL = "goal"
    INTENTION = "intention"
    POLICY = "policy"
    TOOL = "tool"
    DOCUMENT = "document"
    SIGNAL = "signal"
    EVENT = "event"
    PROFILE = "profile"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


class ContextPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MINIMAL = "minimal"


class ContextTrustLevel(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    LOW_CONFIDENCE = "low_confidence"
    CONTRADICTED = "contradicted"


class ContextFreshness(str, Enum):
    REAL_TIME = "real_time"
    RECENT = "recent"
    SHORT_LIVED = "short_lived"
    LONG_LIVED = "long_lived"
    STALE = "stale"
    STATIC = "static"


class ContextReason(str, Enum):
    ACTIVE_GOAL = "active_goal"
    EXPLICIT_USER_FACT = "explicit_user_fact"
    HIGH_SALIENCE_MEMORY = "high_salience_memory"
    RECENT_RELEVANT = "recent_relevant"
    UNRESOLVED_INTENTION = "unresolved_intention"
    POLICY_REQUIREMENT = "policy_requirement"
    EXPLICIT_OVERRIDE = "explicit_override"
    STALE_FACT = "stale_fact"
    RECENT_IRRELEVANT = "recent_irrelevant"
    CONTRADICTED = "contradicted"
    INFERRED_ASSUMPTION = "inferred_assumption"
    CONVERSATIONAL_TRIVIA = "conversational_trivia"
    TOKEN_PRESSURE = "token_pressure"
    OMITTED = "omitted"
    SELECTED = "selected"
    CONFLICT = "conflict"


_PRIORITY_SCORE: dict[ContextPriority, int] = {
    ContextPriority.CRITICAL: 1000,
    ContextPriority.HIGH: 750,
    ContextPriority.MEDIUM: 500,
    ContextPriority.LOW: 250,
    ContextPriority.MINIMAL: 0,
}

_REASON_MODIFIER: dict[ContextReason, int] = {
    ContextReason.ACTIVE_GOAL: 300,
    ContextReason.EXPLICIT_USER_FACT: 250,
    ContextReason.HIGH_SALIENCE_MEMORY: 200,
    ContextReason.POLICY_REQUIREMENT: 200,
    ContextReason.UNRESOLVED_INTENTION: 150,
    ContextReason.RECENT_RELEVANT: 100,
    ContextReason.EXPLICIT_OVERRIDE: 100,
    ContextReason.CONVERSATIONAL_TRIVIA: -400,
    ContextReason.STALE_FACT: -500,
    ContextReason.RECENT_IRRELEVANT: -300,
    ContextReason.INFERRED_ASSUMPTION: -100,
    ContextReason.TOKEN_PRESSURE: -200,
    ContextReason.CONTRADICTED: -1000,
}

_FRESHNESS_MODIFIER: dict[ContextFreshness, int] = {
    ContextFreshness.REAL_TIME: 50,
    ContextFreshness.RECENT: 30,
    ContextFreshness.SHORT_LIVED: 10,
    ContextFreshness.LONG_LIVED: 20,
    ContextFreshness.STATIC: 5,
    ContextFreshness.STALE: -500,
}

_TRUST_MODIFIER: dict[ContextTrustLevel, int] = {
    ContextTrustLevel.EXPLICIT: 0,
    ContextTrustLevel.INFERRED: -20,
    ContextTrustLevel.ASSUMED: -50,
    ContextTrustLevel.LOW_CONFIDENCE: -80,
    ContextTrustLevel.CONTRADICTED: -1000,
}


@dataclass(slots=True)
class ContextBudget:
    max_items: int = 20
    max_tokens: int = 4096
    priority_floor: ContextPriority = ContextPriority.MINIMAL
    reserved_for_critical: int = 2
    requirement_limits: dict[str, int] = field(default_factory=dict)
    min_trust_level: ContextTrustLevel = ContextTrustLevel.LOW_CONFIDENCE

    def effective_capacity(self) -> int:
        return max(0, self.max_items - self.reserved_for_critical)
    
    def meets_priority_floor(self, priority: ContextPriority) -> bool:
        floor_order = [ContextPriority.MINIMAL, ContextPriority.LOW, ContextPriority.MEDIUM, 
                      ContextPriority.HIGH, ContextPriority.CRITICAL]
        try:
            return floor_order.index(priority) >= floor_order.index(self.priority_floor)
        except ValueError:
            return False


@dataclass(slots=True)
class ContextSource:
    kind: ContextKind
    reference: str = ""
    freshness: ContextFreshness = ContextFreshness.LONG_LIVED
    trust_level: ContextTrustLevel = ContextTrustLevel.EXPLICIT


@dataclass(slots=True)
class ContextConflict:
    with_candidate_id: str
    reason: str = ""
    severity: str = "medium"


@dataclass(slots=True)
class ContextOmission:
    reason: ContextReason
    detail: str = ""
    omitted_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContextCandidate:
    candidate_id: str
    kind: ContextKind
    content: str
    priority: ContextPriority = ContextPriority.MEDIUM
    reason: ContextReason = ContextReason.RECENT_RELEVANT
    trust_level: ContextTrustLevel = ContextTrustLevel.EXPLICIT
    freshness: ContextFreshness = ContextFreshness.LONG_LIVED
    source: ContextSource | None = None
    conflicts: list[ContextConflict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def score(self) -> int:
        base = _PRIORITY_SCORE.get(self.priority, 0)
        reason_mod = _REASON_MODIFIER.get(self.reason, 0)
        freshness_mod = _FRESHNESS_MODIFIER.get(self.freshness, 0)
        trust_mod = _TRUST_MODIFIER.get(self.trust_level, 0)
        return base + reason_mod + freshness_mod + trust_mod

    def is_selectable(self) -> bool:
        return self.trust_level != ContextTrustLevel.CONTRADICTED and self.freshness != ContextFreshness.STALE


@dataclass(slots=True)
class ContextRequirement:
    kind: ContextKind
    priority: ContextPriority = ContextPriority.MEDIUM
    reason: str = ""
    freshness: ContextFreshness = ContextFreshness.LONG_LIVED
    max_items: int = 3
    min_trust_level: ContextTrustLevel = ContextTrustLevel.EXPLICIT
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContextPlan:
    requirements: list[ContextRequirement] = field(default_factory=list)
    candidates: list[ContextCandidate] = field(default_factory=list)
    included: list[ContextCandidate] = field(default_factory=list)
    omitted: list[ContextOmission] = field(default_factory=list)
    conflicts: list[ContextConflict] = field(default_factory=list)
    budget: ContextBudget = field(default_factory=ContextBudget)
    explanation: str = ""
    trace_id: str = ""
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def select(self) -> list[ContextCandidate]:
        selected: list[ContextCandidate] = []
        seen_ids: set[str] = set()
        tokens_used = 0

        def sort_key(c: ContextCandidate) -> tuple[int, int, str]:
            return (-c.score(), len(c.conflicts), c.candidate_id)

        sorted_candidates = sorted(self.candidates, key=sort_key)

        for candidate in sorted_candidates:
            if candidate.candidate_id in seen_ids:
                continue
            if not candidate.is_selectable():
                continue
            if not self.budget.meets_priority_floor(candidate.priority):
                continue
            
            candidate_tokens = len(candidate.content)
            if tokens_used + candidate_tokens > self.budget.max_tokens:
                continue
            
            requirement_limit = self._get_requirement_limit(candidate)
            requirement_count = sum(1 for s in selected if s.kind == candidate.kind)
            if requirement_count >= requirement_limit:
                continue
            
            selected.append(candidate)
            seen_ids.add(candidate.candidate_id)
            tokens_used += candidate_tokens

        return selected

    def _get_requirement_limit(self, candidate: ContextCandidate) -> int:
        for req in self.requirements:
            if req.kind == candidate.kind:
                return req.max_items
        return self.budget.requirement_limits.get(candidate.kind.value, self.budget.max_items)

    def explain_selection(self, selected: list[ContextCandidate]) -> list[str]:
        explanations: list[str] = []
        for candidate in selected:
            explanations.append(
                f"selected {candidate.candidate_id} "
                f"priority={candidate.priority.value} "
                f"reason={candidate.reason.value} "
                f"trust={candidate.trust_level.value} "
                f"freshness={candidate.freshness.value} "
                f"score={candidate.score()}"
            )
        return explanations
