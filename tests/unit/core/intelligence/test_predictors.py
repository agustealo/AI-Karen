from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.ml_runtime import MLRuntime
from ai_karen_engine.core.intelligence.ml.predictors.ambiguity import AmbiguityPredictor
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor
from ai_karen_engine.core.intelligence.ml.predictors.capability import CapabilityPredictor
from ai_karen_engine.core.intelligence.ml.predictors.complexity import ComplexityPredictor
from ai_karen_engine.core.intelligence.ml.predictors.domain import DomainClassifier
from ai_karen_engine.core.intelligence.ml.predictors.intent import IntentPredictor
from ai_karen_engine.core.intelligence.ml.predictors.memory_relevance import MemoryRelevancePredictor
from ai_karen_engine.core.intelligence.features import IntelligenceFeatures


@pytest.mark.asyncio
async def test_intent_predictor():
    predictor = IntentPredictor()
    features = IntelligenceFeatures(text="What is the weather today?")
    result = await predictor.predict(features)
    assert result.task.value == "intent"
    assert result.label in ("information_seeking", "unknown")
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_domain_classifier():
    predictor = DomainClassifier()
    features = IntelligenceFeatures(text="I need to write some code in Python.")
    result = await predictor.predict(features)
    assert result.task.value == "domain"
    assert result.label == "software_development"


@pytest.mark.asyncio
async def test_complexity_predictor():
    predictor = ComplexityPredictor()
    features = IntelligenceFeatures(text="Run the tests and deploy.", token_count=5, sentence_count=1)
    result = await predictor.predict(features)
    assert result.task.value == "complexity"
    assert result.label in ("simple", "moderate", "complex")


@pytest.mark.asyncio
async def test_ambiguity_predictor():
    predictor = AmbiguityPredictor()
    features = IntelligenceFeatures(text="Do it.", token_count=2, entity_count=0)
    result = await predictor.predict(features)
    assert result.task.value == "ambiguity"
    assert result.label in ("clear", "moderate", "ambiguous")


@pytest.mark.asyncio
async def test_memory_relevance_predictor():
    predictor = MemoryRelevancePredictor()
    features = IntelligenceFeatures(text="Remember what we discussed yesterday.")
    result = await predictor.predict(features)
    assert result.task.value == "memory_relevance"
    assert result.value > 0.0


@pytest.mark.asyncio
async def test_capability_predictor():
    predictor = CapabilityPredictor()
    features = IntelligenceFeatures(text="Search for Python tutorials and run the code.")
    result = await predictor.predict(features)
    assert result.task.value == "capability"
    assert isinstance(result.value, dict)
