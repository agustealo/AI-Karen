"""Soft Reasoning capability.

Canonical production path:
- ``SoftExplorationEngine`` performs controlled first-token embedding search.
- ``SoftGenerationPort`` is supplied by a compatible local model runtime.
- ``VerifierGuidedObjective`` converts structured verifier judgments into the
  scalar reward consumed by KAREN's default profile.
- ``BayesianOptimizer`` uses a real Gaussian Process posterior with configurable
  UCB/EI/PI/Thompson acquisition.
- ``PaperRewardComposer`` supplies the explicit Zhu et al. verifier-plus-
  generation-coherence reward used by ``SoftExplorationConfig.paper_2025()``.

Research fidelity note:
The canonical algorithm now contains the paper-critical GP search, Expected
Improvement profile, projected 50-dimensional search profile, and typed
verifier-plus-log-probability reward composition. Runtime must still inject an
authorized local model adapter that exposes first-token embedding control and
generation log-probabilities before ``paper_2025`` can execute. The default
``karen_default`` profile intentionally remains KAREN-specific.

The older retrieval/writeback ``SoftReasoningEngine`` remains available only as
an on-demand compatibility surface while legacy callers are migrated. It is
deliberately not imported during canonical Soft Reasoning startup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
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
    OptimizationConfig,
    OptimizationResult,
    optimize_embedding_batch,
)
from ai_karen_engine.core.reasoning.soft_reasoning.paper_reward import (
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
    "EmbeddingPerturber",
    "OptimizationConfig",
    "OptimizationResult",
    "PaperReward",
    "PaperRewardComposer",
    "PaperRewardConfig",
    "PerturbationConfig",
    "PerturbationStrategy",
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
    # Compatibility-only lazy exports. Remove after legacy caller migration.
    "RecallConfig",
    "SRHealth",
    "SoftReasoningEngine",
    "WritebackConfig",
]
