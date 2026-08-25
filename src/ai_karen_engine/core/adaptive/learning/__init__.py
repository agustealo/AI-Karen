"""Adaptive learning public API.

The package root is intentionally import-light. Importing one learning primitive
must not initialize optional numerical policy/evaluation machinery or unrelated
runtime dependencies. Historical package-root exports remain available lazily.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .aggregates import EvidenceAggregator

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "BaselinePolicy": (".contextual_policy", "BaselinePolicy"),
    "LinearContextualPolicy": (".contextual_policy", "LinearContextualPolicy"),
    "DoublyRobustEstimator": (".estimators", "DoublyRobustEstimator"),
    "IPSEstimator": (".estimators", "IPSEstimator"),
    "SNIPSEstimator": (".estimators", "SNIPSEstimator"),
    "compute_overlap_diagnostics": (".estimators", "compute_overlap_diagnostics"),
    "AdaptiveObservationProcessor": (".observations", "AdaptiveObservationProcessor"),
    "OfflinePolicyEvaluator": (".offline_evaluation", "OfflinePolicyEvaluator"),
    "ActionRiskClass": (".policy_contracts", "ActionRiskClass"),
    "DecisionType": (".policy_contracts", "DecisionType"),
    "PolicyContext": (".policy_contracts", "PolicyContext"),
    "PolicyDecision": (".policy_contracts", "PolicyDecision"),
    "PolicyObservation": (".policy_contracts", "PolicyObservation"),
    "PolicyStatus": (".policy_contracts", "PolicyStatus"),
    "PromotionDecision": (".policy_contracts", "PromotionDecision"),
    "UtilityComponents": (".policy_contracts", "UtilityComponents"),
    "UtilityPolicy": (".policy_contracts", "UtilityPolicy"),
    "PromotionConfig": (".promotion", "PromotionConfig"),
    "PromotionEvidence": (".promotion", "PromotionEvidence"),
    "PolicyPromotionDecision": (".promotion", "PolicyPromotionDecision"),
    "evaluate_promotion": (".promotion", "evaluate_promotion"),
    "PolicyRegistry": (".registry", "PolicyRegistry"),
    "DerivedUtilityRecord": (".utility", "DerivedUtilityRecord"),
    "RawOutcomeRecord": (".utility", "RawOutcomeRecord"),
    "compute_scalar_utility": (".utility", "compute_scalar_utility"),
    "compute_utility_components": (".utility", "compute_utility_components"),
    "derive_utility_record": (".utility", "derive_utility_record"),
    "is_utility_valid": (".utility", "is_utility_valid"),
    "BeliefAssessmentLike": (".reflection_contracts", "BeliefAssessmentLike"),
    "ConsolidationPolicyLike": (".reflection_contracts", "ConsolidationPolicyLike"),
    "ExperienceEvent": (".reflection_contracts", "ExperienceEvent"),
    "FailureLessonCandidate": (".reflection_contracts", "FailureLessonCandidate"),
    "GoalContextLike": (".reflection_contracts", "GoalContextLike"),
    "OutcomeEvidence": (".reflection_contracts", "OutcomeEvidence"),
    "PromotionAction": (".reflection_contracts", "PromotionAction"),
    "PromotionPolicy": (".reflection_contracts", "PromotionPolicy"),
    "PromotionResult": (".reflection_contracts", "PromotionResult"),
    "ReflectionCandidate": (".reflection_contracts", "ReflectionCandidate"),
    "ReflectionCandidateType": (".reflection_contracts", "ReflectionCandidateType"),
    "ReflectionContext": (".reflection_contracts", "ReflectionContext"),
    "ReflectionEvent": (".reflection_contracts", "ReflectionEvent"),
    "ReflectionInput": (".reflection_contracts", "ReflectionInput"),
    "ReflectionPolicy": (".reflection_contracts", "ReflectionPolicy"),
    "make_candidate_id": (".reflection_contracts", "make_candidate_id"),
    "make_event_id": (".reflection_contracts", "make_event_id"),
    "PromotionGate": (".reflector", "PromotionGate"),
    "ReflectionEngine": (".reflector", "ReflectionEngine"),
    "make_experience_event": (".reflector", "make_experience_event"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    module = import_module(module_name, package=__name__)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "ActionRiskClass",
    "AdaptiveObservationProcessor",
    "BaselinePolicy",
    "BeliefAssessmentLike",
    "ConsolidationPolicyLike",
    "DerivedUtilityRecord",
    "DoublyRobustEstimator",
    "EvidenceAggregator",
    "ExperienceEvent",
    "FailureLessonCandidate",
    "GoalContextLike",
    "IPSEstimator",
    "LinearContextualPolicy",
    "OfflinePolicyEvaluator",
    "OutcomeEvidence",
    "PolicyContext",
    "PolicyDecision",
    "PolicyObservation",
    "PolicyRegistry",
    "PolicyStatus",
    "PolicyPromotionDecision",
    "PromotionAction",
    "PromotionConfig",
    "PromotionDecision",
    "PromotionEvidence",
    "PromotionGate",
    "PromotionPolicy",
    "PromotionResult",
    "RawOutcomeRecord",
    "ReflectionCandidate",
    "ReflectionCandidateType",
    "ReflectionContext",
    "ReflectionEngine",
    "ReflectionEvent",
    "ReflectionInput",
    "ReflectionPolicy",
    "SNIPSEstimator",
    "UtilityComponents",
    "UtilityPolicy",
    "compute_overlap_diagnostics",
    "compute_scalar_utility",
    "compute_utility_components",
    "derive_utility_record",
    "evaluate_promotion",
    "is_utility_valid",
    "make_candidate_id",
    "make_event_id",
    "make_experience_event",
]
