"""Tenant, lifecycle, and artifact integrity boundaries for spaCy inference."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest
from ai_karen_engine.core.intelligence.ml.predictors.registry_spacy import RegistryBackedSpacyPredictor
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry


def _candidate(tmp_path: Path, tenant: str = "tenant-a"):
    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "config.cfg").write_text("artifact", encoding="utf-8")
    from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory
    key = hashlib.sha256(tenant.encode()).hexdigest()[:16]
    model_id = f"tenant-{key}-intent-spacy-test"
    manifest = MLModelManifest(
        model_id=model_id, purpose="intent", architecture="spacy",
        artifact_path=str(artifact), artifact_hash=_hash_directory(artifact),
        model_version="v1", feature_version="spacy_textcat_v1",
        metrics={"mode": "textcat"}, status="CANDIDATE",
    )
    registry.register(manifest)
    return registry, manifest


def test_candidate_requires_explicit_approval_and_tenant_scope(tmp_path):
    registry, candidate = _candidate(tmp_path)
    predictor = RegistryBackedSpacyPredictor(registry=registry)
    with pytest.raises(ValueError, match="not eligible"):
        predictor._verified(model_id=candidate.model_id, tenant_id="tenant-a", allow_candidate=False)
    with pytest.raises(PermissionError, match="outside tenant"):
        predictor._verified(model_id=candidate.model_id, tenant_id="tenant-b", allow_candidate=True)
    assert predictor._verified(
        model_id=candidate.model_id, tenant_id="tenant-a", allow_candidate=True,
    ).model_id == candidate.model_id


def test_tampered_spacy_candidate_is_rejected_before_loading(tmp_path):
    registry, candidate = _candidate(tmp_path)
    (Path(candidate.artifact_path) / "config.cfg").write_text("tampered", encoding="utf-8")
    predictor = RegistryBackedSpacyPredictor(registry=registry)
    with pytest.raises(ValueError, match="integrity"):
        predictor._verified(model_id=candidate.model_id, tenant_id="tenant-a", allow_candidate=True)


@pytest.mark.asyncio
async def test_spacy_classification_candidate_uses_canonical_prediction_contract(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
    from ai_karen_engine.core.intelligence.ml.predictors.registry_spacy import (
        SpacyCandidateBenchmarkPredictor,
    )

    registry, candidate = _candidate(tmp_path)
    adapter = SpacyCandidateBenchmarkPredictor(
        registry=registry, tenant_id="tenant-a",
        candidate_model_id=candidate.model_id, task=PredictionTask.INTENT,
    )
    monkeypatch.setattr(adapter._inference, "predict_text", lambda **kwargs: {
        "label": "intent-a", "confidence": 0.85, "scores": {"intent-a": 0.85},
    })
    prediction = await adapter.predict(SimpleNamespace(text="hello"))
    assert prediction.model_id == candidate.model_id
    assert prediction.model_version == candidate.model_version
    assert prediction.task == PredictionTask.INTENT
    assert prediction.label == "intent-a"
    assert prediction.fallback_used is False


@pytest.mark.asyncio
async def test_spacy_ner_cannot_enter_classification_benchmark(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
    from ai_karen_engine.core.intelligence.ml.predictors.registry_spacy import (
        SpacyCandidateBenchmarkPredictor,
    )

    registry, candidate = _candidate(tmp_path)
    registry.register(replace(candidate, metrics={"mode": "ner"}))
    adapter = SpacyCandidateBenchmarkPredictor(
        registry=registry, tenant_id="tenant-a",
        candidate_model_id=candidate.model_id, task=PredictionTask.INTENT,
    )
    with pytest.raises(ValueError, match="Only matching text categorization"):
        await adapter.predict(SimpleNamespace(text="Alice"))
