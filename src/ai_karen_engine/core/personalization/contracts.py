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
    # Helpers
    "make_preference_id",
    "make_evidence_id",
    "make_contradiction_id",
    "make_pattern_id",
    "make_goal_id",
    "make_candidate_id",
]
