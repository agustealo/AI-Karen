from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.topology import (
    ExecutionTopologyPredictor,
)
from ai_karen_engine.core.intelligence.ml.predictors.topology_features import (
    FEATURE_VERSION,
    TopologyFeatureVector,
    build_topology_feature_vector,
    topology_feature_vector_to_dict,
)


def test_build_topology_feature_vector_deterministic():
    features = IntelligenceFeatures(
        text="What is the capital of Ghana?",
        token_count=6,
        sentence_count=1,
        entity_count=0,
        request_features={
            "intent_confidence": 0.9,
            "complexity": "simple",
            "ambiguity": "clear",
            "memory_relevance": 0.0,
            "capability_candidates": [],
            "tool_requirements": [],
            "topology_signals": {
                "multiple_actions": False,
                "dependency_chain": False,
                "external_lookup": False,
                "code_execution": False,
                "filesystem_operation": False,
                "parallelizable": False,
                "requires_followup": False,
            },
            "capability_hints": {
                "web_search": False,
                "code_execution": False,
                "filesystem_read": False,
                "filesystem_write": False,
                "tool_use": False,
                "deep_reasoning": False,
                "structured_output": False,
            },
            "risk_score": 0.0,
        },
    )
    vector = build_topology_feature_vector(features)
    assert vector.feature_version == FEATURE_VERSION
    assert vector.token_count == 6
    assert vector.sentence_count == 1
    assert vector.entity_count == 0
    assert vector.complexity_score == 0.0
    assert vector.multiple_actions is False


def test_topology_feature_vector_to_dict():
    features = IntelligenceFeatures(
        text="Test",
        token_count=5,
        sentence_count=2,
        request_features={},
    )
    vector = build_topology_feature_vector(features)
    data = topology_feature_vector_to_dict(vector)
    assert data["token_count"] == 5
    assert data["sentence_count"] == 2
    assert "multiple_actions" in data


@pytest.mark.asyncio
async def test_execution_topology_predictor_baseline_without_model():
    predictor = ExecutionTopologyPredictor()
    features = IntelligenceFeatures(text="What is the capital of Ghana?")
    prediction = await predictor.predict(features)
    assert prediction is not None
    assert prediction.task == PredictionTask.EXECUTION_TOPOLOGY
    assert prediction.fallback_used is True
    assert prediction.inference_method == "deterministic_baseline"
    assert prediction.label in {"direct", "reasoning", "workflow", "multi_agent"}
    assert "probabilities" in prediction.metadata
    assert set(prediction.metadata["probabilities"].keys()) == {
        "direct",
        "reasoning",
        "workflow",
        "multi_agent",
    }
