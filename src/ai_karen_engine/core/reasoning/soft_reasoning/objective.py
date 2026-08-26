"""Structured verifier objective for Soft Reasoning.

The Soft Reasoning paper requires a verifier-guided scalar reward. This module
turns structured judgments from an injected verification runtime into that
reward without selecting a provider, invoking memory, constructing prompts, or
inventing heuristic correctness signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence, runtime_checkable

from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftVerificationScore,
    SoftVerifierPort,
)


@dataclass(frozen=True, slots=True)
class CandidateJudgment:
    """Structured assessment returned by an authorized verifier runtime."""

    correctness: float
    coherence: float
    completeness: float
    relevance: float
    confidence: float
    evidence_support: float = 0.0
    contradiction_penalty: float = 0.0
    feedback: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "correctness",
            "coherence",
            "completeness",
            "relevance",
            "confidence",
            "evidence_support",
            "contradiction_penalty",
        ):
            value = float(getattr(self, name))
            object.__setattr__(self, name, max(0.0, min(1.0, value)))


@runtime_checkable
class CandidateJudgePort(Protocol):
    """Runtime-injected candidate judge.

    Runtime owns how the verifier is implemented and which already-authorized
    model/capability performs it. Core consumes only this typed result.
    """

    def judge(
        self,
        objective: str,
        response: str,
        *,
        evidence: Sequence[str],
    ) -> CandidateJudgment:
        ...


@dataclass(frozen=True, slots=True)
class VerifierObjectiveConfig:
    correctness_weight: float = 0.35
    coherence_weight: float = 0.15
    completeness_weight: float = 0.15
    relevance_weight: float = 0.15
    evidence_support_weight: float = 0.20
    contradiction_penalty_weight: float = 0.25
    acceptance_threshold: float = 0.65
    minimum_judge_confidence: float = 0.50

    def __post_init__(self) -> None:
        positive_weights = (
            self.correctness_weight,
            self.coherence_weight,
            self.completeness_weight,
            self.relevance_weight,
            self.evidence_support_weight,
        )
        if any(weight < 0.0 for weight in positive_weights):
            raise ValueError("verifier objective weights must be non-negative")
        if sum(positive_weights) <= 0.0:
            raise ValueError("verifier objective requires at least one positive weight")
        if self.contradiction_penalty_weight < 0.0:
            raise ValueError("contradiction_penalty_weight must be non-negative")
        for name in ("acceptance_threshold", "minimum_judge_confidence"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")


class VerifierGuidedObjective(SoftVerifierPort):
    """Calibrated scalar objective backed by structured verifier judgments."""

    def __init__(
        self,
        judge: CandidateJudgePort,
        config: VerifierObjectiveConfig | None = None,
    ) -> None:
        if not isinstance(judge, CandidateJudgePort):
            raise TypeError("judge must implement CandidateJudgePort")
        self._judge = judge
        self._config = config or VerifierObjectiveConfig()

    def score(
        self,
        objective: str,
        response: str,
        *,
        evidence: Sequence[str],
    ) -> SoftVerificationScore:
        if not objective.strip():
            raise ValueError("verification objective must not be empty")
        if not response.strip():
            return SoftVerificationScore(
                score=0.0,
                confidence=1.0,
                passed=False,
                feedback="empty_candidate_response",
                components={"empty_response": 1.0},
            )

        judgment = self._judge.judge(
            objective,
            response,
            evidence=tuple(evidence),
        )
        config = self._config
        weighted_components = {
            "correctness": judgment.correctness * config.correctness_weight,
            "coherence": judgment.coherence * config.coherence_weight,
            "completeness": judgment.completeness * config.completeness_weight,
            "relevance": judgment.relevance * config.relevance_weight,
            "evidence_support": (
                judgment.evidence_support * config.evidence_support_weight
            ),
        }
        positive_weight = (
            config.correctness_weight
            + config.coherence_weight
            + config.completeness_weight
            + config.relevance_weight
            + config.evidence_support_weight
        )
        raw_positive = sum(weighted_components.values()) / positive_weight
        penalty = judgment.contradiction_penalty * config.contradiction_penalty_weight
        score = max(0.0, min(1.0, raw_positive - penalty))

        passed = (
            score >= config.acceptance_threshold
            and judgment.confidence >= config.minimum_judge_confidence
        )
        components = {
            "correctness": judgment.correctness,
            "coherence": judgment.coherence,
            "completeness": judgment.completeness,
            "relevance": judgment.relevance,
            "evidence_support": judgment.evidence_support,
            "contradiction_penalty": judgment.contradiction_penalty,
            "raw_positive_score": raw_positive,
            "penalty": penalty,
        }
        feedback = judgment.feedback.strip()
        if not feedback:
            feedback = "verifier_accept" if passed else "verifier_reject"

        return SoftVerificationScore(
            score=score,
            confidence=judgment.confidence,
            passed=passed,
            feedback=feedback,
            components=components,
        )


__all__ = [
    "CandidateJudgePort",
    "CandidateJudgment",
    "VerifierGuidedObjective",
    "VerifierObjectiveConfig",
]
