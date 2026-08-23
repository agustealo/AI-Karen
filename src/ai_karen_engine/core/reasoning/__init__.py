"""Reasoning Module - specialist cognition exports.

Keep this package import-light. Concrete submodules are loaded lazily so that
importing reasoning helpers does not bootstrap the full orchestration stack or
trigger unrelated model/provider initialization.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ReasoningRequest",
    "ReasoningResult",
    "ReasoningEvidence",
    "ReasoningHypothesis",
    "ReasoningContradiction",
    "ReasoningAssessment",
    "ReasoningEvidenceNeed",
    "ReasoningEscalationRequest",
    "ReasoningAction",
    "ReasoningBudget",
    "ReasoningStatus",
    "ReasoningMode",
    "ReasoningDisposition",
    "ReasoningErrorCode",
    "HypothesisStatus",
    "ContradictionSeverity",
    "EvidenceSensitivity",
    "EvidenceProvider",
    "ReasoningGenerationClient",
    "ReasoningToolClient",
    "ReasoningStrategyEngine",
    "ReasoningExecutor",
    "get_reasoning_executor",
    # Core Soft Reasoning
    "SoftReasoningEngine",
    "RecallConfig",
    "WritebackConfig",
    "SRHealth",
    "EmbeddingPerturber",
    "PerturbationStrategy",
    "PerturbationConfig",
    "BayesianOptimizer",
    "OptimizationConfig",
    "OptimizationResult",
    "AcquisitionFunction",
    "ReasoningVerifier",
    "VerifierConfig",
    "VerificationResult",
    "VerificationCriterion",
    # Graph reasoning
    "ReasoningGraph",
    "CapsuleGraph",
    "Node",
    "Edge",
    # Synthesis & ICE
    "PremiumICEWrapper",
    "KariICEWrapper",
    "ICEWritebackPolicy",
    "ReasoningTrace",
    "RecallStrategy",
    "SynthesisMode",
    "ICEPerformanceBaseline",
    "ICECircuitBreaker",
    "SynthesisSubEngine",
    "LangGraphSubEngine",
    "DSPySubEngine",
    "SelfRefiner",
    "RefinementConfig",
    "RefinementResult",
    "FeedbackPoint",
    "RefinementStage",
    "create_self_refiner",
    "MetacognitiveMonitor",
    "MetacognitiveState",
    "MetacognitiveConfig",
    "CognitiveState",
    "PerformanceMetrics",
    # Retrieval
    "SRRetriever",
    "SRCompositeRetriever",
    "VectorStore",
    "Result",
    "LlamaIndexVectorAdapter",
    "ReasoningEvidenceAdapter",
    "EvidenceBundle",
    # Causal reasoning
    "CausalReasoningEngine",
    "CausalGraph",
    "CausalEdge",
    "CausalIntervention",
    "CounterfactualScenario",
    "CausalExplanation",
    "CausalRelationType",
    "get_causal_engine",
    "CognitiveCausalReasoner",
    "CausalReasoningMode",
    "EvidenceQuality",
    "CausalHypothesis",
    "CausalReasoningState",
    "EnhancedCausalExplanation",
    "CounterfactualComparison",
    "create_cognitive_causal_reasoner",
    # KRO orchestrator
    "KROOrchestrator",
    "get_kro_orchestrator",
    # Strategies
    "KROReasoningStrategy",
    "CausalReasoner",
    "SoftReasoner",
    "Verifier",
    "Refiner",
    "MetacognitionStrategy",
    "get_default_strategies",
    "get_default_executor",
    "ReasoningEngine",
]

_EXPORTS = {
    # Canonical contracts
    "ReasoningRequest": ("ai_karen_engine.core.reasoning.contracts", "ReasoningRequest"),
    "ReasoningResult": ("ai_karen_engine.core.reasoning.contracts", "ReasoningResult"),
    "ReasoningEvidence": ("ai_karen_engine.core.reasoning.contracts", "ReasoningEvidence"),
    "ReasoningHypothesis": ("ai_karen_engine.core.reasoning.contracts", "ReasoningHypothesis"),
    "ReasoningContradiction": ("ai_karen_engine.core.reasoning.contracts", "ReasoningContradiction"),
    "ReasoningConfidence": ("ai_karen_engine.core.reasoning.contracts", "ReasoningConfidence"),
    "ReasoningEvidenceNeed": ("ai_karen_engine.core.reasoning.contracts", "ReasoningEvidenceNeed"),
    "ReasoningAction": ("ai_karen_engine.core.reasoning.contracts", "ReasoningAction"),
    "ReasoningBudget": ("ai_karen_engine.core.reasoning.contracts", "ReasoningBudget"),
    "ReasoningStrategy": ("ai_karen_engine.core.reasoning.contracts", "ReasoningStrategy"),
    "ReasoningPlan": ("ai_karen_engine.core.reasoning.contracts", "ReasoningPlan"),
    "ReasoningStatus": ("ai_karen_engine.core.reasoning.contracts", "ReasoningStatus"),
    "ReasoningMode": ("ai_karen_engine.core.reasoning.contracts", "ReasoningMode"),
    "HypothesisStatus": ("ai_karen_engine.core.reasoning.contracts", "HypothesisStatus"),
    "ContradictionSeverity": ("ai_karen_engine.core.reasoning.contracts", "ContradictionSeverity"),
    "StrategyDeterminism": ("ai_karen_engine.core.reasoning.contracts", "StrategyDeterminism"),
    "EvidenceProvider": ("ai_karen_engine.core.reasoning.contracts", "EvidenceProvider"),
    "ReasoningGenerationClient": ("ai_karen_engine.core.reasoning.contracts", "ReasoningGenerationClient"),
    "ReasoningToolClient": ("ai_karen_engine.core.reasoning.contracts", "ReasoningToolClient"),
    "ReasoningStrategyEngine": ("ai_karen_engine.core.reasoning.strategy", "ReasoningStrategyEngine"),
    "ReasoningStrategyRegistry": ("ai_karen_engine.core.reasoning.strategy", "ReasoningStrategyRegistry"),
    "ReasoningExecutor": ("ai_karen_engine.core.reasoning.executor", "ReasoningExecutor"),
    "get_reasoning_executor": ("ai_karen_engine.core.reasoning.executor", "get_reasoning_executor"),
    "get_reasoning_strategy_registry": ("ai_karen_engine.core.reasoning.strategy", "get_reasoning_strategy_registry"),
    # Soft reasoning
    "SoftReasoningEngine": ("ai_karen_engine.core.reasoning.soft_reasoning.engine", "SoftReasoningEngine"),
    "RecallConfig": ("ai_karen_engine.core.reasoning.soft_reasoning.engine", "RecallConfig"),
    "WritebackConfig": ("ai_karen_engine.core.reasoning.soft_reasoning.engine", "WritebackConfig"),
    "SRHealth": ("ai_karen_engine.core.reasoning.soft_reasoning.engine", "SRHealth"),
    "EmbeddingPerturber": ("ai_karen_engine.core.reasoning.soft_reasoning.perturbation", "EmbeddingPerturber"),
    "PerturbationStrategy": ("ai_karen_engine.core.reasoning.soft_reasoning.perturbation", "PerturbationStrategy"),
    "PerturbationConfig": ("ai_karen_engine.core.reasoning.soft_reasoning.perturbation", "PerturbationConfig"),
    "BayesianOptimizer": ("ai_karen_engine.core.reasoning.soft_reasoning.optimization", "BayesianOptimizer"),
    "OptimizationConfig": ("ai_karen_engine.core.reasoning.soft_reasoning.optimization", "OptimizationConfig"),
    "OptimizationResult": ("ai_karen_engine.core.reasoning.soft_reasoning.optimization", "OptimizationResult"),
    "AcquisitionFunction": ("ai_karen_engine.core.reasoning.soft_reasoning.optimization", "AcquisitionFunction"),
    "ReasoningVerifier": ("ai_karen_engine.core.reasoning.soft_reasoning.verifier", "ReasoningVerifier"),
    "VerifierConfig": ("ai_karen_engine.core.reasoning.soft_reasoning.verifier", "VerifierConfig"),
    "VerificationResult": ("ai_karen_engine.core.reasoning.soft_reasoning.verifier", "VerificationResult"),
    "VerificationCriterion": ("ai_karen_engine.core.reasoning.soft_reasoning.verifier", "VerificationCriterion"),
    # Graph reasoning
    "ReasoningGraph": ("ai_karen_engine.core.reasoning.graph.reasoning", "ReasoningGraph"),
    "CapsuleGraph": ("ai_karen_engine.core.reasoning.graph.capsule", "CapsuleGraph"),
    "Node": ("ai_karen_engine.core.reasoning.graph.capsule", "Node"),
    "Edge": ("ai_karen_engine.core.reasoning.graph.capsule", "Edge"),
    # Synthesis
    "PremiumICEWrapper": ("ai_karen_engine.core.reasoning.synthesis.ice_wrapper", "PremiumICEWrapper"),
    "ICEWritebackPolicy": ("ai_karen_engine.core.reasoning.synthesis.ice_wrapper", "ICEWritebackPolicy"),
    "ReasoningTrace": ("ai_karen_engine.core.reasoning.synthesis.ice_wrapper", "ReasoningTrace"),
    "RecallStrategy": ("ai_karen_engine.core.reasoning.synthesis.ice_wrapper", "RecallStrategy"),
    "SynthesisMode": ("ai_karen_engine.core.reasoning.synthesis.ice_wrapper", "SynthesisMode"),
    "ICEPerformanceBaseline": ("ai_karen_engine.core.reasoning.synthesis.ice_wrapper", "ICEPerformanceBaseline"),
    "ICECircuitBreaker": ("ai_karen_engine.core.reasoning.synthesis.ice_wrapper", "ICECircuitBreaker"),
    "SynthesisSubEngine": ("ai_karen_engine.core.reasoning.synthesis.subengines", "SynthesisSubEngine"),
    "LangGraphSubEngine": ("ai_karen_engine.core.reasoning.synthesis.subengines", "LangGraphSubEngine"),
    "DSPySubEngine": ("ai_karen_engine.core.reasoning.synthesis.subengines", "DSPySubEngine"),
    "SelfRefiner": ("ai_karen_engine.core.reasoning.synthesis.self_refine", "SelfRefiner"),
    "RefinementConfig": ("ai_karen_engine.core.reasoning.synthesis.self_refine", "RefinementConfig"),
    "RefinementResult": ("ai_karen_engine.core.reasoning.synthesis.self_refine", "RefinementResult"),
    "FeedbackPoint": ("ai_karen_engine.core.reasoning.synthesis.self_refine", "FeedbackPoint"),
    "RefinementStage": ("ai_karen_engine.core.reasoning.synthesis.self_refine", "RefinementStage"),
    "create_self_refiner": ("ai_karen_engine.core.reasoning.synthesis.self_refine", "create_self_refiner"),
    "MetacognitiveMonitor": ("ai_karen_engine.core.reasoning.synthesis.metacognition", "MetacognitiveMonitor"),
    "MetacognitiveState": ("ai_karen_engine.core.reasoning.synthesis.metacognition", "MetacognitiveState"),
    "MetacognitiveConfig": ("ai_karen_engine.core.reasoning.synthesis.metacognition", "MetacognitiveConfig"),
    "CognitiveState": ("ai_karen_engine.core.reasoning.synthesis.metacognition", "CognitiveState"),
    "PerformanceMetrics": ("ai_karen_engine.core.reasoning.synthesis.metacognition", "PerformanceMetrics"),
    # Retrieval
    "SRRetriever": ("ai_karen_engine.core.reasoning.retrieval.adapters", "SRRetriever"),
    "SRCompositeRetriever": ("ai_karen_engine.core.reasoning.retrieval.adapters", "SRCompositeRetriever"),
    "VectorStore": ("ai_karen_engine.core.reasoning.retrieval.vector_stores", "VectorStore"),
    "Result": ("ai_karen_engine.core.reasoning.retrieval.adapters", "Result"),
    "LlamaIndexVectorAdapter": ("ai_karen_engine.core.reasoning.retrieval.vector_stores", "LlamaIndexVectorAdapter"),
    "ReasoningEvidenceAdapter": ("ai_karen_engine.core.reasoning.retrieval.adapters", "ReasoningEvidenceAdapter"),
    "EvidenceBundle": ("ai_karen_engine.core.reasoning.retrieval.adapters", "EvidenceBundle"),
    # Causal
    "CausalReasoningEngine": ("ai_karen_engine.core.reasoning.causal.engine", "CausalReasoningEngine"),
    "CausalGraph": ("ai_karen_engine.core.reasoning.causal.engine", "CausalGraph"),
    "CausalEdge": ("ai_karen_engine.core.reasoning.causal.engine", "CausalEdge"),
    "CausalIntervention": ("ai_karen_engine.core.reasoning.causal.engine", "CausalIntervention"),
    "CounterfactualScenario": ("ai_karen_engine.core.reasoning.causal.engine", "CounterfactualScenario"),
    "CausalExplanation": ("ai_karen_engine.core.reasoning.causal.engine", "CausalExplanation"),
    "CausalRelationType": ("ai_karen_engine.core.reasoning.causal.engine", "CausalRelationType"),
    "get_causal_engine": ("ai_karen_engine.core.reasoning.causal.engine", "get_causal_engine"),
    "CognitiveCausalReasoner": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "CognitiveCausalReasoner"),
    "CausalReasoningMode": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "CausalReasoningMode"),
    "EvidenceQuality": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "EvidenceQuality"),
    "CausalHypothesis": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "CausalHypothesis"),
    "CausalReasoningState": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "CausalReasoningState"),
    "EnhancedCausalExplanation": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "EnhancedCausalExplanation"),
    "CounterfactualComparison": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "CounterfactualComparison"),
    "create_cognitive_causal_reasoner": ("ai_karen_engine.core.reasoning.causal.cognitive_causal", "create_cognitive_causal_reasoner"),
    # KRO
    "KROOrchestrator": ("ai_karen_engine.core.reasoning.kro_orchestrator", "KROOrchestrator"),
    "get_kro_orchestrator": ("ai_karen_engine.core.reasoning.kro_orchestrator", "get_kro_orchestrator"),
    # Strategy
    "KROReasoningStrategy": ("ai_karen_engine.core.reasoning.strategies.kro_strategy", "KROReasoningStrategy"),
    "CausalReasoner": ("ai_karen_engine.core.reasoning.strategies.causal_strategy", "CausalReasoner"),
    "SoftReasoner": ("ai_karen_engine.core.reasoning.strategies.soft_strategy", "SoftReasoner"),
    "Verifier": ("ai_karen_engine.core.reasoning.strategies.verifier_strategy", "Verifier"),
    "Refiner": ("ai_karen_engine.core.reasoning.strategies.refiner_strategy", "Refiner"),
    "MetacognitionStrategy": ("ai_karen_engine.core.reasoning.strategies.metacognition_strategy", "MetacognitionStrategy"),
    "get_default_strategies": ("ai_karen_engine.core.reasoning.defaults", "get_default_strategies"),
    "get_default_executor": ("ai_karen_engine.core.reasoning.defaults", "get_default_executor"),
}


def __getattr__(name: str) -> Any:
    if name == "KariICEWrapper":
        module = import_module("ai_karen_engine.core.reasoning.synthesis.ice_wrapper")
        return getattr(module, "PremiumICEWrapper")

    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attr_name)


from ai_karen_engine.agents.agent_reasoning import ReasoningEngine
