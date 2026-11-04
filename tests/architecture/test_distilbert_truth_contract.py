from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENCODER = ROOT / "src/ai_karen_engine/core/intelligence/ml/encoders/distilbert.py"
SERVICE = ROOT / "src/ai_karen_engine/core/memory/signals/distilbert_service.py"


def test_encoder_does_not_fabricate_hash_semantic_embeddings() -> None:
    source = ENCODER.read_text(encoding="utf-8")

    assert "def _fallback_embedding" not in source
    assert 'model_id = "unavailable"' in source
    assert "vector=[]" in source


def test_compat_service_does_not_fabricate_zero_embeddings() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "[0.0] * self.config.embedding_dimension" not in source
    assert "embeddings.append([])" in source


def test_unavailable_model_never_claims_safe_or_neutral_inference() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert 'sentiment="unknown"' in source
    assert "is_safe=False" in source
    assert 'flagged_categories=["model_unavailable"]' in source
    assert '"safety_check": False' in source
    assert '"confidence": 0.0' in source
    assert '"context_continuity": 0.0' in source



def test_encoder_resolves_sha_pinned_canonical_model_slot(tmp_path) -> None:
    from ai_karen_engine.core.intelligence.ml.encoders.distilbert import (
        DistilBertSemanticEncoder,
    )

    root = tmp_path / "transformers"
    revision = root / "distilbert--distilbert-base-uncased" / ("a" * 40)
    revision.mkdir(parents=True)
    (revision / "config.json").write_text("{}", encoding="utf-8")
    # Avoid heavyweight initialization; exercise the exact discovery helper.
    encoder = object.__new__(DistilBertSemanticEncoder)
    encoder.config = type("Config", (), {"local_model_root": str(root)})()
    assert encoder._resolve_model_source(
        "distilbert/distilbert-base-uncased", "", ""
    ) == str(revision)



def _uninitialized_distilbert_encoder(*, fallback: bool = False):
    from ai_karen_engine.core.intelligence.ml.encoders.distilbert import (
        DistilBertSemanticEncoder,
    )

    encoder = object.__new__(DistilBertSemanticEncoder)
    encoder.config = SimpleNamespace(
        model_name="distilbert-base-uncased", enable_fallback=True
    )
    encoder.lock = threading.RLock()
    encoder.cache = {}
    encoder.model = None if fallback else object()
    encoder.fallback_mode = fallback
    encoder._cache_hits = 0
    encoder._cache_misses = 0
    encoder._error_count = 0
    encoder._last_error = None
    return encoder


@pytest.mark.asyncio
async def test_embedding_is_unit_length_only_when_reported_normalized() -> None:
    encoder = _uninitialized_distilbert_encoder()
    encoder._generate_embedding = AsyncMock(return_value=[3.0, 4.0])
    result = await encoder.encode("a meaningful request")

    assert result.vector == pytest.approx([0.6, 0.8])
    assert result.dimensions == 2
    assert result.normalized is True
    assert result.fallback_used is False
    assert result.model_id == "distilbert-base-uncased"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_vector", [[0.0, 0.0], [float("nan"), 1.0], [float("inf"), 0.0]])
async def test_invalid_embedding_never_claims_normalized_or_safe_fallback(invalid_vector) -> None:
    encoder = _uninitialized_distilbert_encoder()
    encoder._generate_embedding = AsyncMock(return_value=invalid_vector)

    result = await encoder.encode("another request")
    assert result.vector == []
    assert result.dimensions == 0
    assert result.normalized is False
    assert result.fallback_used is True
    assert result.model_id == "unavailable"


@pytest.mark.asyncio
async def test_missing_encoder_model_never_reports_normalized_vector() -> None:
    encoder = _uninitialized_distilbert_encoder(fallback=True)
    result = await encoder.encode("model missing")

    assert result.vector == []
    assert result.normalized is False
    assert result.fallback_used is True
    assert result.model_id == "unavailable"
