"""Paper-aligned reward composition for Soft Reasoning.

Zhu et al. combine a verifier reward with a model-generation coherence signal
when optimizing first-token embedding perturbations. KAREN keeps those signals
typed and separate: verifier output comes from ``SoftVerificationScore`` and
coherence comes from generation log-probability fields on
``SoftGenerationOutput``.

This module does not select models, invoke providers, build prompts, or perform
verification. It only composes already-authorized signals into the scalar search
reward used by Bayesian optimisation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftGenerationOutput,
    SoftVerificationScore,
)


class SoftReasoningCoherenceUnavailable(ValueError):
    """Raised when paper-aligned reward lacks a generation coherence signal."""


@dataclass(frozen=True, slots=True)
class PaperRewardConfig:
    verifier_weight: float = 1.0
    coherence_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.verifier_weight < 0.0:
            raise ValueError("verifier_weight must be non-negative")
        if self.coherence_weight < 0.0:
            raise ValueError("coherence_weight must be non-negative")
        if self.verifier_weight + self.coherence_weight <= 0.0:
            raise ValueError("paper reward requires at least one positive weight")


@dataclass(frozen=True, slots=True)
class PaperReward:
    score: float
    verifier_reward: float
    coherence_reward: float
    mean_token_log_probability: float


class PaperRewardComposer:
    """Compose verifier success and generation coherence into search reward."""

    reward_kind = "paper_2025_verifier_plus_coherence"

    def __init__(self, config: PaperRewardConfig | None = None) -> None:
        self._config = config or PaperRewardConfig()

    def compose(
        self,
        verification: SoftVerificationScore,
        output: SoftGenerationOutput,
    ) -> PaperReward:
        mean_log_probability = self._mean_log_probability(output)
        # exp(mean log p) is the geometric-mean token probability and remains in
        # [0, 1] for valid log probabilities. Clamp positive values defensively.
        coherence_reward = math.exp(min(0.0, mean_log_probability))
        verifier_reward = 1.0 if verification.passed else 0.0
        score = (
            self._config.verifier_weight * verifier_reward
            + self._config.coherence_weight * coherence_reward
        )
        return PaperReward(
            score=float(score),
            verifier_reward=verifier_reward,
            coherence_reward=float(coherence_reward),
            mean_token_log_probability=float(mean_log_probability),
        )

    @staticmethod
    def _mean_log_probability(output: SoftGenerationOutput) -> float:
        if output.mean_token_log_probability is not None:
            return float(output.mean_token_log_probability)
        if (
            output.sequence_log_probability is not None
            and output.token_count > 0
        ):
            return float(output.sequence_log_probability) / float(output.token_count)
        raise SoftReasoningCoherenceUnavailable(
            "paper_2025 reward requires mean_token_log_probability or "
            "sequence_log_probability with token_count"
        )


__all__ = [
    "PaperReward",
    "PaperRewardComposer",
    "PaperRewardConfig",
    "SoftReasoningCoherenceUnavailable",
]
