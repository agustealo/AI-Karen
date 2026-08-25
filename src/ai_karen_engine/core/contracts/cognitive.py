"""Canonical cross-domain cognitive contracts.

This module owns concepts that must mean exactly one thing across cognitive
subsystems. Domain-specific contracts remain with their domain owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ReasoningDepth(str, Enum):
    """Canonical reasoning/verification depth."""

    NONE = "none"
    LIGHT = "light"
    STANDARD = "standard"
    DEEP = "deep"


class VerificationReason(str, Enum):
    """Canonical reason that verification may be required."""

    LOW_CONFIDENCE = "low_confidence"
    LOW_MEMORY_CONFIDENCE = "low_memory_confidence"
    LOW_REASONING_CONFIDENCE = "low_reasoning_confidence"
    HIGH_RISK = "high_risk"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    EVIDENCE_INCONSISTENT = "evidence_inconsistent"
    STALE_MEMORY = "stale_memory"
    STALE_EVIDENCE = "stale_evidence"
    EXTERNAL_FACT = "external_fact"
    FAILED_PREVIOUS_STRATEGY = "failed_previous_strategy"


@dataclass(frozen=True, slots=True)
class VerificationRequirement:
    """Single verification contract shared by Meta, CORTEX, and Runtime.

    Meta recommends a requirement, CORTEX decides whether verification becomes
    selected behavior, and Runtime executes the authorized verification.
    """

    required: bool = False
    reason: VerificationReason | str | None = None
    depth: ReasoningDepth = ReasoningDepth.STANDARD
    urgency: float = 0.0
    source: str = "cortex"
    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "urgency", max(0.0, min(1.0, self.urgency)))


@dataclass(frozen=True, slots=True)
class ConfidenceValue:
    """Base value object for non-interchangeable confidence domains."""

    value: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", max(0.0, min(1.0, self.value)))

    def __float__(self) -> float:
        return self.value


@dataclass(frozen=True, slots=True)
class EpistemicConfidence(ConfidenceValue):
    """Confidence that a claim/belief is epistemically supported."""


@dataclass(frozen=True, slots=True)
class RetrievalConfidence(ConfidenceValue):
    """Confidence in recall quality/relevance, not truth."""


@dataclass(frozen=True, slots=True)
class SalienceConfidence(ConfidenceValue):
    """Confidence that a salience assessment is reliable."""


@dataclass(frozen=True, slots=True)
class BehaviorConfidence(ConfidenceValue):
    """Confidence that the selected behavior is appropriate."""


@dataclass(frozen=True, slots=True)
class MetaConfidence(ConfidenceValue):
    """Confidence in cognitive self-assessment."""


@dataclass(frozen=True, slots=True)
class LearningConfidence(ConfidenceValue):
    """Confidence in an experience-derived learning signal."""


@dataclass(frozen=True, slots=True)
class CognitiveScope:
    """Explicit cognitive scope. Tenant identity is never implicit."""

    tenant_id: str
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("tenant_id must be explicit and non-default")


@dataclass(frozen=True, slots=True)
class CognitiveVersion:
    """Version lineage for replayable cognitive outputs."""

    policy_version: str = "1.0.0"
    schema_version: str = "1.0.0"
    scoring_version: str = "1.0.0"
    created_at: datetime = datetime.now(timezone.utc)


__all__ = [
    "BehaviorConfidence",
    "CognitiveScope",
    "CognitiveVersion",
    "ConfidenceValue",
    "EpistemicConfidence",
    "LearningConfidence",
    "MetaConfidence",
    "ReasoningDepth",
    "RetrievalConfidence",
    "SalienceConfidence",
    "VerificationReason",
    "VerificationRequirement",
]
