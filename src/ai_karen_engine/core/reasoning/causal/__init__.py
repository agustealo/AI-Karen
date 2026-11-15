"""
Causal Reasoning Module

Provides advanced causal reasoning capabilities based on Pearl's causal hierarchy.

Components:
- CausalReasoningEngine: Main engine for causal analysis
- CausalGraph: DAG for causal relationships
- CausalEdge, CausalIntervention, CounterfactualScenario: Data structures
- CausalExplanation: Explanation generation

Cognitive Extensions (NEW):
- CognitiveCausalReasoner: Human-like causal reasoning with uncertainty
- Enhanced explanations with confidence and alternatives
- Counterfactual comparison and causal attribution
- Evidence quality assessment and adaptive reasoning
"""

from ai_karen_engine.core.reasoning.causal.engine import (
    CausalReasoningEngine,
    CausalIdentificationError,
    CausalGraph,
    CausalEdge,
    CausalIntervention,
    CounterfactualScenario,
    CausalExplanation,
    CausalRelationType,
    get_causal_engine,
)

from ai_karen_engine.core.reasoning.causal.cognitive_causal import (
    CognitiveCausalReasoner,
    CausalReasoningMode,
    EvidenceQuality,
    CausalHypothesis,
    CausalReasoningState,
    EnhancedCausalExplanation,
    CounterfactualComparison,
    create_cognitive_causal_reasoner,
)

__all__ = [
    # Core causal reasoning
    "CausalReasoningEngine",
    "CausalIdentificationError",
    "CausalGraph",
    "CausalEdge",
    "CausalIntervention",
    "CounterfactualScenario",
    "CausalExplanation",
    "CausalRelationType",
    "get_causal_engine",

    # Cognitive causal reasoning (NEW)
    "CognitiveCausalReasoner",
    "CausalReasoningMode",
    "EvidenceQuality",
    "CausalHypothesis",
    "CausalReasoningState",
    "EnhancedCausalExplanation",
    "CounterfactualComparison",
    "create_cognitive_causal_reasoner",
]
