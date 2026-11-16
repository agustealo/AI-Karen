"""KCM dataset preflight verifies source receipts without authorizing training."""

from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

import pytest

from ai_karen_engine.learning.kcm_dataset_preflight import (
    KcmDatasetEvidenceError,
    inspect_kcm_dataset_evidence,
)


def uid(n: int) -> str:
    return str(uuid.UUID(int=n))


TENANT, USER = uid(1), uid(2)
SOURCES = (uid(11), uid(12))
REVISION = "a" * 64


def manifest() -> tuple[dict[str, Any], bytes]:
    content = b"synthetic authorized examples, no personal data"
    members: list[dict[str, Any]] = []
    for i, source in enumerate(SOURCES):
        members.append({
            "assessment_id": uid(31 + i),
            "source_artifact_id": source,
            "source_revision": REVISION,
            "content_sha256": "b" * 64,
            "leakage_group_id": f"group-{i}",
            "split": "train" if i == 0 else "dev",
            "consent_receipt_id": f"consent-{i}",
            "rights_receipt_id": f"rights-{i}",
            "verification_receipt_id": f"verified-{i}",
        })
    return {
        "schema_version": "1.0.0", "dataset_id": uid(3),
        "dataset_version": 1, "tenant_id": TENANT, "owner_user_id": USER,
        "objective_id": "procedural_skill", "objective_version": "v1",
        "status": "frozen", "content_sha256": hashlib.sha256(content).hexdigest(),
        "selection_recipe": {
            "recipe_id": "coverage", "version": "v1",
            "config_sha256": "a" * 64, "seed": 11,
        },
        "members": members,
        "split_strategy": {
            "name": "group", "leakage_group_fields": ["task_id"],
            "test_locked": True,
        },
        "governance": {
            "consent_policy_version": "v1", "license_policy_version": "v1",
            "deletion_epoch": 7, "revocation_check_at": "2026-11-14T00:00:00Z",
        },
        "created_at": "2026-11-15T00:00:00Z", "policy_version": "v1",
    }, content


@dataclass(frozen=True)
class Evidence:
    tenant_id: str
    user_id: str
    source_ref: str
    source_revision: str
    objective: str
    source_valid: bool = True
    current: bool = True
    consent_valid: bool = True
    rights_valid: bool = True
    target_verified: bool = True
    sensitivity_cleared: bool = True
    target_ref: str = "test-target"
    consent_receipt_id: str = ""
    rights_receipt_id: str = ""
    verification_receipt_id: str = ""


class Resolver:
    def __init__(self, evidence: dict[str, Evidence]) -> None:
        self.evidence = evidence
        self.calls = 0

    async def resolve(self, **kwargs: str) -> Evidence | None:
        self.calls += 1
        return self.evidence.get(kwargs["source_ref"])


