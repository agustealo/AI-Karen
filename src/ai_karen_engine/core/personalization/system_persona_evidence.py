"""KCM-02B1: truthful self-knowledge of canonical built-in Persona settings.

This source is deliberately narrower than demonstrated competence. It reads
only the system Persona registry, never user-created Personas, preferences,
chat content, or outcomes. A configuration receipt is not a skill license,
policy permission or independently reviewed training label.

All output uses the existing personalization SelfModel contracts and the
KCM-02A evidence-gated projector. Nothing is persisted or trained.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ai_karen_engine.core.persona.contracts import Persona, SYSTEM_PERSONAS

from .contracts import (
    IdentityDomain,
    IdentityFacet,
    ModelPropertyStatus,
    Provenance,
    SelfModel,
)
from .self_model_projection import (
    OperationalSelfModelRead,
    SelfModelEvidenceAuthority,
    SelfModelEvidenceReceipt,
    SelfModelEvidenceStatus,
    SelfModelEvidenceSubject,
    SelfModelProjector,
    self_model_claim_sha256,
)

_FIELDS: tuple[tuple[str, str], ...] = (
    ("default_tone", "tone"),
    ("default_verbosity", "verbosity"),
    ("default_language", "language"),
)
_REFERENCE_PREFIX = "kcm:persona:system:"


def _tenant_id(tenant_id: str) -> str:
    try:
        candidate = str(uuid.UUID(str(tenant_id).strip()))
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("authenticated tenant UUID required") from exc
    if candidate == str(uuid.UUID(int=0)):
        raise ValueError("authenticated tenant UUID required")
    return candidate


def _canonical_persona_revision(persona: Persona) -> str:
    """Hash the entire current semantic configuration, not uptime clocks."""
    values = persona.model_dump(
        mode="json", exclude={"created_at", "updated_at"},
    )
    payload = json.dumps(
        values, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _PersonaFacetSource:
    evidence_ref: str
    revision: str
    facet: IdentityFacet


def _current_system_facets(*, at: datetime) -> tuple[_PersonaFacetSource, ...]:
    """Re-read actual canonical system Personas on every verification."""
    entries: list[_PersonaFacetSource] = []
    seen: set[str] = set()

    for persona in SYSTEM_PERSONAS:
        if not isinstance(persona, Persona):
            raise ValueError("canonical Persona source invalid")
        if not persona.is_system_persona or not persona.is_active:
            continue
        if not persona.id or ":" in persona.id or persona.id in seen:
            raise ValueError("canonical system Persona identity invalid")
        seen.add(persona.id)
        revision = _canonical_persona_revision(persona)
        for attribute, label in _FIELDS:
            configured = getattr(persona, attribute)
            value = configured.value
            ref = f"{_REFERENCE_PREFIX}{persona.id}:{attribute}"
            facet = IdentityFacet(
                facet_id=ref,
                domain=IdentityDomain.PREFERENCE,
                key=f"persona.system.{persona.id}.{attribute}",
                value=value,
                description=(
                    f"Built-in {persona.id} Persona {label} configuration"
                ),
                provenance=Provenance(
                    source="canonical-system-persona",
                    confidence=1.0,
                    evidence_refs=[ref],
                    first_observed_at=at,
                    last_confirmed_at=at,
                    valid_from=at,
                    valid_until=None,
                    supersedes=None,
                    status=ModelPropertyStatus.CONFIRMED,
                ),
                is_limitation=False,
            )
            entries.append(_PersonaFacetSource(ref, revision, facet))
    return tuple(entries)


class CanonicalSystemPersonaEvidenceReader:
    """In-process configuration verifier, not a general-purpose review issuer.

    tenant_id is explicitly required and normalized even though the built-in
    configuration is globally shared. The resulting SelfModel is still
    tenant-scoped. No individual user's Persona choices are loaded.
    """

    async def verify_many(
        self,
        *,
        tenant_id: str,
        evidence_refs: tuple[str, ...],
    ) -> dict[str, SelfModelEvidenceReceipt]:
        tenant = _tenant_id(tenant_id)
        if not isinstance(evidence_refs, tuple):
            raise ValueError("bounded evidence references required")
        if not evidence_refs or len(evidence_refs) != len(set(evidence_refs)):
            raise ValueError("unique evidence references required")
        if any(
            not isinstance(ref, str)
            or not ref.startswith(_REFERENCE_PREFIX)
            or len(ref) > 200
            for ref in evidence_refs
        ):
            raise ValueError("unknown evidence reference")

        timestamp = datetime.now(timezone.utc)
        actual = {
            row.evidence_ref: row
            for row in _current_system_facets(at=timestamp)
        }
        verified: dict[str, SelfModelEvidenceReceipt] = {}
        for ref in evidence_refs:
            entry = actual.get(ref)
            if entry is None:
                continue
            claim = self_model_claim_sha256(entry.facet)
            if claim is None:
                continue
            receipt_id = hashlib.sha256(
                f"{ref}\x00{entry.revision}\x00{claim}".encode("utf-8")
            ).hexdigest()
            verified[ref] = SelfModelEvidenceReceipt(
                evidence_ref=ref,
                tenant_id=tenant,
                receipt_id=receipt_id,
                source_revision=entry.revision,
                status=SelfModelEvidenceStatus.ACTIVE,
                authority=SelfModelEvidenceAuthority.CONFIGURATION,
                subject=SelfModelEvidenceSubject.KAREN_SELF,
                verified_at=timestamp,
                claim_sha256=claim,
            )
        return verified


class CanonicalSystemPersonaSelfModel:
    """Assemble and verify a *temporary* configuration-only SelfModel.

    The calling runtime must supply its authenticated tenant, and cannot use
    the result as user-specific selection, cognition, training or RBAC truth.
    """

    def __init__(self, *, max_evidence_refs: int) -> None:
        self._reader = CanonicalSystemPersonaEvidenceReader()
        self._projector = SelfModelProjector(
            evidence_reader=self._reader,
            max_evidence_refs=max_evidence_refs,
        )

    async def read(self, *, tenant_id: str) -> OperationalSelfModelRead:
        tenant = _tenant_id(tenant_id)
        now = datetime.now(timezone.utc)
        entries = _current_system_facets(at=now)
        candidate = SelfModel(
            model_id="kcm:canonical-system-personas",
            tenant_id=tenant,
            identity_facets=[entry.facet for entry in entries],
            capability_beliefs=[],
            principles=[],
            limits=[],
            confidence_summary={},
            created_at=now,
            updated_at=now,
            version="1.0.0",
            metadata={"source": "canonical-system-persona"},
        )
        return await self._projector.project(
            model=candidate, tenant_id=tenant,
        )


__all__ = [
    "CanonicalSystemPersonaEvidenceReader",
    "CanonicalSystemPersonaSelfModel",
]
