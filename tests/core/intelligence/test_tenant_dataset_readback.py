"""Real immutable-import readback, scoped FD, and no training authorization."""
from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import Path

import pytest

from ai_karen_engine.core.intelligence.ml.training import dataset_import
from ai_karen_engine.core.intelligence.ml.training.consumption_evidence import (
    create_sklearn_fit_observation,
    inspect_sklearn_fit_input_snapshot,
)
from ai_karen_engine.core.intelligence.ml.training.dataset_import import (
    DatasetImportError,
    import_jsonl_dataset,
    read_tenant_sklearn_dataset_snapshot,
    tenant_dataset_directory,
)
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

_TENANT = "tenant-verified-readback"
_USER = "owner-verified-readback"
_VERSION = "kcm-snapshot-v1"
_KEY = bytes.fromhex("a7" * 32)
_KEY_ID = "test-fit-v1"


def principal(tenant_id: str = _TENANT) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id, user_id=_USER, session_id="verified-session",
    )


def examples():
    return [
        {
            "example_id": f"11111111-2222-3333-4444-{index + 1:012x}",
            "feature_version": "v1",
            "features": {
                "score": (index + 1) / 20,
                "length": index + 11,
            },
            "target": "class-a" if index < 9 else "class-b",
        }
        for index in range(12)
    ]


def canonical(rows) -> bytes:
    return b"".join(
        (
            json.dumps(
                row, ensure_ascii=False, allow_nan=False,
                separators=(",", ":"),
            ) + "\n"
        ).encode("utf-8")
        for row in rows
    )


def publish(tmp_path, rows=None, *, version=_VERSION):
    root = tmp_path / "datasets"
    raw = canonical(examples() if rows is None else rows)
    receipt = import_jsonl_dataset(
        source=BytesIO(raw), root=root, tenant_id=_TENANT,
        version=version,
    )
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    path = tenant_dataset_directory(root, _TENANT) / (version + ".jsonl")
    return root, path, raw, receipt


def snapshot(root, digest, *, subject=None, version=_VERSION, **options):
    return read_tenant_sklearn_dataset_snapshot(
        principal=subject or principal(),
        root=root, version=version, expected_sha256=digest, **options,
    )


def test_canonical_import_roundtrip_exact_fd_bytes_and_all_claims_blocked(tmp_path):
    root, path, raw, receipt = publish(tmp_path)
    result = snapshot(root, receipt["sha256"])
    assert path.read_bytes() == raw == result.raw_bytes
    assert result.sha256 == hashlib.sha256(raw).hexdigest()
    assert result.byte_count == len(raw)
    assert result.row_count == 12
    assert result.dataset_version == _VERSION
    assert result.tenant_id == _TENANT
    assert result.user_id == _USER
    assert [r.example_id for r in result.examples] == [
        r["example_id"] for r in examples()
    ]
    assert result.canonical_tenant_file_read_verified is True
    assert result.supplied_expected_digest_matches is True
    assert result.independently_attested_input_bytes is False
    assert result.source_to_feature_transformation_verified is False
    assert result.source_ancestry_verified is False
    assert result.actual_worker_input_verified is False
    assert result.actual_model_artifact_bound is False
    assert result.training_example_inventory_verified is False
    assert result.training_evaluation_disjointness_verified is False
    assert result.independent_oracle_verified is False
    assert result.training_authorized is False
    assert result.execution_authorized is False
    assert result.general_skill_certified is False
    assert "class-a" not in repr(result)
    assert result.raw_bytes.hex()[:32] not in repr(result)


def test_actual_tenant_readback_can_be_supplied_to_existing_keyed_fit_comparison(
    tmp_path,
):
    root, _, _, receipt = publish(tmp_path)
    readback = snapshot(root, receipt["sha256"])
    rows = list(readback.examples)
    encoded = create_sklearn_fit_observation(
        tenant_id=_TENANT, job_id="real-readback-job",
        model_id="test-tenant-model", model_version="fit-v1",
        dataset_version=_VERSION, feature_version="v1", seed=7,
        examples=rows, train_indices=list(range(9)),
        holdout_indices=list(range(9, 12)),
        key_id=_KEY_ID, key=_KEY,
    )
    concordance = inspect_sklearn_fit_input_snapshot(
        encoded, examples=rows, tenant_id=_TENANT,
        job_id="real-readback-job", model_id="test-tenant-model",
        model_version="fit-v1", dataset_version=_VERSION,
        key_id=_KEY_ID, key=_KEY,
    )
    assert concordance is not None
    assert concordance.receipt_matches_supplied_snapshot is True
    assert concordance.sample_count == readback.row_count
    assert concordance.actual_model_artifact_bound is False
    assert concordance.independently_attested_input_bytes is False
    assert concordance.training_authorized is False
    # Modifying the loaded input invalidates the worker HMAC relation.
    rows[0].features["score"] = 999
    assert inspect_sklearn_fit_input_snapshot(
        encoded, examples=rows, tenant_id=_TENANT,
        job_id="real-readback-job", model_id="test-tenant-model",
        model_version="fit-v1", dataset_version=_VERSION,
        key_id=_KEY_ID, key=_KEY,
    ) is None


