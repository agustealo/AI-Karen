"""Real off-policy evaluation estimators.

Implements IPS, SNIPS, and Doubly Robust estimators with overlap diagnostics,
weight clipping, and confidence intervals.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from scipy import stats

from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    OPEIneligibilityReason,
    OverlapDiagnostics,
    PolicyContext,
    PolicyDecision,
    PolicyEstimate,
    PolicyObservation,
    PolicyStatus,
    PromotionBlockReason,
    PromotionDecision,
    validate_probability_distribution,
)

logger = logging.getLogger(__name__)


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


def _compute_overlap_diagnostics(
    observations: list[PolicyObservation],
    candidate_policy: Any,
    max_importance_weight: float,
) -> OverlapDiagnostics:
    ess_values = []
    all_propensities = []
    action_support: dict[str, int] = {}
    max_iw = 0.0
    unsupported_actions: list[str] = []

    for obs in observations:
        if not obs.behavior_probabilities or not obs.candidate_probabilities:
            continue
        b_prob = obs.behavior_probabilities.get(obs.chosen_action, 0.0)
        c_prob = obs.candidate_probabilities.get(obs.chosen_action, 0.0)
        if b_prob <= 0.0 or c_prob <= 0.0:
            continue
        iw = c_prob / b_prob
        ess_values.append(iw)
        all_propensities.append(b_prob)
        max_iw = max(max_iw, iw)
        for action in obs.eligible_actions:
            action_support[action] = action_support.get(action, 0) + 1

    ess = float(np.mean(ess_values) ** 2 / np.var(ess_values)) if len(ess_values) > 1 else 0.0
    min_propensity = float(np.min(all_propensities)) if all_propensities else 0.0
    total_eligible = sum(action_support.values())
    coverage = len(action_support) / max(len(observations), 1)

    is_supported = True
    if min_propensity <= 0.0:
        is_supported = False
    if max_iw > max_importance_weight:
        is_supported = False
    if not action_support:
        is_supported = False

    return OverlapDiagnostics(
        effective_sample_size=ess,
        minimum_propensity=min_propensity,
        maximum_importance_weight=max_iw,
        coverage=coverage,
        action_support=dict(action_support),
        is_supported=is_supported,
        unsupported_actions=unsupported_actions,
    )


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
    b_prob = obs.behavior_probabilities[obs.chosen_action]
    c_prob = obs.candidate_probabilities[obs.chosen_action]
    if b_prob <= 0.0 or np.isnan(b_prob) or np.isinf(b_prob):
        return f"invalid_behavior_probability:{b_prob}"
    if c_prob <= 0.0 or np.isnan(c_prob) or np.isinf(c_prob):
        return f"invalid_candidate_probability:{c_prob}"
    return None


class IPSEstimator(OffPolicyEstimator):
    def __init__(self, max_importance_weight: float = 100.0) -> None:
        self.max_importance_weight = max_importance_weight

    def estimate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any,
    ) -> PolicyEstimate:
        if not observations:
            raise OPEIneligibleError(
                OPEIneligibilityReason.MISSING_REWARD,
                "empty observations",
            )

        weights = []
        rewards = []
        clipped_count = 0

        for obs in observations:
            err = _validate_observation(obs)
            if err:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY, err)

            b_prob = obs.behavior_probabilities[obs.chosen_action]
            c_prob = obs.candidate_probabilities[obs.chosen_action]
            iw = c_prob / b_prob
            clipped = False
            if iw > self.max_importance_weight:
                iw = self.max_importance_weight
                clipped = True
            if iw < 0.0:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY)
            weights.append(iw)
            rewards.append(obs.reward)
            if clipped:
                clipped_count += 1

        weights_arr = np.array(weights, dtype=np.float64)
        rewards_arr = np.array(rewards, dtype=np.float64)
        estimate = float(np.mean(weights_arr * rewards_arr))

        n = len(weights_arr)
        if n > 1:
            se = float(np.std(weights_arr * rewards_arr, ddof=1) / np.sqrt(n))
        else:
            se = 0.0
        alpha = 0.05
        ci = stats.norm.ppf(1.0 - alpha / 2.0) * se
        lower = estimate - ci
        upper = estimate + ci

        ess = float(np.mean(weights_arr) ** 2 / np.var(weights_arr)) if n > 1 else 0.0

        return PolicyEstimate(
            estimator_name="ips",
            estimate=estimate,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=1.0 - alpha,
            sample_count=n,
            effective_sample_size=ess,
            clipped_weight_count=clipped_count,
            clipped_weight_rate=clipped_count / max(n, 1),
        )


class SNIPSEstimator(OffPolicyEstimator):
    def __init__(self, max_importance_weight: float = 100.0) -> None:
        self.max_importance_weight = max_importance_weight

    def estimate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any,
    ) -> PolicyEstimate:
        if not observations:
            raise OPEIneligibleError(
                OPEIneligibilityReason.MISSING_REWARD,
                "empty observations",
            )

        weighted_rewards = []
        weights = []
        clipped_count = 0

        for obs in observations:
            err = _validate_observation(obs)
            if err:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY, err)

            b_prob = obs.behavior_probabilities[obs.chosen_action]
            c_prob = obs.candidate_probabilities[obs.chosen_action]
            iw = c_prob / b_prob
            clipped = False
            if iw > self.max_importance_weight:
                iw = self.max_importance_weight
                clipped = True
            if iw < 0.0:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY)
            weighted_rewards.append(iw * obs.reward)
            weights.append(iw)
            if clipped:
                clipped_count += 1

        weights_arr = np.array(weights, dtype=np.float64)
        weighted_rewards_arr = np.array(weighted_rewards, dtype=np.float64)
        weight_sum = float(np.sum(weights_arr))
        if weight_sum <= 0.0:
            raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY)
        estimate = float(np.sum(weighted_rewards_arr) / weight_sum)

        n = len(weights_arr)
        if n > 1:
            se = float(np.std(weighted_rewards_arr, ddof=1) / np.sqrt(n))
        else:
            se = 0.0
        alpha = 0.05
        ci = stats.norm.ppf(1.0 - alpha / 2.0) * se
        lower = estimate - ci
        upper = estimate + ci

        ess = float(np.mean(weights_arr) ** 2 / np.var(weights_arr)) if n > 1 else 0.0

        return PolicyEstimate(
            estimator_name="snips",
            estimate=estimate,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=1.0 - alpha,
            sample_count=n,
            effective_sample_size=ess,
            clipped_weight_count=clipped_count,
            clipped_weight_rate=clipped_count / max(n, 1),
        )


class DoublyRobustEstimator(OffPolicyEstimator):
    def __init__(
        self,
        reward_model: Any = None,
        max_importance_weight: float = 100.0,
    ) -> None:
        self.reward_model = reward_model
        self.max_importance_weight = max_importance_weight

    def _predict_reward(self, obs: PolicyObservation) -> float:
        if self.reward_model is None:
            return obs.reward
        try:
            features = np.array(list(obs.context.normalized_features.values()), dtype=np.float64)
            if features.size == 0:
                return obs.reward
            pred = self.reward_model.predict(features.reshape(1, -1))[0]
            return float(np.clip(pred, 0.0, 1.0))
        except Exception:
            return obs.reward

    def estimate(
        self,
        observations: list[PolicyObservation],
        candidate_policy: Any,
    ) -> PolicyEstimate:
        if not observations:
            raise OPEIneligibleError(
                OPEIneligibilityReason.MISSING_REWARD,
                "empty observations",
            )

        residuals = []
        weights = []
        clipped_count = 0

        for obs in observations:
            err = _validate_observation(obs)
            if err:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY, err)

            b_prob = obs.behavior_probabilities[obs.chosen_action]
            c_prob = obs.candidate_probabilities[obs.chosen_action]
            iw = c_prob / b_prob
            clipped = False
            if iw > self.max_importance_weight:
                iw = self.max_importance_weight
                clipped = True
            if iw < 0.0:
                raise OPEIneligibleError(OPEIneligibilityReason.INVALID_PROPENSITY)

            direct_reward = self._predict_reward(obs)
            residual = obs.reward - direct_reward
            residuals.append(direct_reward + iw * residual)
            weights.append(iw)
            if clipped:
                clipped_count += 1

        residuals_arr = np.array(residuals, dtype=np.float64)
        estimate = float(np.mean(residuals_arr))

        n = len(residuals_arr)
        if n > 1:
            se = float(np.std(residuals_arr, ddof=1) / np.sqrt(n))
        else:
            se = 0.0
        alpha = 0.05
        ci = stats.norm.ppf(1.0 - alpha / 2.0) * se
        lower = estimate - ci
        upper = estimate + ci

        ess = float(np.mean(weights) ** 2 / np.var(weights)) if n > 1 and float(np.var(weights)) > 1e-12 else 0.0

        return PolicyEstimate(
            estimator_name="dr",
            estimate=estimate,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=1.0 - alpha,
            sample_count=n,
            effective_sample_size=ess,
            clipped_weight_count=clipped_count,
            clipped_weight_rate=clipped_count / max(n, 1),
        )


def compute_overlap_diagnostics(
    observations: list[PolicyObservation],
    candidate_policy: Any,
    max_importance_weight: float,
) -> OverlapDiagnostics:
    return _compute_overlap_diagnostics(observations, candidate_policy, max_importance_weight)


def validate_observation(obs: PolicyObservation) -> str | None:
    return _validate_observation(obs)
