"""Bayesian-search utilities for Soft Reasoning.

Important research-fidelity boundary:
This module currently implements a lightweight kernel-regression surrogate with
Bayesian-optimization-style acquisition functions. It is *not* a mathematically
complete Gaussian Process posterior implementation. The canonical
``paper_2025`` Soft Reasoning profile must not claim paper-faithful GP Bayesian
optimization until Runtime wires a true GP-backed optimizer.

The current implementation remains useful as a low-dependency local-first search
fallback and is intentionally named ``BayesianOptimizer`` for compatibility with
existing callers. Its diagnostics report the surrogate kind explicitly.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AcquisitionFunction(Enum):
    """Acquisition functions supported by the local surrogate search."""

    UCB = "ucb"
    EI = "ei"
    PI = "pi"
    THOMPSON = "thompson"


@dataclass
class OptimizationConfig:
    """Configuration for local surrogate-guided optimization."""

    acquisition_fn: AcquisitionFunction = AcquisitionFunction.UCB
    exploration_weight: float = 2.0
    max_iterations: int = 20
    convergence_threshold: float = 0.01
    initial_samples: int = 5
    length_scale: float = 1.0
    noise_variance: float = 0.01

    def __post_init__(self) -> None:
        if self.max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")
        if self.initial_samples <= 0:
            raise ValueError("initial_samples must be positive")
        if self.length_scale <= 0.0:
            raise ValueError("length_scale must be positive")
        if self.noise_variance < 0.0:
            raise ValueError("noise_variance must be non-negative")


@dataclass
class OptimizationResult:
    """Result from surrogate-guided embedding optimization."""

    best_embedding: List[float]
    best_score: float
    num_iterations: int
    converged: bool
    history: List[Tuple[List[float], float]]
    surrogate_kind: str = "kernel_regression"


class BayesianOptimizer:
    """Compatibility optimizer using a lightweight local surrogate.

    This is not a full Gaussian Process implementation. It uses an RBF-kernel
    weighted regression mean and a proximity-derived uncertainty estimate, then
    applies UCB/EI/PI/Thompson-style acquisition functions. It is appropriate as
    a deterministic low-dependency fallback, not as the paper-faithful optimizer.
    """

    surrogate_kind = "kernel_regression"

    def __init__(self, config: Optional[OptimizationConfig] = None):
        self.config = config or OptimizationConfig()
        self._observations: List[Tuple[List[float], float]] = []
        self._best_score = float("-inf")
        self._best_embedding: Optional[List[float]] = None

    def optimize(
        self,
        initial_embedding: List[float],
        score_function: Callable[[List[float]], float],
        *,
        perturb_fn: Optional[Callable[[List[float]], List[float]]] = None,
    ) -> OptimizationResult:
        logger.info(
            "soft_reasoning.optimizer_started",
            extra={
                "surrogate_kind": self.surrogate_kind,
                "acquisition": self.config.acquisition_fn.value,
            },
        )

        self._initialize(initial_embedding, score_function, perturb_fn)

        converged = False
        for iteration in range(self.config.max_iterations):
            candidate = self._select_next_candidate(initial_embedding, perturb_fn)
            score = score_function(candidate)
            self._observations.append((candidate, score))

            if score > self._best_score:
                improvement = score - self._best_score
                self._best_score = score
                self._best_embedding = candidate
                logger.debug(
                    "Soft Reasoning iteration %d: score %.4f improvement %.4f",
                    iteration,
                    score,
                    improvement,
                )
                if improvement < self.config.convergence_threshold:
                    converged = True
                    break

        if self._best_embedding is None:
            self._best_embedding = list(initial_embedding)
            self._best_score = score_function(initial_embedding)

        return OptimizationResult(
            best_embedding=list(self._best_embedding),
            best_score=float(self._best_score),
            num_iterations=len(self._observations),
            converged=converged,
            history=[(list(item), float(score)) for item, score in self._observations],
            surrogate_kind=self.surrogate_kind,
        )

    def _initialize(
        self,
        initial_embedding: List[float],
        score_function: Callable[[List[float]], float],
        perturb_fn: Optional[Callable[[List[float]], List[float]]],
    ) -> None:
        self._observations.clear()
        self._best_score = float("-inf")
        self._best_embedding = None

        initial_score = score_function(initial_embedding)
        self._observations.append((list(initial_embedding), float(initial_score)))
        self._best_score = float(initial_score)
        self._best_embedding = list(initial_embedding)

        for _ in range(self.config.initial_samples - 1):
            candidate = (
                perturb_fn(initial_embedding)
                if perturb_fn
                else self._default_perturb(initial_embedding)
            )
            score = score_function(candidate)
            self._observations.append((list(candidate), float(score)))
            if score > self._best_score:
                self._best_score = float(score)
                self._best_embedding = list(candidate)

    def _select_next_candidate(
        self,
        initial_embedding: List[float],
        perturb_fn: Optional[Callable[[List[float]], List[float]]],
    ) -> List[float]:
        base = self._best_embedding or initial_embedding
        candidates = [
            perturb_fn(base) if perturb_fn else self._default_perturb(base)
            for _ in range(20)
        ]
        acquisition_values = [self._acquisition_value(c) for c in candidates]
        best_idx = max(range(len(candidates)), key=lambda i: acquisition_values[i])
        return candidates[best_idx]

    def _acquisition_value(self, embedding: List[float]) -> float:
        if self.config.acquisition_fn == AcquisitionFunction.UCB:
            return self._ucb(embedding)
        if self.config.acquisition_fn == AcquisitionFunction.EI:
            return self._expected_improvement(embedding)
        if self.config.acquisition_fn == AcquisitionFunction.PI:
            return self._probability_improvement(embedding)
        if self.config.acquisition_fn == AcquisitionFunction.THOMPSON:
            return self._thompson_sampling(embedding)
        return self._ucb(embedding)

    def _ucb(self, embedding: List[float]) -> float:
        mean, std = self._surrogate_predict(embedding)
        return mean + self.config.exploration_weight * std

    def _expected_improvement(self, embedding: List[float]) -> float:
        mean, std = self._surrogate_predict(embedding)
        if std < 1e-8:
            return 0.0
        improvement = mean - self._best_score
        z = improvement / std
        cdf_z = 0.5 * (1.0 + math.erf(z / math.sqrt(2)))
        pdf_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
        return max(0.0, improvement * cdf_z + std * pdf_z)

    def _probability_improvement(self, embedding: List[float]) -> float:
        mean, std = self._surrogate_predict(embedding)
        if std < 1e-8:
            return 0.0
        z = (mean - self._best_score) / std
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))

    def _thompson_sampling(self, embedding: List[float]) -> float:
        mean, std = self._surrogate_predict(embedding)
        return random.gauss(mean, std)

    def _surrogate_predict(self, embedding: List[float]) -> Tuple[float, float]:
        """Return local kernel-regression mean and proximity uncertainty."""
        if not self._observations:
            return (0.0, 1.0)

        similarities: List[float] = []
        scores: List[float] = []
        for observed_embedding, observed_score in self._observations:
            similarities.append(self._rbf_kernel(embedding, observed_embedding))
            scores.append(float(observed_score))

        total_similarity = sum(similarities) + 1e-8
        mean = sum(
            similarity * score
            for similarity, score in zip(similarities, scores)
        ) / total_similarity
        max_similarity = max(similarities)
        variance_proxy = max(0.0, 1.0 - max_similarity + self.config.noise_variance)
        return (mean, math.sqrt(variance_proxy))

    # Backward-compatible private alias. Remove when no callers/tests reference it.
    def _gp_predict(self, embedding: List[float]) -> Tuple[float, float]:
        return self._surrogate_predict(embedding)

    def _rbf_kernel(self, x1: List[float], x2: List[float]) -> float:
        squared_dist = sum((a - b) ** 2 for a, b in zip(x1, x2))
        return math.exp(-squared_dist / (2 * self.config.length_scale**2))

    @staticmethod
    def _default_perturb(embedding: List[float]) -> List[float]:
        return [x + random.gauss(0.0, 0.1) for x in embedding]

    def reset(self) -> None:
        self._observations.clear()
        self._best_score = float("-inf")
        self._best_embedding = None


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
