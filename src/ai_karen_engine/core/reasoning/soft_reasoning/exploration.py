"""Research-aligned Soft Reasoning exploration engine.

The algorithm follows the architectural shape of Zhu et al. (ICML 2025):
1. obtain the model's first answer-token embedding from an injected runtime;
2. explore a low-dimensional latent space projected into hidden space;
3. generate candidate solutions under controlled embedding perturbations;
4. score candidates with an injected verifier objective;
5. use Gaussian-process Bayesian optimisation to refine the latent perturbation.

Research fidelity boundary:
The optimizer now uses a real Gaussian Process posterior. The default KAREN
profile still differs from the paper in acquisition/search defaults and reward
composition: KAREN defaults to UCB and its structured verifier score, while a
paper-faithful profile must select Expected Improvement and combine verifier
reward with typed generation-coherence/log-probability data.

The engine is intentionally unaware of providers, memory stores, plugins,
tools, HTTP, UI, and prompt assembly. Runtime must inject the model capability,
verifier, and a versioned prepared prompt.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Sequence

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftCandidate,
    SoftExplorationTrace,
    SoftGenerationPort,
    SoftVerifierPort,
)
from ai_karen_engine.core.reasoning.soft_reasoning.optimization import (
    AcquisitionFunction,
    BayesianOptimizer,
    OptimizationConfig,
)


class SoftReasoningUnavailable(RuntimeError):
    """Raised when the injected runtime cannot support embedding exploration."""


class SoftReasoningBudgetError(RuntimeError):
    """Raised when the authorized model-call budget cannot run the algorithm."""


@dataclass(frozen=True, slots=True)
class SoftExplorationConfig:
    projection_dimension: int = 16
    initial_samples: int = 4
    max_iterations: int = 4
    perturbation_std: float = 0.35
    embedding_scale: float = 0.15
    acquisition: AcquisitionFunction = AcquisitionFunction.UCB
    exploration_weight: float = 2.0
    convergence_threshold: float = 0.01
    default_seed: int = 17
    research_profile: str = "karen_default"

    def __post_init__(self) -> None:
        if self.projection_dimension <= 0:
            raise ValueError("projection_dimension must be positive")
        if self.initial_samples <= 0:
            raise ValueError("initial_samples must be positive")
        if self.max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")
        if self.perturbation_std <= 0:
            raise ValueError("perturbation_std must be positive")
        if self.embedding_scale <= 0:
            raise ValueError("embedding_scale must be positive")
        if not self.research_profile.strip():
            raise ValueError("research_profile must not be empty")


class SoftExplorationEngine:
    """Verifier-guided search over first-token embedding perturbations."""

    def __init__(
        self,
        *,
        generation: SoftGenerationPort,
        verifier: SoftVerifierPort,
        config: SoftExplorationConfig | None = None,
    ) -> None:
        self._generation = generation
        self._verifier = verifier
        self._config = config or SoftExplorationConfig()

    def explore(
        self,
        prompt: str,
        *,
        objective: str,
        evidence: Sequence[str] = (),
        max_model_calls: int,
        max_output_tokens: int,
        correlation_id: str = "",
    ) -> SoftExplorationTrace:
        if not prompt.strip():
            raise ValueError("prepared prompt must not be empty")
        if not objective.strip():
            raise ValueError("objective must not be empty")
        if max_output_tokens <= 0:
            raise SoftReasoningBudgetError("max_output_tokens must be positive")

        capabilities = self._generation.capabilities()
        if not capabilities.supports_first_token_embedding_control:
            raise SoftReasoningUnavailable(
                f"runtime {capabilities.runtime_engine!r} does not expose first-token embedding control"
            )

        base_embedding = tuple(
            float(value) for value in self._generation.first_token_embedding(prompt)
        )
        if len(base_embedding) != capabilities.hidden_size:
            raise SoftReasoningUnavailable(
                "runtime first-token embedding size does not match declared hidden_size"
            )
        if not base_embedding:
            raise SoftReasoningUnavailable("runtime returned an empty first-token embedding")

        required_minimum = max(1, self._config.initial_samples)
        if max_model_calls < required_minimum:
            raise SoftReasoningBudgetError(
                f"soft exploration requires at least {required_minimum} model calls; budget={max_model_calls}"
            )

        seed = self._seed(correlation_id)
        rng = random.Random(seed)
        projection = self._projection_matrix(
            latent_dim=self._config.projection_dimension,
            hidden_dim=len(base_embedding),
            rng=rng,
        )

        max_iterations = min(
            self._config.max_iterations,
            max(0, max_model_calls - self._config.initial_samples),
        )
        optimizer = BayesianOptimizer(
            OptimizationConfig(
                acquisition_fn=self._config.acquisition,
                exploration_weight=self._config.exploration_weight,
                max_iterations=max_iterations,
                convergence_threshold=self._config.convergence_threshold,
                initial_samples=self._config.initial_samples,
                length_scale=1.0,
                noise_variance=0.01,
            )
        )

        candidates: dict[tuple[float, ...], SoftCandidate] = {}
        model_calls = 0
        verifier_calls = 0

        def perturb(latent: list[float]) -> list[float]:
            return [
                value + rng.gauss(0.0, self._config.perturbation_std)
                for value in latent
            ]

        def score_latent(latent: list[float]) -> float:
            nonlocal model_calls, verifier_calls
            if model_calls >= max_model_calls:
                return 0.0

            key = tuple(round(float(value), 12) for value in latent)
            existing = candidates.get(key)
            if existing is not None:
                return existing.verification.score

            guided_embedding = self._apply_projection(
                base_embedding=base_embedding,
                latent=latent,
                projection=projection,
                scale=self._config.embedding_scale,
            )
            call_seed = seed + model_calls
            output = self._generation.generate_with_first_token_embedding(
                prompt,
                guided_embedding,
                max_tokens=max_output_tokens,
                seed=call_seed,
            )
            model_calls += 1

            verification = self._verifier.score(
                objective,
                output.text,
                evidence=evidence,
            )
            verifier_calls += 1

            candidate_id = hashlib.sha256(
                f"{correlation_id}|{model_calls}|{key}".encode("utf-8")
            ).hexdigest()[:16]
            candidates[key] = SoftCandidate(
                candidate_id=f"soft-{candidate_id}",
                latent=tuple(float(value) for value in latent),
                first_token_embedding=guided_embedding,
                output=output,
                verification=verification,
                iteration=model_calls - 1,
            )
            return verification.score

        initial_latent = [0.0] * self._config.projection_dimension
        optimization = optimizer.optimize(
            initial_embedding=initial_latent,
            score_function=score_latent,
            perturb_fn=perturb,
        )

        if not candidates:
            raise SoftReasoningUnavailable("soft exploration produced no candidates")

        best = max(candidates.values(), key=lambda item: item.verification.score)
        baseline = candidates.get(tuple(0.0 for _ in initial_latent))
        baseline_score = baseline.verification.score if baseline else optimization.history[0][1]
        best_score = best.verification.score

        ordered = tuple(sorted(candidates.values(), key=lambda item: item.iteration))
        return SoftExplorationTrace(
            best_candidate=best,
            candidates=ordered,
            baseline_score=float(baseline_score),
            best_score=float(best_score),
            improvement=float(best_score - baseline_score),
            projection_dimension=self._config.projection_dimension,
            model_calls=model_calls,
            verifier_calls=verifier_calls,
            seed=seed,
            runtime_engine=capabilities.runtime_engine,
            model_id=capabilities.model_id,
            optimizer_surrogate_kind=optimization.surrogate_kind,
            acquisition_function=self._config.acquisition.value,
            research_profile=self._config.research_profile,
        )

    def _seed(self, correlation_id: str) -> int:
        if not correlation_id:
            return self._config.default_seed
        digest = hashlib.sha256(correlation_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big", signed=False)

    @staticmethod
    def _projection_matrix(
        *,
        latent_dim: int,
        hidden_dim: int,
        rng: random.Random,
    ) -> tuple[tuple[float, ...], ...]:
        normalizer = 1.0 / math.sqrt(float(latent_dim))
        return tuple(
            tuple(rng.gauss(0.0, 1.0) * normalizer for _ in range(hidden_dim))
            for _ in range(latent_dim)
        )

    @staticmethod
    def _apply_projection(
        *,
        base_embedding: tuple[float, ...],
        latent: Sequence[float],
        projection: tuple[tuple[float, ...], ...],
        scale: float,
    ) -> tuple[float, ...]:
        hidden_dim = len(base_embedding)
        delta = [0.0] * hidden_dim
        for latent_value, row in zip(latent, projection):
            for index, projected_value in enumerate(row):
                delta[index] += float(latent_value) * projected_value
        return tuple(
            base_embedding[index] + scale * delta[index]
            for index in range(hidden_dim)
        )


__all__ = [
    "SoftExplorationConfig",
    "SoftExplorationEngine",
    "SoftReasoningBudgetError",
    "SoftReasoningUnavailable",
]
