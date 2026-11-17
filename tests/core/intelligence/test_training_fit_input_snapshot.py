"""Adversarial proof that a keyed fit receipt matches supplied row content.

Input rows are not independently sourced or authenticated by this unit. Tests
must never claim training inventory, model artifact provenance or permission.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO

import pytest

from ai_karen_engine.core.intelligence.ml.training.consumption_evidence import (
    create_sklearn_fit_observation,
    inspect_sklearn_fit_input_snapshot,
)
from ai_karen_engine.core.intelligence.ml.training.dataset_import import (
    import_jsonl_dataset,
    tenant_dataset_directory,
)
from ai_karen_engine.core.intelligence.ml.training.datasets import (
    JsonlTrainingDatasetProvider,
    TopologyTrainingExample,
)

_KEY = bytes.fromhex("d7" * 32)
_KEY_ID = "kcm-test-key"
_TENANT = "tenant-sample-owner"
_JOB = "job-frozen-snapshot"
_MODEL = "tenant-model-fit"
_VERSION = "train-r1"
_DATASET = "tenant-snapshot-v1"


def rows() -> list[TopologyTrainingExample]:
    return [
        TopologyTrainingExample(
            example_id=f"synthetic-assessment-{index}",
            feature_version="feature-v1",
            features={"confidence": index / 20, "sample_size": index + 3},
            target="class-a" if index < 6 else "class-b",
        )
        for index in range(12)
    ]


def seal(examples=None):
    source = rows() if examples is None else examples
    return create_sklearn_fit_observation(
        tenant_id=_TENANT, job_id=_JOB, model_id=_MODEL,
        model_version=_VERSION, dataset_version=_DATASET,
        feature_version="feature-v1", seed=7,
        examples=source, train_indices=list(range(9)),
        holdout_indices=list(range(9, 12)),
        key_id=_KEY_ID, key=_KEY,
    )


def inspect(encoded=None, examples=None, **overrides):
    context = {
        "encoded": seal() if encoded is None else encoded,
        "examples": rows() if examples is None else examples,
        "tenant_id": _TENANT, "job_id": _JOB,
        "model_id": _MODEL, "model_version": _VERSION,
        "dataset_version": _DATASET, "key_id": _KEY_ID, "key": _KEY,
    }
    context.update(overrides)
    return inspect_sklearn_fit_input_snapshot(**context)


def test_receipt_matches_complete_supplied_snapshot_without_promoting_claims():
    evidence = seal()
    result = inspect(evidence)
    assert result is not None
    assert result.receipt_sha256 == hashlib.sha256(evidence).hexdigest()
    assert result.receipt_matches_supplied_snapshot is True
    assert (result.sample_count, result.observed_train_count, result.observed_holdout_count) == (
        12, 9, 3,
    )
    assert result.observation_key_id == _KEY_ID
    assert result.independently_attested_input_bytes is False
    assert result.source_to_feature_transformation_verified is False
    assert result.source_ancestry_verified is False
    assert result.actual_model_artifact_bound is False
    assert result.training_example_inventory_verified is False
    assert result.training_evaluation_disjointness_verified is False
    assert result.independent_oracle_verified is False
    assert result.training_authorized is False
    assert result.execution_authorized is False
    assert result.general_skill_certified is False
    assert "synthetic-assessment-" not in repr(result)
    assert "class-a" not in repr(result)
    assert "confidence" not in repr(result)


def test_snapshot_input_row_order_does_not_change_hmac_multiset():
    records = rows()
    assert inspect(examples=list(reversed(records))) is not None


@pytest.mark.parametrize("alter", [
    "id", "feature", "target", "feature_version", "feature_name",
    "duplicate_id", "missing", "additional", "nan_feature", "non_numeric",
])
def test_any_row_id_content_or_count_difference_is_rejected(alter):
    records = rows()
    if alter == "id":
        records[0] = replace(records[0], example_id="forged-id")
    elif alter == "feature":
        records[0].features["confidence"] = 9876.2
    elif alter == "target":
        records[0] = replace(records[0], target="forged-label")
    elif alter == "feature_version":
        records[0] = replace(records[0], feature_version="v2")
    elif alter == "feature_name":
        records[0].features["new_name"] = records[0].features.pop("confidence")
    elif alter == "duplicate_id":
        records[1] = replace(records[1], example_id=records[0].example_id)
    elif alter == "missing":
        records.pop()
    elif alter == "additional":
        records.append(replace(records[0], example_id="extra-row"))
    elif alter == "nan_feature":
        records[0].features["confidence"] = float("nan")
    else:
        records[0].features["confidence"] = object()
    assert inspect(examples=records) is None


@pytest.mark.parametrize("scope", [
    {"tenant_id": "wrong-tenant"},
    {"job_id": "wrong-job"},
    {"model_id": "wrong-model"},
    {"model_version": "wrong-model-version"},
    {"dataset_version": "wrong-dataset-version"},
    {"key_id": "rotated"},
    {"key": b"z" * 32},
    {"key": b"too-short"},
])
def test_wrong_owner_job_model_dataset_or_key_fails_closed(scope):
    assert inspect(**scope) is None


@pytest.mark.parametrize("payload", [
    b"",
    b"{\"invalid\":true}\n",
    b"[" * 2000 + b"0" + b"]" * 2000,
])
def test_malformed_or_unkeyed_receipts_fail_closed(payload):
    assert inspect(encoded=payload) is None


def test_modified_or_unsigned_receipt_fails_closed():
    original = seal()
    assert inspect(encoded=original + b" ") is None
    assert inspect(encoded=original.replace(b'"train_count":9', b'"train_count":8')) is None


def test_null_wrong_type_and_unbounded_rows_fail_closed():
    assert inspect(examples=[]) is None
    assert inspect(examples=[1, 2]) is None
    assert inspect(examples=tuple(rows()) * 900) is None
    assert inspect(examples="not a sequence of verified rows") is None


def test_real_canonical_tenant_jsonl_importer_roundtrip_is_concordant(tmp_path):
    import json

    original = rows()
    raw = b"".join(
        (
            json.dumps({
                "example_id": item.example_id,
                "feature_version": item.feature_version,
                "features": item.features,
                "target": item.target,
            }, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()
        for item in original
    )
    root = tmp_path / "datasets"
    result = import_jsonl_dataset(
        source=BytesIO(raw), root=root, tenant_id=_TENANT, version=_DATASET,
    )
    assert result["rows"] == len(original)
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    imported = JsonlTrainingDatasetProvider(
        tenant_dataset_directory(root, _TENANT),
    ).load(_DATASET)
    proof = inspect(encoded=seal(original), examples=imported)
    assert proof is not None
    assert proof.receipt_matches_supplied_snapshot
    assert not proof.independently_attested_input_bytes
    assert not proof.actual_model_artifact_bound
    assert not proof.training_authorized



@pytest.mark.parametrize("mutation", [
    "huge_feature_string", "huge_feature_name", "huge_target",
    "huge_feature_version", "too_many_features", "huge_integer",
])
def test_oversized_supplied_content_rejected_before_hmac_serialization(
    monkeypatch, mutation,
):
    """A small valid receipt must not cause unbounded sample JSON work."""
    from ai_karen_engine.core.intelligence.ml.training import (
        consumption_evidence,
    )

    source = rows()
    if mutation == "huge_feature_string":
        source[0].features["confidence"] = "x" * (16 * 1024 * 1024)
    elif mutation == "huge_feature_name":
        source[0].features["y" * (16 * 1024 * 1024)] = 1
    elif mutation == "huge_target":
        source[0] = replace(source[0], target="z" * (2 * 1024 * 1024))
    elif mutation == "huge_feature_version":
        source[0] = replace(
            source[0], feature_version="v" * (2 * 1024 * 1024),
        )
    elif mutation == "too_many_features":
        source[0] = replace(source[0], features={str(i): i for i in range(129)})
    else:
        source[0].features["confidence"] = 1 << 10000

    def disallow_hmac_serialization(*args, **kwargs):
        raise AssertionError("unbounded input reached HMAC serialization")

    baseline_receipt = seal()
    monkeypatch.setattr(
        consumption_evidence, "_members", disallow_hmac_serialization,
    )
    assert inspect(encoded=baseline_receipt, examples=source) is None


def test_aggregate_snapshot_budget_enforced_before_commitment_build(
    monkeypatch,
):
    from ai_karen_engine.core.intelligence.ml.training import (
        consumption_evidence,
    )

    feature_names = {
        f"{index:04d}_" + "k" * 123: index
        for index in range(128)
    }
    many = [
        TopologyTrainingExample(
            example_id=f"snapshot-row-{index}",
            feature_version="v1",
            features=feature_names,
            target="class-a" if index < 30 else "class-b",
        )
        for index in range(60)
    ]
    encoded = create_sklearn_fit_observation(
        tenant_id=_TENANT, job_id=_JOB, model_id=_MODEL,
        model_version=_VERSION, dataset_version=_DATASET,
        feature_version="v1", seed=7, examples=many,
        train_indices=list(range(45)),
        holdout_indices=list(range(45, 60)),
        key_id=_KEY_ID, key=_KEY,
    )

    def disallow_hmac_serialization(*args, **kwargs):
        raise AssertionError("oversized aggregate reached HMAC serialization")

    monkeypatch.setattr(
        consumption_evidence, "_members", disallow_hmac_serialization,
    )
    assert inspect(encoded=encoded, examples=many) is None
