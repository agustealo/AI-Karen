from __future__ import annotations

import asyncio
from pathlib import Path

import ai_karen_engine.core.intelligence as intelligence_package
from ai_karen_engine.core.memory.ports import IntelligenceEmbeddingPort

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_karen_engine"


def test_retired_nlp_service_manager_is_deleted() -> None:
    path = SRC_ROOT / "core" / "memory" / "signals" / "nlp_service_manager.py"
    assert not path.exists(), (
        "NLPServiceManager is retired. Restore behavior in IntelligenceRuntime, "
        "PromptRuntime, ExpressionGateway, or the canonical lifecycle owner instead."
    )


def test_memory_embedding_port_does_not_bypass_intelligence_runtime() -> None:
    path = SRC_ROOT / "core" / "memory" / "ports.py"
    source = path.read_text(encoding="utf-8")
    assert "core.model_runtime.model_manager" not in source
    assert "get_model_manager" not in source
    assert "get_intelligence_runtime" in source


def test_intelligence_spacy_config_is_not_owned_by_memory() -> None:
    path = SRC_ROOT / "core" / "intelligence" / "linguistic" / "spacy_analyzer.py"
    source = path.read_text(encoding="utf-8")
    assert "core.memory.signals.nlp_config" not in source
    assert "core.intelligence.linguistic.spacy_config" in source


def test_spacy_runtime_downloads_are_disabled_by_default() -> None:
    from ai_karen_engine.core.intelligence.linguistic.spacy_config import SpacyConfig

    assert SpacyConfig().download_missing is False


def test_embedding_port_delegates_to_canonical_intelligence_runtime(monkeypatch) -> None:
    class FakeIntelligenceRuntime:
        async def embed(self, texts: list[str]) -> list[list[float] | None]:
            assert texts == ["remember this"]
            return [[0.25, 0.5, 0.75]]

    fake_runtime = FakeIntelligenceRuntime()
    monkeypatch.setattr(
        intelligence_package,
        "get_intelligence_runtime",
        lambda: fake_runtime,
    )

    result = asyncio.run(IntelligenceEmbeddingPort().embed("remember this"))
    assert list(result) == [0.25, 0.5, 0.75]


def test_embedding_port_fails_honestly_when_encoder_is_unavailable(monkeypatch) -> None:
    class UnavailableIntelligenceRuntime:
        async def embed(self, texts: list[str]) -> list[list[float] | None]:
            return [None]

    monkeypatch.setattr(
        intelligence_package,
        "get_intelligence_runtime",
        lambda: UnavailableIntelligenceRuntime(),
    )

    try:
        asyncio.run(IntelligenceEmbeddingPort().embed("no encoder"))
    except RuntimeError as exc:
        assert "embedding is unavailable" in str(exc)
    else:
        raise AssertionError("Unavailable embeddings must fail honestly")
