"""
Personalization domain contracts for AI-Karen.

Defines the canonical data structures for user personalization:
preferences, behavior patterns, goals, snapshots, and evidence.
These are domain contracts, NOT persistence models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ===================================
# ENUMS
# ===================================

class PreferenceCategory(str, Enum):
    """Top-level preference taxonomy."""
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
    """How durable a preference is expected to be."""
    SESSION = "session"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"
    DURABLE = "durable"


class PreferenceState(str, Enum):
    """Lifecycle state of a preference record."""
    OBSERVED = "observed"
    TENTATIVE = "tentative"
    ESTABLISHED = "established"
    STABLE = "stable"
    CONTRADICTED = "contradicted"
    DECAYING = "decaying"
    RETIRED = "retired"


class PreferenceScope(str, Enum):
    """Applicability scope of a preference."""
    GLOBAL = "global"
    DOMAIN = "domain"
    PROJECT = "project"
    CONVERSATION = "conversation"
    SESSION = "session"
    TASK_TYPE = "task_type"


class PreferenceEvidenceSourceType(str, Enum):
    """Source of preference evidence."""
    EXPLICIT_USER_STATEMENT = "explicit_user_statement"
    USER_CORRECTION = "user_correction"
    REPEATED_BEHAVIOR = "repeated_behavior"
    TOOL_SELECTION = "tool_selection"
    OUTPUT_EDIT = "output_edit"
    TASK_OUTCOME = "task_outcome"
    SYSTEM_INFERENCE = "system_inference"


class DriftState(str, Enum):
    """Concept drift detection states."""
    STABLE = "stable"
    WATCH = "watch"
    DRIFTING = "drifting"
    CHANGED = "changed"
    UNKNOWN = "unknown"


class UserGoalStatus(str, Enum):
    """Goal lifecycle states."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class UserModelHealth(str, Enum):
    """Personalization subsystem health states."""
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


# ===================================
# MODEL PROPERTY STATUS
# ===================================

class ModelPropertyStatus(str, Enum):
    """Lifecycle and trust status for inferred model properties."""
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    OBSERVED = "observed"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    STALE = "stale"
    RETRACTED = "retracted"


class EvidenceStatus(str, Enum):
    """Provenance status for evidence backing a model property."""
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    STALE = "stale"


class IdentityDomain(str, Enum):
    """Taxonomy for Karen self-identity facets."""
    CAPABILITY = "capability"
    LIMITATION = "limitation"
    PRINCIPLE = "principle"
    PREFERENCE = "preference"
    PROJECT = "project"
    SKILL = "skill"
    RESOURCE = "resource"


class RelationshipType(str, Enum):
    """Relationship classification between Karen and a user."""
    PROFESSIONAL = "professional"
    COLLABORATIVE = "collaborative"
    MENTORSHIP = "mentorship"
    SERVICE = "service"
    PERSONAL = "personal"


class InteractionNormType(str, Enum):
    """Types of interaction norms tracked in relationships."""
    RESPONSE_STYLE = "response_style"
    AVAILABILITY = "availability"
    FEEDBACK_PREFERENCE = "feedback_preference"
    TOOL_USAGE = "tool_usage"
    COMMUNICATION_CHANNEL = "communication_channel"


class CommitmentType(str, Enum):
    """Types of commitments in a relationship."""
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    RECURRING = "recurring"
    ONE_SHOT = "one_shot"


class CapabilityBeliefType(str, Enum):
    """Types of capability beliefs Karen holds about herself or the user."""
    STRENGTH = "strength"
    LIMITATION = "limitation"
    EMERGING = "emerging"
    DEGRADED = "degraded"


# ===================================
# PROVENANCE
# ===================================

@dataclass
class Provenance:
    """Confidence and provenance for an inferred model property."""
    source: str
    confidence: float
    evidence_refs: List[str]
    first_observed_at: datetime
    last_confirmed_at: Optional[datetime]
    valid_from: datetime
    valid_until: Optional[datetime]
    supersedes: Optional[str]
    status: ModelPropertyStatus

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.evidence_refs = list(self.evidence_refs)


# ===================================
# MODEL EVIDENCE AND REVISION
# ===================================

@dataclass
class ModelEvidence:
    """Single piece of evidence supporting a model property."""
    evidence_id: str
    source: str
    evidence_type: str
    content_ref: str
    observed_at: datetime
    confidence: float
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class ModelRevision:
    """Records a revision to a model property."""
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


# ===================================
# SELF MODEL CONTRACTS
# ===================================

@dataclass
class IdentityFacet:
    """A facet of Karen's self-identity."""
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
    """Karen's belief about a capability."""
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
    """Karen's model of her own identity, principles, capabilities, and limits."""
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


# ===================================
# USER MODEL CONTRACTS
# ===================================

@dataclass
class PreferenceSignal:
    """A user preference with full provenance."""
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
class GoalState:
    """A user goal with provenance."""
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
    """Karen's model of the user."""
    model_id: str
    user_id: str
    tenant_id: str
    preference_signals: List[PreferenceSignal]
    behavior_patterns: List[BehaviorPattern]
    goals: List[GoalState]
    skills: List[IdentityFacet]
    projects: List[str]
    confidence_summary: Dict[str, "ConfidenceState"]
    created_at: datetime
    updated_at: datetime
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===================================
# RELATIONSHIP MODEL CONTRACTS
# ===================================

