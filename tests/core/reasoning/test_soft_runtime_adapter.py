from __future__ import annotations

from contextlib import nullcontext

import pytest

from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    ModelRuntimeCapabilities,
)
from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
    TransformersRuntime,
)
from ai_karen_engine.core.runtime.soft_reasoning_runtime import (
    ReferenceEmbeddingMode,
    TransformersSoftGenerationAdapter,
    TransformersSoftReasoningConfig,
)


class FakeTokenRow:
    def __init__(self, values: list[int]) -> None:
        self._values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self) -> list[int]:
        return list(self._values)


class FakeInputIds:
    def __init__(self, values: list[int]) -> None:
        self._values = values

    def __getitem__(self, index: int) -> FakeTokenRow:
        assert index == 0
        return FakeTokenRow(self._values)


class FakeTokenizer:
    eos_token_id = 2
    pad_token_id = 2

    def __init__(self, token_ids: list[int]) -> None:
        self._token_ids = token_ids

    def __call__(self, prompt: str, **kwargs):
        return {"input_ids": FakeInputIds(self._token_ids)}


class FakeWeight:
    shape = (128, 8)


class FakeEmbeddingLayer:
    weight = FakeWeight()


class FakeModel:
    def get_input_embeddings(self) -> FakeEmbeddingLayer:
        return FakeEmbeddingLayer()


class FakeResolvedRuntime:
    def __init__(self, token_ids: list[int]) -> None:
        self.tokenizer = FakeTokenizer(token_ids)

    def generation_components(self):
        return FakeModel(), self.tokenizer, nullcontext()

    def runtime_capabilities(self) -> ModelRuntimeCapabilities:
        return ModelRuntimeCapabilities(
            runtime_engine="transformers",
            model_id="local-test-model",
            supports_streaming=True,
        )


def test_base_transformers_runtime_does_not_claim_soft_embedding_control() -> None:
    runtime = TransformersRuntime(model_path=None)

    capabilities = runtime.runtime_capabilities()

    assert capabilities.runtime_engine == "transformers"
    assert capabilities.supports_first_token_embedding_control is False


def test_specialized_adapter_advertises_control_only_after_model_validation() -> None:
    runtime = FakeResolvedRuntime([1, 25, 7, 25, 9])
    adapter = TransformersSoftGenerationAdapter(
        runtime,
        TransformersSoftReasoningConfig(
            insertion_token_id=25,
            occurrence_from_end=1,
        ),
    )

    capabilities = adapter.capabilities()

    assert capabilities.supports_first_token_embedding_control is True
    assert capabilities.hidden_size == 8
    assert capabilities.model_id == "local-test-model"
    assert capabilities.runtime_engine == "transformers:first_token_embedding_hook:v2"
    assert capabilities.supports_logprobs is False


def test_paper_runtime_profile_requires_greedy_reference_last_marker_and_logprobs() -> None:
    config = TransformersSoftReasoningConfig.paper_2025(25)

    assert config.reference_embedding_mode == ReferenceEmbeddingMode.GREEDY_FIRST_ANSWER_TOKEN
    assert config.require_last_position is True
    assert config.collect_logprobs is True


def test_prompt_contract_uses_configured_occurrence_from_end() -> None:
    runtime = FakeResolvedRuntime([25, 3, 25, 4, 25, 5])
    adapter = TransformersSoftGenerationAdapter(
        runtime,
        TransformersSoftReasoningConfig(
            insertion_token_id=25,
            occurrence_from_end=2,
        ),
    )

    assert adapter.validate_prompt_contract("prepared prompt") == 2


def test_prompt_contract_fails_closed_when_marker_is_missing() -> None:
    runtime = FakeResolvedRuntime([1, 2, 3, 4])
    adapter = TransformersSoftGenerationAdapter(
        runtime,
        TransformersSoftReasoningConfig(insertion_token_id=25),
    )

    with pytest.raises(GenerationFailed, match="does not contain"):
        adapter.validate_prompt_contract("prepared prompt")


def test_paper_prompt_contract_requires_marker_at_last_token() -> None:
    runtime = FakeResolvedRuntime([1, 25, 7])
    adapter = TransformersSoftGenerationAdapter(
        runtime,
        TransformersSoftReasoningConfig.paper_2025(25),
    )

    with pytest.raises(GenerationFailed, match="last prompt token"):
        adapter.validate_prompt_contract("prepared prompt")


def test_prompt_contract_rejects_invalid_occurrence() -> None:
    with pytest.raises(ValueError, match="occurrence_from_end"):
        TransformersSoftReasoningConfig(
            insertion_token_id=25,
            occurrence_from_end=0,
        )
