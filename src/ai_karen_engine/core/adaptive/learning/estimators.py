"""Compatibility facade for historical adaptive off-policy estimators.

Canonical IPS, SNIPS, Doubly Robust estimators and overlap diagnostics now live
in ``ai_karen_engine.core.intelligence.ml.policy_evaluation.estimators``.
"""

from ai_karen_engine.core.intelligence.ml.policy_evaluation.estimators import (
    DoublyRobustEstimator,
    IPSEstimator,
    OPEIneligibleError,
    OffPolicyEstimator,
    SNIPSEstimator,
    compute_overlap_diagnostics,
    validate_observation,
)

__all__ = [
    "DoublyRobustEstimator",
    "IPSEstimator",
    "OPEIneligibleError",
    "OffPolicyEstimator",
    "SNIPSEstimator",
    "compute_overlap_diagnostics",
    "validate_observation",
]
