"""Governed, read-only KCM assessment-to-sklearn-JSONL structural join.

A matching assessment UUID in a training row is NOT an independently
authenticated transformation of a reviewed source artifact, and is not proof
that the row was consumed by an actual model fit. This verifier intentionally
keeps provenance, inventory, disjointness and all authority flags false.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

from .kcm_dataset_preflight import (
    KcmDeletionEpochReader,
    inspect_kcm_dataset_evidence,
)

if TYPE_CHECKING:
    from ai_karen_engine.echocore.training_admission import TrainingEvidenceResolver

logger = logging.getLogger(__name__)

_MAX_MEMBERS = 10_000
_MAX_DATASET_BYTES = 32 * 1024 * 1024
_MAX_FIELDS = 128
_ROW_KEYS = frozenset({"example_id", "feature_version", "features", "target"})


class KcmSklearnAssessmentJoinError(ValueError):
    """A dataset/assessment relationship cannot be accepted as structurally sound."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class KcmSklearnAssessmentJoinReport:
    """Structure and live receipt checks only, never verified training ancestry."""

    manifest_sha256: str
    governed_dataset_sha256: str
    training_jsonl_sha256: str
    evidence_sha256: str
    deletion_epoch: int
    assessment_count: int
    training_row_count: int
    inspected_at: datetime
    frozen_assessment_membership_consistent: bool = True
    evidence_current_at_inspection: bool = True
    training_rows_independently_attested: bool = False
    source_to_feature_transformation_verified: bool = False
    source_ancestry_verified: bool = False
    actual_fit_membership_verified: bool = False
    training_example_inventory_verified: bool = False
    training_evaluation_disjointness_verified: bool = False
    independent_oracle_verified: bool = False
    training_authorized: bool = False
    execution_authorized: bool = False
    general_skill_certified: bool = False


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise KcmSklearnAssessmentJoinError("example_id_not_assessment_uuid")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise KcmSklearnAssessmentJoinError(
            "example_id_not_assessment_uuid",
        ) from None
    if parsed.int == 0 or str(parsed) != value:
        raise KcmSklearnAssessmentJoinError("example_id_not_assessment_uuid")
    return value


def _valid_text(value: object, maximum: int = 128) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= maximum


def _training_assessments(*, encoded: bytes, max_members: int) -> frozenset[str]:
    if not isinstance(encoded, bytes) or not 0 < len(encoded) <= _MAX_DATASET_BYTES:
        raise KcmSklearnAssessmentJoinError("training_jsonl_size_invalid")
    if not encoded.endswith(b"\n"):
        raise KcmSklearnAssessmentJoinError("training_jsonl_not_canonical")
    seen: set[str] = set()
    try:
        decoded = encoded.decode("utf-8")
        lines = decoded.splitlines(keepends=True)
        if len(lines) > max_members:
            raise KcmSklearnAssessmentJoinError("training_row_budget_exceeded")
        if len(lines) < 2:
            raise KcmSklearnAssessmentJoinError("training_rows_insufficient")
        for line in lines:
            record = json.loads(line)
            if not isinstance(record, dict) or set(record) != _ROW_KEYS:
                raise KcmSklearnAssessmentJoinError("training_row_schema_invalid")
            # Match the canonical immutable JSONL importer, not arbitrary
            # JSON representations or user-supplied source references.
            canonical = (
                json.dumps(
                    record, ensure_ascii=False, allow_nan=False,
                    separators=(",", ":"),
                ) + "\n"
            )
            if canonical != line:
                raise KcmSklearnAssessmentJoinError("training_jsonl_not_canonical")
            assessment = _canonical_uuid(record["example_id"])
            if assessment in seen:
                raise KcmSklearnAssessmentJoinError("duplicate_assessment_row")
            seen.add(assessment)
            if not _valid_text(record["feature_version"]):
                raise KcmSklearnAssessmentJoinError("feature_version_invalid")
            if not _valid_text(record["target"]):
                raise KcmSklearnAssessmentJoinError("training_target_invalid")
            features = record["features"]
            if (
                not isinstance(features, dict)
                or not 1 <= len(features) <= _MAX_FIELDS
            ):
                raise KcmSklearnAssessmentJoinError("feature_schema_invalid")
            for name, value in features.items():
                if (
                    not _valid_text(name)
                    or not isinstance(value, (int, float, bool))
                    or not math.isfinite(float(value))
                ):
                    raise KcmSklearnAssessmentJoinError("training_feature_invalid")
    except KcmSklearnAssessmentJoinError:
        raise
    except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError):
        raise KcmSklearnAssessmentJoinError("training_jsonl_invalid") from None
    return frozenset(seen)


