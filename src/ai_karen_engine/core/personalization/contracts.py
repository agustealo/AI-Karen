"""Personalization domain contracts for AI-Karen.

Personalization owns user/self/relationship models and preferences. The richer
cognitive goal lifecycle is owned by personalization/goals.GoalState; this
module keeps UserGoalStatus only as a legacy compatibility vocabulary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _require_tenant(tenant_id: str, contract: str) -> None:
    if not tenant_id or tenant_id == "default":
        raise ValueError(f"{contract} requires an explicit tenant_id")


class PreferenceCategory(str, Enum):
    COMMUNICATION = "communication"
    WORKFLOW = "workflow"
    TOOL = "tool"
    MODEL_LOCALITY = "model_locality"
    OUTPUT_FORMAT = "output_format"
    AUTOMATION = "automation"
    INTERACTION = "interaction"
    DOMAIN = "domain"
    RISK = "risk"
    PRIVACY = "privacy"


class PreferenceStability(str, Enum):
    SESSION = "session"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    DURABLE = "durable"


class PreferenceState(str, Enum):
    OBSERVED = "observed"
    TENTATIVE = "tentative"
    ESTABLISHED = "established"
    STABLE = "stable"
    CONTRADICTED = "contradicted"
    DECAYING = "decaying"
    RETIRED = "retired"


class PreferenceScope(str, Enum):
    GLOBAL = "global"
    DOMAIN = "domain"
    PROJECT = "project"
    CONVERSATION = "conversation"
    SESSION = "session"
    TASK_TYPE = "task_type"


class PreferenceEvidenceSourceType(str, Enum):
    EXPLICIT_USER_STATEMENT = "explicit_user_statement"
    USER_CORRECTION = "user_correction"
    REPEATED_BEHAVIOR = "repeated_behavior"
    TOOL_SELECTION = "tool_selection"
    OUTPUT_EDIT = "output_edit"
    TASK_OUTCOME = "task_outcome"
    SYSTEM_INFERENCE = "system_inference"


class PreferenceDriftState(str, Enum):
    STABLE = "stable"
    WATCH = "watch"
    DRIFTING = "drifting"
    CHANGED = "changed"
    UNKNOWN = "unknown"


# Compatibility alias only. Adaptive/drift owns generic drift semantics.
# Sunset: remove DriftState alias after personalization callers migrate.
DriftState = PreferenceDriftState


class UserGoalStatus(str, Enum):
    """Legacy goal status vocabulary.

    Canonical cognitive goal lifecycle: personalization/goals.GoalState.
    Sunset: remove after UserGoal compatibility adapters are retired.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class UserModelHealth(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ModelPropertyStatus(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    OBSERVED = "observed"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    STALE = "stale"
    RETRACTED = "retracted"


class EvidenceStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    STALE = "stale"


class IdentityDomain(str, Enum):
    CAPABILITY = "capability"
    LIMITATION = "limitation"
    PRINCIPLE = "principle"
    PREFERENCE = "preference"
    PROJECT = "project"
    SKILL = "skill"
    RESOURCE = "resource"


class RelationshipType(str, Enum):
    PROFESSIONAL = "professional"
    COLLABORATIVE = "collaborative"
    MENTORSHIP = "mentorship"
    SERVICE = "service"
    PERSONAL = "personal"


class InteractionNormType(str, Enum):
    RESPONSE_STYLE = "response_style"
    AVAILABILITY = "availability"
    FEEDBACK_PREFERENCE = "feedback_preference"
    TOOL_USAGE = "tool_usage"
    COMMUNICATION_CHANNEL = "communication_channel"


class CommitmentType(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    RECURRING = "recurring"
    ONE_SHOT = "one_shot"


class CapabilityBeliefType(str, Enum):
    STRENGTH = "strength"
    LIMITATION = "limitation"
    EMERGING = "emerging"
    DEGRADED = "degraded"


@dataclass
class Provenance:
    source: str
    confidence: float
    evidence_refs: List[str]
    first_observed_at: datetime
    last_confirmed_at: Optional[datetime]
    valid_from: datetime
    valid_until: Optional[datetime]
    supersedes: Optional[str]
    status: ModelPropertyStatus

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.evidence_refs = list(self.evidence_refs)
        self.first_observed_at = _utc(self.first_observed_at)  # type: ignore[assignment]
        self.last_confirmed_at = _utc(self.last_confirmed_at)
        self.valid_from = _utc(self.valid_from)  # type: ignore[assignment]
        self.valid_until = _utc(self.valid_until)


@dataclass
class ModelEvidence:
    evidence_id: str
    source: str
    evidence_type: str
    content_ref: str
    observed_at: datetime
    confidence: float
    event_time: datetime | None = None
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.observed_at = _utc(self.observed_at)  # type: ignore[assignment]
        self.event_time = _utc(self.event_time)


@dataclass
class ModelRevision:
    revision_id: str
    property_key: str
    model_type: str
    old_value: Any
    new_value: Any
    old_status: ModelPropertyStatus
    new_status: ModelPropertyStatus
    reason: str
    evidence_refs: List[str]
    revised_at: datetime
    revised_by: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentityFacet:
    facet_id: str
    domain: IdentityDomain
    key: str
    value: Any
    description: str
    provenance: Provenance
    is_limitation: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityBelief:
    belief_id: str
    capability: str
    belief_type: CapabilityBeliefType
    description: str
    provenance: Provenance
    evidence_refs: List[str]
    is_self_reference: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SelfModel:
    model_id: str
    tenant_id: str
    identity_facets: List[IdentityFacet]
    capability_beliefs: List[CapabilityBelief]
    principles: List[IdentityFacet]
    limits: List[IdentityFacet]
    confidence_summary: Dict[str, "ConfidenceState"]
    created_at: datetime
    updated_at: datetime
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "SelfModel")


@dataclass
class PreferenceSignal:
    signal_id: str
    key: str
    value: Any
    polarity: str
    provenance: Provenance
    scope: PreferenceScope
    category: PreferenceCategory
    stability: PreferenceStability
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserGoalModelState:
    """User-model projection of a goal, not the canonical GoalState lifecycle."""

    goal_id: str
    description: str
    status: UserGoalStatus
    provenance: Provenance
    scope: PreferenceScope
    started_at: datetime
    target_date: Optional[datetime] = None
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserModel:
    model_id: str
    user_id: str
    tenant_id: str
    preference_signals: List[PreferenceSignal]
    behavior_patterns: List["BehaviorPattern"]
    goals: List[UserGoalModelState]
    skills: List[IdentityFacet]
    projects: List[str]
    confidence_summary: Dict[str, "ConfidenceState"]
    created_at: datetime
    updated_at: datetime
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "UserModel")


@dataclass
class RelationshipContext:
    context_id: str
    relationship_type: RelationshipType
    key: str
    value: Any
    provenance: Provenance
    shared_projects: List[str]
    working_rhythm: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InteractionPattern:
    pattern_id: str
    pattern_type: InteractionNormType
    description: str
    confidence: float
    provenance: Provenance
    observed_count: int
    first_seen: datetime
    last_seen: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.observed_count = max(0, self.observed_count)


@dataclass
class CommitmentState:
    commitment_id: str
    commitment_type: CommitmentType
    description: str
    parties: List[str]
    provenance: Provenance
    started_at: datetime
    target_date: Optional[datetime] = None
    status: UserGoalStatus = UserGoalStatus.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationshipModel:
    model_id: str
    tenant_id: str
    user_id: str
    relationship_type: RelationshipType
    shared_history: List[str]
    working_patterns: List[InteractionPattern]
    active_commitments: List[CommitmentState]
    relationship_context: List[RelationshipContext]
    confidence_summary: Dict[str, "ConfidenceState"]
    created_at: datetime
    updated_at: datetime
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "RelationshipModel")


