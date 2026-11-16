"""Governed, side-effect-free training admission for the Karen Consciousness-Model.

This evaluator is *not* memory admission and does not enqueue data or train a model.
All training approvals require a trusted evidence resolver owned by the host.
Untrusted memory metadata is only allowed to reject or locate evidence, never
assert that verification or consent succeeded.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Mapping, Protocol

if TYPE_CHECKING:
    from .contracts import RuntimeMemoryArtifact

logger = logging.getLogger(__name__)


class TrainingAdmissionStatus(str, Enum):
    POLICY_BLOCKED = "policy_blocked"
    NEEDS_VERIFICATION = "needs_verification"
    REVIEW = "review"
    APPROVED = "approved"


QUALITY_WEIGHTS: Mapping[str, float] = {
    "correctness": 0.30,
    "verified_outcome": 0.20,
    "learning_relevance": 0.20,
    "provenance": 0.15,
    "target_clarity": 0.10,
    "coverage": 0.05,
}


@dataclass(frozen=True, slots=True)
class TrainingAdmissionPolicy:
    """Explicit, versioned policy; activation is disabled until wired and audited."""

    enabled: bool = False
    version: str = "kcm-admission-v1"
    minimum_quality: float = 0.82
    minimum_correctness: float = 0.90
    minimum_provenance: float = 0.80
    supported_objectives: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"persona_expression", "procedural_skill", "verified_correction"}
        )
    )

    def __post_init__(self) -> None:
        for name in ("minimum_quality", "minimum_correctness", "minimum_provenance"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must lie within [0, 1]")
        if not self.version.strip() or not self.supported_objectives:
            raise ValueError("Admission policy requires a version and supported objectives")


@dataclass(frozen=True, slots=True)
class VerifiedTrainingEvidence:
    """Evidence resolved from trusted host stores, never client-provided metadata."""

    tenant_id: str
    user_id: str
    source_ref: str
    source_revision: str
    objective: str
    verification_receipt_id: str
    consent_receipt_id: str
    rights_receipt_id: str
    target_ref: str
    source_valid: bool
    target_verified: bool
    consent_valid: bool
    rights_valid: bool
    sensitivity_cleared: bool
    current: bool
    dimensions: Mapping[str, float]


class TrainingEvidenceResolver(Protocol):
    async def resolve(
        self,
        *,
        tenant_id: str,
        user_id: str,
        source_ref: str,
        source_revision: str,
        objective: str,
    ) -> VerifiedTrainingEvidence | None:
        """Verify source, target, purpose-specific consent and rights externally."""
        ...


@dataclass(frozen=True, slots=True)
class TrainingAdmissionAssessment:
    artifact_id: str
    objective: str
    status: TrainingAdmissionStatus
    reason_codes: tuple[str, ...]
    policy_version: str
    quality_score: float | None = None
    verification_receipt_id: str | None = None

    @property
    def approved(self) -> bool:
        return self.status is TrainingAdmissionStatus.APPROVED


class TrainingAdmissionEvaluator:
    """Read-only quality and governance gate; no persistence or execution."""

    _BLOCKED_TAGS = frozenset(
        {"no_training", "no_export", "sensitive", "restricted", "prohibited"}
    )
    _BLOCKED_STATUSES = frozenset(
        {"deleted", "expired", "revoked", "quarantined", "superseded"}
    )
    _BLOCKED_TRUST = frozenset({"suspicious", "poisoned"})

    def __init__(
        self,
        *,
        policy: TrainingAdmissionPolicy | None = None,
        evidence_resolver: TrainingEvidenceResolver | None = None,
    ) -> None:
        self.policy = policy or TrainingAdmissionPolicy()
        self.evidence_resolver = evidence_resolver

    def _result(
        self,
        artifact_id: str,
        objective: str,
        status: TrainingAdmissionStatus,
        *reason_codes: str,
        quality_score: float | None = None,
        receipt: str | None = None,
    ) -> TrainingAdmissionAssessment:
        return TrainingAdmissionAssessment(
            artifact_id=artifact_id,
            objective=objective,
            status=status,
            reason_codes=tuple(reason_codes),
            policy_version=self.policy.version,
            quality_score=quality_score,
            verification_receipt_id=receipt,
        )

    async def evaluate(
        self,
        artifact: RuntimeMemoryArtifact,
        *,
        objective: str,
    ) -> TrainingAdmissionAssessment:
        artifact_id = str(getattr(artifact, "artifact_id", "") or "")
        objective = str(objective or "").strip()
        blocked = TrainingAdmissionStatus.POLICY_BLOCKED
        pending = TrainingAdmissionStatus.NEEDS_VERIFICATION

        if not self.policy.enabled:
            return self._result(artifact_id, objective, blocked, "admission_disabled")
        if objective not in self.policy.supported_objectives:
            return self._result(artifact_id, objective, blocked, "objective_not_supported")

        tenant_id = str(getattr(artifact, "tenant_id", "") or "").strip()
        user_id = str(getattr(artifact, "user_id", "") or "").strip()
        if not artifact_id or not user_id or not tenant_id or tenant_id == "default":
            return self._result(artifact_id, objective, blocked, "scope_invalid")

        metadata = getattr(artifact, "metadata", None)
        if not isinstance(metadata, dict):
            return self._result(artifact_id, objective, pending, "metadata_unavailable")

        tags = {
            str(getattr(tag, "value", tag)).strip().lower()
            for tag in (getattr(artifact, "privacy_tags", None) or ())
        }
        if tags & self._BLOCKED_TAGS:
            return self._result(artifact_id, objective, blocked, "privacy_prohibits_training")
        upstream_eligibility = getattr(artifact, "training_eligibility", None)
        upstream_value = str(getattr(upstream_eligibility, "value", upstream_eligibility or ""))
        if (
            upstream_value.strip().lower() == "ineligible"
            or str(metadata.get("training_eligibility", "")).strip().lower() == "ineligible"
        ):
            return self._result(artifact_id, objective, blocked, "artifact_ineligible")
        if str(metadata.get("memory_status", "")).strip().lower() in self._BLOCKED_STATUSES:
            return self._result(artifact_id, objective, blocked, "source_not_active")
        if str(metadata.get("trust_class", "")).strip().lower() in self._BLOCKED_TRUST:
            return self._result(artifact_id, objective, blocked, "source_tainted")
        if metadata.get("revoked") is True or metadata.get("taint_indicators"):
            return self._result(artifact_id, objective, blocked, "source_revoked_or_tainted")

        source_ref = str(metadata.get("source_ref") or artifact_id).strip()
        source_revision = str(metadata.get("source_revision") or "").strip()
        if not source_ref or not source_revision:
            return self._result(artifact_id, objective, pending, "immutable_source_missing")
        if self.evidence_resolver is None:
            return self._result(artifact_id, objective, pending, "trusted_resolver_unavailable")

        try:
            evidence = await self.evidence_resolver.resolve(
                tenant_id=tenant_id,
                user_id=user_id,
                source_ref=source_ref,
                source_revision=source_revision,
                objective=objective,
            )
        except Exception:
            logger.warning("kcm.training_admission.evidence_resolution_failed", exc_info=False)
            return self._result(artifact_id, objective, pending, "evidence_resolution_failed")

        if evidence is None:
            return self._result(artifact_id, objective, pending, "evidence_unavailable")
        if (
            evidence.tenant_id != tenant_id
            or evidence.user_id != user_id
            or evidence.source_ref != source_ref
            or evidence.source_revision != source_revision
            or evidence.objective != objective
        ):
            return self._result(artifact_id, objective, blocked, "evidence_scope_mismatch")
        if not evidence.consent_valid or not evidence.consent_receipt_id:
            return self._result(artifact_id, objective, blocked, "training_consent_missing")
        if not evidence.rights_valid or not evidence.rights_receipt_id:
            return self._result(artifact_id, objective, blocked, "training_rights_missing")
        if not evidence.sensitivity_cleared:
            return self._result(artifact_id, objective, blocked, "sensitivity_not_cleared")
        if not evidence.source_valid or not evidence.current:
            return self._result(artifact_id, objective, blocked, "source_invalid_or_stale")
        if not evidence.target_verified or not evidence.target_ref or not evidence.verification_receipt_id:
            return self._result(artifact_id, objective, pending, "training_target_unverified")

        dimensions = dict(evidence.dimensions)
        if set(dimensions) != set(QUALITY_WEIGHTS):
            return self._result(artifact_id, objective, pending, "quality_dimensions_missing")
        if any(
            not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not 0.0 <= value <= 1.0
            for value in dimensions.values()
        ):
            return self._result(artifact_id, objective, pending, "quality_dimensions_invalid")

        quality = sum(dimensions[name] * weight for name, weight in QUALITY_WEIGHTS.items())
        if (
            quality < self.policy.minimum_quality
            or dimensions["correctness"] < self.policy.minimum_correctness
            or dimensions["provenance"] < self.policy.minimum_provenance
        ):
            return self._result(
                artifact_id,
                objective,
                TrainingAdmissionStatus.REVIEW,
                "quality_below_threshold",
                quality_score=quality,
                receipt=evidence.verification_receipt_id,
            )
        return self._result(
            artifact_id,
            objective,
            TrainingAdmissionStatus.APPROVED,
            "verified_for_objective",
            quality_score=quality,
            receipt=evidence.verification_receipt_id,
        )


__all__ = [
    "QUALITY_WEIGHTS",
    "TrainingAdmissionAssessment",
    "TrainingAdmissionEvaluator",
    "TrainingAdmissionPolicy",
    "TrainingAdmissionStatus",
    "TrainingEvidenceResolver",
    "VerifiedTrainingEvidence",
]
