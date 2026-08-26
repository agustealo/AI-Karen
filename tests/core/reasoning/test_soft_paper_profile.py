from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftGenerationCapabilities,
    SoftGenerationOutput,
    SoftVerificationScore,
)
from ai_karen_engine.core.reasoning.soft_reasoning.exploration import (
    SoftExplorationConfig,
    SoftExplorationEngine,
    SoftReasoningUnavailable,
)
from ai_karen_engine.core.reasoning.soft_reasoning.optimization import (
    AcquisitionFunction,
)
from ai_karen_engine.core.reasoning.soft_reasoning.paper_reward import (
    PaperRewardComposer,
    SoftReasoningCoherenceUnavailable,
)


@dataclass
class PaperGenerationRuntime:
    include_coherence: bool = True
    hidden_size: int = 64

    def capabilities(self) -> SoftGenerationCapabilities:
        return SoftGenerationCapabilities(
            supports_first_token_embedding_control=True,
            hidden_size=self.hidden_size,
            runtime_engine="paper-test-runtime",
            model_id="paper-test-model",
        )

    def first_token_embedding(self, prompt: str) -> list[float]:
        return [0.0] * self.hidden_size

    def generate_with_first_token_embedding(
        self,
        prompt: str,
        first_token_embedding: list[float] | tuple[float, ...],
        *,
        max_tokens: int,
        seed: int,
    ) -> SoftGenerationOutput:
        del prompt, max_tokens, seed
        signal = sum(first_token_embedding)
        return SoftGenerationOutput(
            text=f"candidate={signal:.8f}",
            token_count=4,
            model_id="paper-test-model",
            runtime_engine="paper-test-runtime",
            mean_token_log_probability=(
                -0.2 + min(0.0, signal * 0.001)
                if self.include_coherence
                else None
            ),
        )


class PassingVerifier:
    def score(
        self,
        objective: str,
        response: str,
        *,
        evidence: tuple[str, ...] | list[str],
    ) -> SoftVerificationScore:
        del objective, response, evidence
        return SoftVerificationScore(
            score=0.8,
            confidence=0.9,
            passed=True,
        )


def test_paper_reward_combines_verifier_success_and_generation_coherence() -> None:
    output = SoftGenerationOutput(
        text="answer",
        token_count=4,
        mean_token_log_probability=-0.5,
    )
    verification = SoftVerificationScore(
        score=0.8,
        confidence=0.9,
        passed=True,
    )

    reward = PaperRewardComposer().compose(verification, output)

    assert reward.verifier_reward == 1.0
    assert reward.coherence_reward == pytest.approx(math.exp(-0.5))
    assert reward.score == pytest.approx(1.0 + math.exp(-0.5))


def test_paper_reward_can_derive_mean_log_probability_from_sequence_total() -> None:
    output = SoftGenerationOutput(
        text="answer",
        token_count=4,
        sequence_log_probability=-2.0,
    )
    verification = SoftVerificationScore(score=0.2, passed=False)

    reward = PaperRewardComposer().compose(verification, output)

    assert reward.mean_token_log_probability == pytest.approx(-0.5)
    assert reward.verifier_reward == 0.0
    assert reward.coherence_reward == pytest.approx(math.exp(-0.5))


def test_paper_reward_fails_closed_without_coherence_signal() -> None:
    output = SoftGenerationOutput(text="answer", token_count=4)

    with pytest.raises(SoftReasoningCoherenceUnavailable):
        PaperRewardComposer().compose(
            SoftVerificationScore(score=0.9, passed=True),
            output,
        )


def test_paper_2025_profile_uses_expected_improvement_and_50_dimensions() -> None:
    config = SoftExplorationConfig.paper_2025()

    assert config.research_profile == "paper_2025"
    assert config.projection_dimension == 50
    assert config.acquisition == AcquisitionFunction.EI


def test_paper_2025_exploration_uses_composite_search_reward() -> None:
    engine = SoftExplorationEngine(
        generation=PaperGenerationRuntime(include_coherence=True),
        verifier=PassingVerifier(),
        config=SoftExplorationConfig.paper_2025(),
    )

    trace = engine.explore(
        "PROMPT-V1: solve",
        objective="solve",
        max_model_calls=4,
        max_output_tokens=16,
        correlation_id="paper-profile",
    )

    assert trace.research_profile == "paper_2025"
    assert trace.acquisition_function == "ei"
    assert trace.optimizer_surrogate_kind == "gaussian_process"
    assert trace.best_candidate.search_score is not None
    assert trace.best_score > trace.best_candidate.verification.score


def test_paper_2025_exploration_refuses_runtime_without_coherence() -> None:
    engine = SoftExplorationEngine(
        generation=PaperGenerationRuntime(include_coherence=False),
        verifier=PassingVerifier(),
        config=SoftExplorationConfig.paper_2025(),
    )

    with pytest.raises(SoftReasoningUnavailable):
        engine.explore(
            "PROMPT-V1: solve",
            objective="solve",
            max_model_calls=4,
            max_output_tokens=16,
            correlation_id="paper-profile-no-coherence",
        )
