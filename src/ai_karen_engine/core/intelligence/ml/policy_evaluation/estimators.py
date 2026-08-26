"""Off-policy evaluation estimators for Intelligence/ML.

Implements IPS, SNIPS, and Doubly Robust estimators with overlap diagnostics,
importance-weight clipping, and confidence intervals. These estimators evaluate
logged decisions only; they never execute or authorize runtime actions.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from .contracts import (
    OPEIneligibilityReason,
    OverlapDiagnostics,
    PolicyEstimate,
    PolicyObservation,
)


class OPEIneligibleError(Exception):
    def __init__(self, reason: OPEIneligibilityReason, message: str = "") -> None:
        self.reason = reason
        super().__init__(message or reason.value)


class OffPolicyEstimator:
    def estimate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any,
    ) -> PolicyEstimate:
        raise NotImplementedError


def _validate_observation(obs: PolicyObservation) -> str | None:
    if not obs.context.eligible_actions:
        return "empty_eligible_actions"
    if not obs.behavior_probabilities:
        return "missing_behavior_probabilities"
    if not obs.candidate_probabilities:
        return "missing_candidate_probabilities"
    if obs.chosen_action not in obs.behavior_probabilities:
        return "chosen_action_missing_from_behavior"
    if obs.chosen_action not in obs.candidate_probabilities:
        return "chosen_action_missing_from_candidate"
    behavior_probability = obs.behavior_probabilities[obs.chosen_action]
    candidate_probability = obs.candidate_probabilities[obs.chosen_action]
    if (
        behavior_probability <= 0.0
        or np.isnan(behavior_probability)
        or np.isinf(behavior_probability)
    ):
        return f"invalid_behavior_probability:{behavior_probability}"
    if (
        candidate_probability <= 0.0
        or np.isnan(candidate_probability)
        or np.isinf(candidate_probability)
    ):
        return f"invalid_candidate_probability:{candidate_probability}"
    return None


def _effective_sample_size(weights: np.ndarray) -> float:
    if weights.size <= 1:
        return 0.0
    variance = float(np.var(weights))
    if variance <= 1e-12:
        return float(weights.size)
    mean = float(np.mean(weights))
    return float((mean * mean) / variance)


def _confidence_interval(values: np.ndarray, estimate: float) -> tuple[float, float]:
    if values.size <= 1:
        return estimate, estimate
    standard_error = float(np.std(values, ddof=1) / np.sqrt(values.size))
    radius = float(stats.norm.ppf(0.975) * standard_error)
    return estimate - radius, estimate + radius


class IPSEstimator(OffPolicyEstimator):
    def __init__(self, max_importance_weight: float = 100.0) -> None:
        self.max_importance_weight = max_importance_weight

    def estimate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any,
    ) -> PolicyEstimate:
        del candidate_policy
        if not observations:
            raise OPEIneligibleError(OPEIneligibilityReason.MISSING_REWARD, "empty observations")

        weights: list[float] = []
        rewards: list[float] = []
        clipped_count = 0
        for obs in observations:
            error = _validate_observation(obs)
            if error:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY, error)
            behavior_probability = obs.behavior_probabilities[obs.chosen_action]
            candidate_probability = obs.candidate_probabilities[obs.chosen_action]
            importance_weight = candidate_probability / behavior_probability
            if importance_weight > self.max_importance_weight:
                importance_weight = self.max_importance_weight
                clipped_count += 1
            weights.append(importance_weight)
            rewards.append(obs.reward)

        weights_array = np.asarray(weights, dtype=np.float64)
        rewards_array = np.asarray(rewards, dtype=np.float64)
        weighted_rewards = weights_array * rewards_array
        estimate = float(np.mean(weighted_rewards))
        lower, upper = _confidence_interval(weighted_rewards, estimate)
        sample_count = len(observations)
        return PolicyEstimate(
            estimator_name="ips",
            estimate=estimate,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=0.95,
            sample_count=sample_count,
            effective_sample_size=_effective_sample_size(weights_array),
            clipped_weight_count=clipped_count,
            clipped_weight_rate=clipped_count / max(sample_count, 1),
        )


class SNIPSEstimator(OffPolicyEstimator):
    def __init__(self, max_importance_weight: float = 100.0) -> None:
        self.max_importance_weight = max_importance_weight

    def estimate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any,
    ) -> PolicyEstimate:
        del candidate_policy
        if not observations:
            raise OPEIneligibleError(OPEIneligibilityReason.MISSING_REWARD, "empty observations")

        weights: list[float] = []
        weighted_rewards: list[float] = []
        clipped_count = 0
        for obs in observations:
            error = _validate_observation(obs)
            if error:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY, error)
            behavior_probability = obs.behavior_probabilities[obs.chosen_action]
            candidate_probability = obs.candidate_probabilities[obs.chosen_action]
            importance_weight = candidate_probability / behavior_probability
            if importance_weight > self.max_importance_weight:
                importance_weight = self.max_importance_weight
                clipped_count += 1
            weights.append(importance_weight)
            weighted_rewards.append(importance_weight * obs.reward)

        weights_array = np.asarray(weights, dtype=np.float64)
        weighted_rewards_array = np.asarray(weighted_rewards, dtype=np.float64)
        weight_sum = float(np.sum(weights_array))
        if weight_sum <= 0.0:
            raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY)
        estimate = float(np.sum(weighted_rewards_array) / weight_sum)
        normalized = weighted_rewards_array / weight_sum * len(observations)
        lower, upper = _confidence_interval(normalized, estimate)
        sample_count = len(observations)
        return PolicyEstimate(
            estimator_name="snips",
            estimate=estimate,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=0.95,
            sample_count=sample_count,
            effective_sample_size=_effective_sample_size(weights_array),
            clipped_weight_count=clipped_count,
            clipped_weight_rate=clipped_count / max(sample_count, 1),
        )


class DoublyRobustEstimator(OffPolicyEstimator):
    def __init__(
        self,
        reward_model: Any = None,
        max_importance_weight: float = 100.0,
    ) -> None:
        self.reward_model = reward_model
        self.max_importance_weight = max_importance_weight

    def _predict_reward(self, observation: PolicyObservation) -> float:
        if self.reward_model is None:
            return observation.reward
        try:
            features = np.asarray(
                list(observation.context.normalized_features.values()),
                dtype=np.float64,
            )
            if features.size == 0:
                return observation.reward
            prediction = self.reward_model.predict(features.reshape(1, -1))[0]
            return float(np.clip(prediction, 0.0, 1.0))
        except Exception:
            return observation.reward

    def estimate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any,
    ) -> PolicyEstimate:
        del candidate_policy
        if not observations:
            raise OPEIneligibleError(OPEIneligibilityReason.MISSING_REWARD, "empty observations")

        values: list[float] = []
        weights: list[float] = []
        clipped_count = 0
        for obs in observations:
            error = _validate_observation(obs)
            if error:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY, error)
            behavior_probability = obs.behavior_probabilities[obs.chosen_action]
            candidate_probability = obs.candidate_probabilities[obs.chosen_action]
            importance_weight = candidate_probability / behavior_probability
            if importance_weight > self.max_importance_weight:
                importance_weight = self.max_importance_weight
                clipped_count += 1
            direct_reward = self._predict_reward(obs)
            values.append(direct_reward + importance_weight * (obs.reward - direct_reward))
            weights.append(importance_weight)

        values_array = np.asarray(values, dtype=np.float64)
        weights_array = np.asarray(weights, dtype=np.float64)
        estimate = float(np.mean(values_array))
        lower, upper = _confidence_interval(values_array, estimate)
        sample_count = len(observations)
        return PolicyEstimate(
            estimator_name="dr",
            estimate=estimate,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=0.95,
            sample_count=sample_count,
            effective_sample_size=_effective_sample_size(weights_array),
            clipped_weight_count=clipped_count,
            clipped_weight_rate=clipped_count / max(sample_count, 1),
        )


def compute_overlap_diagnostics(
    observations: list[PolicyObservation],
    candidate_policy: Any,
    max_importance_weight: float,
) -> OverlapDiagnostics:
    del candidate_policy
    weights: list[float] = []
    propensities: list[float] = []
    action_support: dict[str, int] = {}
    unsupported_actions: set[str] = set()

    for obs in observations:
        for action in obs.context.eligible_actions:
            action_support[action] = action_support.get(action, 0) + 1
        behavior_probability = obs.behavior_probabilities.get(obs.chosen_action, 0.0)
        candidate_probability = obs.candidate_probabilities.get(obs.chosen_action, 0.0)
        if behavior_probability <= 0.0 or candidate_probability <= 0.0:
            unsupported_actions.add(obs.chosen_action)
            continue
        propensities.append(behavior_probability)
        weights.append(candidate_probability / behavior_probability)

    weights_array = np.asarray(weights, dtype=np.float64)
    minimum_propensity = min(propensities) if propensities else 0.0
    maximum_importance_weight = max(weights) if weights else 0.0
    is_supported = bool(action_support) and minimum_propensity > 0.0
    if maximum_importance_weight > max_importance_weight:
        is_supported = False
    if unsupported_actions:
        is_supported = False

    return OverlapDiagnostics(
        effective_sample_size=_effective_sample_size(weights_array),
        minimum_propensity=float(minimum_propensity),
        maximum_importance_weight=float(maximum_importance_weight),
        coverage=len(action_support) / max(len(observations), 1),
        action_support=action_support,
        is_supported=is_supported,
        unsupported_actions=sorted(unsupported_actions),
    )


def validate_observation(obs: PolicyObservation) -> str | None:
    return _validate_observation(obs)
