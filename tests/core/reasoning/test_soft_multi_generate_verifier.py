from __future__ import annotations

from dataclasses import dataclass

from ai_karen_engine.core.model_runtime.provider_contracts import ModelRuntimeCapabilities
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry
from ai_karen_engine.core.runtime.prompt.prompt_service import PromptRuntimeService
from ai_karen_engine.core.runtime.soft_reasoning_verifier import (
    NormalizedFinalAnswerExtractor,
    RuntimeMultiGenerateVerifier,
)


@dataclass
class FakeVerifierRuntime:
    output: str = "Reasoning...\nFinal Answer: 42"
    prompts: list[str] | None = None

    def __post_init__(self) -> None:
        self.prompts = []

    def generate_text(self, prompt: str, **kwargs) -> str:
        assert self.prompts is not None
        self.prompts.append(prompt)
        assert kwargs["temperature"] == 0.0
        return self.output

    def runtime_capabilities(self) -> ModelRuntimeCapabilities:
        return ModelRuntimeCapabilities(
            runtime_engine="transformers",
            model_id="same-model",
        )


def test_final_answer_extractor_handles_explicit_and_boxed_answers() -> None:
    extractor = NormalizedFinalAnswerExtractor()

    assert extractor.extract("work\nFinal Answer: 42.") == "42"
    assert extractor.extract(r"therefore $\\boxed{YES}$") == "yes"
    assert extractor.extract("line one\nNo") == "no"


def test_multi_generate_verifier_uses_registered_prompt_and_binary_answer_match(tmp_path) -> None:
    registry = PromptRegistry(tmp_path / "prompt-registry")
    service = PromptRuntimeService(registry=registry)
    runtime = FakeVerifierRuntime()
    verifier = RuntimeMultiGenerateVerifier(
        runtime=runtime,
        prompt_registry=registry,
        prompt_service=service,
    )

    result = verifier.verify_batch(
        "What is six times seven?",
        [
            "Compute 6*7.\nFinal Answer: 42",
            "I think it is 41.\nFinal Answer: 41",
            "Another derivation.\nAnswer: 42.",
        ],
        evidence=("6 groups of 7 contain 42 items",),
    )

    assert result.verifier_model_id == "same-model"
    assert result.runtime_engine == "transformers"
    assert [score.passed for score in result.candidate_scores] == [True, False, True]
    assert result.metadata["verifier_strategy"] == "multi_generate"
    assert result.metadata["prompt_id"] == "soft_reasoning.multi_generate_verifier"
    assert runtime.prompts is not None
    assert len(runtime.prompts) == 1
    prompt = runtime.prompts[0]
    assert "CANDIDATE SOLUTIONS" in prompt
    assert "Candidate 1" in prompt
    assert "Candidate 3" in prompt
    assert "AUTHORIZED EVIDENCE" in prompt


def test_multi_generate_verifier_does_not_majority_vote(tmp_path) -> None:
    registry = PromptRegistry(tmp_path / "prompt-registry")
    service = PromptRuntimeService(registry=registry)
    runtime = FakeVerifierRuntime(output="Independent solution\nFinal Answer: blue")
    verifier = RuntimeMultiGenerateVerifier(
        runtime=runtime,
        prompt_registry=registry,
        prompt_service=service,
    )

    result = verifier.verify_batch(
        "Choose the correct color.",
        [
            "Final Answer: red",
            "Final Answer: red",
            "Final Answer: blue",
        ],
        evidence=(),
    )

    assert [score.passed for score in result.candidate_scores] == [False, False, True]
