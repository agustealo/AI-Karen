from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.linguistic.spacy_analyzer import SpacyAnalyzer
from ai_karen_engine.core.intelligence.linguistic.spacy_config import SpacyConfig


@pytest.mark.asyncio
async def test_spacy_analyzer_parse():
    config = SpacyConfig(model_name="en_core_web_sm", enable_fallback=True)
    analyzer = SpacyAnalyzer(config)
    result = await analyzer.parse("Hello world, this is a test.")
    assert isinstance(result.tokens, list)
    assert len(result.tokens) > 0


@pytest.mark.asyncio
async def test_spacy_analyzer_fallback():
    config = SpacyConfig(model_name="nonexistent_model", enable_fallback=True)
    analyzer = SpacyAnalyzer(config)
    result = await analyzer.parse("Hello world")
    assert result.used_fallback is True


@pytest.mark.asyncio
async def test_spacy_analyzer_health():
    config = SpacyConfig(model_name="en_core_web_sm", enable_fallback=True)
    analyzer = SpacyAnalyzer(config)
    health = await analyzer.health()
    assert "status" in health


@pytest.mark.asyncio
async def test_spacy_analyzer_metadata():
    config = SpacyConfig(model_name="en_core_web_sm")
    analyzer = SpacyAnalyzer(config)
    metadata = await analyzer.metadata()
    assert metadata.model_id == "en_core_web_sm"
