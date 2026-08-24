"""Adaptive learning."""

from __future__ import annotations

from ai_karen_engine.core.adaptive.learning.aggregates import EvidenceAggregator
from ai_karen_engine.core.adaptive.learning.contextual_policy import (
    BaselinePolicy,
    LinearContextualPolicy,
)
from ai_karen_engine.core.adaptive.learning.estimators import (
    DoublyRobustEstimator,
    IPSEstimator,
    SNIPSEstimator,
    compute_overlap_diagnostics,
)
from ai_karen_engine.core.adaptive.learning.observations import (
    AdaptiveObservationProcessor,
)
from ai_karen_engine.core.adaptive.learning.offline_evaluation import (
    OfflinePolicyEvaluator,
)
from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
    PolicyDecision,
    PolicyObservation,
    PolicyStatus,
    PromotionDecision,
    UtilityComponents,
    UtilityPolicy,
)
from ai_karen_engine.core.adaptive.learning.promotion import (
    PromotionConfig,
    PromotionEvidence,
    PolicyPromotionDecision,
    evaluate_promotion,
)
from ai_karen_engine.core.adaptive.learning.registry import PolicyRegistry
from ai_karen_engine.core.adaptive.learning.utility import (
    DerivedUtilityRecord,
    RawOutcomeRecord,
    compute_scalar_utility,
    compute_utility_components,
    derive_utility_record,
    is_utility_valid,
)

__all__ = [
    "AdaptiveObservationProcessor",
    "BaselinePolicy",
    "DerivedUtilityRecord",
    "EvidenceAggregator",
    "IPSEstimator",
    "LinearContextualPolicy",
    "OfflinePolicyEvaluator",
    "PolicyContext",
    "PolicyDecision",
    "PolicyObservation",
    "PolicyRegistry",
    "PolicyStatus",
    "PolicyPromotionDecision",
    "PromotionConfig",
    "PromotionDecision",
    "PromotionEvidence",
    "RawOutcomeRecord",
    "SNIPSEstimator",
    "UtilityComponents",
    "UtilityPolicy",
    "compute_overlap_diagnostics",
    "compute_scalar_utility",
    "compute_utility_components",
    "derive_utility_record",
    "evaluate_promotion",
    "is_utility_valid",
]
