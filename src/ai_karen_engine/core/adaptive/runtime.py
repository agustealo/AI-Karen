"""Adaptive runtime service.

Produces ranked, explainable recommendations for the existing executive/runtime path.
It recommends. It does not execute.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from ai_karen_engine.core.adaptive.candidates.filters import HardConstraintFilter
from ai_karen_engine.core.adaptive.candidates.generator import ActionCandidateGenerator
from ai_karen_engine.core.adaptive.contracts import (
    AdaptiveActionType,
    AdaptiveRecommendationSet,
    HistoricalEvidence,
    SystemCapabilitySnapshot,
    UserStateSnapshot,
)
from ai_karen_engine.core.adaptive.ranking.baseline import RuleBasedAdaptivePolicy
from ai_karen_engine.core.adaptive.suggestions.engine import SuggestionEngine
from ai_karen_engine.monitoring.adaptive_metrics import get_adaptive_metrics
from ai_karen_engine.platform.observability.context import get_correlation_context

logger = logging.getLogger(__name__)


class AdaptiveRuntime:
    """Canonical adaptive decision advisor.

    Given a task, user, and historical evidence, produces ranked action
    recommendations. It does not authorize, execute, or choose providers.
    """

    def __init__(
        self,
        candidate_generator: ActionCandidateGenerator | None = None,
        constraint_filter: HardConstraintFilter | None = None,
        baseline_policy: RuleBasedAdaptivePolicy | None = None,
        suggestion_engine: SuggestionEngine | None = None,
        evidence_provider: Any | None = None,
    ) -> None:
        self._candidate_generator = candidate_generator or ActionCandidateGenerator()
        self._constraint_filter = constraint_filter or HardConstraintFilter()
        self._baseline_policy = baseline_policy or RuleBasedAdaptivePolicy()
        self._suggestion_engine = suggestion_engine or SuggestionEngine()
        self._evidence_provider = evidence_provider
        self._shadow_mode = True
        self._adaptive_metrics = get_adaptive_metrics()

    async def recommend(
        self,
        task_signature: Any,
        user_state: UserStateSnapshot,
        resolved_preferences: Any,
        behavior_patterns: Any,
        system_capabilities: SystemCapabilitySnapshot,
        historical_evidence: HistoricalEvidence | None = None,
        policy_version: str = "v1",
        feature_version: str = "v1",
    ) -> AdaptiveRecommendationSet:
        """Produce adaptive recommendations for a request."""
        start = time.time()
        ctx = get_correlation_context()
        request_id = ctx.request_id or str(uuid.uuid4())
        correlation_id = ctx.correlation_id or str(uuid.uuid4())

        from ai_karen_engine.core.adaptive.context import AdaptiveContextBuilder

        builder = AdaptiveContextBuilder(evidence_provider=self._evidence_provider)
        adaptive_context = builder.build(
            request_id=request_id,
            correlation_id=correlation_id,
            task_signature=task_signature,
            user_state=user_state,
            resolved_preferences=resolved_preferences,
            behavior_patterns=behavior_patterns,
            system_capabilities=system_capabilities,
            policy_version=policy_version,
            feature_version=feature_version,
        )

        logger.debug("Adaptive recommend started request_id=%s", request_id)

        candidates = self._candidate_generator.generate(
            task_signature=task_signature,
            user_state=user_state,
            available_capabilities=self._capabilities_from_snapshot(system_capabilities),
        )

        filtered = self._constraint_filter.filter(
            candidates,
            context={
                "risk_level": getattr(task_signature, "risk", "low"),
                "local_only": system_capabilities.local_only_mode,
                "privacy_requirement": getattr(
                    resolved_preferences, "model_locality", "any"
                ),
            },
        )

        if not filtered:
            filtered = [
                {
                    "action_type": AdaptiveActionType.RESPOND_DIRECTLY,
                    "target_id": None,
                    "source": "fallback.no_candidates",
                }
            ]

        recommendations = self._baseline_policy.rank(
            context=adaptive_context, candidates=filtered
        )

        recommendations.shadow_mode = self._shadow_mode

        latency_ms = (time.time() - start) * 1000.0
        logger.debug(
            "Adaptive recommend completed request_id=%s latency_ms=%.2f candidates=%d",
            request_id,
            latency_ms,
            len(filtered),
        )

        try:
            task_type = getattr(task_signature, "task_type", "unknown") or "unknown"
            self._adaptive_metrics.record_recommendation(
                task_type=task_type,
                execution_path="recommend",
                status="success",
            )
            self._adaptive_metrics.record_ranking(
                task_type=task_type,
                duration_seconds=latency_ms / 1000.0,
            )
            self._adaptive_metrics.record_candidate_count(
                task_type=task_type,
                count=len(filtered),
            )
        except Exception:
            pass

        return recommendations

    async def generate_suggestions(
        self,
        task_signature: Any,
        user_state: UserStateSnapshot,
        behavior_patterns: Any,
        system_capabilities: SystemCapabilitySnapshot,
    ) -> list[Any]:
        """Generate user-facing suggestions separate from execution recommendations."""
        suggestions = await self._suggestion_engine.generate(
            task_signature=task_signature,
            user_state=user_state,
            behavior_patterns=behavior_patterns,
            system_capabilities=system_capabilities,
        )
        try:
            task_type = getattr(task_signature, "task_type", "unknown") or "unknown"
            for suggestion in suggestions:
                suggestion_type = (
                    getattr(suggestion, "suggestion_type", "unknown") or "unknown"
                )
                self._adaptive_metrics.record_suggestion(
                    suggestion_type=suggestion_type,
                    status="emitted",
                )
        except Exception:
            pass
        return suggestions

    def _capabilities_from_snapshot(
        self, snapshot: SystemCapabilitySnapshot
    ) -> dict[str, Any]:
        return {
            "tools": snapshot.available_tools,
            "agents": snapshot.available_agents,
            "workflows": snapshot.available_workflows,
            "inference_targets": snapshot.healthy_inference_targets,
            "memory_available": snapshot.memory_available,
            "local_only": snapshot.local_only_mode,
        }

    def set_shadow_mode(self, enabled: bool) -> None:
        self._shadow_mode = enabled

    @property
    def shadow_mode(self) -> bool:
        return self._shadow_mode
