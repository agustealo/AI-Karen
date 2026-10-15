"""Versioned, side-effect-free semantic assertion contract for governed memory.

The contract describes evidence; it never authorizes a write, chooses a memory
tier, or declares a model extraction true. Formation and NeuroVault retain
their existing authority. No database schema changes occur in this slice.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

SCHEMA_VERSION = 1


class SubjectKind(str, Enum):
    SELF = "self"
    OTHER_PERSON = "other_person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    DEVICE = "device"
    PLACE = "place"
    ABSTRACT_ENTITY = "abstract_entity"


class AssertionModality(str, Enum):
    ASSERTED = "asserted"
    INFERRED = "inferred"
    HYPOTHETICAL = "hypothetical"
    QUOTED = "quoted"
    NEGATED = "negated"
    UNCERTAIN = "uncertain"


class FactCardinality(str, Enum):
    SINGLETON = "singleton"
    SET = "set"
    SCOPED_SINGLETON = "scoped_singleton"
    TEMPORAL_SERIES = "temporal_series"
    EVENT = "event"


class MemoryOperation(str, Enum):
    CREATE = "create"
    REINFORCE = "reinforce"
    REFINE = "refine"
    COEXIST = "coexist"
    SUPERSEDE = "supersede"
    CONTRADICT = "contradict"
    QUARANTINE = "quarantine"
    ARCHIVE = "archive"
    DELETE = "delete"
    NOOP = "noop"
    ROLLBACK = "rollback"


def _required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def _utc(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SemanticSubject:
    kind: SubjectKind
    entity_id: str | None = None
    relation_to_user: str | None = None

    def __post_init__(self) -> None:
        if self.entity_id is not None:
            object.__setattr__(self, "entity_id", _required(self.entity_id, "entity_id"))
        if self.kind is not SubjectKind.SELF and not self.entity_id:
            raise ValueError("non-self subjects require an entity_id")


@dataclass(frozen=True, slots=True)
class SemanticPredicate:
    namespace: str
    relation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _required(self.namespace, "predicate.namespace").casefold())
        object.__setattr__(self, "relation", _required(self.relation, "predicate.relation").casefold())


@dataclass(frozen=True, slots=True)
class SemanticObject:
    type: str
    canonical_value: str
    display_value: str | None = None
    entity_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _required(self.type, "object.type").casefold())
        object.__setattr__(self, "canonical_value", _required(self.canonical_value, "object.canonical_value"))
        if self.display_value is not None:
            object.__setattr__(self, "display_value", _required(self.display_value, "object.display_value"))


@dataclass(frozen=True, slots=True)
class SemanticQualifiers:
    domain: str | None = None
    facet: str | None = None
    context: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    location: str | None = None

    def scope(self) -> dict[str, str]:
        return {
            name: str(value).strip().casefold()
            for name in ("domain", "facet", "context", "project_id", "task_id", "location")
            if (value := getattr(self, name)) is not None and str(value).strip()
        }


@dataclass(frozen=True, slots=True)
class SemanticTemporality:
    observed_at: datetime
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    temporal_scope: str | None = None
    recurrence: str | None = None

    def __post_init__(self) -> None:
        for name in ("observed_at", "valid_from", "valid_until"):
            object.__setattr__(self, name, _utc(getattr(self, name), name))
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("valid_from must not exceed valid_until")


@dataclass(frozen=True, slots=True)
class SemanticConfidence:
    extraction: float
    assertion: float
    source_trust: float
    stability: float | None = None

    def __post_init__(self) -> None:
        for name in ("extraction", "assertion", "source_trust", "stability"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 <= value <= 1.0
            ):
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class SemanticProvenance:
    source_event_id: str
    source_message_id: str
    source_origin: str
    speaker: str
    evidence_text: str
    evidence_span_start: int
    evidence_span_end: int
    extractor: str
    extractor_version: str
    prompt_contract_version: str | None = None

    def __post_init__(self) -> None:
        for name in ("source_event_id", "source_message_id", "source_origin", "speaker",
                     "evidence_text", "extractor", "extractor_version"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if (self.evidence_span_start < 0 or self.evidence_span_end <= self.evidence_span_start
                or self.evidence_span_end - self.evidence_span_start != len(self.evidence_text)):
            raise ValueError("evidence span must match evidence text length")

    @property
    def evidence_hash(self) -> str:
        return hashlib.sha256(self.evidence_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SemanticAssertion:
    """One evidence-bound assertion, not an authorization or mutable belief."""

    tenant_id: str
    user_id: str
    subject: SemanticSubject
    predicate: SemanticPredicate
    object: SemanticObject
    qualifiers: SemanticQualifiers
    temporality: SemanticTemporality
    modality: AssertionModality
    confidence: SemanticConfidence
    cardinality: FactCardinality
    provenance: SemanticProvenance
    schema_version: int = SCHEMA_VERSION
    # This identifier is a derivation only. Governance, consent and lifecycle
    # remain owned by the formation evaluator and NeuroVault.
    extension: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("tenant_id", "user_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported semantic assertion schema version")
        if self.subject.kind is SubjectKind.SELF and self.subject.entity_id not in (None, self.user_id):
            raise ValueError("self subject cannot refer to another user")
        if not isinstance(self.extension, Mapping) or self.extension:
            # Unknown fields must not silently become privileged semantics.
            raise ValueError("v1 assertion extensions are not admitted")

    @property
    def scope_key(self) -> str:
        data = self.qualifiers.scope()
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    @property
    def fact_key(self) -> str:
        """Stable relationship identity; SET members have separate identities.

        Temporal series and events deliberately retain evidence-event identity.
        """
        key: dict[str, str] = {
            "tenant": self.tenant_id,
            "user": self.user_id,
            "subject_kind": self.subject.kind.value,
            "subject_id": self.subject.entity_id or self.user_id,
            "predicate": f"{self.predicate.namespace}.{self.predicate.relation}",
            "object_type": self.object.type,
            "scope": self.scope_key,
        }
        if self.cardinality is FactCardinality.SET:
            key["member"] = self.object.canonical_value.casefold()
        if self.cardinality in (FactCardinality.EVENT, FactCardinality.TEMPORAL_SERIES):
            key["event_id"] = self.provenance.source_event_id
        serialized = json.dumps(key, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# Transport metadata is compatibility state, not semantic assertion authority.
# Keep one boundary policy shared by formation (before vault writes) and
# projection (after successful governed commits).
RUNTIME_METADATA_KEYS = frozenset({
    "request_id", "correlation_id", "tenant_id", "user_id",
    "session_id", "conversation_id", "memory_actor",
})
SEMANTIC_METADATA_KEYS = frozenset({
    "category", "attribute", "normalized_value", "semantic_class",
    "preference_key", "domain", "facet", "scope", "stability",
    "polarity", "retention_scope", "explicit_user_statement",
    "relationship_type", "goal_type", "event_type", "project_id",
    "task_id", "task_type", "location", "cardinality",
    "subject", "predicate", "object", "modality", "temporality",
    "fact_key", "scope_key", "schema_version", "sensitivity",
    "consent_state", "propagation_allowed",
})
RESERVED_MEMORY_METADATA_KEYS = frozenset({
    "signal_semantics", "runtime_context",
})


def merge_memory_metadata(
    *,
    signal_metadata: Mapping[str, Any] | None,
    runtime_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge legacy metadata without crossing semantic/transport ownership.

    This compatibility adapter never interprets semantic facts or grants a
    persistence policy. A disagreeing shared key fails closed before NeuroVault
    commits, and a projected replay uses exactly the same validation.
    """
    if signal_metadata is not None and not isinstance(signal_metadata, Mapping):
        raise ValueError("signal metadata must be a mapping")
    if runtime_metadata is not None and not isinstance(runtime_metadata, Mapping):
        raise ValueError("runtime metadata must be a mapping")
    semantic = dict(signal_metadata or {})
    runtime = dict(runtime_metadata or {})
    if any(not isinstance(key, str) for key in (*semantic, *runtime)):
        raise ValueError("memory metadata keys must be strings")
    if RESERVED_MEMORY_METADATA_KEYS.intersection(semantic) or (
        RESERVED_MEMORY_METADATA_KEYS.intersection(runtime)
    ):
        raise ValueError("reserved memory metadata namespace supplied")

    for key in semantic.keys() & runtime.keys():
        if semantic[key] != runtime[key]:
            namespace = "runtime" if key in RUNTIME_METADATA_KEYS else "semantic"
            raise ValueError(f"conflicting {namespace} projection metadata: {key}")

    # A signal cannot claim transport identity when the runtime has not
    # authenticated/provided it. Matching duplicates are retained only as a
    # backward-compatible read of the same authoritative value.
    for key in RUNTIME_METADATA_KEYS:
        if key in semantic and key not in runtime:
            raise ValueError(f"untrusted runtime projection metadata: {key}")

    merged = dict(runtime)
    merged.update(semantic)
    return merged


__all__ = [
    "SCHEMA_VERSION", "SubjectKind", "AssertionModality", "FactCardinality",
    "MemoryOperation", "SemanticSubject", "SemanticPredicate",
    "SemanticObject", "SemanticQualifiers", "SemanticTemporality",
    "SemanticConfidence", "SemanticProvenance", "SemanticAssertion",
    "SEMANTIC_METADATA_KEYS", "RUNTIME_METADATA_KEYS",
    "RESERVED_MEMORY_METADATA_KEYS", "merge_memory_metadata",
]
