from __future__ import annotations

"""First-class RuntimePolicy authorization for reasoning modes.

CORTEX decides which reasoning modes are cognitively desirable. RuntimePolicy
owns whether those requested modes are authorized under the active runtime
level, risk envelope, and explicit execution budget. Runtime remains responsible
for capability/executability checks after authorization.

This module deliberately does not inspect providers, models, prompts, memory, or
user text. It operates only on canonical reasoning-mode identifiers and trusted
runtime/policy signals.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from ai_karen_engine.core.reasoning.contracts import ReasoningMode, normalize_reasoning_modes


SOFT_EXPLORATION_MIN_MODEL_CALLS = 30


class ReasoningPolicyReason(str, Enum):
    ALLOWED = "allowed"
    RUNTIME_LEVEL_DENIED = "runtime_level_denied"
    RISK_LEVEL_DENIED = "risk_level_denied"
    MODEL_CALL_BUDGET_INSUFFICIENT = "model_call_budget_insufficient"


@dataclass(frozen=True, slots=True)
class ReasoningModePolicyResult:
    """RuntimePolicy result for one canonical reasoning-mode request."""

    requested_modes: tuple[str, ...]
    allowed_modes: tuple[str, ...]
    denied_modes: tuple[str, ...]
    denial_reasons: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def fully_authorized(self) -> bool:
        return not self.denied_modes

    @property
    def any_authorized(self) -> bool:
        return bool(self.allowed_modes)


_RUNTIME_LEVEL_ALLOWED: dict[str, frozenset[str]] = {
    "FULL": frozenset(mode.value for mode in ReasoningMode),
    "REDUCED": frozenset(
        {
            ReasoningMode.CAUSAL.value,
            ReasoningMode.EVIDENCE_SYNTHESIS.value,
            ReasoningMode.VERIFICATION.value,
            ReasoningMode.REFINEMENT.value,
            ReasoningMode.METACOGNITION.value,
        }
    ),
    "SAFE": frozenset(
        {
            ReasoningMode.CAUSAL.value,
            ReasoningMode.EVIDENCE_SYNTHESIS.value,
            ReasoningMode.VERIFICATION.value,
            ReasoningMode.REFINEMENT.value,
        }
    ),
    "EMERGENCY": frozenset(
        {
            ReasoningMode.EVIDENCE_SYNTHESIS.value,
            ReasoningMode.VERIFICATION.value,
        }
    ),
}

_HIGH_RISK_DENIED = frozenset(
    {
        ReasoningMode.SOFT_EXPLORATION.value,
        ReasoningMode.COUNTERFACTUAL.value,
    }
)

_CRITICAL_RISK_DENIED = frozenset(
    {
        ReasoningMode.SOFT_EXPLORATION.value,
        ReasoningMode.COUNTERFACTUAL.value,
        ReasoningMode.HYPOTHESIS_COMPARISON.value,
    }
)


def _runtime_level_value(runtime_level: object) -> str:
    value = getattr(runtime_level, "value", runtime_level)
    normalized = str(value or "FULL").strip().upper()
    return normalized if normalized in _RUNTIME_LEVEL_ALLOWED else "FULL"


def _risk_level_value(risk_level: object) -> str:
    value = getattr(risk_level, "value", risk_level)
    normalized = str(value or "low").strip().lower()
    return normalized if normalized in {"low", "medium", "high", "critical"} else "low"


def authorize_reasoning_modes(
    requested_modes: Iterable[str],
    *,
    runtime_level: object = "FULL",
    risk_level: object = "low",
    max_model_calls: int = 0,
) -> ReasoningModePolicyResult:
    """Authorize canonical reasoning modes without inventing new cognition.

    Rules intentionally separate cognitive desirability from execution policy:

    * CORTEX supplies ``requested_modes``.
    * Runtime level can reduce the permitted reasoning surface.
    * High/critical risk rejects exploratory modes whose benefit depends on
      speculative search rather than authoritative evidence.
    * strict Soft Reasoning requires its full declared test-time compute budget.

    An empty request remains empty; RuntimePolicy never creates a default mode.
    """

    canonical = tuple(normalize_reasoning_modes(list(requested_modes)))
    if not canonical:
        return ReasoningModePolicyResult((), (), (), {})

    level = _runtime_level_value(runtime_level)
    risk = _risk_level_value(risk_level)
    allowed_at_level = _RUNTIME_LEVEL_ALLOWED[level]

    allowed: list[str] = []
    denied: list[str] = []
    reasons: dict[str, tuple[str, ...]] = {}

    risk_denied = (
        _CRITICAL_RISK_DENIED
        if risk == "critical"
        else _HIGH_RISK_DENIED
        if risk == "high"
        else frozenset()
    )

    for mode in canonical:
        mode_reasons: list[str] = []

        if mode not in allowed_at_level:
            mode_reasons.append(ReasoningPolicyReason.RUNTIME_LEVEL_DENIED.value)

        if mode in risk_denied:
            mode_reasons.append(ReasoningPolicyReason.RISK_LEVEL_DENIED.value)

        if (
            mode == ReasoningMode.SOFT_EXPLORATION.value
            and int(max_model_calls) < SOFT_EXPLORATION_MIN_MODEL_CALLS
        ):
            mode_reasons.append(
                ReasoningPolicyReason.MODEL_CALL_BUDGET_INSUFFICIENT.value
            )

        if mode_reasons:
            denied.append(mode)
            reasons[mode] = tuple(dict.fromkeys(mode_reasons))
        else:
            allowed.append(mode)

    return ReasoningModePolicyResult(
        requested_modes=canonical,
        allowed_modes=tuple(allowed),
        denied_modes=tuple(denied),
        denial_reasons=reasons,
    )


__all__ = [
    "ReasoningModePolicyResult",
    "ReasoningPolicyReason",
    "SOFT_EXPLORATION_MIN_MODEL_CALLS",
    "authorize_reasoning_modes",
]
