"""Memory trust provenance and consent policy contracts."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MemoryTrustClass(str, Enum):
    EXPLICIT_USER = "explicit_user"
    VERIFIED_TOOL = "verified_tool"
    TRUSTED_DOCUMENT = "trusted_document"
    INFERRED = "inferred"
    EXTERNAL_WEB = "external_web"
    UNVERIFIED = "unverified"
    SUSPICIOUS = "suspicious"
    POISONED = "poisoned"


class MemoryOrigin(str, Enum):
    USER_INPUT = "user_input"
    SYSTEM_GENERATED = "system_generated"
    TOOL_OUTPUT = "tool_output"
    DOCUMENT_IMPORT = "document_import"
    WEB_FETCH = "web_fetch"
    API_RESPONSE = "api_response"
    DERIVED_INFERENCE = "derived_inference"
    CONSOLIDATED = "consolidated"


class MemorySensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"


class MemoryRetentionScope(str, Enum):
    SESSION = "session"
    CONVERSATION = "conversation"
    USER_PROFILE = "user_profile"
    TENANT_WIDE = "tenant_wide"
    PERMANENT = "permanent"
    EPHEMERAL = "ephemeral"


@dataclass(slots=True)
class MemoryTrustProvenance:
    origin: MemoryOrigin = MemoryOrigin.INFERRED
    trust_class: MemoryTrustClass = MemoryTrustClass.INFERRED
    authority: str = ""
    source_ref: str = ""
    verification_timestamp: str | None = None
    verification_confidence: float = 0.0
    security_classification: str = "unclassified"
    taint_indicators: list[str] = field(default_factory=list)
    allowed_memory_classes: list[str] = field(default_factory=list)
    promotion_eligible: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_promotable(self) -> bool:
        if not self.promotion_eligible:
            return False
        if self.trust_class in (MemoryTrustClass.SUSPICIOUS, MemoryTrustClass.POISONED):
            return False
        if self.taint_indicators:
            return False
        return True

    def has_high_authority(self) -> bool:
        return self.verification_confidence >= 0.8


@dataclass(slots=True)
class MemoryConsentPolicy:
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    explicit_user_intent: bool = False
    retention_scope: MemoryRetentionScope = MemoryRetentionScope.CONVERSATION
    tenant_policy: str = "default"
    purpose: str = "general"
    deletion_rights: str = "user_controlled"
    min_confidence_for_persistence: float = 0.6
    require_explicit_consent: bool = False
    auto_delete_after: str | None = None
    propagation_allowed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def can_persist(self, confidence: float) -> bool:
        if self.sensitivity == MemorySensitivity.PROHIBITED:
            return False
        if self.require_explicit_consent and not self.explicit_user_intent:
            return False
        if confidence < self.min_confidence_for_persistence:
            return False
        return True

    def can_propagate(self) -> bool:
        return self.propagation_allowed and self.sensitivity != MemorySensitivity.PROHIBITED


@dataclass(slots=True)
class MemoryDeletionPropagation:
    memory_id: str
    deletion_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    propagation_status: str = "pending"
    affected_systems: list[str] = field(default_factory=list)
    semantic_cleanup_required: bool = True
    belief_state_cleared: bool = False
    relationship_model_cleared: bool = False
    adaptive_profile_cleared: bool = False
    context_cache_cleared: bool = False
    vector_index_cleared: bool = False
    graph_associations_cleared: bool = False
    reflection_candidate_removed: bool = False
    consolidation_prevented: bool = False
    verification_status: str = "pending"
    reason_for_deletion: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_complete_propagation(self) -> bool:
        required_clearances = [
            self.belief_state_cleared,
            self.relationship_model_cleared,
            self.adaptive_profile_cleared,
            self.context_cache_cleared,
            self.vector_index_cleared,
            self.graph_associations_cleared,
            self.reflection_candidate_removed,
        ]
        return all(required_clearances)

    def get_systems_cleared(self) -> list[str]:
        systems = []
        if self.belief_state_cleared:
            systems.append("belief_state")
        if self.relationship_model_cleared:
            systems.append("relationship_model")
        if self.adaptive_profile_cleared:
            systems.append("adaptive_profile")
        if self.context_cache_cleared:
            systems.append("context_cache")
        if self.vector_index_cleared:
            systems.append("vector_index")
        if self.graph_associations_cleared:
            systems.append("graph_associations")
        if self.reflection_candidate_removed:
            systems.append("reflection_candidate")
        return systems


@dataclass(slots=True)
class MemoryGuards:
    trust_provenance: MemoryTrustProvenance | None = None
    consent_policy: MemoryConsentPolicy | None = None
    deletion_propagation: MemoryDeletionPropagation | None = None
    enabled_guards: list[str] = field(default_factory=lambda: [
        "trust_provenance",
        "consent_policy", 
        "deletion_propagation",
    ])
    strict_mode: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def can_create_memory(self, confidence: float, content: str) -> tuple[bool, str]:
        if self.trust_provenance and not self.trust_provenance.is_promotable():
            return False, "memory not promotable due to trust issues"
        
        if self.consent_policy and not self.consent_policy.can_persist(confidence):
            return False, f"memory cannot persist due to consent policy: {self.consent_policy.sensitivity}"
        
        if self.trust_provenance and self.trust_provenance.trust_class == MemoryTrustClass.POISONED:
            return False, "memory flagged as poisoned"
            
        return True, "memory creation allowed"

    def should_propagate_deletion(self) -> bool:
        if not self.deletion_propagation:
            return False
        return not self.deletion_propagation.is_complete_propagation()