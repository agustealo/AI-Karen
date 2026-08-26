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
