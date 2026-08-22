from __future__ import annotations

from typing import Any, Dict, List, Optional

from ai_karen_engine.core.cortex.contracts import (
    IntentSignal,
    KireSignal,
    PredictorSignal,
    ReasoningDepth,
    RouteFamily,
)


class KireSignalProducer:
    """Canonical KIRE signal producer.

    KIRE is a CORTEX reasoning/routing intelligence component. It produces
    signals (preferred capabilities, latency sensitivity, privacy requirement,
    local preference, reasoning requirement, model capability requirement).
    It does NOT select providers or models.

    Provider selection is owned by RuntimePolicy + ProviderRouter.
    """

    @staticmethod
    def produce(
        intent: IntentSignal,
        predictors: PredictorSignal,
        route_family: RouteFamily,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KireSignal:
        requires_reasoning = (
            route_family == RouteFamily.REASONING
            or predictors.complexity_score >= 0.7
            or predictors.multi_step_likelihood >= 0.6
        )

        if predictors.degraded_risk >= 0.5:
            depth = ReasoningDepth.LIGHT
        elif predictors.complexity_score >= 0.8 or route_family == RouteFamily.REASONING:
            depth = ReasoningDepth.DEEP
        elif predictors.complexity_score >= 0.4:
            depth = ReasoningDepth.STANDARD
        else:
            depth = ReasoningDepth.NONE

        return KireSignal(
            requires_reasoning=requires_reasoning,
            reasoning_depth=depth,
            reasoning_modes=[route_family.value],
            strategy_hint=intent.primary_intent,
            should_use_memory=predictors.memory_relevance >= 0.1,
            should_use_tools=predictors.tool_likelihood >= 0.4,
            should_use_retrieval_reasoning=requires_reasoning and predictors.memory_relevance >= 0.2,
            should_use_causal_reasoning=route_family == RouteFamily.REASONING,
            should_use_graph_reasoning=route_family == RouteFamily.REASONING,
            should_self_refine=predictors.complexity_score >= 0.6,
            should_verify=predictors.complexity_score >= 0.5 or predictors.ambiguity_score >= 0.5,
        )
