from __future__ import annotations

from pathlib import Path


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
