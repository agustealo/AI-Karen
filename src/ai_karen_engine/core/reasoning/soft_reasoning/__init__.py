"""Soft Reasoning capability.

Canonical production path:
- ``SoftExplorationEngine`` implements controlled first-token embedding search.
- ``SoftGenerationPort`` is supplied by a compatible local model runtime.
- ``SoftVerifierPort`` supplies the verifier-guided objective.
- Bayesian optimisation refines a low-dimensional latent perturbation projected
  into the model hidden space.

The older ``SoftReasoningEngine`` is a retrieval/writeback compatibility
implementation and is not the canonical Soft Reasoning algorithm. It remains
importable temporarily while ICE/retrieval callers are migrated.
"""

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

# Compatibility-only retrieval/writeback surface. Do not use for new Soft
# Reasoning execution. Removal is gated on the ICE/retrieval migration.
from ai_karen_engine.core.reasoning.soft_reasoning.engine import (
    RecallConfig,
    SRHealth,
    SoftReasoningEngine,
    WritebackConfig,
)

__all__ = [
    "AcquisitionFunction",
    "BayesianOptimizer",
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
    "optimize_embedding_batch",
    # Compatibility-only exports.
    "RecallConfig",
    "SRHealth",
    "SoftReasoningEngine",
    "WritebackConfig",
]
