"""Utility/reward contracts and derived utility computation.

Explicit, versioned transformation of raw outcomes into policy utility.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    ActionRiskClass,
    DecisionType,
    DerivedUtilityRecord,
    UtilityComponents,
    UtilityPolicy,
)

logger = logging.getLogger(__name__)


class UtilityComputationError(Exception):
    pass


@dataclass(slots=True)
class RawOutcomeRecord:
    """Neutral wrapper for raw outcome data."""

    outcome_id: str
    execution_status: str
    latency_ms: float = 0.0
    fallback_used: bool = False
    user_feedback: str | None = None
    correction: bool = False
    completion: bool = False
    verification_success: bool | None = None
    safety_violation: bool = False
    authorization_violation: bool = False
    cost: float = 0.0
    quality_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


def compute_utility_components(
    outcome: RawOutcomeRecord,
    utility_policy: UtilityPolicy,
) -> UtilityComponents:
    if outcome.safety_violation or outcome.authorization_violation:
        return UtilityComponents(safety_penalty=1.0)

    success = 1.0 if outcome.execution_status == "success" else 0.0
    completion = 1.0 if outcome.completion else 0.0
    quality = float(np.clip(outcome.quality_score, 0.0, 1.0))
    latency = float(np.clip(outcome.latency_ms / 10000.0, 0.0, 1.0))
    fallback_penalty = 1.0 if outcome.fallback_used else 0.0
    cost = float(np.clip(outcome.cost / 10.0, 0.0, 1.0))
    user_feedback = 0.5
    if outcome.user_feedback == "accepted":
        user_feedback = 1.0
    elif outcome.user_feedback == "dismissed":
        user_feedback = 0.0
    elif outcome.user_feedback == "corrected":
        user_feedback = 0.0
    if outcome.correction:
        user_feedback = min(user_feedback, 0.0)
    verification_success = 1.0 if outcome.verification_success else (0.5 if outcome.verification_success is None else 0.0)

    components = UtilityComponents(
        quality=quality,
        success=success,
        latency=latency,
        fallback_penalty=fallback_penalty,
        cost=cost,
        user_feedback=user_feedback,
        verification_success=verification_success,
        safety_penalty=0.0,
    )
    return components


def compute_scalar_utility(
    components: UtilityComponents,
    utility_policy: UtilityPolicy,
) -> float:
    return components.to_scalar(utility_policy.weights)


def derive_utility_record(
    outcome: RawOutcomeRecord,
    utility_policy: UtilityPolicy,
) -> DerivedUtilityRecord:
    components = compute_utility_components(outcome, utility_policy)
    scalar = compute_scalar_utility(components, utility_policy)
    return DerivedUtilityRecord(
        record_id=f"util-{uuid.uuid4().hex}",
        utility_policy_version=utility_policy.utility_policy_version,
        source_outcome_ids=[outcome.outcome_id],
        components=components,
        scalar_utility=scalar,
    )


def is_utility_valid(components: UtilityComponents) -> bool:
    return components.safety_penalty == 0.0
