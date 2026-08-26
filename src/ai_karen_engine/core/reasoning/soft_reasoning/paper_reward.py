"""Paper/reference-code reward composition for Soft Reasoning.

The ICML paper defines coherence as the sum of token log probabilities:
    r_coherence(y) = sum_t log P(w_t)
while the released reference implementation computes the arithmetic mean of
per-token probabilities. KAREN keeps both semantics explicit so experiments can
state whether they reproduce the paper equation or the released code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftGenerationOutput,
    SoftVerificationScore,
)


class SoftReasoningCoherenceUnavailable(ValueError):
    pass


class CoherenceMode(Enum):
    PAPER_SEQUENCE_LOG_PROBABILITY = "paper_sequence_log_probability"
    REFERENCE_MEAN_TOKEN_PROBABILITY = "reference_mean_token_probability"


@dataclass(frozen=True, slots=True)
class PaperRewardConfig:
    verifier_weight: float = 1.0
    coherence_weight: float = 1.0
    coherence_mode: CoherenceMode = CoherenceMode.PAPER_SEQUENCE_LOG_PROBABILITY

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
    coherence_mode: str
    sequence_log_probability: float | None = None
    mean_token_probability: float | None = None


class PaperRewardComposer:
    reward_kind = "soft_reasoning_verifier_plus_coherence"

    def __init__(self, config: PaperRewardConfig | None = None) -> None:
        self._config = config or PaperRewardConfig()

    def compose(
        self,
        verification: SoftVerificationScore,
        output: SoftGenerationOutput,
    ) -> PaperReward:
        verifier_reward = 1.0 if verification.passed else 0.0
        sequence_log_probability: float | None = None
        mean_token_probability: float | None = None

        if (
            self._config.coherence_mode
            == CoherenceMode.PAPER_SEQUENCE_LOG_PROBABILITY
        ):
            coherence_reward = self._sequence_log_probability(output)
            sequence_log_probability = coherence_reward
        else:
            coherence_reward = self._mean_token_probability(output)
            mean_token_probability = coherence_reward

        score = (
            self._config.verifier_weight * verifier_reward
            + self._config.coherence_weight * coherence_reward
        )
        return PaperReward(
            score=float(score),
            verifier_reward=verifier_reward,
            coherence_reward=float(coherence_reward),
            coherence_mode=self._config.coherence_mode.value,
            sequence_log_probability=sequence_log_probability,
            mean_token_probability=mean_token_probability,
        )

    @staticmethod
    def _sequence_log_probability(output: SoftGenerationOutput) -> float:
        if output.sequence_log_probability is not None:
            return float(output.sequence_log_probability)
        if output.token_log_probabilities:
            return float(sum(output.token_log_probabilities))
        if output.mean_token_log_probability is not None and output.token_count > 0:
            return float(output.mean_token_log_probability) * float(output.token_count)
        raise SoftReasoningCoherenceUnavailable(
            "paper equation requires sequence_log_probability, token log "
            "probabilities, or mean_token_log_probability with token_count"
        )

    @staticmethod
    def _mean_token_probability(output: SoftGenerationOutput) -> float:
        if output.token_log_probabilities:
            return float(
                sum(math.exp(min(0.0, value)) for value in output.token_log_probabilities)
                / len(output.token_log_probabilities)
            )
        raise SoftReasoningCoherenceUnavailable(
            "reference-code coherence requires token_log_probabilities so the "
            "arithmetic mean of token probabilities can be reproduced exactly"
        )


__all__ = [
    "CoherenceMode",
    "PaperReward",
    "PaperRewardComposer",
    "PaperRewardConfig",
    "SoftReasoningCoherenceUnavailable",
]
