from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
    IntelligenceSignal,
    SignalSourceType,
    SignalType,
    TaskAmbiguity,
    TaskComplexity,
    TaskRisk,
    TaskSignature,
)
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.task_signature_builder import TaskSignatureBuilder


def test_task_signature_builder_basic():
    builder = TaskSignatureBuilder()
    analysis = IntelligenceAnalysisResult(
        intent="information_seeking",
        intent_confidence=0.8,
        entities=[{"text": "Python", "label": "PRODUCT"}],
        topics=["technology"],
        task_complexity="moderate",
        memory_relevance=0.3,
        risk_signals={"categories": [], "score": 0.1},
        capability_hints={"web_search": True, "code_execution": True},
        topology_signals={"external_lookup": True},
        signals=[
            IntelligenceSignal(
                signal_type=SignalType.EMBEDDING,
                value=[0.1, 0.2, 0.3],
                confidence=0.7,
                source_type=SignalSourceType.TRANSFORMER,
            )
        ],
    )
    predictions = {
        PredictionTask.INTENT: Prediction(task=PredictionTask.INTENT, label="information_seeking", confidence=0.85),
        PredictionTask.COMPLEXITY: Prediction(task=PredictionTask.COMPLEXITY, label="moderate", confidence=0.7),
        PredictionTask.AMBIGUITY: Prediction(task=PredictionTask.AMBIGUITY, label="clear", confidence=0.6),
        PredictionTask.CAPABILITY: Prediction(task=PredictionTask.CAPABILITY, value={"web_search": 0.9, "code_execution": 0.8}, confidence=0.8),
    }
    signature = builder.build(analysis, predictions)
    assert isinstance(signature, TaskSignature)
    assert signature.intent == "information_seeking"
    assert signature.complexity == TaskComplexity.MODERATE
    assert signature.ambiguity == TaskAmbiguity.CLEAR
    assert "web_search" in signature.tool_requirements
    assert signature.risk == TaskRisk.LOW
