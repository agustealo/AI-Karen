from __future__ import annotations

"""Typed CORTEX contracts for reasoning-strategy eligibility.

CORTEX owns the cognitive decision about which reasoning modes are desirable.
This module does not resolve providers/models, execute strategies, authorize
capabilities, or mutate Runtime budgets. RuntimePolicy remains the sole
authorization owner and Runtime remains the execution owner.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai_karen_engine.core.reasoning.contracts import normalize_reasoning_modes


class EligibilityDisposition(str, Enum):
    """Advisory CORTEX disposition for a candidate reasoning mode."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class ReasoningModeEligibility:
    """CORTEX's advisory assessment of one reasoning strategy.

    Scores are cognitive estimates, not authorization decisions. RuntimePolicy
    may still deny an eligible strategy and Runtime may fail closed if the
    selected model/runtime cannot execute it.
    """

    mode: str
    disposition: EligibilityDisposition
    expected_utility: float = 0.0
    confidence: float = 0.0
    estimated_model_calls: int = 0
    estimated_latency_ms: int = 0
    reason_codes: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = normalize_reasoning_modes([self.mode])
        if len(normalized) != 1:
            raise ValueError("reasoning eligibility requires exactly one mode")
        object.__setattr__(self, "mode", normalized[0])

        if not 0.0 <= float(self.expected_utility) <= 1.0:
            raise ValueError("expected_utility must be within [0, 1]")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        if self.estimated_model_calls < 0:
            raise ValueError("estimated_model_calls must be non-negative")
        if self.estimated_latency_ms < 0:
            raise ValueError("estimated_latency_ms must be non-negative")

        if self.disposition == EligibilityDisposition.ELIGIBLE and self.rejection_reasons:
            raise ValueError("eligible reasoning mode cannot carry rejection reasons")


@dataclass(frozen=True, slots=True)
class ReasoningEligibilityDecision:
    """Canonical CORTEX reasoning-eligibility decision.

    The decision is advisory and deliberately provider/model agnostic. CORTEX
    may rank/select cognitively useful modes; RuntimePolicy authorizes them and
    Runtime validates executability against the resolved runtime capability and
    budget before activation.
    """

    assessments: tuple[ReasoningModeEligibility, ...] = ()
    selected_modes: tuple[str, ...] = ()
    decision_confidence: float = 0.0
    reason_codes: tuple[str, ...] = ()
    policy_hints: dict[str, Any] = field(default_factory=dict)
    provenance_version: str = "reasoning-eligibility-v1"

    def __post_init__(self) -> None:
        normalized_selected = tuple(normalize_reasoning_modes(list(self.selected_modes)))
        object.__setattr__(self, "selected_modes", normalized_selected)

        if not 0.0 <= float(self.decision_confidence) <= 1.0:
            raise ValueError("decision_confidence must be within [0, 1]")

        by_mode = {assessment.mode: assessment for assessment in self.assessments}
        missing = [mode for mode in normalized_selected if mode not in by_mode]
        if missing:
            raise ValueError(
                "selected reasoning mode(s) missing eligibility assessment: "
                + ",".join(missing)
            )

        ineligible = [
            mode
            for mode in normalized_selected
            if by_mode[mode].disposition != EligibilityDisposition.ELIGIBLE
        ]
        if ineligible:
            raise ValueError(
                "selected reasoning mode(s) are not eligible: " + ",".join(ineligible)
            )

    @property
    def eligible_modes(self) -> tuple[str, ...]:
        return tuple(
            assessment.mode
            for assessment in self.assessments
            if assessment.disposition == EligibilityDisposition.ELIGIBLE
        )

    @property
    def estimated_model_calls(self) -> int:
        selected = set(self.selected_modes)
        return sum(
            assessment.estimated_model_calls
            for assessment in self.assessments
            if assessment.mode in selected
        )

    @property
    def estimated_latency_ms(self) -> int:
        selected = set(self.selected_modes)
        return sum(
            assessment.estimated_latency_ms
            for assessment in self.assessments
            if assessment.mode in selected
        )


__all__ = [
    "EligibilityDisposition",
    "ReasoningEligibilityDecision",
    "ReasoningModeEligibility",
]
