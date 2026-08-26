"""Runtime-owned Multi-Generate verifier for the Soft Reasoning paper profile.

This adapter deliberately receives an already-resolved model runtime and the
canonical PromptRuntime services. It never selects providers/models and never
constructs an alternate prompt registry.

The paper's Multi-Generate strategy asks the same LLM to inspect all k candidate
solutions together and generate a refined solution. Candidates whose extracted
final answer matches that refined answer receive binary verifier reward.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence, runtime_checkable

from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    ModelRuntimeCapabilities,
)
from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftBatchVerification,
    SoftVerificationScore,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry
from ai_karen_engine.core.runtime.prompt.prompt_service import PromptRuntimeService
from ai_karen_engine.core.runtime.prompt.soft_reasoning_prompts import (
    SOFT_REASONING_MULTI_GENERATE_PROMPT_ID,
    SOFT_REASONING_MULTI_GENERATE_PROMPT_VERSION,
    ensure_soft_reasoning_prompts,
)


@runtime_checkable
class SoftVerifierGenerationRuntime(Protocol):
    """Already-resolved runtime needed by the Multi-Generate verifier."""

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        ...

    def runtime_capabilities(self) -> ModelRuntimeCapabilities:
        ...


@runtime_checkable
class FinalAnswerExtractorPort(Protocol):
    def extract(self, text: str) -> str:
        ...


@dataclass(frozen=True, slots=True)
class NormalizedFinalAnswerExtractor(FinalAnswerExtractorPort):
    """Dataset-neutral final-answer extraction and comparison normalization.

    It supports common explicit answer markers and otherwise uses the final
    non-empty line. Domain-specific benchmark adapters may inject a stricter
    extractor without changing Core reasoning.
    """

    case_sensitive: bool = False
    strip_terminal_punctuation: bool = True

    _FINAL_MARKERS = (
        "final answer:",
        "answer:",
        "therefore:",
    )

    def extract(self, text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return ""

        boxed = re.findall(r"\\boxed\{([^{}]+)\}", value)
        if boxed:
            return self._normalize(boxed[-1])

        lower = value.lower()
        for marker in self._FINAL_MARKERS:
            index = lower.rfind(marker)
            if index >= 0:
                return self._normalize(value[index + len(marker) :])

        lines = [line.strip() for line in value.splitlines() if line.strip()]
        return self._normalize(lines[-1] if lines else value)

    def _normalize(self, value: str) -> str:
        normalized = " ".join(str(value).strip().split())
        if self.strip_terminal_punctuation:
            normalized = normalized.rstrip(".。!！?？")
        if not self.case_sensitive:
            normalized = normalized.casefold()
        return normalized


@dataclass(frozen=True, slots=True)
class MultiGenerateVerifierConfig:
    prompt_id: str = SOFT_REASONING_MULTI_GENERATE_PROMPT_ID
    prompt_version: str = SOFT_REASONING_MULTI_GENERATE_PROMPT_VERSION
    max_output_tokens: int = 1024
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.temperature < 0.0:
            raise ValueError("temperature must be non-negative")


class RuntimeMultiGenerateVerifier:
    """Prompt-first implementation of the paper's batch verifier strategy."""

    verifier_strategy = "multi_generate"

    def __init__(
        self,
        *,
        runtime: SoftVerifierGenerationRuntime,
        prompt_registry: PromptRegistry,
        prompt_service: PromptRuntimeService,
        answer_extractor: FinalAnswerExtractorPort | None = None,
        config: MultiGenerateVerifierConfig | None = None,
    ) -> None:
        if not isinstance(runtime, SoftVerifierGenerationRuntime):
            raise TypeError("runtime must implement SoftVerifierGenerationRuntime")
        self._runtime = runtime
        self._registry = prompt_registry
        self._prompt_service = prompt_service
        self._extractor = answer_extractor or NormalizedFinalAnswerExtractor()
        self._config = config or MultiGenerateVerifierConfig()
        ensure_soft_reasoning_prompts(self._registry)

    def verify_batch(
        self,
        objective: str,
        responses: Sequence[str],
        *,
        evidence: Sequence[str],
    ) -> SoftBatchVerification:
        if not objective.strip():
            raise ValueError("verification objective must not be empty")
        if not responses:
            raise ValueError("Multi-Generate verification requires candidates")
        if any(not str(response).strip() for response in responses):
            raise ValueError("Multi-Generate candidates must not be empty")

        prompt_definition = self._registry.get_prompt(
            self._config.prompt_id,
            self._config.prompt_version,
        )
        user_payload = self._render_user_payload(
            objective=objective,
            responses=responses,
            evidence=evidence,
        )
        messages = [
            {"role": "system", "content": prompt_definition.system_instructions},
            {"role": "user", "content": user_payload},
        ]
        prompt = self._prompt_service.render_text_prompt(messages)

        try:
            refined = self._runtime.generate_text(
                prompt,
                max_new_tokens=self._config.max_output_tokens,
                temperature=self._config.temperature,
            ).strip()
        except Exception as exc:
            raise GenerationFailed(
                f"Soft Reasoning Multi-Generate verifier failed: {exc}"
            ) from exc
        if not refined:
            raise GenerationFailed(
                "Soft Reasoning Multi-Generate verifier returned an empty solution"
            )

        refined_answer = self._extractor.extract(refined)
        if not refined_answer:
            raise GenerationFailed(
                "Soft Reasoning Multi-Generate verifier produced no extractable final answer"
            )

        candidate_scores = tuple(
            self._score_candidate(response, refined_answer)
            for response in responses
        )
        capabilities = self._runtime.runtime_capabilities()
        return SoftBatchVerification(
            refined_output=refined,
            candidate_scores=candidate_scores,
            verifier_model_id=capabilities.model_id,
            runtime_engine=capabilities.runtime_engine,
            metadata={
                "verifier_strategy": self.verifier_strategy,
                "prompt_id": prompt_definition.prompt_id,
                "prompt_version": prompt_definition.version,
                "candidate_count": len(responses),
            },
        )

    def _score_candidate(
        self,
        response: str,
        refined_answer: str,
    ) -> SoftVerificationScore:
        candidate_answer = self._extractor.extract(response)
        matched = bool(candidate_answer) and candidate_answer == refined_answer
        return SoftVerificationScore(
            score=1.0 if matched else 0.0,
            confidence=1.0,
            passed=matched,
            feedback=(
                "multi_generate_answer_match"
                if matched
                else "multi_generate_answer_mismatch"
            ),
            components={"multi_generate_match": 1.0 if matched else 0.0},
        )

    @staticmethod
    def _render_user_payload(
        *,
        objective: str,
        responses: Sequence[str],
        evidence: Sequence[str],
    ) -> str:
        sections = ["ORIGINAL TASK", objective.strip()]
        if evidence:
            sections.extend(
                [
                    "AUTHORIZED EVIDENCE",
                    "\n".join(
                        f"[{index}] {str(item).strip()}"
                        for index, item in enumerate(evidence, start=1)
                        if str(item).strip()
                    ),
                ]
            )
        sections.append("CANDIDATE SOLUTIONS")
        sections.append(
            "\n\n".join(
                f"Candidate {index}:\n{str(response).strip()}"
                for index, response in enumerate(responses, start=1)
            )
        )
        sections.extend(
            [
                "VERIFICATION TASK",
                "Solve the original task using the candidates only as potentially useful reasoning. Return one refined solution with an explicit final answer.",
            ]
        )
        return "\n\n".join(section for section in sections if section)


__all__ = [
    "FinalAnswerExtractorPort",
    "MultiGenerateVerifierConfig",
    "NormalizedFinalAnswerExtractor",
    "RuntimeMultiGenerateVerifier",
    "SoftVerifierGenerationRuntime",
]
