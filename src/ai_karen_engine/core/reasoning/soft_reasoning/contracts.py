"""Typed contracts for research-grade Soft Reasoning.

Core owns the exploration algorithm and typed ports. Runtime owns model
selection, prompt preparation, authorization, and the concrete adapters.

The paper path needs two signals that must remain explicit:
- token-level generation log probabilities for coherence;
- batch-relative verifier judgments over k candidate solutions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from ai_karen_engine.core.model_runtime.provider_contracts import (
    ModelRuntimeCapabilities,
)

SoftGenerationCapabilities = ModelRuntimeCapabilities


@dataclass(frozen=True, slots=True)
class SoftGenerationOutput:
    text: str
    token_count: int = 0
    finish_reason: str = ""
    model_id: str = ""
    runtime_engine: str = ""
    token_log_probabilities: tuple[float, ...] = ()
    sequence_log_probability: float | None = None
    mean_token_log_probability: float | None = None
    first_token_probability: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.token_count < 0:
            raise ValueError("token_count must be non-negative")
        if self.token_log_probabilities and (
            self.token_count != len(self.token_log_probabilities)
        ):
            raise ValueError(
                "token_count must equal token_log_probabilities length when provided"
            )


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
class SoftBatchVerification:
    """Batch-relative verifier result used by the paper profile.

    Zhu et al. evaluate a set of candidate solutions together, generate a
    verifier/refined answer, and derive binary candidate rewards from agreement
    with that verifier result. Runtime adapters are responsible for answer
    extraction/comparison; Core consumes only the typed per-candidate scores.
    """

    refined_output: str
    candidate_scores: tuple[SoftVerificationScore, ...]
    verifier_model_id: str = ""
    runtime_engine: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SoftCandidate:
    candidate_id: str
    latent: tuple[float, ...]
    first_token_embedding: tuple[float, ...]
    output: SoftGenerationOutput
    verification: SoftVerificationScore
    iteration: int
    search_score: float | None = None


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
    optimizer_surrogate_kind: str = "gaussian_process"
    acquisition_function: str = "ucb"
    research_profile: str = "karen_default"
    batches: int = 0
    convergence_reason: str = ""


@runtime_checkable
class SoftGenerationPort(Protocol):
    def capabilities(self) -> ModelRuntimeCapabilities:
        ...

    def first_token_embedding(self, prompt: str) -> Sequence[float]:
        """Return the reference embedding z used for exploration."""
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
    def score(
        self,
        objective: str,
        response: str,
        *,
        evidence: Sequence[str],
    ) -> SoftVerificationScore:
        ...


@runtime_checkable
class SoftBatchVerifierPort(Protocol):
    """Paper-style multi-candidate verifier supplied by Runtime."""

    def verify_batch(
        self,
        objective: str,
        responses: Sequence[str],
        *,
        evidence: Sequence[str],
    ) -> SoftBatchVerification:
        ...


__all__ = [
    "SoftBatchVerification",
    "SoftBatchVerifierPort",
    "SoftCandidate",
    "SoftExplorationTrace",
    "SoftGenerationCapabilities",
    "SoftGenerationOutput",
    "SoftGenerationPort",
    "SoftVerificationScore",
    "SoftVerifierPort",
]
