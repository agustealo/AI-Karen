from __future__ import annotations

import math

from sklearn.gaussian_process import GaussianProcessRegressor

from ai_karen_engine.core.reasoning.soft_reasoning.optimization import (
    AcquisitionFunction,
    BayesianOptimizer,
    OptimizationConfig,
)


def _quadratic_score(embedding: list[float]) -> float:
    distance = sum((value - 0.35) ** 2 for value in embedding)
    return 1.0 - distance


def test_soft_optimizer_uses_real_gaussian_process_surrogate() -> None:
    optimizer = BayesianOptimizer(
        OptimizationConfig(
            acquisition_fn=AcquisitionFunction.EI,
            initial_samples=3,
            max_iterations=2,
            candidate_pool_size=12,
            random_seed=7,
            noise_variance=1e-4,
        )
    )

    assert optimizer.surrogate_kind == "gaussian_process"
    assert isinstance(optimizer._build_gp(), GaussianProcessRegressor)

    result = optimizer.optimize([0.0, 0.0], _quadratic_score)

    assert result.surrogate_kind == "gaussian_process"
    assert result.num_iterations <= 2
    assert len(result.history) >= 3
    assert math.isfinite(result.best_score)

    posterior_mean, posterior_std = optimizer._gp_predict([0.2, 0.2])
    assert math.isfinite(posterior_mean)
    assert math.isfinite(posterior_std)
    assert posterior_std >= 0.0


def test_expected_improvement_is_non_negative_under_gp_posterior() -> None:
    optimizer = BayesianOptimizer(
        OptimizationConfig(
            acquisition_fn=AcquisitionFunction.EI,
            initial_samples=3,
            max_iterations=0,
            candidate_pool_size=8,
            random_seed=11,
        )
    )
    optimizer.optimize([0.0, 0.0], _quadratic_score)

    value = optimizer._expected_improvement([0.25, 0.25])

    assert math.isfinite(value)
    assert value >= 0.0


def test_gp_optimizer_is_reproducible_for_fixed_seed() -> None:
    config = OptimizationConfig(
        acquisition_fn=AcquisitionFunction.EI,
        initial_samples=3,
        max_iterations=2,
        candidate_pool_size=10,
        random_seed=19,
    )

    first = BayesianOptimizer(config).optimize([0.0, 0.0], _quadratic_score)
    second = BayesianOptimizer(config).optimize([0.0, 0.0], _quadratic_score)

    assert first.best_embedding == second.best_embedding
    assert first.best_score == second.best_score
    assert first.history == second.history
