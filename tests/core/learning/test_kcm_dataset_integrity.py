"""Adversarial, side-effect-free KCM manifest integrity checks."""

from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy

import pytest

from ai_karen_engine.learning.kcm_dataset_integrity import (
    KcmManifestIntegrityError,
    inspect_kcm_dataset_manifest,
)


def uid(n: int) -> str:
    return str(uuid.UUID(int=n))


def member(n: int, split: str, *, group: str | None = None) -> dict:
    return {
        "assessment_id": uid(n + 20),
        "source_artifact_id": uid(n + 200),
        "source_revision": f"{n:064x}",
        "content_sha256": f"{n + 100:064x}",
        "leakage_group_id": group or f"case-{n}",
        "split": split,
        "consent_receipt_id": uid(n + 40),
        "rights_receipt_id": uid(n + 50),
        "verification_receipt_id": uid(n + 60),
    }


def fixture() -> tuple[dict, bytes]:
    data = b"synthetic training records for test only"
    return {
        "schema_version": "1.0.0", "dataset_id": uid(1),
        "dataset_version": 1, "tenant_id": uid(2), "owner_user_id": uid(3),
        "objective_id": "procedural_skill", "objective_version": "v1",
        "status": "frozen", "content_sha256": hashlib.sha256(data).hexdigest(),
        "selection_recipe": {"recipe_id": "coverage", "version": "v1", "config_sha256": "a" * 64, "seed": 13},
        "members": [member(1, "train"), member(2, "dev"), member(3, "test")],
        "split_strategy": {"name": "by-task", "leakage_group_fields": ["task_id"], "test_locked": True},
        "governance": {"consent_policy_version": "v1", "license_policy_version": "v1", "deletion_epoch": 4, "revocation_check_at": "2026-11-15T00:00:00Z"},
        "created_at": "2026-11-16T00:00:00Z", "policy_version": "v1",
    }, data


def inspect(manifest: dict, data: bytes, *, epoch: int = 4):
    return inspect_kcm_dataset_manifest(manifest, dataset_bytes=data, current_deletion_epoch=epoch)


def test_manifest_reproducible_integrity_not_training_authorization() -> None:
    manifest, data = fixture()
    one = inspect(manifest, data)
    two = inspect(deepcopy(manifest), data)
    assert one.manifest_sha256 == two.manifest_sha256
    assert (one.member_count, one.group_count, one.train_count, one.dev_count, one.test_count) == (3, 3, 1, 1, 1)
    assert one.training_authorized is False


@pytest.mark.parametrize("mutation", [
    lambda m: m["members"][0].update({"source_revision": 1}),
    lambda m: m["members"][1].update({"leakage_group_id": "case-1"}),
    lambda m: m["members"][1].update({"source_revision": m["members"][0]["source_revision"], "source_artifact_id": m["members"][0]["source_artifact_id"]}),
    lambda m: m["members"][0].update({"consent_receipt_id": ""}),
    lambda m: m["members"][2].update({"target_text": "raw private data must not be in manifest"}),
    lambda m: m.update({"owner_user_id": "wrong-user"}),
    lambda m: m.update({"created_at": "2026-11-16"}),
    lambda m: m["split_strategy"].update({"test_locked": False}),
    lambda m: m.update({"status": "approved"}),
    lambda m: m["selection_recipe"].update({"private_text": "not a recipe field"}),
    lambda m: m["governance"].update({"raw_user_data": "not governance"}),
    lambda m: m["split_strategy"].update({"sensitive_content": "not a split key"}),
    lambda m: m.update({"model_compatibility": {"unverified_user_data": "no"}}),
])
def test_rejects_bad_lineage_or_privacy_shape(mutation) -> None:
    m, data = fixture()
    mutation(m)
    with pytest.raises(KcmManifestIntegrityError):
        inspect(m, data)


def test_dataset_bytes_and_deletion_epoch_cannot_be_faked_by_metadata() -> None:
    m, data = fixture()
    with pytest.raises(KcmManifestIntegrityError, match="content digest"):
        inspect(m, data + b"tampering")
    with pytest.raises(KcmManifestIntegrityError, match="deletion epoch"):
        inspect(m, data, epoch=5)


def test_member_order_required_for_reproducible_frozen_release() -> None:
    m, data = fixture()
    m["members"].reverse()
    with pytest.raises(KcmManifestIntegrityError, match="canonical order"):
        inspect(m, data)


def test_missing_authoritative_epoch_cannot_pass_validation() -> None:
    m, data = fixture()
    with pytest.raises(KcmManifestIntegrityError):
        inspect_kcm_dataset_manifest(m, dataset_bytes=data, current_deletion_epoch=None)  # type: ignore[arg-type]
