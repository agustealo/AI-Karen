from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ai_karen_engine.core.adaptive.salience.contracts import (
    GoalSalienceAdjustment,
    MemorySalienceSignal,
    PredictionError,
    RelationshipRelevanceSignal,
    SalienceAssessment,
    SalienceAssessmentRequest,
    SalienceAssessmentResult,
    SalienceDimension,
    SalienceReasonCode,
    SalienceSignal,
    SalienceSource,
    UserEmphasisSignal,
)

logger = logging.getLogger(__name__)


class SalienceAssessmentEngine:
    """Assesses multi-dimensional salience from cognitive signals."""

    def assess(self, request: SalienceAssessmentRequest) -> SalienceAssessmentResult:
        """Produce a salience assessment from signals and context."""
        assessment = SalienceAssessment()
        reason_codes: list[SalienceReasonCode] = []
        source_refs: list[str] = []

        for signal in request.signals:
            self._apply_signal(assessment, signal)
            reason_codes.extend(signal.reason_codes)
            if signal.source_ref:
                source_refs.append(signal.source_ref)

        for error in request.prediction_errors:
            self._apply_prediction_error(assessment, error)
            if SalienceReasonCode.PREDICTION_ERROR not in reason_codes:
                reason_codes.append(SalienceReasonCode.PREDICTION_ERROR)

        for emphasis in request.user_emphasis:
            self._apply_user_emphasis(assessment, emphasis)
            if SalienceReasonCode.USER_EXPLICIT_EMPHASIS not in reason_codes:
                reason_codes.append(SalienceReasonCode.USER_EXPLICIT_EMPHASIS)

        for rel in request.relationship_signals:
            self._apply_relationship(assessment, rel)
            if SalienceReasonCode.RELATIONSHIP_RELEVANCE not in reason_codes:
                reason_codes.append(SalienceReasonCode.RELATIONSHIP_RELEVANCE)

        assessment.reason_codes = list(dict.fromkeys(reason_codes))
        assessment.source_refs = list(dict.fromkeys(source_refs))
        assessment.confidence = self._compute_confidence(assessment, request.signals)

        memory_signals = self._build_memory_signals(assessment, request)
        goal_adjustments = self._build_goal_adjustments(assessment, request)

        return SalienceAssessmentResult(
            assessment=assessment,
            memory_signals=memory_signals,
            goal_adjustments=goal_adjustments,
        )

    def _apply_signal(self, assessment: SalienceAssessment, signal: SalienceSignal) -> None:
        dim = signal.dimension.value
        current = getattr(assessment, dim, 0.0)
        setattr(assessment, dim, max(0.0, min(1.0, current + signal.value)))

    def _apply_prediction_error(self, assessment: SalienceAssessment, error: PredictionError) -> None:
        current = getattr(assessment, error.dimension_affected.value, 0.0)
        setattr(assessment, error.dimension_affected.value, max(0.0, min(1.0, current + error.error_magnitude)))

    def _apply_user_emphasis(self, assessment: SalienceAssessment, emphasis: UserEmphasisSignal) -> None:
        current = getattr(assessment, SalienceDimension.USER_EMPHASIS.value, 0.0)
        setattr(assessment, SalienceDimension.USER_EMPHASIS.value, max(0.0, min(1.0, current + emphasis.strength)))

    def _apply_relationship(self, assessment: SalienceAssessment, rel: RelationshipRelevanceSignal) -> None:
        current = getattr(assessment, SalienceDimension.RELATIONSHIP_IMPORTANCE.value, 0.0)
        setattr(assessment, SalienceDimension.RELATIONSHIP_IMPORTANCE.value, max(0.0, min(1.0, current + rel.relevance_strength)))

    def _compute_confidence(self, assessment: SalienceAssessment, signals: list[SalienceSignal]) -> float:
        if not signals:
            return 0.0
        return max(0.0, min(1.0, sum(s.confidence for s in signals) / len(signals)))

    def _build_memory_signals(self, assessment: SalienceAssessment, request: SalienceAssessmentRequest) -> list[MemorySalienceSignal]:
        signals = []
        for goal_id in request.context.current_goals:
            signals.append(MemorySalienceSignal(
                memory_id=goal_id,
                salience_value=assessment.goal_relevance,
                dimensions={SalienceDimension.GOAL_RELEVANCE.value: assessment.goal_relevance},
                tenant_id=request.context.tenant_id,
            ))
        return signals

    def _build_goal_adjustments(self, assessment: SalienceAssessment, request: SalienceAssessmentRequest) -> list[GoalSalienceAdjustment]:
        adjustments = []
        for goal_id in request.context.current_goals:
            reasons = [rc.value for rc in assessment.reason_codes]
            adjustments.append(GoalSalienceAdjustment(
                goal_id=goal_id,
                adjustment=assessment.goal_relevance,
                reason_codes=reasons,
                tenant_id=request.context.tenant_id,
            ))
        return adjustments