@dataclass
class RelationshipContext:
    """Context about the Karen-user relationship."""
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
    """Observed interaction pattern between Karen and the user."""
    pattern_id: str
    pattern_type: InteractionNormType
    description: str
    confidence: float
    provenance: Provenance
    observed_count: int
    first_seen: datetime
    last_seen: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.observed_count = max(0, self.observed_count)


@dataclass
class CommitmentState:
    """An open commitment in the relationship."""
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
    """Karen's model of the relationship with a specific user."""
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


@dataclass
class ConfidenceState:
    """Tracks confidence and evidence health for a model property."""
    property_key: str
    model_type: str
    confidence: float
    evidence_count: int
    contradiction_count: int
    last_updated: datetime
    trend: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.evidence_count = max(0, self.evidence_count)
        self.contradiction_count = max(0, self.contradiction_count)


# ===================================
# PREFERENCE CONTRACTS
# ===================================

@dataclass
class PreferenceEvidence:
    """Single piece of evidence for a preference."""
    evidence_id: str
    preference_key: str
    source_type: PreferenceEvidenceSourceType
    source_ref: Optional[str]
    observed_value: Any
    polarity: str  # "positive" | "negative" | "neutral"
    confidence: float
    observed_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class PreferenceContradiction:
    """Records a contradiction between old and new preference evidence."""
    contradiction_id: str
    preference_id: str
    user_id: str
    tenant_id: str
    old_value: Any
    new_value: Any
    old_state: PreferenceState
    new_state: PreferenceState
    resolution: Optional[str] = None  # "supersede" | "merge" | "keep_old" | "keep_new"
    resolved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PreferenceRecord:
    """Canonical preference record with evidence and uncertainty."""
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

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.evidence_count = max(0, self.evidence_count)
        self.contradiction_count = max(0, self.contradiction_count)
        self.version = max(1, self.version)


# ===================================
# BEHAVIOR CONTRACTS
# ===================================

@dataclass
class BehaviorPattern:
    """Inferred repeated behavior pattern."""
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

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.observation_count = max(0, self.observation_count)


# ===================================
# GOAL CONTRACTS
# ===================================

@dataclass
class UserGoal:
    """User goal separate from preferences."""
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

    def __post_init__(self):
        self.confidence = max(0.0, min(1.0, self.confidence))


# ===================================
# STATE CONTRACTS
# ===================================

@dataclass
class CurrentUserState:
    """Fast-changing current state (temporary, session-scoped)."""
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


@dataclass
class UserStateSnapshot:
    """Read-only snapshot of user state for consumer use."""
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
    """Preferences resolved for a specific task/context."""
    user_id: str
    tenant_id: str
    task_context: Dict[str, Any]
    resolved: Dict[str, Any]
    confidence: float
    applied_scope: PreferenceScope
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===================================
# HEALTH CONTRACTS
# ===================================

@dataclass
class UserModelHealthStatus:
    """Personalization subsystem health report."""
    repository: UserModelHealth
    memory_integration: UserModelHealth
    queue: UserModelHealth
    snapshot_cache: UserModelHealth
    evidence_processor: UserModelHealth
    overall: UserModelHealth
    details: Dict[str, Any] = field(default_factory=dict)


# ===================================
# EXTRACTION CONTRACTS
# ===================================

@dataclass
class PreferenceCandidate:
    """Candidate preference extracted from interaction."""
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
    """Candidate behavior pattern extracted from outcomes."""
    candidate_id: str
    user_id: str
    tenant_id: str
    pattern_type: str
    context_signature: str
    observation: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===================================
# HELPER FUNCTIONS
# ===================================

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
    # Enums
    "PreferenceCategory",
    "PreferenceStability",
    "PreferenceState",
    "PreferenceScope",
    "PreferenceEvidenceSourceType",
    "DriftState",
    "UserGoalStatus",
    "UserModelHealth",
    "ModelPropertyStatus",
    "EvidenceStatus",
    "IdentityDomain",
    "RelationshipType",
    "InteractionNormType",
    "CommitmentType",
    "CapabilityBeliefType",
    # Contracts
    "PreferenceEvidence",
    "PreferenceContradiction",
    "PreferenceRecord",
    "BehaviorPattern",
    "UserGoal",
    "CurrentUserState",
    "UserStateSnapshot",
    "ResolvedPreferences",
    "UserModelHealthStatus",
    "PreferenceCandidate",
    "BehaviorCandidate",
    "Provenance",
    "ModelEvidence",
    "ModelRevision",
    "IdentityFacet",
    "CapabilityBelief",
    "SelfModel",
    "PreferenceSignal",
    "GoalState",
    "UserModel",
    "RelationshipContext",
    "InteractionPattern",
    "CommitmentState",
    "RelationshipModel",
    "ConfidenceState",
    # Helpers
    "make_preference_id",
    "make_evidence_id",
    "make_contradiction_id",
    "make_pattern_id",
    "make_goal_id",
    "make_candidate_id",
]
