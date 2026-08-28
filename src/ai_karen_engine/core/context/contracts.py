"""Canonical context-domain contracts.

Context owns typed context requirements and resolved context vocabulary. It does
not decide cognitive behavior, authorize access, execute retrieval, or become a
second request orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


class EvidenceContradictionStatus(str, Enum):
    """Typed contradiction state attached to resolved evidence."""

    UNKNOWN = "unknown"
    NONE = "none"
    POSSIBLE = "possible"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    """Where resolved evidence came from and which resolver produced it."""

    source_ref: str | None = None
    source_record_id: str | None = None
    resolver_id: str = ""
    resolver_version: str = ""
    retrieval_method: str = ""
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceTemporalContext:
    """Temporal meaning of evidence, separate from retrieval time."""

    observed_at: datetime | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    expires_at: datetime | None = None
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvidenceContradiction:
    """Conflict state without embedding untyped claim payloads in the contract."""

    status: EvidenceContradictionStatus = EvidenceContradictionStatus.UNKNOWN
    conflicting_evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    resolution_ref: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceScope:
    """Identity and conversation scope carried with one evidence item.

    This envelope records the scope actually used by Runtime resolution. It does
    not authorize that scope. RuntimePolicy remains the authorization authority.
    The temporary legacy default tenant is preserved here until TENANT-SCOPE-1
    removes it at ingress/runtime identity authority.
    """

    tenant_id: str
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("evidence tenant_id must be present")


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
    """Typed Stage-1 CORTEX output describing evidence needs, not access grants.

    The legacy runtime contract still permits tenant_id="default". This context
    contract therefore preserves that value during CORTEX-CONTEXT-1 instead of
    silently turning the cognitive migration into a breaking ingress migration.
    TENANT-SCOPE-1 must remove the legacy default at the canonical ingress/runtime
    identity boundary after a caller audit.
    """

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
        if not self.tenant_id:
            raise ValueError("context tenant_id must be present")
        if not self.user_id:
            raise ValueError("context user_id must be explicit")

    @property
    def uses_legacy_default_tenant(self) -> bool:
        return self.tenant_id == "default"

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
            "legacy_default_tenant": self.uses_legacy_default_tenant,
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
    provenance: EvidenceProvenance = field(default_factory=EvidenceProvenance)
    temporal: EvidenceTemporalContext = field(default_factory=EvidenceTemporalContext)
    contradiction: EvidenceContradiction = field(default_factory=EvidenceContradiction)
    scope: EvidenceScope | None = None
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
        if not self.tenant_id:
            raise ValueError("cognitive context tenant_id must be present")
        if self.requirements.tenant_id != self.tenant_id:
            raise ValueError("cognitive context tenant scope must match requirements")
        if self.requirements.user_id != self.user_id:
            raise ValueError("cognitive context user scope must match requirements")

    @property
    def uses_legacy_default_tenant(self) -> bool:
        return self.tenant_id == "default"


__all__ = [
    "CognitiveContext",
    "ContextEvidence",
    "ContextRequirement",
    "ContextRequirements",
    "ContextScope",
    "ContextSnapshot",
    "EvidenceContradiction",
    "EvidenceContradictionStatus",
    "EvidenceProvenance",
    "EvidenceScope",
    "EvidenceSource",
    "EvidenceTemporalContext",
]
