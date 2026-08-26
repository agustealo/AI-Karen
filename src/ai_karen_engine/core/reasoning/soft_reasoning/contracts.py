"""Typed contracts for research-grade Soft Reasoning.

This module models the capability boundary required by the ICML 2025 Soft
Reasoning method: controlled first-token embedding exploration followed by
verifier-guided Bayesian refinement.

Core owns the algorithm and contracts only. Runtime owns model selection and
must inject an implementation of ``SoftGenerationPort`` for a model runtime
that exposes first-token embedding control. No provider lookup, persistence,
tool execution, or fallback lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True, slots=True)
class SoftGenerationCapabilities:
    supports_first_token_embedding_control: bool
    hidden_size: int
    runtime_engine: str
    model_id: str
    supports_seed: bool = True

    def __post_init__(self) -> None:
        if self.hidden_size < 0:
            raise ValueError("hidden_size must be non-negative")
        if self.supports_first_token_embedding_control and self.hidden_size <= 0:
            raise ValueError(
                "embedding-control runtimes must report a positive hidden_size"
            )


@dataclass(frozen=True, slots=True)
class SoftGenerationOutput:
    text: str
    token_count: int = 0
    finish_reason: str = ""
    model_id: str = ""
    runtime_engine: str = ""
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


@runtime_checkable
class SoftGenerationPort(Protocol):
    """Runtime adapter for model-internal first-token embedding control."""

    def capabilities(self) -> SoftGenerationCapabilities:
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
