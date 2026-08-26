"""Typed contracts for research-grade Soft Reasoning.

Core owns the exploration algorithm and verifier/generation ports. Runtime owns
model selection and injects an adapter for an already-resolved model runtime.

The contracts separate model-generation coherence signals from verifier scores
so KAREN can support both its richer verifier objective and a paper-consistent
Soft Reasoning profile without hiding research-critical values in metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from ai_karen_engine.core.model_runtime.provider_contracts import (
    ModelRuntimeCapabilities,
)

# Compatibility alias. Canonical capability authority now lives in
# core.model_runtime.provider_contracts. Remove this alias when Soft Reasoning
# contract v3 is introduced.
SoftGenerationCapabilities = ModelRuntimeCapabilities


@dataclass(frozen=True, slots=True)
class SoftGenerationOutput:
    text: str
    token_count: int = 0
    finish_reason: str = ""
    model_id: str = ""
    runtime_engine: str = ""
    sequence_log_probability: float | None = None
    mean_token_log_probability: float | None = None
    first_token_probability: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SoftVerificationScore:
    score: float
    confidence: float = 0.0
    passed: bool = False
    feedback: str = ""
    components: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", max(0.0, min(1.0, float(self.score))))
        object.__setattr__(
            self, "confidence", max(0.0, min(1.0, float(self.confidence)))
        )


@dataclass(frozen=True, slots=True)
class SoftCandidate:
    candidate_id: str
    latent: tuple[float, ...]
    first_token_embedding: tuple[float, ...]
    output: SoftGenerationOutput
    verification: SoftVerificationScore
    iteration: int


@dataclass(frozen=True, slots=True)
class SoftExplorationTrace:
    best_candidate: SoftCandidate
    candidates: tuple[SoftCandidate, ...]
    baseline_score: float
    best_score: float
    improvement: float
    projection_dimension: int
    model_calls: int
    verifier_calls: int
    seed: int
    runtime_engine: str
    model_id: str
    optimizer_surrogate_kind: str = "kernel_regression"
    acquisition_function: str = "ucb"
    research_profile: str = "karen_default"


@runtime_checkable
class SoftGenerationPort(Protocol):
    """Adapter for model-internal first-token embedding control."""

    def capabilities(self) -> ModelRuntimeCapabilities:
        ...

    def first_token_embedding(self, prompt: str) -> Sequence[float]:
        ...

    def generate_with_first_token_embedding(
        self,
        prompt: str,
        first_token_embedding: Sequence[float],
        *,
        max_tokens: int,
        seed: int,
    ) -> SoftGenerationOutput:
        ...


@runtime_checkable
class SoftVerifierPort(Protocol):
    """Verifier objective used by Bayesian exploration."""

    def score(
        self,
        objective: str,
        response: str,
        *,
        evidence: Sequence[str],
    ) -> SoftVerificationScore:
        ...


__all__ = [
    "SoftCandidate",
    "SoftExplorationTrace",
    "SoftGenerationCapabilities",
    "SoftGenerationOutput",
    "SoftGenerationPort",
    "SoftVerificationScore",
    "SoftVerifierPort",
]
