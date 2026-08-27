from __future__ import annotations

"""Runtime-owned activation bridge for specialist reasoning strategies.

CORTEX decides reasoning modes and RuntimePolicy authorizes them. This module
resolves Runtime-owned dependencies for those already-authorized modes and
returns a ReasoningExecutor plus request metadata. Core reasoning strategies do
not discover providers, models, prompts, or policy on their own.
"""

from dataclasses import dataclass, field
from typing import Any, Sequence

from ai_karen_engine.core.reasoning.contracts import normalize_reasoning_modes
from ai_karen_engine.core.reasoning.defaults import get_default_strategies
from ai_karen_engine.core.reasoning.executor import ReasoningExecutor
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.soft_reasoning_composition import (
    ComposedSoftReasoning,
    SoftReasoningCompositionUnavailable,
    get_runtime_soft_reasoning_composer,
)


SOFT_EXPLORATION_MODE = "soft_exploration"


class ReasoningActivationError(RuntimeError):
    """Raised when an authorized reasoning mode cannot be activated safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReasoningActivation:
    executor: ReasoningExecutor
    reasoning_modes: tuple[str, ...]
    request_metadata: dict[str, Any] = field(default_factory=dict)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeReasoningBridge:
    """Compose runtime-specific strategies for an authorized reasoning plan."""

    def activate(
        self,
        *,
        objective: str,
        evidence: Sequence[str],
        decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan,
        preferred_provider: str | None,
        preferred_model: str | None,
    ) -> ReasoningActivation:
        requested_modes = tuple(
            normalize_reasoning_modes(list(decision.reasoning_modes))
        )
        authorized_modes = tuple(normalize_reasoning_modes(list(plan.reasoning_modes)))

        if not requested_modes:
            raise ReasoningActivationError(
                "reasoning_mode_not_requested",
                "CORTEX did not request a reasoning mode; Runtime cannot invent one",
            )
        if not authorized_modes:
            raise ReasoningActivationError(
                "reasoning_mode_not_authorized",
                "RuntimePolicy did not authorize any reasoning mode",
            )

        unauthorized = sorted(set(requested_modes) - set(authorized_modes))
        if unauthorized:
            raise ReasoningActivationError(
                "reasoning_mode_not_authorized",
                "RuntimePolicy did not authorize reasoning mode(s): "
                + ",".join(unauthorized),
            )

        optional_strategies = []
        request_metadata: dict[str, Any] = {}
        runtime_metadata: dict[str, Any] = {
            "reasoning_modes": list(requested_modes),
            "reasoning_activation": "core_defaults",
        }

        if SOFT_EXPLORATION_MODE in requested_modes:
            composed = self._compose_soft_reasoning(
                objective=objective,
                evidence=evidence,
                preferred_provider=preferred_provider,
                preferred_model=preferred_model,
            )
            self._validate_soft_budget(composed, plan)
            optional_strategies.append(composed.strategy)
            request_metadata.update(
                {
                    "soft_reasoning_prompt": composed.prepared_prompt,
                    "soft_reasoning_prompt_version": composed.prompt_version,
                    "soft_reasoning_profile": composed.profile,
                }
            )
            runtime_metadata.update(
                {
                    "reasoning_activation": "runtime_composed",
                    "soft_reasoning_profile": composed.profile,
                    "soft_reasoning_provider": composed.provider_id,
                    "soft_reasoning_model": composed.model_id,
                    "soft_reasoning_runtime_engine": composed.runtime_engine,
                    "soft_reasoning_marker_token_id": composed.marker_token_id,
                    "soft_reasoning_maximum_total_model_calls": (
                        composed.maximum_total_model_calls
                    ),
                }
            )

        strategies = get_default_strategies(optional_strategies=optional_strategies)
        return ReasoningActivation(
            executor=ReasoningExecutor(strategies=strategies),
            reasoning_modes=requested_modes,
            request_metadata=request_metadata,
            runtime_metadata=runtime_metadata,
        )

    @staticmethod
    def _compose_soft_reasoning(
        *,
        objective: str,
        evidence: Sequence[str],
        preferred_provider: str | None,
        preferred_model: str | None,
    ) -> ComposedSoftReasoning:
        try:
            return get_runtime_soft_reasoning_composer().compose_paper_2025(
                objective=objective,
                evidence=evidence,
                preferred_provider=preferred_provider,
                preferred_model=preferred_model,
            )
        except SoftReasoningCompositionUnavailable as exc:
            raise ReasoningActivationError(
                "soft_reasoning_runtime_unavailable",
                str(exc),
            ) from exc

    @staticmethod
    def _validate_soft_budget(
        composed: ComposedSoftReasoning,
        plan: AuthorizedExecutionPlan,
    ) -> None:
        available = int(plan.budget.max_model_calls)
        required = int(composed.maximum_total_model_calls)
        if available < required:
            raise ReasoningActivationError(
                "soft_reasoning_model_budget_insufficient",
                "Strict Soft Reasoning requires a model-call budget of at least "
                f"{required}; RuntimePolicy authorized {available}",
            )


def get_runtime_reasoning_bridge() -> RuntimeReasoningBridge:
    return RuntimeReasoningBridge()


__all__ = [
    "ReasoningActivation",
    "ReasoningActivationError",
    "RuntimeReasoningBridge",
    "SOFT_EXPLORATION_MODE",
    "get_runtime_reasoning_bridge",
]
