"""KCM-02A: evidence-gated view of Karen's canonical personalization SelfModel.

The projection is side-effect free. It does not create another model or memory
store, infer competence from fluent text, grant execution privileges, or train
neural weights. Every displayed claim requires live tenant-scoped evidence
from an explicit independently governed evidence reader.

The trusted reader is deliberately an injected port. Until it is wired to
canonical, reviewed evidence stores, callers cannot claim the view is ready.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from .contracts import (
    CapabilityBelief,
    IdentityFacet,
    ModelPropertyStatus,
    SelfModel,
)


class SelfModelProjectionHealth(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"


class SelfModelEvidenceStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    REVOKED = "revoked"


class SelfModelEvidenceAuthority(str, Enum):
    """Identity configuration is not an independently evaluated skill."""

    CONFIGURATION = "configuration"
    INDEPENDENT_EVALUATION = "independent_evaluation"


@dataclass(frozen=True, slots=True)
class SelfModelEvidenceReceipt:
    """Result returned by an authorized verifier, not caller metadata.

    The verifier is responsible for tenant isolation, signature/reviewer
    checks, source revision, withdrawal and access-control authorization.
    """

    evidence_ref: str
    tenant_id: str
    receipt_id: str
    source_revision: str
    status: SelfModelEvidenceStatus
    authority: SelfModelEvidenceAuthority
    verified_at: datetime
    valid_until: datetime | None = None


class SelfModelEvidenceReader(Protocol):
    """Batch, tenant-scoped verification against canonical evidence owners."""

    async def verify_many(
        self, *, tenant_id: str, evidence_refs: tuple[str, ...]
    ) -> Mapping[str, SelfModelEvidenceReceipt]:
        ...


@dataclass(frozen=True, slots=True)
class OperationalSelfModelRead:
    """Advisory projection only; cannot become a CORTEX or RBAC grant."""

    model: SelfModel
    health: SelfModelProjectionHealth
    checked_at: datetime
    verified_claims: int
    omitted_claims: int
    evidence_sha256: str
    reason_codes: tuple[str, ...]
    execution_authorized: bool = False
    training_authorized: bool = False


_BLOCKED_STATES = frozenset({
    ModelPropertyStatus.DISPUTED,
    ModelPropertyStatus.RETRACTED,
    ModelPropertyStatus.SUPERSEDED,
    ModelPropertyStatus.STALE,
})
_ALLOWED_STATES = frozenset({
    ModelPropertyStatus.EXPLICIT,
    ModelPropertyStatus.CONFIRMED,
    ModelPropertyStatus.OBSERVED,
})


def _utc(value: datetime) -> datetime:
    """Canonical memory records may use naive PostgreSQL UTC timestamps."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _empty(model: SelfModel) -> SelfModel:
    """Return the existing canonical SelfModel shape, never a rival type."""
    return replace(
        model,
        identity_facets=[],
        capability_beliefs=[],
        principles=[],
        limits=[],
        confidence_summary={},
        metadata={},
    )


def _references(model: SelfModel) -> tuple[str, ...]:
    seen: set[str] = set()
    for item in (
        *model.identity_facets, *model.principles, *model.limits,
        *model.capability_beliefs,
    ):
        for value in (
            *item.provenance.evidence_refs,
            *(item.evidence_refs if isinstance(item, CapabilityBelief) else ()),
        ):
            if isinstance(value, str) and value.strip():
                seen.add(value.strip())
    return tuple(sorted(seen))


def _active_receipt(
    ref: str,
    receipts: Mapping[str, SelfModelEvidenceReceipt],
    *,
    tenant_id: str,
    at: datetime,
) -> SelfModelEvidenceReceipt | None:
    receipt = receipts.get(ref)
    if (
        type(receipt) is not SelfModelEvidenceReceipt
        or receipt.evidence_ref != ref
        or receipt.tenant_id != tenant_id
        or not receipt.receipt_id.strip()
        or not receipt.source_revision.strip()
        or receipt.status is not SelfModelEvidenceStatus.ACTIVE
        or _utc(receipt.verified_at) > at
        or (
            receipt.valid_until is not None
            and _utc(receipt.valid_until) <= at
        )
    ):
        return None
    return receipt


def _valid_provenance(
    item: IdentityFacet | CapabilityBelief,
    receipts: Mapping[str, SelfModelEvidenceReceipt],
    *,
    tenant_id: str,
    at: datetime,
    independent: bool,
) -> bool:
    provenance = item.provenance
    if provenance.status in _BLOCKED_STATES:
        return False
    if provenance.status not in _ALLOWED_STATES:
        return False
    if _utc(provenance.valid_from) > at:
        return False
    if provenance.valid_until is not None and _utc(provenance.valid_until) <= at:
        return False
    if independent and provenance.status is not ModelPropertyStatus.CONFIRMED:
        return False

    refs = (
        *provenance.evidence_refs,
        *(item.evidence_refs if isinstance(item, CapabilityBelief) else ()),
    )
    if not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        return False
    verified = [
        _active_receipt(ref.strip(), receipts, tenant_id=tenant_id, at=at)
        for ref in refs
    ]
    if any(receipt is None for receipt in verified):
        return False
    if independent:
        return all(
            receipt is not None
            and receipt.authority is SelfModelEvidenceAuthority.INDEPENDENT_EVALUATION
            for receipt in verified
        )
    return True


