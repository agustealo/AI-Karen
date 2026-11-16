"""Regression contracts for KCM training admission, isolated from memory retention."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

from ai_karen_engine.echocore.training_admission import (
    QUALITY_WEIGHTS,
    TrainingAdmissionEvaluator,
    TrainingAdmissionPolicy,
    TrainingAdmissionStatus,
    VerifiedTrainingEvidence,
)


@dataclass
class Artifact:
    artifact_id: str = "memory-1"
    tenant_id: str | None = "tenant-a"
    user_id: str = "user-a"
    importance_score: float = 0.99
    retention_score: float = 0.99
    privacy_tags: list[str] = field(default_factory=list)
    training_eligibility: str | None = None
    metadata: dict[str, object] = field(
        default_factory=lambda: {"source_ref": "memory-1", "source_revision": "rev-1"}
    )


def verified_evidence(**updates: object) -> VerifiedTrainingEvidence:
    base = VerifiedTrainingEvidence(
        tenant_id="tenant-a",
        user_id="user-a",
        source_ref="memory-1",
        source_revision="rev-1",
        objective="procedural_skill",
        verification_receipt_id="test-receipt",
        consent_receipt_id="consent-receipt",
        rights_receipt_id="rights-receipt",
        target_ref="verified-target-1",
        source_valid=True,
        target_verified=True,
        consent_valid=True,
        rights_valid=True,
        sensitivity_cleared=True,
        current=True,
        dimensions={name: 0.95 for name in QUALITY_WEIGHTS},
    )
    return replace(base, **updates)


class EvidencePort:
    def __init__(self, evidence: VerifiedTrainingEvidence | None) -> None:
        self.evidence = evidence
        self.calls = 0

    async def resolve(self, **kwargs: object) -> VerifiedTrainingEvidence | None:
        self.calls += 1
        return self.evidence


class BrokenPort:
    async def resolve(self, **kwargs: object) -> VerifiedTrainingEvidence | None:
        raise RuntimeError("downstream secret")


def evaluator(port: EvidencePort | BrokenPort | None = None) -> TrainingAdmissionEvaluator:
    return TrainingAdmissionEvaluator(
        policy=TrainingAdmissionPolicy(enabled=True), evidence_resolver=port
    )


@pytest.mark.asyncio
async def test_disabled_by_default_even_for_important_ltm() -> None:
    result = await TrainingAdmissionEvaluator(policy=TrainingAdmissionPolicy()).evaluate(
        Artifact(), objective="procedural_skill"
    )
    assert result.status is TrainingAdmissionStatus.POLICY_BLOCKED
    assert result.reason_codes == ("admission_disabled",)


@pytest.mark.asyncio
async def test_untrusted_importance_and_quality_metadata_cannot_approve() -> None:
    artifact = Artifact()
    artifact.metadata["verified"] = True
    artifact.metadata["quality_score"] = 1.0
    result = await evaluator().evaluate(artifact, objective="procedural_skill")
    assert result.status is TrainingAdmissionStatus.NEEDS_VERIFICATION


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["no_training", "no_export", "restricted", "sensitive"])
async def test_privacy_vetoes_even_verified_source(tag: str) -> None:
    port = EvidencePort(verified_evidence())
    result = await evaluator(port).evaluate(
        Artifact(privacy_tags=[tag]), objective="procedural_skill"
    )
    assert result.status is TrainingAdmissionStatus.POLICY_BLOCKED
    assert port.calls == 0


@pytest.mark.asyncio
async def test_scope_and_stale_source_fail_closed() -> None:
    res = await evaluator(EvidencePort(verified_evidence())).evaluate(
        Artifact(tenant_id="default"), objective="procedural_skill"
    )
    assert res.reason_codes == ("scope_invalid",)
    res = await evaluator(EvidencePort(verified_evidence())).evaluate(
        Artifact(metadata={"source_ref": "memory-1", "source_revision": "rev-1", "memory_status": "revoked"}),
        objective="procedural_skill",
    )
    assert res.reason_codes == ("source_not_active",)


@pytest.mark.asyncio
async def test_trusted_source_and_purpose_consent_both_required() -> None:
    for updates, reason in [
        ({"tenant_id": "tenant-b"}, "evidence_scope_mismatch"),
        ({"consent_valid": False}, "training_consent_missing"),
        ({"rights_valid": False}, "training_rights_missing"),
        ({"sensitivity_cleared": False}, "sensitivity_not_cleared"),
        ({"current": False}, "source_invalid_or_stale"),
        ({"target_verified": False}, "training_target_unverified"),
    ]:
        decision = await evaluator(EvidencePort(verified_evidence(**updates))).evaluate(
            Artifact(), objective="procedural_skill"
        )
        assert decision.reason_codes == (reason,)
        assert not decision.approved


@pytest.mark.asyncio
async def test_approved_only_with_verified_score_and_receipts() -> None:
    result = await evaluator(EvidencePort(verified_evidence())).evaluate(
        Artifact(), objective="procedural_skill"
    )
    assert result.approved is True
    assert result.quality_score == pytest.approx(0.95)
    assert result.verification_receipt_id == "test-receipt"


@pytest.mark.asyncio
async def test_bad_quality_and_unknown_labels_not_approved() -> None:
    low = verified_evidence(dimensions={name: 0.7 for name in QUALITY_WEIGHTS})
    result = await evaluator(EvidencePort(low)).evaluate(
        Artifact(), objective="procedural_skill"
    )
    assert result.status is TrainingAdmissionStatus.REVIEW
    malformed = verified_evidence(dimensions={"correctness": 1.0})
    result = await evaluator(EvidencePort(malformed)).evaluate(
        Artifact(), objective="procedural_skill"
    )
    assert result.status is TrainingAdmissionStatus.NEEDS_VERIFICATION


@pytest.mark.asyncio
async def test_resolver_failure_is_not_training_success() -> None:
    result = await evaluator(BrokenPort()).evaluate(
        Artifact(), objective="procedural_skill"
    )
    assert result.status is TrainingAdmissionStatus.NEEDS_VERIFICATION
    assert result.reason_codes == ("evidence_resolution_failed",)


def test_policy_rejects_invalid_thresholds() -> None:
    with pytest.raises(ValueError):
        TrainingAdmissionPolicy(minimum_quality=float("nan"))


@pytest.mark.asyncio
async def test_upstream_ineligible_never_promoted() -> None:
    result = await evaluator(EvidencePort(verified_evidence())).evaluate(
        Artifact(training_eligibility="ineligible"), objective="procedural_skill"
    )
    assert result.status is TrainingAdmissionStatus.POLICY_BLOCKED
    assert result.reason_codes == ("artifact_ineligible",)
