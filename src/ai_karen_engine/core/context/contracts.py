"""Canonical context-domain contracts.

Context owns typed context requirements and resolved context vocabulary. It does
not decide cognitive behavior, authorize access, execute retrieval, or become a
second request orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai_karen_engine.core.cognitive.state import ContextSnapshot
from ai_karen_engine.core.contracts.cognitive import CognitiveScope

# Context scope is the canonical cross-domain CognitiveScope. Keep the alias as
# identity, not a wrapper/subclass, so tenant semantics cannot drift.
ContextScope = CognitiveScope


class EvidenceSource(str, Enum):
    """Governed evidence domains that Runtime may resolve for cognition."""

    MEMORY = "memory"
    SELF_MODEL = "self_model"
    USER_MODEL = "user_model"
    RELATIONSHIP_MODEL = "relationship_model"
    GOALS = "goals"
    COMMITMENTS = "commitments"
    LIVE_STATE = "live_state"
    EXTERNAL = "external"


@dataclass(slots=True)
class ContextRequirement:
    """One Stage-1 request for evidence from a governed source."""

    source: EvidenceSource
    capability: str
    required: bool = False
    scopes: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    max_items: int = 0
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "capability": self.capability,
            "required": self.required,
            "scopes": list(self.scopes),
            "classes": list(self.classes),
            "max_items": self.max_items,
            "reason_codes": list(self.reason_codes),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ContextRequirements:
    """Typed Stage-1 CORTEX output describing evidence needs, not access grants."""

    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    session_id: str | None = None
    conversation_id: str | None = None
    requirements: list[ContextRequirement] = field(default_factory=list)
    verification_required: bool = False
    temporal_horizon: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("context tenant_id must be explicit and non-default")
        if not self.user_id:
            raise ValueError("context user_id must be explicit")

    @property
    def requested_capabilities(self) -> list[str]:
        return list(
            dict.fromkeys(
                requirement.capability
                for requirement in self.requirements
                if requirement.capability
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "requirements": [item.to_dict() for item in self.requirements],
            "verification_required": self.verification_required,
            "temporal_horizon": self.temporal_horizon,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ContextEvidence:
    """Evidence envelope preserved between authorized resolution and cognition."""

    evidence_id: str
    source: EvidenceSource
    content: str
    source_ref: str | None = None
    relevance: float | None = None
    confidence: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    temporal: dict[str, Any] = field(default_factory=dict)
    contradiction: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CognitiveContext:
    """Typed context supplied to CORTEX Stage 2.

    Authorization metadata is first-class so Stage 2 can distinguish unavailable,
    denied, unresolved, and actually resolved evidence instead of treating all
    missing context as equivalent.
    """

    context_id: str
    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    requirements: ContextRequirements
    authorized_sources: list[str] = field(default_factory=list)
    denied_sources: list[str] = field(default_factory=list)
    unresolved_sources: list[str] = field(default_factory=list)
    evidence: list[ContextEvidence] = field(default_factory=list)
    policy_decision_id: str | None = None
    policy_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError("cognitive context tenant_id must be explicit and non-default")
        if self.requirements.tenant_id != self.tenant_id:
            raise ValueError("cognitive context tenant scope must match requirements")
        if self.requirements.user_id != self.user_id:
            raise ValueError("cognitive context user scope must match requirements")


__all__ = [
    "CognitiveContext",
    "ContextEvidence",
    "ContextRequirement",
    "ContextRequirements",
    "ContextScope",
    "ContextSnapshot",
    "EvidenceSource",
]
