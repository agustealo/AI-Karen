"""Canonical contracts for the COG-EVAL-1 cognitive benchmark.

Defines the declarative scenario schema and the result/diagnosis vocabularies
that the scenario runner and assertions operate on.  This module is pure
data: it deliberately avoids importing production cognitive modules so that
``mypy tests/benchmarks/cognitive`` stays clean and the benchmark remains a
test-only artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ScenarioKind(str, Enum):
    """Category of cognitive behaviour under test."""

    MEMORY_CONTINUITY = "memory_continuity"
    CONTRADICTION = "contradiction"
    BEHAVIOR_SELECTION = "behavior_selection"
    GOAL_INTENTION = "goal_intention"
    SALIENCE = "salience"
    META_COGNITION = "meta_cognition"
    POLICY_DOMINANCE = "policy_dominance"
    MEMORY_POISONING = "memory_poisoning"
    DELETION = "deletion"
    LEARNING = "learning"


class ContradictionResult(str, Enum):
    """Distinguished outputs for belief-integrity scenarios."""

    CONTRADICTION = "CONTRADICTION"
    SUPERSESSION = "SUPERSESSION"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    VERIFY = "VERIFY"
    RETRACTED = "RETRACTED"
    INACTIVE = "INACTIVE"


class BehaviorOption(str, Enum):
    """Decision the behavior selector should make for a request."""

    ASK = "ASK"
    ACT = "ACT"
    VERIFY = "VERIFY"
    POLICY_WINS = "POLICY_WINS"


class SecurityCheck(str, Enum):
    """Outcome of a security/policy posture check."""

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"


@dataclass
class BehaviorDecision:
    """Result produced by the reference DecisionModel."""

    option: BehaviorOption
    rationale: str
    confidence: float
    applied_constraints: list[str]
    allowed: SecurityCheck = SecurityCheck.ALLOWED

    def to_dict(self) -> dict[str, Any]:
        return {
            "option": self.option.value,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "applied_constraints": list(self.applied_constraints),
            "allowed": self.allowed.value,
        }


class MetaDiagnosis(str, Enum):
    """Distinct meta-cognitive diagnostics."""

    LOW_MEMORY_CONFIDENCE = "LOW_MEMORY_CONFIDENCE"
    LOW_REASONING_CONFIDENCE = "LOW_REASONING_CONFIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    STALE_MEMORY = "STALE_MEMORY"
    REPEATED_FAILED_STRATEGY = "REPEATED_FAILED_STRATEGY"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    UNKNOWN = "UNKNOWN"


class DeletionStatus(str, Enum):
    """Deletion provenance tracked by NeuroVault."""

    RETRACTED = "RETRACTED"
    DELETED = "DELETED"
    PURGED = "PURGED"


class DefectSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ExpectedSpec:
    """The assertions a scenario declares about cognitive behaviour."""

    result: str = ""
    confidence_min: float = 0.0
    confidence_max: float = 1.0
    active: bool | None = None
    retained: bool | None = None
    tenant_scoped: bool | None = None
    policy_violation: bool | None = None
    promoted_to_trusted: bool | None = None
    appears_in: list[str] | None = None
    not_appears_in: list[str] | None = None
    flags: dict[str, Any] | None = None
    description: str = ""


@dataclass
class Scenario:
    """A declarative cognitive scenario loaded from YAML."""

    scenario_id: str
    kind: ScenarioKind
    user_id: str
    tenant_id: str
    description: str
    expected: ExpectedSpec
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str:
        return self.raw.get("domain", "")

    def flag(self, name: str, default: Any = None) -> Any:
        return self.expected.flags.get(name, default) if self.expected.flags else default


@dataclass
class CognitiveResult:
    """Result produced by the scenario runner against real cognitive modules."""

    scenario_id: str
    kind: ScenarioKind
    verdict: str = ""
    confidence: float = 0.0
    active: bool = True
    retained: bool = True
    tenant_scoped: bool = True
    policy_violation: bool = False
    promoted_to_trusted: bool = True
    appears_in: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    defects: list["DefectRecord"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "kind": self.kind.value,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "active": self.active,
            "retained": self.retained,
            "tenant_scoped": self.tenant_scoped,
            "policy_violation": self.policy_violation,
            "promoted_to_trusted": self.promoted_to_trusted,
            "appears_in": list(self.appears_in),
            "flags": dict(self.flags),
            "defects": [d.to_dict() for d in self.defects],
        }


@dataclass
class DefectRecord:
    """Records a defect exposed by a scenario (owned by COG-CLOSE-1)."""

    scenario_id: str
    expected: str
    actual: str
    affected_owner: str
    severity: DefectSeverity
    kind: ScenarioKind
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "kind": self.kind.value,
            "expected": self.expected,
            "actual": self.actual,
            "affected_owner": self.affected_owner,
            "severity": self.severity.value,
            "detail": self.detail,
        }


# Canonical report groupings used by the deterministic summary.
REPORT_GROUPS: dict[str, list[ScenarioKind]] = {
    "Cognitive Continuity": [ScenarioKind.MEMORY_CONTINUITY],
    "Belief Integrity": [ScenarioKind.CONTRADICTION],
    "Goal/Intent Behavior": [ScenarioKind.GOAL_INTENTION, ScenarioKind.BEHAVIOR_SELECTION],
    "Salience Semantics": [ScenarioKind.SALIENCE],
    "Meta-Cognition": [ScenarioKind.META_COGNITION],
    "Policy Dominance": [ScenarioKind.POLICY_DOMINANCE],
    "Memory Security": [
        ScenarioKind.MEMORY_POISONING,
        ScenarioKind.DELETION,
    ],
    "Learning Safety": [ScenarioKind.LEARNING],
}


__all__ = [
    "BehaviorDecision",
    "ContradictionResult",
    "CognitiveResult",
    "DefectRecord",
    "DefectSeverity",
    "DeletionStatus",
    "ExpectedSpec",
    "MetaDiagnosis",
    "REPORT_GROUPS",
    "Scenario",
    "ScenarioKind",
]
