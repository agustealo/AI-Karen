"""Canonical semantic interpretation stays descriptive and conservative."""

import pytest

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
    SemanticInterpretation,
    TaskAmbiguity,
)


def test_existing_intelligence_results_remain_compatible():
    result = IntelligenceAnalysisResult(intent="general_assist")
    assert result.interpretation is None


def test_interpretation_keeps_unknown_uncertainty_and_no_authority():
    meaning = SemanticInterpretation(
        intent_family="personal_recall",
        subject="user",
        predicate=None,
        ambiguity=TaskAmbiguity.AMBIGUOUS,
        candidate_interpretations=("birthplace", "upbringing_location"),
        evidence_needs=("memory",),
        provenance=("local_semantic_analyzer",),
    )
    assert meaning.confidence is None
    assert meaning.ambiguity is TaskAmbiguity.AMBIGUOUS
    assert meaning.candidate_interpretations == ("birthplace", "upbringing_location")
    assert not hasattr(meaning, "memory_write_allowed")
    assert not hasattr(meaning, "memory_read_authorized")


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_invalid_confidence_is_rejected(confidence):
    with pytest.raises(ValueError, match="confidence"):
        SemanticInterpretation(confidence=confidence)


def test_intelligence_result_can_carry_semantic_interpretation():
    interpretation = SemanticInterpretation(intent_family="statement", predicate="birthplace")
    result = IntelligenceAnalysisResult(interpretation=interpretation)
    assert result.interpretation is interpretation


def test_runtime_builds_interpretation_without_inventing_confidence():
    import asyncio
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.intelligence.intelligence_runtime import (
        IntelligenceRuntime,
    )

    runtime = IntelligenceRuntime.__new__(IntelligenceRuntime)
    runtime._initialized = True
    runtime._linguistic = None
    runtime._ml_runtime = type(
        "UnavailableML",
        (),
        {
            "encode": AsyncMock(return_value=None),
            "predict": AsyncMock(return_value=None),
        },
    )()

    analysis = asyncio.run(runtime.analyze("Where did I grow up?"))
    assert analysis.interpretation is not None
    assert analysis.interpretation.confidence is None
    assert analysis.interpretation.ambiguity is TaskAmbiguity.UNKNOWN
    assert analysis.interpretation.subject is None
    assert analysis.interpretation.evidence_needs == ()
