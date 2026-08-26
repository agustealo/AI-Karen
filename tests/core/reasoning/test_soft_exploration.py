from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_karen_engine.core.reasoning.defaults import get_default_strategies
from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftGenerationCapabilities,
    SoftGenerationOutput,
    SoftVerificationScore,
)
from ai_karen_engine.core.reasoning.soft_reasoning.exploration import (
    SoftExplorationConfig,
    SoftExplorationEngine,
    SoftReasoningBudgetError,
    SoftReasoningUnavailable,
)


@dataclass
class FakeGenerationRuntime:
    enabled: bool = True
    hidden_size: int = 8
    calls: int = 0

    def capabilities(self) -> SoftGenerationCapabilities:
        return SoftGenerationCapabilities(
            supports_first_token_embedding_control=self.enabled,
            hidden_size=self.hidden_size if self.enabled else 0,
            runtime_engine="fake-local-runtime",
            model_id="fake-model",
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
        self.calls += 1
        signal = sum(first_token_embedding)
        return SoftGenerationOutput(
            text=f"candidate signal={signal:.8f}",
            token_count=min(max_tokens, 4),
            finish_reason="stop",
            model_id="fake-model",
            runtime_engine="fake-local-runtime",
            metadata={"seed": seed, "signal": signal},
        )


@dataclass
class FakeVerifier:
    calls: int = 0

    def score(
        self,
        objective: str,
        response: str,
        *,
        evidence: tuple[str, ...] | list[str],
    ) -> SoftVerificationScore:
        self.calls += 1
        signal = float(response.rsplit("=", 1)[1])
        score = max(0.0, min(1.0, 0.5 + signal * 0.05))
        return SoftVerificationScore(
            score=score,
            confidence=0.9,
            passed=score >= 0.5,
            feedback="deterministic fake verifier",
            components={"signal": score},
        )


def test_soft_exploration_uses_embedding_candidates_and_verifier_within_budget() -> None:
    runtime = FakeGenerationRuntime()
    verifier = FakeVerifier()
    engine = SoftExplorationEngine(
        generation=runtime,
        verifier=verifier,
        config=SoftExplorationConfig(
            projection_dimension=4,
            initial_samples=3,
            max_iterations=2,
            perturbation_std=0.2,
            embedding_scale=0.1,
            default_seed=11,
        ),
    )

    trace = engine.explore(
        "solve this",
        evidence=("fact one",),
        max_model_calls=5,
        max_output_tokens=32,
        correlation_id="corr-123",
    )

    assert trace.model_calls == runtime.calls
    assert trace.verifier_calls == verifier.calls
    assert 1 <= trace.model_calls <= 5
    assert len(trace.candidates) == trace.model_calls
    assert trace.best_score >= trace.baseline_score
    assert trace.best_candidate.output.text.startswith("candidate signal=")
    assert trace.runtime_engine == "fake-local-runtime"
    assert trace.model_id == "fake-model"
    assert trace.projection_dimension == 4


def test_soft_exploration_is_reproducible_for_same_correlation_id() -> None:
    config = SoftExplorationConfig(
        projection_dimension=4,
        initial_samples=3,
        max_iterations=1,
        default_seed=3,
    )

    first = SoftExplorationEngine(
        generation=FakeGenerationRuntime(),
        verifier=FakeVerifier(),
        config=config,
    ).explore(
        "reason carefully",
        max_model_calls=4,
        max_output_tokens=16,
        correlation_id="same-correlation",
    )
    second = SoftExplorationEngine(
        generation=FakeGenerationRuntime(),
        verifier=FakeVerifier(),
        config=config,
    ).explore(
        "reason carefully",
        max_model_calls=4,
        max_output_tokens=16,
        correlation_id="same-correlation",
    )

    assert first.seed == second.seed
    assert [candidate.latent for candidate in first.candidates] == [
        candidate.latent for candidate in second.candidates
    ]
    assert first.best_score == second.best_score


def test_soft_exploration_rejects_runtime_without_embedding_control() -> None:
    engine = SoftExplorationEngine(
        generation=FakeGenerationRuntime(enabled=False),
        verifier=FakeVerifier(),
    )

    with pytest.raises(SoftReasoningUnavailable):
        engine.explore(
            "reason",
            max_model_calls=4,
            max_output_tokens=16,
        )


def test_soft_exploration_fails_closed_when_model_call_budget_is_too_small() -> None:
    engine = SoftExplorationEngine(
        generation=FakeGenerationRuntime(),
        verifier=FakeVerifier(),
        config=SoftExplorationConfig(initial_samples=4),
    )

    with pytest.raises(SoftReasoningBudgetError):
        engine.explore(
            "reason",
            max_model_calls=3,
            max_output_tokens=16,
        )


def test_soft_reasoning_is_not_bootstrapped_as_a_universal_default() -> None:
    strategy_ids = [strategy.strategy_id for strategy in get_default_strategies()]

    assert "soft_exploration" not in strategy_ids
