"""Rule-based baseline adaptive policy.

Deterministic ranking that is testable and comparable.
This is the baseline before any learned policy.
"""

from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    AdaptiveContext,
    AdaptiveRecommendation,
    AdaptiveRecommendationSet,
    RecommendationReasonCode,
    ScoreComponents,
)

logger = logging.getLogger(__name__)


class RuleBasedAdaptivePolicy:
    """Deterministic baseline policy for adaptive ranking."""

    def rank(
        self, context: AdaptiveContext, candidates: list[dict[str, Any]]
    ) -> AdaptiveRecommendationSet:
        """Rank candidates using deterministic rules."""
        recommendations: list[AdaptiveRecommendation] = []
        for candidate in candidates:
            action_type = candidate.get("action_type")
            target_id = candidate.get("target_id")
            if action_type is None:
                continue

            components = self._score_candidate(action_type, target_id, context)
            utility = components.utility
            confidence = components.confidence

            explanation = self._build_explanation(components, action_type, target_id)

            rec = AdaptiveRecommendation(
                recommendation_id=f"rec-{context.request_id}-{len(recommendations)}",
                action_type=action_type,
                target_id=target_id,
                utility_score=utility,
                confidence=confidence,
                evidence=explanation,
                explanation_codes=list(explanation.keys()),
                score_components=components,
                model_policy_version="rule-based-baseline",
            )
            recommendations.append(rec)

        recommendations.sort(key=lambda r: r.utility_score, reverse=True)

        return AdaptiveRecommendationSet(
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            recommendations=recommendations,
            policy_version="rule-based-baseline",
        )

    def _score_candidate(
        self,
        action_type: AdaptiveActionType,
        target_id: str | None,
        context: AdaptiveContext,
    ) -> ScoreComponents:
        task_context = {
            "task_signature": context.task_signature,
            "resolved_preferences": context.resolved_preferences,
            "user_state": context.user_state,
            "system_capabilities": context.system_capabilities,
            "risk_level": getattr(context.task_signature, "risk", "low"),
            "historical_evidence": context.historical_evidence,
        }

        from ai_karen_engine.core.adaptive.ranking.utility import ActionUtilityEstimator
        estimator = ActionUtilityEstimator()
        return estimator.estimate(
            action_type=action_type,
            target_id=target_id,
            context=task_context,
            historical_profile=self._profile_for_action(action_type, target_id, context),
        )

    def _profile_for_action(
        self,
        action_type: AdaptiveActionType,
        target_id: str | None,
        context: AdaptiveContext,
    ) -> dict[str, Any]:
        profiles = context.historical_evidence
        if not profiles:
            return {}
        capability_profiles = getattr(profiles, "capability_profiles", {}) or {}
        action_key = action_type.value
        target_key = f"{action_key}:{target_id}" if target_id else action_key
        if target_key in capability_profiles:
            return capability_profiles[target_key]
        if action_key in capability_profiles:
            return capability_profiles[action_key]
        return {}

    def _build_explanation(
        self,
        components: ScoreComponents,
        action_type: AdaptiveActionType,
        target_id: str | None,
    ) -> dict[str, Any]:
        codes = []
        if components.task_fit > 0.6:
            codes.append(RecommendationReasonCode.HIGH_TASK_FIT)
        if components.user_preference_fit > 0.6:
            codes.append(RecommendationReasonCode.USER_PREFERS_LOCAL)
        if components.historical_success > 0.7:
            codes.append(RecommendationReasonCode.HISTORICAL_SUCCESS_HIGH)
        if components.risk_penalty < -0.2:
            codes.append(RecommendationReasonCode.HIGH_RISK)
        if components.confidence < 0.3:
            codes.append(RecommendationReasonCode.LOW_SAMPLE_CONFIDENCE)
        if not codes:
            codes.append(RecommendationReasonCode.DEFAULT_BASELINE)

        explanation = {
            "action_type": action_type.value,
            "target_id": target_id,
            "utility": components.utility,
            "components": {
                "task_fit": components.task_fit,
                "user_preference_fit": components.user_preference_fit,
                "historical_success": components.historical_success,
                "latency_penalty": components.latency_penalty,
                "risk_penalty": components.risk_penalty,
                "cost_penalty": components.cost_penalty,
                "interruption_penalty": components.interruption_penalty,
                "confidence": components.confidence,
            },
            "reason_codes": [c.value for c in codes],
        }
        return explanation