@dataclass
class ConfidenceState:
    property_key: str
    model_type: str
    confidence: float
    evidence_count: int
    contradiction_count: int
    last_updated: datetime
    trend: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.evidence_count = max(0, self.evidence_count)
        self.contradiction_count = max(0, self.contradiction_count)


@dataclass
class PreferenceEvidence:
    evidence_id: str
    preference_key: str
    source_type: PreferenceEvidenceSourceType
    source_ref: Optional[str]
    observed_value: Any
    polarity: str
    confidence: float
    observed_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class PreferenceContradiction:
    contradiction_id: str
    preference_id: str
    user_id: str
    tenant_id: str
    old_value: Any
    new_value: Any
    old_state: PreferenceState
    new_state: PreferenceState
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "PreferenceContradiction")


@dataclass
class PreferenceRecord:
    preference_id: str
    user_id: str
    tenant_id: str
    key: str
    value: Any
    confidence: float
    stability: PreferenceStability
    state: PreferenceState
    evidence_count: int
    contradiction_count: int
    first_observed_at: datetime
    last_observed_at: datetime
    last_confirmed_at: Optional[datetime]
    source_types: List[str]
    scope: PreferenceScope
    version: int
    category: PreferenceCategory
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "PreferenceRecord")
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.evidence_count = max(0, self.evidence_count)
        self.contradiction_count = max(0, self.contradiction_count)
        self.version = max(1, self.version)


