"""Soft Reasoning exploration engine.

``karen_default`` remains a low-cost KAREN reasoning strategy. ``paper_2025``
is a strict research profile matching the method described by Zhu et al.:
- z is the greedy first generated token embedding supplied by Runtime;
- x = z + sigma * A u with Gaussian latent perturbations;
- one first-token embedding is controlled and the rest is greedy generation;
- d=50 random projection with N(0,1) entries;
- k=5 candidates are evaluated jointly by a Multi-Generate batch verifier;
- verifier reward is binary and coherence is sequence log probability;
- a true RBF GP with noise-adaptive Expected Improvement selects new points;
- 5000 Gaussian candidate points approximate the EI maximizer;
- convergence uses consecutive batch objective change with a four-round cap.

Runtime must inject model and verifier adapters. Core never selects providers,
models, prompts, tools, memory, or authorization policy.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, replace
from typing import Sequence

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftBatchVerifierPort,
    SoftCandidate,
    SoftExplorationTrace,
    SoftGenerationPort,
    SoftVerifierPort,
)
from ai_karen_engine.core.reasoning.soft_reasoning.optimization import (
    AcquisitionFunction,
    BayesianOptimizer,
    ConvergenceMode,
    OptimizationConfig,
)
from ai_karen_engine.core.reasoning.soft_reasoning.paper_reward import (
    CoherenceMode,
    PaperRewardComposer,
    PaperRewardConfig,
    SoftReasoningCoherenceUnavailable,
)


class SoftReasoningUnavailable(RuntimeError):
    pass


class SoftReasoningBudgetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SoftExplorationConfig:
    projection_dimension: int = 16
    initial_samples: int = 4
    max_iterations: int = 4
    batch_size: int = 1
    perturbation_std: float = 0.35
    embedding_scale: float = 0.15
    normalize_projection: bool = True
    acquisition: AcquisitionFunction = AcquisitionFunction.UCB
    exploration_weight: float = 2.0
    convergence_threshold: float = 0.01
    candidate_pool_size: int = 64
    gp_noise_variance: float = 0.01
    gp_normalize_y: bool = True
    adaptive_ei: bool = False
    adaptive_delta: float = 0.1
    objective_noise_variance: float = 0.01
    default_seed: int = 17
    research_profile: str = "karen_default"

    def __post_init__(self) -> None:
        if self.projection_dimension <= 0:
            raise ValueError("projection_dimension must be positive")
        if self.initial_samples <= 0:
            raise ValueError("initial_samples must be positive")
        if self.max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.perturbation_std <= 0:
            raise ValueError("perturbation_std must be positive")
        if self.embedding_scale <= 0:
            raise ValueError("embedding_scale must be positive")
        if self.candidate_pool_size <= 0:
            raise ValueError("candidate_pool_size must be positive")
        if not self.research_profile.strip():
            raise ValueError("research_profile must not be empty")

    @classmethod
    def paper_2025(cls) -> "SoftExplorationConfig":
        """Strict paper-equation profile.

        The paper does not publish a single universal sigma or verifier noise
        lambda. KAREN therefore exposes ``embedding_scale`` and
        ``objective_noise_variance`` as explicit benchmark parameters; the
        defaults below are reproducible reference values, not claimed paper
        constants.
        """

        return cls(
            projection_dimension=50,
            initial_samples=5,
            max_iterations=4,
            batch_size=5,
            perturbation_std=1.0,
            embedding_scale=1.0,
            normalize_projection=False,
            acquisition=AcquisitionFunction.EI,
            convergence_threshold=0.01,
            candidate_pool_size=5000,
            gp_noise_variance=1e-8,
            gp_normalize_y=False,
            adaptive_ei=True,
            adaptive_delta=0.1,
            objective_noise_variance=0.01,
            research_profile="paper_2025",
        )


class SoftExplorationEngine:
    def __init__(
        self,
        *,
        generation: SoftGenerationPort,
        verifier: SoftVerifierPort,
        batch_verifier: SoftBatchVerifierPort | None = None,
        config: SoftExplorationConfig | None = None,
    ) -> None:
        self._generation = generation
        self._verifier = verifier
        self._batch_verifier = batch_verifier
        self._config = config or SoftExplorationConfig()
        self._paper_reward = PaperRewardComposer(
            PaperRewardConfig(
                coherence_mode=CoherenceMode.PAPER_SEQUENCE_LOG_PROBABILITY
            )
        )

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
        self._validate_request(prompt, objective, max_output_tokens)
        capabilities = self._generation.capabilities()
        if not capabilities.supports_first_token_embedding_control:
            raise SoftReasoningUnavailable(
                f"runtime {capabilities.runtime_engine!r} does not expose first-token embedding control"
            )

        base_embedding = tuple(
            float(value) for value in self._generation.first_token_embedding(prompt)
        )
        if len(base_embedding) != capabilities.hidden_size or not base_embedding:
            raise SoftReasoningUnavailable(
                "runtime first-token embedding does not match declared hidden_size"
            )

        seed = self._seed(correlation_id)
        rng = random.Random(seed)
        projection = self._projection_matrix(
            latent_dim=self._config.projection_dimension,
            hidden_dim=len(base_embedding),
            rng=rng,
            normalize=self._config.normalize_projection,
        )

        if self._config.research_profile == "paper_2025":
            return self._explore_paper_2025(
                prompt=prompt,
                objective=objective,
                evidence=evidence,
                max_model_calls=max_model_calls,
                max_output_tokens=max_output_tokens,
                correlation_id=correlation_id,
                seed=seed,
                rng=rng,
                base_embedding=base_embedding,
                projection=projection,
                runtime_engine=capabilities.runtime_engine,
                model_id=capabilities.model_id,
            )

        return self._explore_karen(
            prompt=prompt,
            objective=objective,
            evidence=evidence,
            max_model_calls=max_model_calls,
            max_output_tokens=max_output_tokens,
            correlation_id=correlation_id,
            seed=seed,
            rng=rng,
            base_embedding=base_embedding,
            projection=projection,
            runtime_engine=capabilities.runtime_engine,
            model_id=capabilities.model_id,
        )

    def _explore_paper_2025(
        self,
        *,
        prompt: str,
        objective: str,
        evidence: Sequence[str],
        max_model_calls: int,
        max_output_tokens: int,
        correlation_id: str,
        seed: int,
        rng: random.Random,
        base_embedding: tuple[float, ...],
        projection: tuple[tuple[float, ...], ...],
        runtime_engine: str,
        model_id: str,
    ) -> SoftExplorationTrace:
        batch_verifier = self._batch_verifier
        if batch_verifier is None:
            raise SoftReasoningUnavailable(
                "paper_2025 requires a Runtime-injected Multi-Generate batch verifier"
            )
        if max_model_calls < self._config.initial_samples:
            raise SoftReasoningBudgetError(
                f"paper_2025 requires at least {self._config.initial_samples} model calls"
            )

        optimizer = BayesianOptimizer(self._optimizer_config(seed, paper=True))
        all_candidates: list[SoftCandidate] = []
        model_calls = 0
        verifier_calls = 0
        batches = 0
        previous_batch_objective: float | None = None
        convergence_reason = "max_iterations"

        def gaussian_latent(_base: list[float] | None = None) -> list[float]:
            return [
                rng.gauss(0.0, self._config.perturbation_std)
                for _ in range(self._config.projection_dimension)
            ]

        initial_latents = [
            gaussian_latent() for _ in range(self._config.initial_samples)
        ]

        for round_index in range(self._config.max_iterations + 1):
            if round_index == 0:
                latents = initial_latents
            else:
                remaining = max_model_calls - model_calls
                if remaining < self._config.batch_size:
                    convergence_reason = "model_call_budget"
                    break
                latents = optimizer.suggest(
                    [0.0] * self._config.projection_dimension,
                    count=self._config.batch_size,
                    candidate_fn=gaussian_latent,
                )

            outputs = []
            guided_embeddings = []
            for latent in latents:
                guided_embedding = self._apply_projection(
                    base_embedding=base_embedding,
                    latent=latent,
                    projection=projection,
                    scale=self._config.embedding_scale,
                )
                output = self._generation.generate_with_first_token_embedding(
                    prompt,
                    guided_embedding,
                    max_tokens=max_output_tokens,
                    seed=seed + model_calls,
                )
                model_calls += 1
                outputs.append(output)
                guided_embeddings.append(guided_embedding)

            verification_batch = batch_verifier.verify_batch(
                objective,
                [output.text for output in outputs],
                evidence=evidence,
            )
            verifier_calls += 1
            batches += 1
            if len(verification_batch.candidate_scores) != len(outputs):
                raise SoftReasoningUnavailable(
                    "batch verifier returned a score count different from candidate count"
                )
            if not verification_batch.verifier_model_id:
                raise SoftReasoningUnavailable(
                    "paper_2025 batch verifier must report verifier_model_id"
                )
            if verification_batch.verifier_model_id != model_id:
                raise SoftReasoningUnavailable(
                    "paper_2025 requires generator and verifier to use the same model"
                )

            observations: list[tuple[list[float], float]] = []
            batch_candidates: list[SoftCandidate] = []
            for local_index, (latent, guided, output, verification) in enumerate(
                zip(
                    latents,
                    guided_embeddings,
                    outputs,
                    verification_batch.candidate_scores,
                )
            ):
                try:
                    reward = self._paper_reward.compose(verification, output)
                except SoftReasoningCoherenceUnavailable as exc:
                    raise SoftReasoningUnavailable(str(exc)) from exc
                candidate = SoftCandidate(
                    candidate_id=self._candidate_id(
                        correlation_id,
                        model_calls - len(outputs) + local_index + 1,
                        latent,
                    ),
                    latent=tuple(float(value) for value in latent),
                    first_token_embedding=guided,
                    output=output,
                    verification=verification,
                    iteration=round_index,
                    search_score=reward.score,
                )
                batch_candidates.append(candidate)
                observations.append((list(latent), reward.score))

            optimizer.observe_batch(observations)
            all_candidates.extend(batch_candidates)
            batch_objective = max(self._candidate_score(candidate) for candidate in batch_candidates)

            if (
                previous_batch_objective is not None
                and abs(batch_objective - previous_batch_objective)
                < self._config.convergence_threshold
            ):
                convergence_reason = "consecutive_objective"
                break
            previous_batch_objective = batch_objective

            if model_calls >= max_model_calls:
                convergence_reason = "model_call_budget"
                break

        if not all_candidates:
            raise SoftReasoningUnavailable("paper_2025 produced no candidates")
        best = max(all_candidates, key=self._candidate_score)
        initial_batch = all_candidates[: self._config.initial_samples]
        baseline_score = max(self._candidate_score(candidate) for candidate in initial_batch)
        best_score = self._candidate_score(best)
        return SoftExplorationTrace(
            best_candidate=best,
            candidates=tuple(all_candidates),
            baseline_score=baseline_score,
            best_score=best_score,
            improvement=best_score - baseline_score,
            projection_dimension=self._config.projection_dimension,
            model_calls=model_calls,
            verifier_calls=verifier_calls,
            seed=seed,
            runtime_engine=runtime_engine,
            model_id=model_id,
            optimizer_surrogate_kind=optimizer.surrogate_kind,
            acquisition_function=self._config.acquisition.value,
            research_profile=self._config.research_profile,
            batches=batches,
            convergence_reason=convergence_reason,
        )

    def _explore_karen(
        self,
        *,
        prompt: str,
        objective: str,
        evidence: Sequence[str],
        max_model_calls: int,
        max_output_tokens: int,
        correlation_id: str,
        seed: int,
        rng: random.Random,
        base_embedding: tuple[float, ...],
        projection: tuple[tuple[float, ...], ...],
        runtime_engine: str,
        model_id: str,
    ) -> SoftExplorationTrace:
        if max_model_calls < self._config.initial_samples:
            raise SoftReasoningBudgetError(
                f"soft exploration requires at least {self._config.initial_samples} model calls"
            )
        max_iterations = min(
            self._config.max_iterations,
            max(0, max_model_calls - self._config.initial_samples),
        )
        optimizer = BayesianOptimizer(
            replace(
                self._optimizer_config(seed, paper=False),
                max_iterations=max_iterations,
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
                return self._candidate_score(existing)

            guided_embedding = self._apply_projection(
                base_embedding=base_embedding,
                latent=latent,
                projection=projection,
                scale=self._config.embedding_scale,
            )
            output = self._generation.generate_with_first_token_embedding(
                prompt,
                guided_embedding,
                max_tokens=max_output_tokens,
                seed=seed + model_calls,
            )
            model_calls += 1
            verification = self._verifier.score(
                objective,
                output.text,
                evidence=evidence,
            )
            verifier_calls += 1
            search_score = float(verification.score)
            candidate = SoftCandidate(
                candidate_id=self._candidate_id(correlation_id, model_calls, latent),
                latent=tuple(float(value) for value in latent),
                first_token_embedding=guided_embedding,
                output=output,
                verification=verification,
                iteration=model_calls - 1,
                search_score=search_score,
            )
            candidates[key] = candidate
            return search_score

        initial_latent = [0.0] * self._config.projection_dimension
        optimization = optimizer.optimize(
            initial_embedding=initial_latent,
            score_function=score_latent,
            perturb_fn=perturb,
        )
        if not candidates:
            raise SoftReasoningUnavailable("soft exploration produced no candidates")
        best = max(candidates.values(), key=self._candidate_score)
        baseline = candidates.get(tuple(0.0 for _ in initial_latent))
        baseline_score = (
            self._candidate_score(baseline)
            if baseline is not None
            else optimization.history[0][1]
        )
        best_score = self._candidate_score(best)
        return SoftExplorationTrace(
            best_candidate=best,
            candidates=tuple(
                sorted(candidates.values(), key=lambda item: item.iteration)
            ),
            baseline_score=baseline_score,
            best_score=best_score,
            improvement=best_score - baseline_score,
            projection_dimension=self._config.projection_dimension,
            model_calls=model_calls,
            verifier_calls=verifier_calls,
            seed=seed,
            runtime_engine=runtime_engine,
            model_id=model_id,
            optimizer_surrogate_kind=optimization.surrogate_kind,
            acquisition_function=self._config.acquisition.value,
            research_profile=self._config.research_profile,
            batches=0,
            convergence_reason="optimizer",
        )

    def _optimizer_config(self, seed: int, *, paper: bool) -> OptimizationConfig:
        return OptimizationConfig(
            acquisition_fn=self._config.acquisition,
            exploration_weight=self._config.exploration_weight,
            max_iterations=self._config.max_iterations,
            convergence_threshold=self._config.convergence_threshold,
            convergence_mode=(
                ConvergenceMode.CONSECUTIVE_OBJECTIVE
                if paper
                else ConvergenceMode.BEST_IMPROVEMENT
            ),
            initial_samples=self._config.initial_samples,
            length_scale=1.0,
            signal_variance=1.0,
            noise_variance=self._config.gp_noise_variance,
            normalize_y=self._config.gp_normalize_y,
            candidate_pool_size=self._config.candidate_pool_size,
            random_seed=seed,
            adaptive_ei=self._config.adaptive_ei,
            adaptive_delta=self._config.adaptive_delta,
            objective_noise_variance=self._config.objective_noise_variance,
        )

    @staticmethod
    def _validate_request(prompt: str, objective: str, max_output_tokens: int) -> None:
        if not prompt.strip():
            raise ValueError("prepared prompt must not be empty")
        if not objective.strip():
            raise ValueError("objective must not be empty")
        if max_output_tokens <= 0:
            raise SoftReasoningBudgetError("max_output_tokens must be positive")

    @staticmethod
    def _candidate_score(candidate: SoftCandidate) -> float:
        if candidate.search_score is not None:
            return float(candidate.search_score)
        return float(candidate.verification.score)

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
        normalize: bool,
    ) -> tuple[tuple[float, ...], ...]:
        scale = 1.0 / math.sqrt(float(latent_dim)) if normalize else 1.0
        return tuple(
            tuple(rng.gauss(0.0, 1.0) * scale for _ in range(hidden_dim))
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

    @staticmethod
    def _candidate_id(
        correlation_id: str,
        index: int,
        latent: Sequence[float],
    ) -> str:
        key = tuple(round(float(value), 12) for value in latent)
        digest = hashlib.sha256(
            f"{correlation_id}|{index}|{key}".encode("utf-8")
        ).hexdigest()[:16]
        return f"soft-{digest}"


__all__ = [
    "SoftExplorationConfig",
    "SoftExplorationEngine",
    "SoftReasoningBudgetError",
    "SoftReasoningUnavailable",
]
