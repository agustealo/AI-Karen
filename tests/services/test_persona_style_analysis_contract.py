"""Persona style analysis supports actual sync dataclasses and async adapters."""

from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.persona.contracts import ToneEnum
from ai_karen_engine.services.formatting.nlp_style_analyzer import NLPStyleAnalyzer
from ai_karen_engine.services.persona.persona_service import PersonaService


def _service(analyzer):
    service = PersonaService.__new__(PersonaService)
    service.nlp_analyzer = analyzer
    return service


@pytest.mark.asyncio
async def test_synchronous_dataclass_analyzer_produces_valid_tone():
    result = await _service(NLPStyleAnalyzer()).analyze_user_style("Hello!")
    assert result["analysis_available"] is True
    assert result["detected_tone"] == ToneEnum.FRIENDLY
    assert result["formality_score"] == 0.5


@pytest.mark.asyncio
async def test_unsupported_neutral_label_does_not_invent_persona_tone():
    result = await _service(NLPStyleAnalyzer()).analyze_user_style("Hello.")
    assert result["analysis_available"] is True
    assert result["detected_tone"] is None


@pytest.mark.asyncio
async def test_registered_async_dictionary_analyzer_remains_supported():
    analyzer = type("Analyzer", (), {
        "analyze_style": AsyncMock(return_value={
            "tone": "professional", "formality": 0.8, "sentiment": 0.0,
        }),
    })()
    result = await _service(analyzer).analyze_user_style("Please review")
    assert result["analysis_available"] is True
    assert result["detected_tone"] == ToneEnum.PROFESSIONAL
    assert result["formality_score"] == 0.8


@pytest.mark.asyncio
async def test_missing_or_invalid_adapter_cannot_claim_analyzed_style():
    missing = await _service(None).analyze_user_style("Hello!")
    broken = await _service(type("Analyzer", (), {
        "analyze_style": lambda self, message: object(),
    })()).analyze_user_style("Hello!")
    assert missing["analysis_available"] is False
    assert missing["detected_tone"] is None
    assert broken["analysis_available"] is False
    assert broken["detected_tone"] is None
