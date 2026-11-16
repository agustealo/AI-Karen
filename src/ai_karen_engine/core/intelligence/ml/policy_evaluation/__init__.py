"""Canonical off-policy evaluation primitives for Intelligence/ML.

This package owns neutral policy-evaluation contracts and estimators used to
measure candidate decision policies from logged outcomes. It does not select
providers, authorize actions, execute runtime work, or own CORTEX policy gates.
"""

from .contracts import (
    ActionRiskClass,
    ContextualPolicy,
    DecisionType,
    DerivedUtilityRecord,
    OPEIneligibilityReason,
    OverlapDiagnostics,
    PolicyContext,
    PolicyDecision,
    PolicyEstimate,
    PolicyObservation,
    PolicyStatus,
    PromotionBlockReason,
    PromotionDecision,
    UtilityComponents,
    UtilityPolicy,
    validate_probability_distribution,
)
from importlib import import_module
from typing import TYPE_CHECKING, Any

# Contract-only consumers (review issuance, API ingress, plugin manifests)
# must not need SciPy, ML estimators, or a candidate-policy runtime merely to
# import the canonical dataclasses. Keep the old package re-export surface
# lazily resolvable for active estimator/promotion consumers.
_ESTIMATOR_EXPORTS = frozenset({
    "DoublyRobustEstimator",
    "IPSEstimator",
    "OPEIneligibleError",
    "OffPolicyEstimator",
    "SNIPSEstimator",
    "compute_overlap_diagnostics",
    "validate_observation",
})
_PROMOTION_EXPORTS = frozenset({
    "PolicyPromotionDecision",
    "PromotionConfig",
    "PromotionEvidence",
    "evaluate_promotion",
})

if TYPE_CHECKING:
    from .estimators import (
        DoublyRobustEstimator,
        IPSEstimator,
        OPEIneligibleError,
        OffPolicyEstimator,
        SNIPSEstimator,
        compute_overlap_diagnostics,
        validate_observation,
    )
    from .promotion import (
        PolicyPromotionDecision,
        PromotionConfig,
        PromotionEvidence,
        evaluate_promotion,
    )


def __getattr__(name: str) -> Any:
    if name in _ESTIMATOR_EXPORTS:
        module = import_module(f"{__name__}.estimators")
    elif name in _PROMOTION_EXPORTS:
        module = import_module(f"{__name__}.promotion")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "ActionRiskClass",
    "ContextualPolicy",
    "DecisionType",
    "DerivedUtilityRecord",
    "DoublyRobustEstimator",
    "IPSEstimator",
    "OPEIneligibilityReason",
    "OPEIneligibleError",
    "OffPolicyEstimator",
    "OverlapDiagnostics",
    "PolicyContext",
    "PolicyDecision",
    "PolicyEstimate",
    "PolicyObservation",
    "PolicyPromotionDecision",
    "PolicyStatus",
    "PromotionBlockReason",
    "PromotionConfig",
    "PromotionDecision",
    "PromotionEvidence",
    "SNIPSEstimator",
    "UtilityComponents",
    "UtilityPolicy",
    "compute_overlap_diagnostics",
    "evaluate_promotion",
    "validate_observation",
    "validate_probability_distribution",
]