class SelfModelProjector:
    """Filter one existing SelfModel with active, independently scoped facts.

    This initial release handles tenant-scoped Karen self-identity only.
    User-specific facts and consent must not be mixed into this view: the
    canonical SelfModel contract currently has tenant_id but no user_id.
    """

    def __init__(
        self,
        *,
        evidence_reader: SelfModelEvidenceReader,
        max_evidence_refs: int,
    ) -> None:
        if evidence_reader is None:
            raise ValueError("trusted evidence reader is required")
        if type(max_evidence_refs) is not int or max_evidence_refs < 1:
            raise ValueError("positive max_evidence_refs is required")
        self._reader = evidence_reader
        self._max_evidence_refs = max_evidence_refs

    async def project(
        self,
        *,
        model: SelfModel,
        tenant_id: str,
        at: datetime | None = None,
    ) -> OperationalSelfModelRead:
        if not isinstance(model, SelfModel):
            raise TypeError("canonical SelfModel required")
        if not tenant_id or model.tenant_id != tenant_id:
            raise PermissionError("self-model tenant scope mismatch")
        if model.metadata.get("user_id") is not None:
            raise PermissionError("user-scoped self-model requires governed user isolation")

        now = _utc(at or datetime.now(timezone.utc))
        refs = _references(model)
        original_count = (
            len(model.identity_facets) + len(model.principles)
            + len(model.limits) + len(model.capability_beliefs)
        )
        safe_model = _empty(model)
        codes: set[str] = set()
        if not refs:
            codes.add("self_model_evidence_missing")
            return OperationalSelfModelRead(
                model=safe_model,
                health=SelfModelProjectionHealth.UNAVAILABLE,
                checked_at=now,
                verified_claims=0,
                omitted_claims=original_count,
                evidence_sha256="",
                reason_codes=tuple(sorted(codes)),
            )
        if len(refs) > self._max_evidence_refs:
            codes.add("self_model_evidence_budget_exceeded")
            return OperationalSelfModelRead(
                model=safe_model,
                health=SelfModelProjectionHealth.UNAVAILABLE,
                checked_at=now,
                verified_claims=0,
                omitted_claims=original_count,
                evidence_sha256="",
                reason_codes=tuple(sorted(codes)),
            )

        try:
            resolved = await self._reader.verify_many(
                tenant_id=tenant_id, evidence_refs=refs
            )
        except Exception:
            codes.add("self_model_evidence_unavailable")
            return OperationalSelfModelRead(
                model=safe_model,
                health=SelfModelProjectionHealth.UNAVAILABLE,
                checked_at=now,
                verified_claims=0,
                omitted_claims=original_count,
                evidence_sha256="",
                reason_codes=tuple(sorted(codes)),
            )
        if not isinstance(resolved, Mapping):
            codes.add("self_model_evidence_invalid")
            return OperationalSelfModelRead(
                model=safe_model,
                health=SelfModelProjectionHealth.UNAVAILABLE,
                checked_at=now,
                verified_claims=0,
                omitted_claims=original_count,
                evidence_sha256="",
                reason_codes=tuple(sorted(codes)),
            )

        # A revoked receipt poisons the entire projection, not merely the
        # corresponding capability: no stale cached claim may stay visible.
        if any(
            receipt is not None
            and receipt.tenant_id == tenant_id
            and receipt.status is SelfModelEvidenceStatus.REVOKED
            for receipt in resolved.values()
        ):
            codes.add("self_model_evidence_revoked")
            return OperationalSelfModelRead(
                model=safe_model,
                health=SelfModelProjectionHealth.REVOKED,
                checked_at=now,
                verified_claims=0,
                omitted_claims=original_count,
                evidence_sha256="",
                reason_codes=tuple(sorted(codes)),
            )

        def facets(items: list[IdentityFacet]) -> list[IdentityFacet]:
            return [
                copy.deepcopy(item) for item in items
                if _valid_provenance(
                    item, resolved, tenant_id=tenant_id,
                    at=now, independent=False,
                )
            ]

        beliefs = [
            copy.deepcopy(item) for item in model.capability_beliefs
            if item.is_self_reference
            and _valid_provenance(
                item, resolved, tenant_id=tenant_id,
                at=now, independent=True,
            )
        ]
        selected = replace(
            safe_model,
            identity_facets=facets(model.identity_facets),
            principles=facets(model.principles),
            limits=facets(model.limits),
            capability_beliefs=beliefs,
        )
        selected_count = (
            len(selected.identity_facets) + len(selected.principles)
            + len(selected.limits) + len(selected.capability_beliefs)
        )
        omitted = original_count - selected_count
        if omitted:
            codes.add("self_model_claims_unverified")
        if not selected_count:
            codes.add("self_model_no_verified_claims")

        used_refs = _references(selected)
        lineage = [
            {
                "ref": ref,
                "receipt": resolved[ref].receipt_id,
                "revision": resolved[ref].source_revision,
                "authority": resolved[ref].authority.value,
            }
            for ref in used_refs
        ]
        digest = (
            hashlib.sha256(
                json.dumps(
                    lineage, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if lineage else ""
        )
        return OperationalSelfModelRead(
            model=selected,
            health=(
                SelfModelProjectionHealth.UNAVAILABLE
                if selected_count == 0
                else SelfModelProjectionHealth.DEGRADED
                if omitted else SelfModelProjectionHealth.READY
            ),
            checked_at=now,
            verified_claims=selected_count,
            omitted_claims=omitted,
            evidence_sha256=digest,
            reason_codes=tuple(sorted(codes)),
        )


__all__ = [
    "SelfModelProjectionHealth",
    "SelfModelEvidenceStatus",
    "SelfModelEvidenceAuthority",
    "SelfModelEvidenceReceipt",
    "SelfModelEvidenceReader",
    "OperationalSelfModelRead",
    "SelfModelProjector",
]
