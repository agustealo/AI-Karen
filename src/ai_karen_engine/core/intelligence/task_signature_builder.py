from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
    SignalType,
    TaskAmbiguity,
    TaskComplexity,
    TaskRisk,
    TaskSignature,
)
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask

logger = logging.getLogger(__name__)


class TaskSignatureBuilder:
    def build(self, analysis: IntelligenceAnalysisResult, predictions: dict[PredictionTask, Prediction] | None = None) -> TaskSignature:
        predictions = predictions or {}

        intent = "general_assist"
        intent_confidence = 0.0
        if analysis.intent:
            intent = analysis.intent
        if analysis.intent_confidence:
            intent_confidence = analysis.intent_confidence
        intent_pred = predictions.get(PredictionTask.INTENT)
        if intent_pred and intent_pred.label:
            intent = intent_pred.label
            intent_confidence = intent_pred.confidence

        complexity = TaskComplexity.SIMPLE
        complexity_pred = predictions.get(PredictionTask.COMPLEXITY)
        if complexity_pred and complexity_pred.label:
            try:
                complexity = TaskComplexity(complexity_pred.label)
            except ValueError:
                pass

        ambiguity = TaskAmbiguity.CLEAR
        ambiguity_pred = predictions.get(PredictionTask.AMBIGUITY)
        if ambiguity_pred and ambiguity_pred.label:
            try:
                ambiguity = TaskAmbiguity(ambiguity_pred.label)
            except ValueError:
                pass

        risk = TaskRisk.LOW
        risk_signals = getattr(analysis, "risk_signals", {}) or {}
        risk_score = float(risk_signals.get("score", 0.0) or 0.0)
        if risk_score >= 0.8:
            risk = TaskRisk.CRITICAL
        elif risk_score >= 0.5:
            risk = TaskRisk.HIGH
        elif risk_score >= 0.2:
            risk = TaskRisk.MEDIUM

        novelty = 0.0
        if hasattr(analysis, "novelty"):
            novelty = analysis.novelty

        tool_requirements = list(getattr(analysis, "capability_hints", {}) or {}).copy()
        topology_signals = getattr(analysis, "topology_signals", {}) or {}
        if topology_signals.get("external_lookup"):
            tool_requirements.append("search")
        if topology_signals.get("code_execution"):
            tool_requirements.append("code_execution")
        if topology_signals.get("filesystem_operation"):
            tool_requirements.append("filesystem_operation")
        tool_requirements = list(dict.fromkeys(tool_requirements))

        reasoning_requirements: list[str] = []
        if complexity in (TaskComplexity.COMPLEX, TaskComplexity.EXPERT):
            reasoning_requirements.append("deep_reasoning")
        if topology_signals.get("dependency_chain"):
            reasoning_requirements.append("chain_of_thought")

        collaboration_value = 0.0
        verification_value = 0.0
        if complexity == TaskComplexity.COMPLEX:
            collaboration_value = 0.7
            verification_value = 0.6
        elif complexity == TaskComplexity.MODERATE:
            collaboration_value = 0.3
            verification_value = 0.2

        capability_pred = predictions.get(PredictionTask.CAPABILITY)
        if capability_pred and capability_pred.value:
            cap_scores = capability_pred.value
            tool_requirements = [k for k, v in cap_scores.items() if v > 0.2]

        semantic_embedding = None
        for signal in getattr(analysis, "signals", []):
            if signal.signal_type == SignalType.EMBEDDING and isinstance(signal.value, list):
                semantic_embedding = signal.value
                break

        metadata: dict[str, Any] = {}
        metadata["intent_confidence"] = intent_confidence
        metadata["feature_version"] = "v1"
        metadata["source"] = "IntelligenceRuntime"

        return TaskSignature(
            intent=intent,
            domains=analysis.domains if hasattr(analysis, "domains") else [],
            entities=[e.get("text", "") for e in analysis.entities] if hasattr(analysis, "entities") else [],
            topics=analysis.topics if hasattr(analysis, "topics") else [],
            semantic_embedding=semantic_embedding,
            complexity=complexity,
            ambiguity=ambiguity,
            novelty=novelty,
            risk=risk,
            tool_requirements=tool_requirements,
            reasoning_requirements=reasoning_requirements,
            collaboration_value=collaboration_value,
            verification_value=verification_value,
            metadata=metadata,
        )
