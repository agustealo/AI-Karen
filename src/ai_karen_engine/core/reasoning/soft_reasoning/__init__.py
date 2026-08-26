"""Soft Reasoning capability.

Canonical ownership:
- Core owns typed exploration, reward, verifier, and GP-search mechanics.
- Runtime owns provider/model selection, authorization, prompt preparation,
  concrete model hooks, batch-verifier execution, and fallback.

``karen_default`` is KAREN-specific. ``paper_2025`` is a strict research profile
that requires the paper's batch Multi-Generate verifier and token-level
probability signals. The released reference code differs from the paper equation
for coherence, so both semantics are explicit rather than conflated.

The older retrieval/writeback ``SoftReasoningEngine`` remains a lazy
compatibility surface only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftBatchVerification,
    SoftBatchVerifierPort,
    SoftCandidate,
    SoftExplorationTrace,
    SoftGenerationCapabilities,
    SoftGenerationOutput,
    SoftGenerationPort,
    SoftVerificationScore,
    SoftVerifierPort,
)
from ai_karen_engine.core.reasoning.soft_reasoning.exploration import (
    SoftExplorationConfig,
    SoftExplorationEngine,
    SoftReasoningBudgetError,
    SoftReasoningUnavailable,
)
from ai_karen_engine.core.reasoning.soft_reasoning.objective import (
    CandidateJudgePort,
    CandidateJudgment,
    VerifierGuidedObjective,
    VerifierObjectiveConfig,
)
from ai_karen_engine.core.reasoning.soft_reasoning.optimization import (
    AcquisitionFunction,
    BayesianOptimizer,
    ConvergenceMode,
    OptimizationConfig,
    OptimizationResult,
    optimize_embedding_batch,
)
from ai_karen_engine.core.reasoning.soft_reasoning.paper_reward import (
    CoherenceMode,
    PaperReward,
    PaperRewardComposer,
    PaperRewardConfig,
    SoftReasoningCoherenceUnavailable,
)
from ai_karen_engine.core.reasoning.soft_reasoning.perturbation import (
    EmbeddingPerturber,
    PerturbationConfig,
    PerturbationStrategy,
)

if TYPE_CHECKING:
    from ai_karen_engine.core.reasoning.soft_reasoning.engine import (
        RecallConfig,
        SRHealth,
        SoftReasoningEngine,
        WritebackConfig,
    )

_LEGACY_EXPORTS = {
    "RecallConfig",
    "SRHealth",
    "SoftReasoningEngine",
    "WritebackConfig",
}


def __getattr__(name: str) -> Any:
    if name not in _LEGACY_EXPORTS:
        raise AttributeError(name)
    from ai_karen_engine.core.reasoning.soft_reasoning import engine as legacy_engine

    return getattr(legacy_engine, name)


__all__ = [
    "AcquisitionFunction",
    "BayesianOptimizer",
    "CandidateJudgePort",
    "CandidateJudgment",
    "CoherenceMode",
    "ConvergenceMode",
    "EmbeddingPerturber",
    "OptimizationConfig",
    "OptimizationResult",
    "PaperReward",
    "PaperRewardComposer",
    "PaperRewardConfig",
    "PerturbationConfig",
    "PerturbationStrategy",
    "SoftBatchVerification",
    "SoftBatchVerifierPort",
    "SoftCandidate",
    "SoftExplorationConfig",
    "SoftExplorationEngine",
    "SoftExplorationTrace",
    "SoftGenerationCapabilities",
    "SoftGenerationOutput",
    "SoftGenerationPort",
    "SoftReasoningBudgetError",
    "SoftReasoningCoherenceUnavailable",
    "SoftReasoningUnavailable",
    "SoftVerificationScore",
    "SoftVerifierPort",
    "VerifierGuidedObjective",
    "VerifierObjectiveConfig",
    "optimize_embedding_batch",
    "RecallConfig",
    "SRHealth",
    "SoftReasoningEngine",
    "WritebackConfig",
]
