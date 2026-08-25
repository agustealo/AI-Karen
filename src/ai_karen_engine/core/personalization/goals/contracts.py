"""
Goal / Intention / Commitment cognitive contracts for AI-Karen.

This module defines the cognitive representation of Karen's unfinished business:
active goals, intentions, commitments, priorities, dependencies, conflicts,
prospective memory, and completion evidence.

These are domain contracts, NOT persistence models and NOT runtime state.
The in-memory GoalStore lives in lifecycle.py and is re-exported here only
for backward compatibility with existing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..contracts import PreferenceScope, UserGoal, UserGoalStatus

# ===================================
# TYPE ALIASES
# ===================================

GoalId = str


# ===================================
# GOAL ENUMS
# ===================================

class GoalType(str, Enum):
    """How a goal originated cognitively."""
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    DERIVED = "derived"


class GoalOrigin(str, Enum):
    """Source of the goal's formation."""
    USER_STATED = "user_stated"
    OBSERVATION = "observation"
    INFERENCE = "inference"
    REFLECTION = "reflection"
    CORTEX = "cortex"


class GoalPriority(str, Enum):
    """Cognitive urgency/priority band."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GoalState(str, Enum):
    """Full goal lifecycle state.

    PROPOSED and SATISFIED are distinct from COMPLETED:
    - SATISFIED: all proof gates have passed.
    - COMPLETED: Karen has received evidence that the goal was actually fulfilled.
    """
    PROPOSED = "proposed"
    ACTIVE = "active"
    BLOCKED = "blocked"
    PAUSED = "paused"
    AT_RISK = "at_risk"
    SATISFIED = "satisfied"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class ConflictType(str, Enum):
    """Type of conflict between goals."""
    VALUE = "value"
    SCOPE = "scope"
    DEPENDENCY = "dependency"
    TEMPORAL = "temporal"


class ConflictSeverity(str, Enum):
    """Severity of a goal conflict."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CompletionEvidenceSource(str, Enum):
    """Source of completion evidence for a goal."""
    USER_CONFIRMED = "user_confirmed"
    TEST_PASSED = "test_passed"
    STATE_CHANGED = "state_changed"
    ARTIFACT_CREATED = "artifact_created"
    RUNTIME_EVENT = "runtime_event"
    EXPLICIT_OUTCOME = "explicit_outcome"