@pytest.mark.parametrize("condition", [
    "wrong_tenant", "wrong_digest", "invalid_digest", "path_escape",
    "no_session", "missing_version", "invalid_max_bytes", "invalid_max_rows",
    "too_few_allowed_rows",
])
def test_identity_digest_filename_and_size_guards_fail_closed(tmp_path, condition):
    root, _, raw, receipt = publish(tmp_path)
    options = {}
    subject = principal()
    digest = receipt["sha256"]
    version = _VERSION
    if condition == "wrong_tenant":
        subject = principal("other-tenant")
    elif condition == "wrong_digest":
        digest = "0" * 64
    elif condition == "invalid_digest":
        digest = "not-a-digest"
    elif condition == "path_escape":
        version = "../other"
    elif condition == "no_session":
        subject.session_id = ""
    elif condition == "missing_version":
        version = "not-published"
    elif condition == "invalid_max_bytes":
        options["max_bytes"] = 0
    elif condition == "invalid_max_rows":
        options["max_rows"] = 0
    elif condition == "too_few_allowed_rows":
        options["max_rows"] = 2
    with pytest.raises(DatasetImportError):
        snapshot(root, digest, subject=subject, version=version, **options)
    assert len(raw) > 0


def test_symlinked_file_and_root_fail_closed(tmp_path):
    root, path, _, receipt = publish(tmp_path)
    link = path.parent / "symlink.jsonl"
    link.symlink_to(path)
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"], version="symlink")
    root_link = tmp_path / "datasets-link"
    root_link.symlink_to(root, target_is_directory=True)
    with pytest.raises(DatasetImportError):
        snapshot(root_link, receipt["sha256"])


def test_hardlinked_file_fails_closed(tmp_path):
    root, path, _, receipt = publish(tmp_path)
    duplicate = path.parent / "hardlink.jsonl"
    os.link(path, duplicate)
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"])


def test_in_place_modification_and_same_inode_wrong_expected_hash_fail(tmp_path):
    root, path, raw, receipt = publish(tmp_path)
    path.write_bytes(raw.replace(b"class-a", b"class-x"))
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"])


def test_readback_rejects_mutation_during_fd_stream(tmp_path, monkeypatch):
    root, path, raw, receipt = publish(tmp_path)
    original_read = dataset_import.os.read
    modified = False

    def changing_read(fd, count):
        nonlocal modified
        chunk = original_read(fd, count)
        if chunk and not modified:
            modified = True
            path.write_bytes(raw.replace(b"class-a", b"class-x"))
        return chunk

    monkeypatch.setattr(dataset_import.os, "read", changing_read)
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"])
    assert modified


def test_readback_rejects_renamed_destination_during_fd_stream(
    tmp_path, monkeypatch,
):
    root, path, raw, receipt = publish(tmp_path)
    original_read = dataset_import.os.read
    moved = False

    def replacing_read(fd, count):
        nonlocal moved
        chunk = original_read(fd, count)
        if chunk and not moved:
            moved = True
            replaced = path.parent / "replaced.jsonl"
            replaced.write_bytes(raw)
            os.replace(replaced, path)
        return chunk

    monkeypatch.setattr(dataset_import.os, "read", replacing_read)
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"])
    assert moved


def test_principal_session_mutation_during_readback_fails_closed(
    tmp_path, monkeypatch,
):
    root, _, _, receipt = publish(tmp_path)
    subject = principal()
    original_read = dataset_import.os.read

    def changing_read(fd, count):
        subject.session_id = "changed-while-reading"
        return original_read(fd, count)

    monkeypatch.setattr(dataset_import.os, "read", changing_read)
    with pytest.raises(DatasetImportError, match="session changed"):
        snapshot(root, receipt["sha256"], subject=subject)


@pytest.mark.parametrize("corruption", [
    "duplicate_id", "invalid_feature", "extra_field", "missing_field",
    "zero_features", "nan_value", "noncanonical_spacing", "unicode_separator",
])
def test_canonical_importer_bytes_must_match_strict_sklearn_snapshot(
    tmp_path, corruption,
):
    rows = examples()
    if corruption == "duplicate_id":
        rows[1]["example_id"] = rows[0]["example_id"]
    elif corruption == "invalid_feature":
        rows[0]["features"]["score"] = "not numeric"
    elif corruption == "extra_field":
        rows[0]["invented_authorization"] = True
    elif corruption == "missing_field":
        del rows[0]["target"]
    elif corruption == "zero_features":
        rows[0]["features"] = {}
    elif corruption == "nan_value":
        rows[0]["features"]["score"] = float("nan")
    elif corruption == "unicode_separator":
        rows[0]["target"] = "class\u2028a"
        root, _, _, receipt = publish(tmp_path, rows)
        result = snapshot(root, receipt["sha256"])
        assert result.examples[0].target == "class\u2028a"
        return
    elif corruption == "noncanonical_spacing":
        root, path, raw, receipt = publish(tmp_path)
        # The stored file is no longer normalized even when an expected digest
        # is recomputed from the altered bytes; source authority stays false.
        changed = raw.replace(b'":', b'": ')
        path.write_bytes(changed)
        with pytest.raises(DatasetImportError):
            snapshot(root, hashlib.sha256(changed).hexdigest())
        return
    if corruption == "nan_value":
        with pytest.raises((ValueError, DatasetImportError)):
            publish(tmp_path, rows)
        return
    root, _, _, receipt = publish(tmp_path, rows)
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"])


def test_bounded_bytes_and_row_count(tmp_path):
    root, _, raw, receipt = publish(tmp_path)
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"], max_bytes=len(raw) - 1)
    with pytest.raises(DatasetImportError):
        snapshot(root, receipt["sha256"], max_rows=11)


def test_canonical_listing_unchanged_after_duplicate_cleanup(tmp_path):
    root, _, _, first = publish(tmp_path)
    rows = examples()
    rows[0]["target"] = "changed"
    _, _, _, second = publish(tmp_path, rows, version="kcm-second-v1")
    result = dataset_import.list_tenant_dataset_versions(
        root=root, tenant_id=_TENANT,
    )
    assert [x["version"] for x in result] == [
        "kcm-second-v1", _VERSION,
    ]
    assert {x["sha256"] for x in result} == {
        first["sha256"], second["sha256"],
    }