def _trusted_claims(principal: AuthenticatedPrincipal) -> tuple[Any, ...]:
    return (
        principal.tenant_id, principal.user_id, principal.session_id,
        tuple(principal.roles), tuple(principal.permissions),
        principal.expires_at,
    )


async def inspect_kcm_sklearn_assessment_join(
    *,
    principal: AuthenticatedPrincipal,
    manifest: Mapping[str, Any],
    governed_dataset_bytes: bytes,
    training_jsonl_bytes: bytes,
    evidence_resolver: TrainingEvidenceResolver,
    deletion_epoch_reader: KcmDeletionEpochReader,
    max_members: int = _MAX_MEMBERS,
) -> KcmSklearnAssessmentJoinReport:
    """Compare exact frozen train assessment IDs to canonical sklearn row IDs.

    The caller must supply bytes loaded through separately authorized, trusted
    storage ports. Their origin cannot be established by this function, so
    matching IDs never imply an independent source-to-feature transform, actual
    fit use, split disjointness, or training permission.

    Recheck receipts and deletion epoch after parsing, because approvals may
    have been revoked during even a read-only inspection.
    """
    if (
        not isinstance(principal, AuthenticatedPrincipal)
        or principal.is_expired()
        or not _valid_text(principal.session_id, 256)
    ):
        raise PermissionError("Authenticated owner session required")
    if (
        type(max_members) is not int
        or not 2 <= max_members <= _MAX_MEMBERS
        or not isinstance(governed_dataset_bytes, bytes)
        or not 0 < len(governed_dataset_bytes) <= _MAX_DATASET_BYTES
    ):
        raise KcmSklearnAssessmentJoinError("inspection_budget_invalid")
    if not isinstance(manifest, Mapping):
        raise KcmSklearnAssessmentJoinError("manifest_invalid")
    identity = _trusted_claims(principal)
    principal_kwargs = {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
    }
    initial = await inspect_kcm_dataset_evidence(
        manifest,
        dataset_bytes=governed_dataset_bytes,
        max_members=max_members,
        evidence_resolver=evidence_resolver,
        deletion_epoch_reader=deletion_epoch_reader,
        **principal_kwargs,
    )
    train_members = manifest["members"]
    approved_ids = frozenset(
        member["assessment_id"] for member in train_members
        if member["split"] == "train"
    )
    if not 2 <= len(approved_ids) <= max_members:
        raise KcmSklearnAssessmentJoinError("frozen_train_budget_invalid")
    training_ids = _training_assessments(
        encoded=training_jsonl_bytes, max_members=max_members,
    )
    if training_ids != approved_ids:
        # A dev/test member in the importer, an unrecognized UUID, duplicate
        # or omitted train row must not be silently accepted.
        raise KcmSklearnAssessmentJoinError("assessment_training_join_mismatch")

    final = await inspect_kcm_dataset_evidence(
        manifest,
        dataset_bytes=governed_dataset_bytes,
        max_members=max_members,
        evidence_resolver=evidence_resolver,
        deletion_epoch_reader=deletion_epoch_reader,
        **principal_kwargs,
    )
    if (
        principal.is_expired()
        or _trusted_claims(principal) != identity
        or final.manifest_sha256 != initial.manifest_sha256
        or final.dataset_sha256 != initial.dataset_sha256
        or final.evidence_sha256 != initial.evidence_sha256
        or final.deletion_epoch != initial.deletion_epoch
        or final.member_count != initial.member_count
    ):
        raise KcmSklearnAssessmentJoinError("governed_evidence_changed")
    logger.info(
        "kcm.sklearn_assessment_join.structural_check",
        extra={
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "manifest_sha256": final.manifest_sha256,
            "training_row_count": len(training_ids),
            "source_ancestry_verified": False,
            "training_example_inventory_verified": False,
        },
    )
    if principal.is_expired() or _trusted_claims(principal) != identity:
        raise KcmSklearnAssessmentJoinError("principal_changed")
    return KcmSklearnAssessmentJoinReport(
        manifest_sha256=final.manifest_sha256,
        governed_dataset_sha256=final.dataset_sha256,
        training_jsonl_sha256=hashlib.sha256(training_jsonl_bytes).hexdigest(),
        evidence_sha256=final.evidence_sha256,
        deletion_epoch=final.deletion_epoch,
        assessment_count=len(approved_ids),
        training_row_count=len(training_ids),
        inspected_at=datetime.now(timezone.utc),
    )


__all__ = [
    "KcmSklearnAssessmentJoinError",
    "KcmSklearnAssessmentJoinReport",
    "inspect_kcm_sklearn_assessment_join",
]