class IntentionState(str, Enum):
    """Lifecycle state of an intention."""
    FORMED = "formed"
    WAITING = "waiting"
    READY = "ready"
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class IntentionPriority(str, Enum):
    """Priority of an intention."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IntentionTriggerType(str, Enum):
    """Semantic trigger types for intentions (not scheduler implementations)."""
    TIME_RELEVANT = "time_relevant"
    EVENT_RELEVANT = "event_relevant"
    CONTEXT_RELEVANT = "context_relevant"
    GOAL_STATE_RELEVANT = "goal_state_relevant"
    USER_RELEVANT = "user_relevant"
    PROJECT_RELEVANT = "project_relevant"


class CommitmentParty(str, Enum):
    """Party to a commitment."""
    USER = "user"
    KAREN = "karen"
    EXTERNAL = "external"


class CommitmentSource(str, Enum):
    """How a commitment was established."""
    USER_STATEMENT = "user_statement"
    OBSERVATION = "observation"
    IMPLICIT_UNDERSTANDING = "implicit_understanding"


class CommitmentStrength(str, Enum):
    """Strength of a commitment.

    COMMITTED and BOUND require stronger evidence than ordinary goals.
    """
    PROFFERED = "proffered"
    COMMITTED = "committed"
    BOUND = "bound"


class CommitmentStatus(str, Enum):
    """Lifecycle status of a commitment."""
    PROPOSED = "proposed"
    ACKNOWLEDGED = "acknowledged"
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class ProspectiveState(str, Enum):
    """State of a prospective memory item."""
    DORMANT = "dormant"
    TRIGGERED = "triggered"
    ARCHIVED = "archived"


class EvidenceSourceType(str, Enum):
    """Source of evidence (generalized, reusable across domains)."""
    USER_STATEMENT = "user_statement"
    OBSERVATION = "observation"
    TOOL_RESULT = "tool_result"
    MEMORY = "memory"
    DOCUMENT = "document"
    EXTERNAL_SOURCE = "external_source"
    SYSTEM_INFERENCE = "system_inference"
    OUTCOME = "outcome"


class GoalRelationship(str, Enum):
    """Relationship type between goals in a hierarchy."""
    PARENT = "parent"
    CHILD = "child"
    DEPENDS_ON = "depends_on"
    BLOCKS = "blocks"
    CONTRIBUTES_TO = "contributes_to"
    CONFLICTS_WITH = "conflicts_with"


# ===================================
# GOAL CONTRACTS
# ===================================

@dataclass
class GoalEvidence:
    """A piece of evidence supporting or forming a goal."""
    evidence_id: str
    claim: str
    source_type: EvidenceSourceType
    source_ref: str | None
    observed_value: Any
    polarity: str
    confidence: float
    observed_at: datetime
    tenant_id: str = ""
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class GoalProgress:
    """Progress tracking for a goal."""
    completed_steps: int = 0
    total_steps: int = 0
    percentage: float = 0.0
    last_updated: datetime | None = None
    milestones: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.percentage = max(0.0, min(1.0, self.percentage))


@dataclass
class GoalOutcome:
    """Outcome of a completed goal."""
    outcome_id: str
    success: bool
    description: str
    evidence_refs: list[str] = field(default_factory=list)
    achieved_at: datetime | None = None


@dataclass
class GoalRevision:
    """Record of a goal revision."""
    revision_id: str
    goal_id: str
    field_changed: str
    old_value: Any
    new_value: Any
    reason: str
    revised_at: datetime
    tenant_id: str = ""
    user_id: str | None = None


@dataclass
class Goal:
    """Cognitive representation of an unfinished business item.

    Evolves around (but does not replace) UserGoal.  A Goal is Karen's
    internal understanding of what matters, not a scheduler entry.
    """
    goal_id: str
    tenant_id: str
    user_id: str | None
    description: str
    goal_type: GoalType
    origin: GoalOrigin
    state: GoalState
    priority: GoalPriority
    scope: PreferenceScope
    confidence: float
    evidence_refs: list[str]
    started_at: datetime
    last_observed_at: datetime
    target_date: datetime | None = None
    parent_goal_id: str | None = None
    child_goal_ids: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    contributes_to: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    progress: GoalProgress | None = None
    outcome: GoalOutcome | None = None
    revisions: list[GoalRevision] = field(default_factory=list)
    completion_evidence_required: list[CompletionEvidenceSource] = field(default_factory=list)
    completion_evidence: list[str] = field(default_factory=list)
    completion_evidence_sources: list[CompletionEvidenceSource] = field(default_factory=list)
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    superseded_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))

    def is_active(self) -> bool:
        return self.state == GoalState.ACTIVE

    def is_terminal(self) -> bool:
        return self.state in (
            GoalState.COMPLETED,
            GoalState.ABANDONED,
            GoalState.EXPIRED,
        )


def goal_from_user_goal(ug: UserGoal) -> Goal:
    """Convert a legacy UserGoal into an enhanced Goal.

    Inferred goals receive lower confidence than explicit ones.
    """
    origin = GoalOrigin.USER_STATED
    goal_type = GoalType.EXPLICIT
    confidence = ug.confidence

    if ug.metadata:
        meta_str = str(ug.metadata).lower()
        if "observation" in meta_str or "observed" in meta_str:
            origin = GoalOrigin.OBSERVATION
        elif "reflection" in meta_str:
            origin = GoalOrigin.REFLECTION
        elif "inferred" in meta_str or "inference" in meta_str:
            origin = GoalOrigin.INFERENCE
        elif "cortex" in meta_str:
            origin = GoalOrigin.CORTEX

    if origin != GoalOrigin.USER_STATED:
        goal_type = GoalType.INFERRED
        confidence = min(ug.confidence, 0.6)

    target_date = ug.target_date
    if isinstance(target_date, str):
        target_date = datetime.fromisoformat(target_date)

    return Goal(
        goal_id=ug.goal_id,
        tenant_id=ug.tenant_id,
        user_id=ug.user_id,
        description=ug.description,
        goal_type=goal_type,
        origin=origin,
        state=_map_user_goal_status(ug.status),
        priority=GoalPriority.MEDIUM,
        scope=ug.scope,
        confidence=confidence,
        evidence_refs=list(ug.evidence),
        started_at=ug.started_at,
        last_observed_at=ug.last_observed_at,
        target_date=target_date,
        metadata=dict(ug.metadata),
    )


def _map_user_goal_status(status: Any) -> GoalState:
    """Map a legacy UserGoalStatus to the richer GoalState."""
    mapping = {
        UserGoalStatus.ACTIVE: GoalState.ACTIVE,
        UserGoalStatus.PAUSED: GoalState.PAUSED,
        UserGoalStatus.COMPLETED: GoalState.COMPLETED,
        UserGoalStatus.ABANDONED: GoalState.ABANDONED,
        UserGoalStatus.UNKNOWN: GoalState.PROPOSED,
    }
    if isinstance(status, str):
        try:
            ugs = UserGoalStatus(status)
        except ValueError:
            return GoalState.PROPOSED
        return mapping.get(ugs, GoalState.PROPOSED)
    return mapping.get(status, GoalState.PROPOSED)


@dataclass
class GoalSnapshot:
    """Read-only snapshot of a Goal for cross-domain consumption.

    This is the stable interface exported to other cognitive sprints
    (e.g. COG-REFLECT-1's GoalContextLike protocol).
    """
    goal_id: str
    tenant_id: str
    user_id: str | None
    description: str
    state: GoalState
    priority: GoalPriority
    goal_type: GoalType
    origin: GoalOrigin
    confidence: float
    evidence_refs: list[str]
    parent_goal_id: str | None
    child_goal_ids: list[str]
    depends_on: list[str]
    blocks: list[str]
    conflicts_with: list[str]
    target_date: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    superseded_by: str | None
    completion_evidence: list[str]
    completion_evidence_sources: list[CompletionEvidenceSource]
    outcome: GoalOutcome | None


def to_snapshot(goal: Goal) -> GoalSnapshot:
    """Create a read-only GoalSnapshot from a Goal."""
    return GoalSnapshot(
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        user_id=goal.user_id,
        description=goal.description,
        state=goal.state,
        priority=goal.priority,
        goal_type=goal.goal_type,
        origin=goal.origin,
        confidence=goal.confidence,
        evidence_refs=list(goal.evidence_refs),
        parent_goal_id=goal.parent_goal_id,
        child_goal_ids=list(goal.child_goal_ids),
        depends_on=list(goal.depends_on),
        blocks=list(goal.blocks),
        conflicts_with=list(goal.conflicts_with),
        target_date=goal.target_date,
        completed_at=goal.completed_at,
        expires_at=goal.expires_at,
        superseded_by=goal.superseded_by,
        completion_evidence=list(goal.completion_evidence),
        completion_evidence_sources=list(goal.completion_evidence_sources),
        outcome=goal.outcome,
    )


@dataclass
class GoalConflict:
    """Detected conflict between two goals."""
    conflict_id: str
    goal_a_id: str
    goal_b_id: str
    conflict_type: ConflictType
    severity: ConflictSeverity
    description: str
    evidence_refs: list[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=datetime.utcnow)
    tenant_id: str = ""
    resolution_candidates: list[str] = field(default_factory=list)


@dataclass
class GoalPriorityAssessment:
    """Result of a cognitive priority assessment."""
    goal_id: str
    score: float
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    assessed_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        self.score = max(0.0, min(1.0, self.score))


# ===================================
# INTENTION CONTRACTS
# ===================================

@dataclass
class Intention:
    """A plan to pursue a goal, triggered by semantic conditions."""
    intention_id: str
    goal_id: str
    tenant_id: str
    user_id: str | None
    description: str
    state: IntentionState
    priority: IntentionPriority
    trigger_type: IntentionTriggerType
    trigger_condition: str
    context: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    formed_at: datetime = field(default_factory=datetime.utcnow)
    activated_at: datetime | None = None
    fulfilled_at: datetime | None = None
    invalidated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class IntentionEvidence:
    """Evidence about an intention."""
    evidence_id: str
    intention_id: str
    claim: str
    source_type: EvidenceSourceType
    confidence: float
    observed_at: datetime
    tenant_id: str = ""
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))


# ===================================
# COMMITMENT CONTRACTS
# ===================================

@dataclass
class CommitmentCondition:
    """A condition under which a commitment holds."""
    condition_id: str
    description: str
    met: bool = False
    evidence_ref: str | None = None


@dataclass
class CommitmentEvidence:
    """Evidence that a commitment was made."""
    evidence_id: str
    source: CommitmentSource
    source_ref: str | None
    confidence: float
    observed_at: datetime
    strength: CommitmentStrength
    tenant_id: str = ""
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class Commitment:
    """A binding commitment by one or more parties.

    A commitment must preserve: who committed, to whom, what, when,
    under what condition, source evidence, confidence, and deadline.
    Commitments require stronger evidence than ordinary goals.
    """
    commitment_id: str
    tenant_id: str
    user_id: str | None
    parties: list[CommitmentParty]
    description: str
    source: CommitmentSource
    strength: CommitmentStrength
    status: CommitmentStatus
    confidence: float
    conditions: list[CommitmentCondition] = field(default_factory=list)
    evidence: list[CommitmentEvidence] = field(default_factory=list)
    deadline: datetime | None = None
    committed_at: datetime = field(default_factory=datetime.utcnow)
    fulfilled_at: datetime | None = None
    failed_at: datetime | None = None
    superseded_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, self.confidence))

    def is_active(self) -> bool:
        return self.status == CommitmentStatus.ACTIVE


# ===================================
# PROSPECTIVE MEMORY CONTRACTS
# ===================================

@dataclass
class ProspectiveTrigger:
    """A semantic trigger for prospective memory.

    Triggers are semantic, not scheduler implementations.
    """
    trigger_type: IntentionTriggerType
    target_ref: str
    description: str
    condition: str | None = None
    tenant_id: str = ""
    user_id: str | None = None


@dataclass
class ProspectiveMemory:
    """Cognitive prospective memory.

    Core owns the intention.  It does not own cron execution.
    """
    pm_id: str
    description: str
    trigger: ProspectiveTrigger
    state: ProspectiveState
    target_intention_id: str | None
    target_goal_id: str | None
    evidence_refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    triggered_at: datetime | None = None
    archived_at: datetime | None = None
    tenant_id: str = ""
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ===================================
# BACKWARD COMPATIBILITY RE-EXPORT
# ===================================

from .lifecycle import GoalStore

__all__ = [
    "Commitment",
    "CommitmentCondition",
    "CommitmentEvidence",
    "CommitmentParty",
    "CommitmentSource",
    "CommitmentStatus",
    "CommitmentStrength",
    "CompletionEvidenceSource",
    "ConflictSeverity",
    "ConflictType",
    "EvidenceSourceType",
    "Goal",
    "GoalConflict",
    "GoalEvidence",
    "GoalId",
    "GoalOrigin",
    "GoalOutcome",
    "GoalPriority",
    "GoalPriorityAssessment",
    "GoalProgress",
    "GoalRelationship",
    "GoalRevision",
    "GoalSnapshot",
    "GoalState",
    "GoalStore",
    "GoalType",
    "Intention",
    "IntentionEvidence",
    "IntentionPriority",
    "IntentionState",
    "IntentionTriggerType",
    "ProspectiveMemory",
    "ProspectiveState",
    "ProspectiveTrigger",
    "UserGoal",
    "UserGoalStatus",
    "goal_from_user_goal",
    "to_snapshot",
]
