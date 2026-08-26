"""Soft Reasoning capability.

Canonical production path:
- ``SoftExplorationEngine`` performs controlled first-token embedding search.
- ``SoftGenerationPort`` is supplied by a compatible local model runtime.
- ``VerifierGuidedObjective`` converts structured verifier judgments into the
  scalar reward consumed by Bayesian exploration.
- ``BayesianOptimizer`` now uses a real Gaussian Process posterior with
  configurable UCB/EI/PI/Thompson acquisition.

Research fidelity note:
The exploration architecture follows Zhu et al. (ICML 2025) and the optimizer
now satisfies the Gaussian-process Bayesian-optimisation requirement. The
canonical KAREN objective is still richer/different from the paper objective,
so a full ``paper_2025`` reproduction still requires Runtime to provide typed
generation-coherence/log-probability reward data and select paper-consistent
search parameters (including Expected Improvement). Do not describe the default
KAREN profile as a complete paper-faithful reproduction yet.

The older retrieval/writeback ``SoftReasoningEngine`` remains available only as
an on-demand compatibility surface while ICE/retrieval callers are migrated. It
is deliberately not imported during canonical Soft Reasoning startup.
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
    "SoftReasoningUnavailable",
    "SoftVerificationScore",
    "SoftVerifierPort",
    "VerifierGuidedObjective",
    "VerifierObjectiveConfig",
    "optimize_embedding_batch",
    # Compatibility-only lazy exports. Remove after ICE/retrieval migration.
    "RecallConfig",
    "SRHealth",
    "SoftReasoningEngine",
    "WritebackConfig",
]
