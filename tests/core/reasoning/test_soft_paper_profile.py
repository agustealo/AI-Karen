from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftBatchVerification,
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
    CoherenceMode,
    PaperRewardComposer,
    PaperRewardConfig,
    SoftReasoningCoherenceUnavailable,
)


@dataclass
class PaperGenerationRuntime:
    include_coherence: bool = True
    hidden_size: int = 64

    def capabilities(self) -> SoftGenerationCapabilities:
        return SoftGenerationCapabilities(
            supports_first_token_embedding_control=True,
            supports_logprobs=self.include_coherence,
            hidden_size=self.hidden_size,
            runtime_engine="paper-test-runtime",
            model_id="paper-test-model",
        )

    def first_token_embedding(self, prompt: str) -> list[float]:
        del prompt
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
        token_logs = (-0.10, -0.20, -0.15, -0.25) if self.include_coherence else ()
        return SoftGenerationOutput(
            text=f"candidate={signal:.8f}",
            token_count=4,
            model_id="paper-test-model",
            runtime_engine="paper-test-runtime",
            token_log_probabilities=token_logs,
            sequence_log_probability=sum(token_logs) if token_logs else None,
            mean_token_log_probability=(sum(token_logs) / 4.0 if token_logs else None),
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
        return SoftVerificationScore(score=0.8, confidence=0.9, passed=True)


class MultiGenerateVerifier:
    def __init__(self, model_id: str = "paper-test-model") -> None:
        self.model_id = model_id
        self.calls = 0

    def verify_batch(
        self,
        objective: str,
        responses: list[str] | tuple[str, ...],
        *,
        evidence: tuple[str, ...] | list[str],
    ) -> SoftBatchVerification:
        del objective, evidence
        self.calls += 1
        scores = tuple(
            SoftVerificationScore(
                score=1.0,
                confidence=0.9,
                passed=True,
                components={"multi_generate_match": 1.0},
            )
            for _ in responses
        )
        return SoftBatchVerification(
            refined_output="candidate consensus",
            candidate_scores=scores,
            verifier_model_id=self.model_id,
            runtime_engine="paper-test-runtime",
        )


def test_paper_equation_uses_sequence_log_probability_exactly() -> None:
    output = SoftGenerationOutput(
        text="answer",
        token_count=4,
        token_log_probabilities=(-0.2, -0.3, -0.4, -0.5),
        sequence_log_probability=-1.4,
        mean_token_log_probability=-0.35,
    )
    verification = SoftVerificationScore(score=0.8, confidence=0.9, passed=True)

    reward = PaperRewardComposer().compose(verification, output)

    assert reward.verifier_reward == 1.0
    assert reward.coherence_reward == pytest.approx(-1.4)
    assert reward.score == pytest.approx(-0.4)
    assert reward.coherence_mode == "paper_sequence_log_probability"


def test_reference_code_mode_uses_arithmetic_mean_token_probability() -> None:
    output = SoftGenerationOutput(
        text="answer",
        token_count=2,
        token_log_probabilities=(-0.1, -1.0),
    )
    verification = SoftVerificationScore(score=0.0, passed=False)
    composer = PaperRewardComposer(
        PaperRewardConfig(
            coherence_mode=CoherenceMode.REFERENCE_MEAN_TOKEN_PROBABILITY
        )
    )

    reward = composer.compose(verification, output)

    expected = (pytest.approx((2.718281828459045 ** -0.1 + 2.718281828459045 ** -1.0) / 2.0))
    assert reward.mean_token_probability == expected
    assert reward.score == expected


def test_paper_reward_fails_closed_without_coherence_signal() -> None:
    output = SoftGenerationOutput(text="answer", token_count=4)

    with pytest.raises(SoftReasoningCoherenceUnavailable):
        PaperRewardComposer().compose(
            SoftVerificationScore(score=0.9, passed=True),
            output,
        )


def test_paper_2025_profile_locks_research_mechanics() -> None:
    config = SoftExplorationConfig.paper_2025()

    assert config.research_profile == "paper_2025"
    assert config.projection_dimension == 50
    assert config.initial_samples == 5
    assert config.batch_size == 5
    assert config.max_iterations == 4
    assert config.acquisition == AcquisitionFunction.EI
    assert config.candidate_pool_size == 5000
    assert config.adaptive_ei is True
    assert config.adaptive_delta == pytest.approx(0.1)
    assert config.normalize_projection is False


def test_paper_2025_requires_multi_generate_batch_verifier() -> None:
    engine = SoftExplorationEngine(
        generation=PaperGenerationRuntime(),
        verifier=PassingVerifier(),
        config=replace(
            SoftExplorationConfig.paper_2025(),
            candidate_pool_size=16,
            max_iterations=0,
        ),
    )

    with pytest.raises(SoftReasoningUnavailable, match="Multi-Generate"):
        engine.explore(
            "PROMPT-V1: solve",
            objective="solve",
            max_model_calls=5,
            max_output_tokens=16,
        )


def test_paper_2025_runs_k_candidate_batch_with_composite_reward() -> None:
    batch_verifier = MultiGenerateVerifier()
    engine = SoftExplorationEngine(
        generation=PaperGenerationRuntime(include_coherence=True),
        verifier=PassingVerifier(),
        batch_verifier=batch_verifier,
        config=replace(
            SoftExplorationConfig.paper_2025(),
            candidate_pool_size=24,
            max_iterations=1,
        ),
    )

    trace = engine.explore(
        "PROMPT-V1: solve",
        objective="solve",
        max_model_calls=10,
        max_output_tokens=16,
        correlation_id="paper-profile",
    )

    assert trace.research_profile == "paper_2025"
    assert trace.acquisition_function == "ei"
    assert trace.optimizer_surrogate_kind == "gaussian_process"
    assert trace.model_calls == 10
    assert trace.verifier_calls == 2
    assert trace.batches == 2
    assert len(trace.candidates) == 10
    assert all(candidate.search_score is not None for candidate in trace.candidates)
    assert batch_verifier.calls == 2


def test_paper_2025_requires_same_generator_and_verifier_model() -> None:
    engine = SoftExplorationEngine(
        generation=PaperGenerationRuntime(),
        verifier=PassingVerifier(),
        batch_verifier=MultiGenerateVerifier(model_id="different-model"),
        config=replace(
            SoftExplorationConfig.paper_2025(),
            candidate_pool_size=16,
            max_iterations=0,
        ),
    )

    with pytest.raises(SoftReasoningUnavailable, match="same model"):
        engine.explore(
            "PROMPT-V1: solve",
            objective="solve",
            max_model_calls=5,
            max_output_tokens=16,
        )


def test_paper_2025_refuses_runtime_without_coherence() -> None:
    engine = SoftExplorationEngine(
        generation=PaperGenerationRuntime(include_coherence=False),
        verifier=PassingVerifier(),
        batch_verifier=MultiGenerateVerifier(),
        config=replace(
            SoftExplorationConfig.paper_2025(),
            candidate_pool_size=16,
            max_iterations=0,
        ),
    )

    with pytest.raises(SoftReasoningUnavailable):
        engine.explore(
            "PROMPT-V1: solve",
            objective="solve",
            max_model_calls=5,
            max_output_tokens=16,
        )
