"""Compatibility facade for historical adaptive policy-promotion imports.

Canonical off-policy promotion evaluation now lives in
``ai_karen_engine.core.intelligence.ml.policy_evaluation.promotion``.
"""

from ai_karen_engine.core.intelligence.ml.policy_evaluation.promotion import (
    PolicyPromotionDecision,
    PromotionConfig,
    PromotionEvidence,
    evaluate_promotion,
)

__all__ = [
    "PolicyPromotionDecision",
    "PromotionConfig",
    "PromotionEvidence",
    "evaluate_promotion",
]