@dataclass
class BehaviorPattern:
    pattern_id: str
    user_id: str
    tenant_id: str
    pattern_type: str
    context_signature: str
    observation_count: int
    confidence: float
    first_seen: datetime
    last_seen: datetime
    recurrence: str
    stability: PreferenceStability
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "BehaviorPattern")
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.observation_count = max(0, self.observation_count)


@dataclass
class UserGoal:
    """Legacy persistence-neutral goal projection.

    New cognition should convert this to personalization/goals.Goal.
    """

    goal_id: str
    user_id: str
    tenant_id: str
    description: str
    scope: PreferenceScope
    status: UserGoalStatus
    confidence: float
    evidence: List[str]
    started_at: datetime
    last_observed_at: datetime
    target_date: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "UserGoal")
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class CurrentUserState:
    user_id: str
    tenant_id: str
    current_project: Optional[str] = None
    current_objective: Optional[str] = None
    recent_topic: Optional[str] = None
    temporary_preferences: Dict[str, Any] = field(default_factory=dict)
    active_workflow: Optional[str] = None
    recent_corrections: List[str] = field(default_factory=list)
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_tenant(self.tenant_id, "CurrentUserState")


@dataclass
class UserStateSnapshot:
    user_id: str
    tenant_id: str
    current_state: CurrentUserState
    stable_preferences: List[PreferenceRecord]
    tentative_preferences: List[PreferenceRecord]
    behavior_patterns: List[BehaviorPattern]
    active_goals: List[UserGoal]
    confidence_summary: Dict[str, float]
    generated_at: datetime
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedPreferences:
    user_id: str
    tenant_id: str
    task_context: Dict[str, Any]
    resolved: Dict[str, Any]
    confidence: float
    applied_scope: PreferenceScope
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserModelHealthStatus:
    repository: UserModelHealth
    memory_integration: UserModelHealth
    queue: UserModelHealth
    snapshot_cache: UserModelHealth
    evidence_processor: UserModelHealth
    overall: UserModelHealth
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PreferenceCandidate:
    candidate_id: str
    user_id: str
    tenant_id: str
    key: str
    value: Any
    category: PreferenceCategory
    scope: PreferenceScope
    stability: PreferenceStability
    source_type: PreferenceEvidenceSourceType
    source_ref: Optional[str]
    confidence: float
    polarity: str
    text_evidence: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BehaviorCandidate:
    candidate_id: str
    user_id: str
    tenant_id: str
    pattern_type: str
    context_signature: str
    observation: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


def make_preference_id() -> str:
    return f"pref_{uuid.uuid4().hex[:16]}"


def make_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex[:16]}"


def make_contradiction_id() -> str:
    return f"contra_{uuid.uuid4().hex[:16]}"


def make_pattern_id() -> str:
    return f"pat_{uuid.uuid4().hex[:16]}"


def make_goal_id() -> str:
    return f"goal_{uuid.uuid4().hex[:16]}"


def make_candidate_id() -> str:
    return f"cand_{uuid.uuid4().hex[:16]}"


__all__ = [
    "BehaviorCandidate",
    "BehaviorPattern",
    "CapabilityBelief",
    "CapabilityBeliefType",
    "CommitmentState",
    "CommitmentType",
    "ConfidenceState",
    "CurrentUserState",
    "DriftState",
    "EvidenceStatus",
    "IdentityDomain",
    "IdentityFacet",
    "InteractionNormType",
    "InteractionPattern",
    "ModelEvidence",
    "ModelPropertyStatus",
    "ModelRevision",
    "PreferenceCandidate",
    "PreferenceCategory",
    "PreferenceContradiction",
    "PreferenceDriftState",
    "PreferenceEvidence",
    "PreferenceEvidenceSourceType",
    "PreferenceRecord",
    "PreferenceScope",
    "PreferenceSignal",
    "PreferenceStability",
    "PreferenceState",
    "Provenance",
    "RelationshipContext",
    "RelationshipModel",
    "RelationshipType",
    "ResolvedPreferences",
    "SelfModel",
    "UserGoal",
    "UserGoalModelState",
    "UserGoalStatus",
    "UserModel",
    "UserModelHealth",
    "UserModelHealthStatus",
    "UserStateSnapshot",
    "make_candidate_id",
    "make_contradiction_id",
    "make_evidence_id",
    "make_goal_id",
    "make_pattern_id",
    "make_preference_id",
]
