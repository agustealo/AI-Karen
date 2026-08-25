from __future__ import annotations

import logging

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
    UserEmphasisSignal,
)
from ai_karen_engine.core.contracts.cognitive import SalienceConfidence

logger = logging.getLogger(__name__)


class SalienceAssessmentEngine:
    """Assess multi-dimensional salience from cognitive signals."""

    def assess(self, request: SalienceAssessmentRequest) -> SalienceAssessmentResult:
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
        for relationship in request.relationship_signals:
            self._apply_relationship(assessment, relationship)
            if SalienceReasonCode.RELATIONSHIP_RELEVANCE not in reason_codes:
                reason_codes.append(SalienceReasonCode.RELATIONSHIP_RELEVANCE)

        assessment.reason_codes = list(dict.fromkeys(reason_codes))
        assessment.source_refs = list(dict.fromkeys(source_refs))
        assessment.confidence = self._compute_confidence(request)
        assessment.activation = assessment._compute_activation()
        assessment.modulation = max(0.0, min(1.0, 1.0 - assessment.interruption_cost))
        assessment.overall = assessment._compute_overall()

        return SalienceAssessmentResult(
            assessment=assessment,
            memory_signals=self._build_memory_signals(assessment, request),
            goal_adjustments=self._build_goal_adjustments(assessment, request),
        )

    @staticmethod
    def _apply_signal(assessment: SalienceAssessment, signal: SalienceSignal) -> None:
        current = getattr(assessment, signal.dimension.value, 0.0)
        setattr(assessment, signal.dimension.value, max(0.0, min(1.0, current + signal.value)))

    @staticmethod
    def _apply_prediction_error(assessment: SalienceAssessment, error: PredictionError) -> None:
        current = getattr(assessment, error.dimension_affected.value, 0.0)
        setattr(
            assessment,
            error.dimension_affected.value,
            max(0.0, min(1.0, current + error.error_magnitude)),
        )

    @staticmethod
    def _apply_user_emphasis(assessment: SalienceAssessment, emphasis: UserEmphasisSignal) -> None:
        current = assessment.user_emphasis
        assessment.user_emphasis = max(0.0, min(1.0, current + emphasis.strength))

    @staticmethod
    def _apply_relationship(
        assessment: SalienceAssessment,
        relationship: RelationshipRelevanceSignal,
    ) -> None:
        current = assessment.relationship_importance
        assessment.relationship_importance = max(
            0.0,
            min(1.0, current + relationship.relevance_strength),
        )

    @staticmethod
    def _compute_confidence(request: SalienceAssessmentRequest) -> SalienceConfidence:
        values: list[float] = [float(signal.confidence) for signal in request.signals]
        values.extend(float(emphasis.confidence) for emphasis in request.user_emphasis)
        values.extend(error.observed.confidence for error in request.prediction_errors)
        values.extend(
            max(0.0, min(1.0, relationship.relevance_strength))
            for relationship in request.relationship_signals
        )
        positive = [value for value in values if value > 0.0]
        return SalienceConfidence(sum(positive) / len(positive) if positive else 0.0)

    @staticmethod
    def _build_memory_signals(
        assessment: SalienceAssessment,
        request: SalienceAssessmentRequest,
    ) -> list[MemorySalienceSignal]:
        output: list[MemorySalienceSignal] = []
        dimensions = {signal.dimension.value: signal.value for signal in request.signals}
        for signal in request.signals:
            memory_id = signal.metadata.get("memory_id")
            if not memory_id:
                continue
            output.append(
                MemorySalienceSignal(
                    memory_id=str(memory_id),
                    tenant_id=request.context.tenant_id,
                    salience_value=assessment.overall,
                    dimensions=dimensions,
                    reason_codes=[code.value for code in assessment.reason_codes],
                )
            )
        return output

    @staticmethod
    def _build_goal_adjustments(
        assessment: SalienceAssessment,
        request: SalienceAssessmentRequest,
    ) -> list[GoalSalienceAdjustment]:
        reasons = [code.value for code in assessment.reason_codes]
        return [
            GoalSalienceAdjustment(
                goal_id=goal_id,
                tenant_id=request.context.tenant_id,
                adjustment=assessment.goal_relevance,
                reason_codes=reasons,
            )
            for goal_id in request.context.current_goals
        ]