class Epoch:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.calls = 0

    async def current_epoch(self, **kwargs: str) -> int | None:
        assert kwargs == {"tenant_id": TENANT, "user_id": USER}
        value = self.values[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value  # type: ignore[return-value]


def authority(m: dict[str, Any]) -> Resolver:
    evidence = {}
    for member in m["members"]:
        source = member["source_artifact_id"]
        evidence[source] = Evidence(
            tenant_id=TENANT, user_id=USER, source_ref=source,
            source_revision=REVISION, objective="procedural_skill",
            consent_receipt_id=member["consent_receipt_id"],
            rights_receipt_id=member["rights_receipt_id"],
            verification_receipt_id=member["verification_receipt_id"],
        )
    return Resolver(evidence)


async def check(
    m: dict[str, Any], data: bytes, r: Resolver, e: Epoch,
    *, tenant: str = TENANT, user: str = USER, max_members: int = 100,
):
    return await inspect_kcm_dataset_evidence(
        m, dataset_bytes=data, tenant_id=tenant, user_id=user,
        max_members=max_members, evidence_resolver=r,
        deletion_epoch_reader=e,
    )


@pytest.mark.asyncio
async def test_valid_sources_are_still_not_training_authorization() -> None:
    m, data = manifest()
    report = await check(m, data, authority(m), Epoch(7, 7))
    assert report.member_count == 2
    assert report.deletion_epoch == 7
    assert not report.training_authorized
    assert report.evidence_current
    assert len(report.evidence_sha256) == 64
    assert report.manifest_sha256


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,code", [
    ({"consent_valid": False}, "evidence_not_current_or_approved"),
    ({"rights_valid": False}, "evidence_not_current_or_approved"),
    ({"target_verified": False}, "evidence_not_current_or_approved"),
    ({"source_valid": False}, "evidence_not_current_or_approved"),
    ({"current": False}, "evidence_not_current_or_approved"),
    ({"sensitivity_cleared": False}, "evidence_not_current_or_approved"),
    ({"tenant_id": uid(99)}, "evidence_scope_mismatch"),
    ({"user_id": uid(99)}, "evidence_scope_mismatch"),
    ({"source_revision": "e" * 64}, "evidence_scope_mismatch"),
    ({"target_ref": ""}, "verified_target_missing"),
    ({"consent_receipt_id": "forged"}, "evidence_receipt_mismatch"),
    ({"rights_receipt_id": "forged"}, "evidence_receipt_mismatch"),
    ({"verification_receipt_id": "forged"}, "evidence_receipt_mismatch"),
])
async def test_bad_host_evidence_fails_closed(changes: dict, code: str) -> None:
    m, data = manifest()
    r = authority(m)
    r.evidence[SOURCES[0]] = replace(r.evidence[SOURCES[0]], **changes)
    with pytest.raises(KcmDatasetEvidenceError) as exc:
        await check(m, data, r, Epoch(7, 7))
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_stale_manifest_or_revocation_during_scan_fails() -> None:
    m, data = manifest()
    with pytest.raises(KcmDatasetEvidenceError, match="manifest_integrity_failed"):
        await check(m, data, authority(m), Epoch(8))
    with pytest.raises(KcmDatasetEvidenceError, match="deletion_epoch_changed"):
        await check(m, data, authority(m), Epoch(7, 8))


@pytest.mark.asyncio
async def test_wrong_principal_and_member_budget_rejected_before_access() -> None:
    m, data = manifest()
    r, e = authority(m), Epoch(7, 7)
    with pytest.raises(KcmDatasetEvidenceError, match="principal_scope_mismatch"):
        await check(m, data, r, e, tenant=uid(99))
    with pytest.raises(KcmDatasetEvidenceError, match="member_budget_exceeded"):
        await check(m, data, r, e, max_members=1)
    assert r.calls == 0 and e.calls == 0


@pytest.mark.asyncio
async def test_missing_resolver_and_missing_epoch_are_not_approval() -> None:
    m, data = manifest()
    with pytest.raises(KcmDatasetEvidenceError, match="trusted_authority_unavailable"):
        await inspect_kcm_dataset_evidence(
            m, dataset_bytes=data, tenant_id=TENANT, user_id=USER,
            max_members=100, evidence_resolver=None,
            deletion_epoch_reader=Epoch(7, 7),
        )
    with pytest.raises(KcmDatasetEvidenceError, match="deletion_epoch_unavailable"):
        await check(m, data, authority(m), Epoch(None))


@pytest.mark.asyncio
async def test_evidence_unavailable_or_worker_error() -> None:
    m, data = manifest()
    r = Resolver({})
    with pytest.raises(KcmDatasetEvidenceError, match="evidence_missing"):
        await check(m, data, r, Epoch(7, 7))
    with pytest.raises(KcmDatasetEvidenceError, match="deletion_epoch_unavailable"):
        await check(m, data, authority(m), Epoch(RuntimeError("no db")))


@pytest.mark.asyncio
async def test_dataset_tamper_rejected_before_reading_evidence() -> None:
    m, data = manifest()
    r = authority(m)
    with pytest.raises(KcmDatasetEvidenceError, match="manifest_integrity_failed"):
        await check(m, data + b"tamper", r, Epoch(7, 7))
    assert r.calls == 0


@pytest.mark.asyncio
async def test_evidence_identity_and_hash_stable() -> None:
    m, data = manifest()
    a = await check(m, data, authority(m), Epoch(7, 7))
    b = await check(deepcopy(m), data, authority(m), Epoch(7, 7))
    assert a.evidence_sha256 == b.evidence_sha256
