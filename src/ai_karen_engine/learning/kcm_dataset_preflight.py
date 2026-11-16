"""Fail-closed KCM dataset evidence preflight, not training authorization.

The integrity inspector verifies manifest structure. This layer refreshes its
provenance via the existing EchoCore TrainingEvidenceResolver contract and
requires an independently trusted, tenant/user-scoped deletion epoch reader.
No caller can use the resulting report to authorize training: authorization
and atomic revocation fencing belong to a later governed training executor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from .kcm_dataset_integrity import (
    KcmManifestIntegrityError,
    inspect_kcm_dataset_manifest,
)

if TYPE_CHECKING:
    from ai_karen_engine.echocore.training_admission import (
        TrainingEvidenceResolver,
        VerifiedTrainingEvidence,
    )

logger = logging.getLogger(__name__)


class KcmDatasetEvidenceError(ValueError):
    """Refuse a manifest whose live evidence cannot be independently proven."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class KcmDeletionEpochReader(Protocol):
    """Canonical host-owned tenant and user scoped revocation watermark."""

    async def current_epoch(self, *, tenant_id: str, user_id: str) -> int | None:
        """Return a trustworthy epoch or None if not provisioned."""
        ...


@dataclass(frozen=True, slots=True)
class KcmDatasetPreflightReport:
    """An evidence audit receipt; explicitly never a model-execution grant."""

    manifest_sha256: str
    dataset_sha256: str
    evidence_sha256: str
    member_count: int
    deletion_epoch: int
    inspected_at: datetime
    evidence_current: bool = True
    training_authorized: bool = False


def _identity(value: object) -> str:
    return str(value or "").strip()


def _same(a: object, b: object) -> bool:
    return hmac.compare_digest(_identity(a).encode(), _identity(b).encode())


def _verified(
    evidence: VerifiedTrainingEvidence | None,
    *,
    tenant_id: str,
    user_id: str,
    source_ref: str,
    source_revision: str,
    objective: str,
    member: Mapping[str, Any],
) -> str | None:
    if evidence is None:
        return "evidence_missing"
    for name, expected in (
        ("tenant_id", tenant_id),
        ("user_id", user_id),
        ("source_ref", source_ref),
        ("source_revision", source_revision),
        ("objective", objective),
    ):
        if not _same(getattr(evidence, name, ""), expected):
            return "evidence_scope_mismatch"
    for name in (
        "source_valid", "current", "consent_valid", "rights_valid",
        "target_verified", "sensitivity_cleared",
    ):
        if getattr(evidence, name, None) is not True:
            return "evidence_not_current_or_approved"
    if not _identity(getattr(evidence, "target_ref", None)):
        return "verified_target_missing"
    for name, manifest_key in (
        ("consent_receipt_id", "consent_receipt_id"),
        ("rights_receipt_id", "rights_receipt_id"),
        ("verification_receipt_id", "verification_receipt_id"),
    ):
        if not _same(getattr(evidence, name, None), member.get(manifest_key)):
            return "evidence_receipt_mismatch"
    return None


async def inspect_kcm_dataset_evidence(
    manifest: Mapping[str, Any],
    *,
    dataset_bytes: bytes,
    tenant_id: str,
    user_id: str,
    max_members: int,
    evidence_resolver: TrainingEvidenceResolver,
    deletion_epoch_reader: KcmDeletionEpochReader,
) -> KcmDatasetPreflightReport:
    """Recheck every manifest member and a deletion epoch at both boundaries.

    These host-injected ports MUST NOT consume untrusted metadata as approval.
    All inputs are scoped to an independently authenticated principal. This
    non-atomic inspection is only diagnostic: the future worker must acquire a
    durable revocation fence and repeat checks at training start and promotion.
    """
    if evidence_resolver is None or deletion_epoch_reader is None:
        raise KcmDatasetEvidenceError("trusted_authority_unavailable")
    if type(max_members) is not int or max_members < 1:
        raise KcmDatasetEvidenceError("member_budget_invalid")
    if not isinstance(manifest, Mapping):
        raise KcmDatasetEvidenceError("manifest_invalid")
    if not _same(manifest.get("tenant_id"), tenant_id) or not _same(
        manifest.get("owner_user_id"), user_id
    ):
        raise KcmDatasetEvidenceError("principal_scope_mismatch")
    members = manifest.get("members")
    if not isinstance(members, list) or len(members) > max_members:
        raise KcmDatasetEvidenceError("member_budget_exceeded")

    try:
        before = await deletion_epoch_reader.current_epoch(
            tenant_id=tenant_id, user_id=user_id
        )
    except Exception:
        logger.warning("kcm.preflight.epoch_reader_error")
        raise KcmDatasetEvidenceError("deletion_epoch_unavailable") from None
    if type(before) is not int or before < 0:
        raise KcmDatasetEvidenceError("deletion_epoch_unavailable")
    try:
        integrity = inspect_kcm_dataset_manifest(
            manifest, dataset_bytes=dataset_bytes,
            current_deletion_epoch=before,
        )
    except KcmManifestIntegrityError:
        raise KcmDatasetEvidenceError("manifest_integrity_failed") from None

    receipts: list[tuple[str, str, str, str, str]] = []
    for member in members:
        source = member["source_artifact_id"]
        revision = member["source_revision"]
        try:
            evidence = await evidence_resolver.resolve(
                tenant_id=tenant_id,
                user_id=user_id,
                source_ref=source,
                source_revision=revision,
                objective=manifest["objective_id"],
            )
        except Exception:
            logger.warning("kcm.preflight.evidence_reader_error")
            raise KcmDatasetEvidenceError("evidence_resolution_failed") from None
        failure = _verified(
            evidence, tenant_id=tenant_id, user_id=user_id,
            source_ref=source, source_revision=revision,
            objective=manifest["objective_id"], member=member,
        )
        if failure is not None:
            raise KcmDatasetEvidenceError(failure)
        receipts.append((
            source, revision, member["consent_receipt_id"],
            member["rights_receipt_id"], member["verification_receipt_id"],
        ))

    try:
        after = await deletion_epoch_reader.current_epoch(
            tenant_id=tenant_id, user_id=user_id
        )
    except Exception:
        logger.warning("kcm.preflight.epoch_recheck_error")
        raise KcmDatasetEvidenceError("deletion_epoch_recheck_failed") from None
    if type(after) is not int or after != before:
        raise KcmDatasetEvidenceError("deletion_epoch_changed")

    receipt_digest = hashlib.sha256(json.dumps(
        receipts, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return KcmDatasetPreflightReport(
        manifest_sha256=integrity.manifest_sha256,
        dataset_sha256=integrity.dataset_sha256,
        evidence_sha256=receipt_digest,
        member_count=integrity.member_count,
        deletion_epoch=after,
        inspected_at=datetime.now(timezone.utc),
    )


__all__ = [
    "KcmDatasetEvidenceError", "KcmDeletionEpochReader",
    "KcmDatasetPreflightReport", "inspect_kcm_dataset_evidence",
]
