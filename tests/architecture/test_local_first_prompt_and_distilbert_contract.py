from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHAT_RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
DISTILBERT = (
    ROOT / "src/ai_karen_engine/core/intelligence/ml/encoders/distilbert.py"
)


def test_chat_runtime_uses_canonical_semantic_prompt_version() -> None:
    source = CHAT_RUNTIME.read_text(encoding="utf-8")

    assert 'prompt_id="karen.chat.default"' in source
    assert 'prompt_version="v1.0.0"' in source
    assert 'prompt_version="v1"' not in source


def test_distilbert_never_falls_back_to_remote_model_identifier() -> None:
    source = DISTILBERT.read_text(encoding="utf-8")

    assert "return model_name" not in source
    assert "-> str | None:" in source
    assert "if resolved is None:" in source
    assert "local_files_only=True" in source


def test_distilbert_missing_local_model_degrades_without_network_resolution() -> None:
    source = DISTILBERT.read_text(encoding="utf-8")

    assert "DistilBERT local model unavailable; using configured fallback mode" in source
    assert "AutoTokenizer.from_pretrained(" in source
    assert "AutoModel.from_pretrained(" in source
