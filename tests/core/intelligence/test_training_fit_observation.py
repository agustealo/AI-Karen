"""Adversarial proof of executor-observed sklearn fit membership."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path

import pytest

from ai_karen_engine.config.learning import LearningSettings
from ai_karen_engine.core.intelligence.ml.training.consumption_evidence import (
    create_sklearn_fit_observation,
    inspect_sklearn_fit_observation,
)
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.datasets import (
    FixtureTrainingDatasetProvider,
    TopologyTrainingExample,
)

_KEY = bytes.fromhex("a4" * 32)
_KEY_ID = "test-key-v1"
_TENANT = "tenant-a"
_JOB = "fit-job-001"
_MODEL = "tenant-142f3a9a-test-model"
_VERSION = "train-fit-001"
_DATASET = "approved-v1"


def _examples(count: int = 40) -> list[TopologyTrainingExample]:
    return [
        TopologyTrainingExample(
            example_id=f"private-example-{i}",
            feature_version="v1",
            features={"count": float(i), "signal": float(i % 3)},
            target="high" if i >= count // 2 else "low",
        )
        for i in range(count)
    ]


def _create(
    examples: list[TopologyTrainingExample] | None = None,
    train_indices: list[int] | None = None,
    holdout_indices: list[int] | None = None,
) -> bytes:
    rows = examples if examples is not None else _examples()
    train = train_indices if train_indices is not None else list(range(30))
    holdout = holdout_indices if holdout_indices is not None else list(range(30, 40))
    return create_sklearn_fit_observation(
        tenant_id=_TENANT, job_id=_JOB, model_id=_MODEL,
        model_version=_VERSION, dataset_version=_DATASET,
        feature_version="v1", seed=7, examples=rows,
        train_indices=train, holdout_indices=holdout,
        key_id=_KEY_ID, key=_KEY,
    )


def _inspect(data: bytes, **overrides):
    kwargs = {
        "tenant_id": _TENANT, "job_id": _JOB, "model_id": _MODEL,
        "model_version": _VERSION, "dataset_version": _DATASET,
        "key_id": _KEY_ID, "key": _KEY,
    }
    kwargs.update(overrides)
    return inspect_sklearn_fit_observation(data, **kwargs)


def test_sklearn_fit_observation_roundtrips_without_leaking_original_rows():
    encoded = _create()
    result = _inspect(encoded)
    assert result is not None
    assert result.worker_observation_integrity_verified is True
    assert result.evidence_sha256 == hashlib.sha256(encoded).hexdigest()
    assert (result.train_count, result.holdout_count) == (30, 10)
    assert result.training_example_inventory_verified is False
    assert result.training_evaluation_disjointness_verified is False
    assert result.independent_oracle_verified is False
    assert result.training_authorized is False
    assert result.execution_authorized is False
    assert result.general_skill_certified is False
    assert b"private-example" not in encoded
    assert b"signal" not in encoded
    assert b"high" not in encoded
    assert b"low" not in encoded


@pytest.mark.parametrize("kwargs", [
    {"tenant_id": "tenant-b"},
    {"job_id": "other-job"},
    {"model_id": "other-model"},
    {"model_version": "other-version"},
    {"dataset_version": "other-dataset"},
    {"key_id": "rotated-key"},
    {"key": b"x" * 32},
])
def test_sklearn_observation_refuses_wrong_authority_or_rotation(kwargs):
    assert _inspect(_create(), **kwargs) is None


def test_sklearn_observation_rejects_forged_permissions_even_with_key():
    payload = json.loads(_create())
    payload["training_authorized"] = True
    body = {k: v for k, v in payload.items() if k != "hmac_sha256"}
    canonical = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()
    payload["hmac_sha256"] = hmac.new(
        _KEY, b"kcm.fit.receipt.v1\0" + canonical(body),
        hashlib.sha256,
    ).hexdigest()
    assert _inspect(canonical(payload)) is None


def test_sklearn_observation_rejects_bad_split_duplicate_ids_and_missing_key():
    rows = _examples()
    with pytest.raises(ValueError, match="Repeated example IDs"):
        _create(
            examples=[rows[0], replace(rows[0]), *rows[2:]],
        )
    with pytest.raises(ValueError, match="Repeated example IDs"):
        _create(train_indices=[0] * 30)
    with pytest.raises(ValueError, match="partition"):
        _create(train_indices=list(range(20)), holdout_indices=list(range(30, 40)))
    with pytest.raises(ValueError, match="key"):
        create_sklearn_fit_observation(
            tenant_id=_TENANT, job_id=_JOB, model_id=_MODEL,
            model_version=_VERSION, dataset_version=_DATASET,
            feature_version="v1", seed=7, examples=rows,
            train_indices=list(range(30)), holdout_indices=list(range(30, 40)),
            key_id=_KEY_ID, key=b"short",
        )


def test_sklearn_observation_rejects_malformed_nested_and_unsigned_receipts():
    encoded = _create()
    assert _inspect(encoded + b" ") is None
    assert _inspect(b"[" * 2000 + b"0" + b"]" * 2000) is None
    assert _inspect(encoded.replace(b'"train_count":30', b'"train_count":31')) is None
    assert _inspect(encoded, key=b"x" * 31) is None
    payload = json.loads(encoded)
    payload["train"][0]["member_hmac"] = payload["holdout"][0]["member_hmac"]
    assert _inspect(json.dumps(payload).encode()) is None


def test_learning_configuration_defaults_off_and_invalid_keys_fail_closed(
    monkeypatch,
):
    setting = LearningSettings()
    assert setting.get_kcm_sklearn_fit_observation_key() is None
    setting.kcm_sklearn_fit_observation_enabled = True
    monkeypatch.delenv("KCM_SKLEARN_FIT_OBSERVATION_HMAC_KEY", raising=False)
    monkeypatch.delenv("KCM_SKLEARN_FIT_OBSERVATION_KEY_ID", raising=False)
    with pytest.raises(ValueError, match="unavailable"):
        setting.get_kcm_sklearn_fit_observation_key()
    monkeypatch.setenv("KCM_SKLEARN_FIT_OBSERVATION_HMAC_KEY", _KEY.hex())
    monkeypatch.setenv("KCM_SKLEARN_FIT_OBSERVATION_KEY_ID", _KEY_ID)
    assert setting.get_kcm_sklearn_fit_observation_key() == (_KEY_ID, _KEY)


def test_real_sklearn_executor_records_exact_fit_indices_not_dataset_claim(
    tmp_path: Path, monkeypatch,
):
    from sklearn.model_selection import train_test_split

    from ai_karen_engine.core.intelligence.ml.training import sklearn_executor

    registry_root = tmp_path / "registry"
    registry_root.mkdir()
    monkeypatch.setattr(
        sklearn_executor, "get_ml_registry_dir", lambda: str(registry_root),
    )
    monkeypatch.setenv("KCM_SKLEARN_FIT_OBSERVATION_HMAC_KEY", _KEY.hex())
    monkeypatch.setenv("KCM_SKLEARN_FIT_OBSERVATION_KEY_ID", _KEY_ID)
    monkeypatch.setattr(
        sklearn_executor, "get_learning_settings",
        lambda: LearningSettings(kcm_sklearn_fit_observation_enabled=True),
    )
    examples = _examples()
    job = TrainingJob(
        job_id=_JOB, task="affect", base_model="sklearn",
        dataset_version=_DATASET,
        metadata={
            "tenant_id": _TENANT, "dataset_scope": "tenant",
            "advanced_config": {
                "test_split": 0.25, "seed": 7, "max_iter": 200,
                "max_samples": 100,
            },
        },
    )
    artifact = sklearn_executor.SklearnTrainingExecutor(
        FixtureTrainingDatasetProvider(examples),
    ).execute(job)
    root = Path(artifact.artifact_path)
    observed = (root / "training_consumption.json").read_bytes()
    metadata = json.loads((root / "training_metadata.json").read_text())
    assert metadata["fit_observation_sha256"] == hashlib.sha256(observed).hexdigest()
    assert metadata["fit_observation_key_id"] == _KEY_ID
    assert sklearn_executor._hash_directory(root) == artifact.artifact_hash
    verified = _inspect(
        observed, model_id=artifact.model_id, model_version=artifact.model_version,
    )
    assert verified is not None
    assert verified.training_example_inventory_verified is False
    indices = list(range(len(examples)))
    labels = [1 if x.target == "low" else 0 for x in examples]
    fitted, heldout = train_test_split(
        indices, random_state=7, test_size=0.25, stratify=labels,
    )
    expected = create_sklearn_fit_observation(
        tenant_id=_TENANT, job_id=_JOB, model_id=artifact.model_id,
        model_version=artifact.model_version, dataset_version=_DATASET,
        feature_version="v1", seed=7, examples=examples,
        train_indices=fitted, holdout_indices=heldout,
        key_id=_KEY_ID, key=_KEY,
    )
    assert observed == expected
    assert (verified.train_count, verified.holdout_count) == (30, 10)


def test_legacy_sklearn_train_does_not_fake_observation(tmp_path, monkeypatch):
    from ai_karen_engine.core.intelligence.ml.training import sklearn_executor

    root = tmp_path / "registry"
    root.mkdir()
    monkeypatch.setattr(sklearn_executor, "get_ml_registry_dir", lambda: str(root))
    monkeypatch.setattr(
        sklearn_executor, "get_learning_settings",
        lambda: LearningSettings(kcm_sklearn_fit_observation_enabled=False),
    )
    result = sklearn_executor.SklearnTrainingExecutor(
        FixtureTrainingDatasetProvider(_examples()),
    ).execute(TrainingJob(
        job_id="legacy-001", task="affect", base_model="sklearn",
        dataset_version="legacy-v1", metadata={
            "advanced_config": {"test_split": 0.25, "max_iter": 200},
        },
    ))
    assert not (Path(result.artifact_path) / "training_consumption.json").exists()
    assert "fit_observation_sha256" not in result.metrics
