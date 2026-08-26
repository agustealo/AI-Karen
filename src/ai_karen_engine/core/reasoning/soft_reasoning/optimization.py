"""Gaussian-process Bayesian optimisation for Soft Reasoning.

The optimizer supports both KAREN-tuned search and the mechanisms described in
Zhu et al. (ICML 2025): RBF Gaussian Processes, Expected Improvement, explicit
observation noise, noise-adaptive EI, large sampled candidate pools, and
convergence on consecutive objective values.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Tuple

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, RBF

logger = logging.getLogger(__name__)


class AcquisitionFunction(Enum):
    UCB = "ucb"
    EI = "ei"
    PI = "pi"
    THOMPSON = "thompson"


class ConvergenceMode(Enum):
    BEST_IMPROVEMENT = "best_improvement"
    CONSECUTIVE_OBJECTIVE = "consecutive_objective"


@dataclass
class OptimizationConfig:
    acquisition_fn: AcquisitionFunction = AcquisitionFunction.UCB
    exploration_weight: float = 2.0
    max_iterations: int = 20
    convergence_threshold: float = 0.01
    convergence_mode: ConvergenceMode = ConvergenceMode.BEST_IMPROVEMENT
    initial_samples: int = 5
    length_scale: float = 1.0
    signal_variance: float = 1.0
    noise_variance: float = 0.01
    normalize_y: bool = True
    candidate_pool_size: int = 64
    random_seed: int = 17
    improvement_offset: float = 0.0
    adaptive_ei: bool = False
    adaptive_delta: float = 0.1
    objective_noise_variance: float = 0.01

    def __post_init__(self) -> None:
        if self.max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")
        if self.initial_samples <= 0:
            raise ValueError("initial_samples must be positive")
        if self.length_scale <= 0.0:
            raise ValueError("length_scale must be positive")
        if self.signal_variance <= 0.0:
            raise ValueError("signal_variance must be positive")
        if self.noise_variance < 0.0:
            raise ValueError("noise_variance must be non-negative")
        if self.candidate_pool_size <= 0:
            raise ValueError("candidate_pool_size must be positive")
        if self.exploration_weight < 0.0:
            raise ValueError("exploration_weight must be non-negative")
        if self.improvement_offset < 0.0:
            raise ValueError("improvement_offset must be non-negative")
        if not 0.0 < self.adaptive_delta < 1.0:
            raise ValueError("adaptive_delta must be within (0, 1)")
        if self.objective_noise_variance <= 0.0:
            raise ValueError("objective_noise_variance must be positive")


@dataclass
class OptimizationResult:
    best_embedding: List[float]
    best_score: float
    num_iterations: int
    converged: bool
    history: List[Tuple[List[float], float]]
    surrogate_kind: str = "gaussian_process"
    adaptive_ei_scale: float = 1.0


class BayesianOptimizer:
    """Gaussian-process Bayesian optimizer for latent embedding search."""

    surrogate_kind = "gaussian_process"

    def __init__(self, config: Optional[OptimizationConfig] = None):
        self.config = config or OptimizationConfig()
        self._observations: List[Tuple[List[float], float]] = []
        self._best_score = float("-inf")
        self._best_embedding: Optional[List[float]] = None
        self._rng = random.Random(self.config.random_seed)

    @property
    def observations(self) -> tuple[tuple[tuple[float, ...], float], ...]:
        return tuple(
            (tuple(float(v) for v in embedding), float(score))
            for embedding, score in self._observations
        )

    def observe(self, embedding: List[float], score: float) -> None:
        if not embedding:
            raise ValueError("embedding must not be empty")
        self._record_observation(embedding, float(score))

    def observe_batch(
        self,
        observations: List[Tuple[List[float], float]],
    ) -> None:
        for embedding, score in observations:
            self.observe(embedding, score)

    def suggest(
        self,
        base_embedding: List[float],
        *,
        count: int = 1,
        candidate_fn: Optional[Callable[[List[float]], List[float]]] = None,
    ) -> List[List[float]]:
        if not self._observations:
            raise ValueError("cannot suggest before at least one observation")
        if count <= 0:
            raise ValueError("count must be positive")
        if count > self.config.candidate_pool_size:
            raise ValueError("count cannot exceed candidate_pool_size")

        base = self._best_embedding or base_embedding
        candidates = [
            candidate_fn(base) if candidate_fn else self._default_perturb(base)
            for _ in range(self.config.candidate_pool_size)
        ]
        means, stds = self._gp_predict_batch(candidates)
        acquisition_values = self._acquisition_values(means, stds)
        ranked = sorted(
            range(len(candidates)),
            key=lambda index: acquisition_values[index],
            reverse=True,
        )
        return [list(candidates[index]) for index in ranked[:count]]

    def optimize(
        self,
        initial_embedding: List[float],
        score_function: Callable[[List[float]], float],
        *,
        perturb_fn: Optional[Callable[[List[float]], List[float]]] = None,
        candidate_fn: Optional[Callable[[List[float]], List[float]]] = None,
    ) -> OptimizationResult:
        if not initial_embedding:
            raise ValueError("initial_embedding must not be empty")

        logger.info(
            "soft_reasoning.optimizer_started",
            extra={
                "surrogate_kind": self.surrogate_kind,
                "acquisition": self.config.acquisition_fn.value,
                "candidate_pool_size": self.config.candidate_pool_size,
                "convergence_mode": self.config.convergence_mode.value,
                "adaptive_ei": self.config.adaptive_ei,
            },
        )

        self._initialize(initial_embedding, score_function, perturb_fn)

        converged = False
        completed_iterations = 0
        previous_iteration_score: float | None = None
        for _ in range(self.config.max_iterations):
            candidate = self.suggest(
                initial_embedding,
                count=1,
                candidate_fn=candidate_fn or perturb_fn,
            )[0]
            score = float(score_function(candidate))
            self._observations.append((list(candidate), score))
            completed_iterations += 1

            previous_best = self._best_score
            if score > self._best_score:
                self._best_score = score
                self._best_embedding = list(candidate)

            if self.config.convergence_mode == ConvergenceMode.CONSECUTIVE_OBJECTIVE:
                if (
                    previous_iteration_score is not None
                    and abs(score - previous_iteration_score)
                    < self.config.convergence_threshold
                ):
                    converged = True
                    break
                previous_iteration_score = score
            elif score > previous_best:
                improvement = score - previous_best
                if improvement < self.config.convergence_threshold:
                    converged = True
                    break

        if self._best_embedding is None:
            self._best_embedding = list(initial_embedding)
            self._best_score = float(score_function(initial_embedding))

        return OptimizationResult(
            best_embedding=list(self._best_embedding),
            best_score=float(self._best_score),
            num_iterations=completed_iterations,
            converged=converged,
            history=[
                (list(embedding), float(score))
                for embedding, score in self._observations
            ],
            surrogate_kind=self.surrogate_kind,
            adaptive_ei_scale=self._adaptive_ei_scale(),
        )

    def _initialize(
        self,
        initial_embedding: List[float],
        score_function: Callable[[List[float]], float],
        perturb_fn: Optional[Callable[[List[float]], List[float]]],
    ) -> None:
        self.reset()
        initial_score = float(score_function(initial_embedding))
        self._record_observation(initial_embedding, initial_score)

        for _ in range(self.config.initial_samples - 1):
            candidate = (
                perturb_fn(initial_embedding)
                if perturb_fn
                else self._default_perturb(initial_embedding)
            )
            score = float(score_function(candidate))
            self._record_observation(candidate, score)

    def _record_observation(self, embedding: List[float], score: float) -> None:
        candidate = list(embedding)
        self._observations.append((candidate, float(score)))
        if score > self._best_score:
            self._best_score = float(score)
            self._best_embedding = candidate

    def _build_gp(self) -> GaussianProcessRegressor:
        kernel = ConstantKernel(
            self.config.signal_variance,
            constant_value_bounds="fixed",
        ) * RBF(
            length_scale=self.config.length_scale,
            length_scale_bounds="fixed",
        )
        sklearn_seed = int(self.config.random_seed) % (2**32)
        return GaussianProcessRegressor(
            kernel=kernel,
            alpha=max(self.config.noise_variance, 1e-16),
            optimizer=None,
            normalize_y=self.config.normalize_y,
            random_state=sklearn_seed,
        )

    def _gp_predict_batch(
        self,
        embeddings: List[List[float]],
    ) -> Tuple[List[float], List[float]]:
        if not embeddings:
            return ([], [])
        if not self._observations:
            return ([0.0] * len(embeddings), [1.0] * len(embeddings))

        x_train = np.asarray(
            [embedding for embedding, _ in self._observations],
            dtype=float,
        )
        y_train = np.asarray(
            [score for _, score in self._observations],
            dtype=float,
        )
        x_query = np.asarray(embeddings, dtype=float)

        gp = self._build_gp()
        gp.fit(x_train, y_train)
        mean, std = gp.predict(x_query, return_std=True)
        return (
            [float(value) for value in mean.tolist()],
            [max(0.0, float(value)) for value in std.tolist()],
        )

    def _gp_predict(self, embedding: List[float]) -> Tuple[float, float]:
        means, stds = self._gp_predict_batch([embedding])
        return (means[0], stds[0])

    def _surrogate_predict(self, embedding: List[float]) -> Tuple[float, float]:
        return self._gp_predict(embedding)

    def _acquisition_values(
        self,
        means: List[float],
        stds: List[float],
    ) -> List[float]:
        return [
            self._acquisition_value_from_stats(mean, std)
            for mean, std in zip(means, stds)
        ]

    def _acquisition_value(self, embedding: List[float]) -> float:
        mean, std = self._gp_predict(embedding)
        return self._acquisition_value_from_stats(mean, std)

    def _acquisition_value_from_stats(self, mean: float, std: float) -> float:
        acquisition = self.config.acquisition_fn
        if acquisition == AcquisitionFunction.UCB:
            return mean + self.config.exploration_weight * std
        if acquisition == AcquisitionFunction.EI:
            return self._expected_improvement_from_stats(mean, std)
        if acquisition == AcquisitionFunction.PI:
            return self._probability_improvement_from_stats(mean, std)
        if acquisition == AcquisitionFunction.THOMPSON:
            return self._rng.gauss(mean, std)
        return mean + self.config.exploration_weight * std

    def _ucb(self, embedding: List[float]) -> float:
        mean, std = self._gp_predict(embedding)
        return mean + self.config.exploration_weight * std

    def _expected_improvement(self, embedding: List[float]) -> float:
        mean, std = self._gp_predict(embedding)
        return self._expected_improvement_from_stats(mean, std)

    def _expected_improvement_from_stats(self, mean: float, std: float) -> float:
        if self.config.adaptive_ei:
            std *= self._adaptive_ei_scale()
        if std < 1e-12:
            return 0.0
        improvement = mean - self._best_score - self.config.improvement_offset
        z = improvement / std
        cdf_z = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        pdf_z = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
        return max(0.0, improvement * cdf_z + std * pdf_z)

    def _adaptive_ei_scale(self) -> float:
        """Return omega_k from the paper's noisy-observation EI formulation."""
        if not self.config.adaptive_ei or not self._observations:
            return 1.0
        gamma = self._information_gain()
        return math.sqrt(
            max(0.0, gamma + 1.0 + math.log(1.0 / self.config.adaptive_delta))
        )

    def _information_gain(self) -> float:
        x_train = np.asarray(
            [embedding for embedding, _ in self._observations],
            dtype=float,
        )
        if x_train.size == 0:
            return 0.0
        sq_norm = np.sum(x_train**2, axis=1).reshape(-1, 1)
        sqdist = np.maximum(
            0.0,
            sq_norm + sq_norm.T - 2.0 * np.matmul(x_train, x_train.T),
        )
        kernel = self.config.signal_variance * np.exp(
            -0.5 * sqdist / (self.config.length_scale**2)
        )
        lam = self.config.objective_noise_variance
        matrix = np.eye(kernel.shape[0], dtype=float) + kernel / lam
        sign, logdet = np.linalg.slogdet(matrix)
        if sign <= 0 or not np.isfinite(logdet):
            return 0.0
        return max(0.0, 0.5 * float(logdet))

    def _probability_improvement(self, embedding: List[float]) -> float:
        mean, std = self._gp_predict(embedding)
        return self._probability_improvement_from_stats(mean, std)

    def _probability_improvement_from_stats(self, mean: float, std: float) -> float:
        if std < 1e-12:
            return 0.0
        improvement = mean - self._best_score - self.config.improvement_offset
        z = improvement / std
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    def _thompson_sampling(self, embedding: List[float]) -> float:
        mean, std = self._gp_predict(embedding)
        return self._rng.gauss(mean, std)

    def _rbf_kernel(self, x1: List[float], x2: List[float]) -> float:
        squared_dist = sum((a - b) ** 2 for a, b in zip(x1, x2))
        return self.config.signal_variance * math.exp(
            -squared_dist / (2.0 * self.config.length_scale**2)
        )

    def _default_perturb(self, embedding: List[float]) -> List[float]:
        return [value + self._rng.gauss(0.0, 0.1) for value in embedding]

    def reset(self) -> None:
        self._observations.clear()
        self._best_score = float("-inf")
        self._best_embedding = None
        self._rng.seed(self.config.random_seed)


def optimize_embedding_batch(
    embeddings: List[List[float]],
    score_function: Callable[[List[float]], float],
    config: Optional[OptimizationConfig] = None,
) -> List[OptimizationResult]:
    optimizer = BayesianOptimizer(config)
    results: List[OptimizationResult] = []
    for embedding in embeddings:
        results.append(optimizer.optimize(embedding, score_function))
        optimizer.reset()
    return results


__all__ = [
    "AcquisitionFunction",
    "BayesianOptimizer",
    "ConvergenceMode",
    "OptimizationConfig",
    "OptimizationResult",
    "optimize_embedding_batch",
]
