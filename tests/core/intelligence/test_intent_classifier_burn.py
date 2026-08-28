from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import SemanticEncoding
from ai_karen_engine.core.intelligence.ml.predictors.intent import IntentPredictor


def _features(text: str) -> IntelligenceFeatures:
    return IntelligenceFeatures(text=text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Can you fix this broken authentication error?", "problem_solving"),
        ("Which database should I choose for this workload?", "decision_making"),
        ("Brainstorm three names for the new runtime.", "creative_assistance"),
        ("Explain how vector recall works.", "information_seeking"),
        ("Please build the release checklist.", "task_completion"),
        ("Hello there", "social_interaction"),
    ],
    ids=[
        "problem_solving",
        "decision_making",
        "creative_assistance",
        "information_seeking",
        "task_completion",
        "social_interaction",
    ],
)
async def test_heuristic_burn_routes_specific_intents_before_generic_request_cues(
    text: str,
    expected: str,
) -> None:
    prediction = await IntentPredictor().predict(_features(text))

    assert prediction.label == expected
    assert prediction.fallback_used is True
    assert prediction.inference_method == "heuristic_fallback"
    assert 0.0 < prediction.confidence <= 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "ZXQ-19 ::: 8841",
        "whatsoever",
        "...",
        "🧩🧩🧩",
        "   ",
    ],
)
async def test_unknown_noise_is_not_fabricated_as_social_intent(text: str) -> None:
    prediction = await IntentPredictor().predict(_features(text))

    assert prediction.label == "unknown"
    assert prediction.confidence == 0.0
    assert prediction.fallback_used is True


class _SemanticEncoder:
    def __init__(
        self,
        vectors: dict[str, list[float]],
        *,
        fallback_used: bool = False,
    ) -> None:
        self.vectors = vectors
        self.fallback_used = fallback_used
        self.calls: list[str] = []
        self.config = SimpleNamespace(model_name="burn-semantic")

    async def encode(self, text: str) -> SemanticEncoding:
        self.calls.append(text)
        return SemanticEncoding(
            vector=self.vectors.get(text, [0.0, 1.0]),
            dimensions=2,
            model_id="burn-semantic",
            model_version="test",
            fallback_used=self.fallback_used,
        )


@pytest.mark.asyncio
async def test_semantic_path_encodes_request_once_and_uses_real_semantic_provenance() -> None:
    text = "I need this broken runtime fixed"
    vectors = {text: [1.0, 0.0]}
    for intent, template in IntentPredictor.INTENT_TEMPLATES.items():
        vectors[template] = [1.0, 0.0] if intent == "problem_solving" else [0.0, 1.0]
    encoder = _SemanticEncoder(vectors)

    prediction = await IntentPredictor(semantic_encoder=encoder).predict(_features(text))

    assert prediction.label == "problem_solving"
    assert prediction.fallback_used is False
    assert prediction.inference_method == "embedding_similarity"
    assert prediction.model_id == "burn-semantic"
    assert encoder.calls.count(text) == 1
    assert len(encoder.calls) == 1 + len(IntentPredictor.INTENT_TEMPLATES)


@pytest.mark.asyncio
async def test_degraded_semantic_encoder_cannot_claim_transformer_intent_truth() -> None:
    text = "Can you fix this error?"
    encoder = _SemanticEncoder({text: [1.0, 0.0]}, fallback_used=True)

    prediction = await IntentPredictor(semantic_encoder=encoder).predict(_features(text))

    assert prediction.label == "problem_solving"
    assert prediction.fallback_used is True
    assert prediction.inference_method == "heuristic_fallback"


@pytest.mark.asyncio
async def test_weak_semantic_match_is_rejected_instead_of_forcing_a_class() -> None:
    text = "ZXQ-19 ::: 8841"
    vectors = {text: [1.0, 0.0]}
    for template in IntentPredictor.INTENT_TEMPLATES.values():
        vectors[template] = [0.0, 1.0]
    encoder = _SemanticEncoder(vectors)

    prediction = await IntentPredictor(
        semantic_encoder=encoder,
        min_semantic_similarity=0.35,
    ).predict(_features(text))

    assert prediction.label == "unknown"
    assert prediction.fallback_used is True
    assert prediction.confidence == 0.0
