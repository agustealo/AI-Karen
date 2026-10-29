"""Production linguistic contract and honest model-provenance regressions."""

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.intelligence.contracts import SignalSourceType, SignalType
from ai_karen_engine.core.intelligence.intelligence_runtime import IntelligenceRuntime
from ai_karen_engine.core.intelligence.linguistic.contracts import (
    LinguisticMetadata,
    ParsedMessage,
)
from ai_karen_engine.core.intelligence.ml.contracts import SemanticEncoding


class _UnavailableML:
    async def encode(self, text, model_id):
        return SemanticEncoding(
            vector=[], dimensions=0, model_id="unavailable",
            model_version="", fallback_used=True,
        )

    async def predict(self, features, task):
        return None


def _runtime(parsed, metadata):
    runtime = IntelligenceRuntime()
    runtime.initialize = AsyncMock()
    runtime._ml_runtime = _UnavailableML()
    runtime._linguistic = type("Analyzer", (), {
        "parse": AsyncMock(return_value=parsed),
        "metadata": AsyncMock(return_value=metadata),
    })()
    return runtime


@pytest.mark.asyncio
async def test_actual_parsed_message_populates_intelligence_signals():
    runtime = _runtime(
        ParsedMessage(
            tokens=["Create", "Troy"],
            entities=[("Troy", "PERSON")],
            noun_phrases=["Troy"],
            sentences=["Create Troy"],
            pos_tags=[("Troy", "PROPN")],
            dependencies=[{"head": "Create", "child": "Troy"}],
        ),
        LinguisticMetadata(model_id="en_core_web_sm", model_version="test"),
    )
    result = await runtime.analyze("Create Troy", tenant_id="tenant-a")
    assert result.entities == [{"text": "Troy", "label": "PERSON"}]
    assert result.key_phrases == ["Troy"]
    signal = next(s for s in result.signals if s.signal_type == SignalType.ENTITY)
    assert signal.source_type == SignalSourceType.SPACY
    assert signal.model_id == "en_core_web_sm"
    assert signal.fallback_used is False


@pytest.mark.asyncio
async def test_missing_embedding_emits_no_fake_model_signal():
    runtime = _runtime(
        ParsedMessage(tokens=["Hello"]),
        LinguisticMetadata(model_id="", fallback_used=True),
    )
    result = await runtime.analyze("Hello")
    assert result.semantic_features["embedding_available"] is False
    assert result.semantic_features["embedding_dim"] == 0
    assert result.degraded is True
    assert not any(s.signal_type == SignalType.EMBEDDING for s in result.signals)


@pytest.mark.asyncio
async def test_fallback_extraction_cannot_claim_loaded_spacy_model():
    runtime = _runtime(
        ParsedMessage(tokens=["Troy"], entities=[("Troy", "PERSON")], used_fallback=True),
        LinguisticMetadata(model_id="en_core_web_sm", fallback_used=True),
    )
    result = await runtime.analyze("Troy")
    signal = next(s for s in result.signals if s.signal_type == SignalType.ENTITY)
    assert signal.source_type == SignalSourceType.FALLBACK
    assert signal.fallback_used is True
    assert signal.model_id == "unavailable"
    assert signal.confidence == 0.0
