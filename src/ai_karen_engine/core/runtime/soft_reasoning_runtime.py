"""Runtime-owned adapters for Soft Reasoning model-internal generation.

The adapter bridges an already-selected local Transformers runtime to Core's
``SoftGenerationPort``. Runtime still owns model selection, authorization,
prompt construction, fallback, and lifecycle.

For the ICML-2025 profile the adapter can:
- derive z from the greedy first answer token predicted *before* the inserted
  marker token;
- require the paper's empirically preferred last-token marker placement;
- replace only that marker embedding for the initial forward pass;
- collect token-level generation log probabilities required by the coherence
  objective.

Compatibility defaults retain the older marker-embedding reference behaviour so
existing callers do not silently change semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, Sequence

from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    ModelRuntimeCapabilities,
    ProviderNotAvailable,
)
from ai_karen_engine.core.reasoning.soft_reasoning.contracts import (
    SoftGenerationOutput,
)


class TransformersGenerationSession(Protocol):
    def generation_components(self) -> tuple[Any, Any, Any]: ...

    def runtime_capabilities(self) -> ModelRuntimeCapabilities: ...


class ReferenceEmbeddingMode(Enum):
    MARKER_TOKEN = "marker_token"
    GREEDY_FIRST_ANSWER_TOKEN = "greedy_first_answer_token"


@dataclass(frozen=True, slots=True)
class TransformersSoftReasoningConfig:
    insertion_token_id: int
    occurrence_from_end: int = 1
    add_special_tokens: bool = False
    skip_special_tokens_on_decode: bool = True
    reference_embedding_mode: ReferenceEmbeddingMode = ReferenceEmbeddingMode.MARKER_TOKEN
    require_last_position: bool = False
    collect_logprobs: bool = False

    def __post_init__(self) -> None:
        if self.insertion_token_id < 0:
            raise ValueError("insertion_token_id must be non-negative")
        if self.occurrence_from_end <= 0:
            raise ValueError("occurrence_from_end must be positive")

    @classmethod
    def paper_2025(cls, insertion_token_id: int) -> "TransformersSoftReasoningConfig":
        return cls(
            insertion_token_id=insertion_token_id,
            occurrence_from_end=1,
            add_special_tokens=False,
            reference_embedding_mode=ReferenceEmbeddingMode.GREEDY_FIRST_ANSWER_TOKEN,
            require_last_position=True,
            collect_logprobs=True,
        )


class TransformersSoftGenerationAdapter:
    runtime_engine = "transformers:first_token_embedding_hook:v2"

    def __init__(
        self,
        runtime: TransformersGenerationSession,
        config: TransformersSoftReasoningConfig,
    ) -> None:
        self._runtime = runtime
        self._config = config

    def capabilities(self) -> ModelRuntimeCapabilities:
        model, _tokenizer, _lock = self._runtime.generation_components()
        embedding_layer = model.get_input_embeddings()
        weight = getattr(embedding_layer, "weight", None)
        shape = getattr(weight, "shape", None)
        if shape is None or len(shape) < 2:
            raise ProviderNotAvailable(
                "Selected Transformers model does not expose input embeddings"
            )
        hidden_size = int(shape[-1])
        if hidden_size <= 0:
            raise ProviderNotAvailable(
                "Selected Transformers model exposes an invalid hidden size"
            )
        base = self._runtime.runtime_capabilities()
        return ModelRuntimeCapabilities(
            runtime_engine=self.runtime_engine,
            model_id=base.model_id,
            hidden_size=hidden_size,
            supports_streaming=False,
            supports_seed=True,
            supports_embeddings=False,
            supports_logprobs=self._config.collect_logprobs,
            supports_first_token_embedding_control=True,
        )

    def first_token_embedding(self, prompt: str) -> Sequence[float]:
        if not prompt.strip():
            raise ValueError("prepared Soft Reasoning prompt must not be empty")
        if (
            self._config.reference_embedding_mode
            == ReferenceEmbeddingMode.GREEDY_FIRST_ANSWER_TOKEN
        ):
            return self._greedy_first_answer_token_embedding(prompt)
        return self._marker_token_embedding(prompt)

    def _marker_token_embedding(self, prompt: str) -> Sequence[float]:
        model, tokenizer, generation_lock = self._runtime.generation_components()
        torch = self._torch()
        encoded = self._tokenize(tokenizer, prompt)
        input_ids = encoded["input_ids"]
        position = self._find_insertion_position(input_ids)
        embedding_layer = model.get_input_embeddings()
        device = self._embedding_device(embedding_layer)
        input_ids = input_ids.to(device)

        with generation_lock, torch.no_grad():
            embeddings = embedding_layer(input_ids)
            vector = embeddings[0, position, :].detach().float().cpu().tolist()
        return tuple(float(value) for value in vector)

    def _greedy_first_answer_token_embedding(self, prompt: str) -> Sequence[float]:
        model, tokenizer, generation_lock = self._runtime.generation_components()
        torch = self._torch()
        encoded = self._tokenize(tokenizer, prompt)
        input_ids = encoded["input_ids"]
        attention_mask = encoded.get("attention_mask")
        position = self._find_insertion_position(input_ids)
        if position != int(input_ids.shape[-1]) - 1:
            raise GenerationFailed(
                "paper_2025 requires the inserted Soft Reasoning marker to be "
                "the final prompt token"
            )

        base_input_ids = input_ids[:, :position]
        if int(base_input_ids.shape[-1]) == 0:
            raise GenerationFailed(
                "cannot derive greedy first answer token from an empty base prompt"
            )
        base_attention_mask = (
            attention_mask[:, :position] if attention_mask is not None else None
        )

        embedding_layer = model.get_input_embeddings()
        device = self._embedding_device(embedding_layer)
        base_input_ids = base_input_ids.to(device)
        if base_attention_mask is not None:
            base_attention_mask = base_attention_mask.to(device)

        forward_kwargs: dict[str, Any] = {"input_ids": base_input_ids}
        if base_attention_mask is not None:
            forward_kwargs["attention_mask"] = base_attention_mask

        try:
            with generation_lock, torch.no_grad():
                model.eval()
                outputs = model(**forward_kwargs)
                logits = outputs.logits[0, -1, :]
                token_id = int(torch.argmax(logits, dim=-1).item())
                token_tensor = torch.as_tensor(
                    [[token_id]],
                    dtype=base_input_ids.dtype,
                    device=device,
                )
                vector = (
                    embedding_layer(token_tensor)[0, 0, :]
                    .detach()
                    .float()
                    .cpu()
                    .tolist()
                )
        except Exception as exc:
            raise GenerationFailed(
                f"Failed to derive greedy first answer-token embedding: {exc}"
            ) from exc

        return tuple(float(value) for value in vector)

    def generate_with_first_token_embedding(
        self,
        prompt: str,
        first_token_embedding: Sequence[float],
        *,
        max_tokens: int,
        seed: int,
    ) -> SoftGenerationOutput:
        if not prompt.strip():
            raise ValueError("prepared Soft Reasoning prompt must not be empty")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        model, tokenizer, generation_lock = self._runtime.generation_components()
        torch = self._torch()
        encoded = self._tokenize(tokenizer, prompt)
        input_ids = encoded["input_ids"]
        attention_mask = encoded.get("attention_mask")
        position = self._find_insertion_position(input_ids)
        embedding_layer = model.get_input_embeddings()
        hidden_size = self.capabilities().hidden_size
        replacement_values = tuple(float(value) for value in first_token_embedding)
        if len(replacement_values) != hidden_size:
            raise ValueError(
                "guided first-token embedding size does not match model hidden size: "
                f"{len(replacement_values)} != {hidden_size}"
            )

        device = self._embedding_device(embedding_layer)
        input_ids = input_ids.to(device)
        if attention_mask is not None:
            attention_mask = attention_mask.to(device)

        applied = False

        def replace_initial_embedding(_module: Any, _inputs: Any, output: Any) -> Any:
            nonlocal applied
            if applied:
                return output
            if getattr(output, "ndim", 0) != 3 or int(output.shape[1]) <= position:
                return output
            replacement = torch.as_tensor(
                replacement_values,
                dtype=output.dtype,
                device=output.device,
            )
            modified = output.clone()
            modified[0, position, :] = replacement
            applied = True
            return modified

        handle = embedding_layer.register_forward_hook(replace_initial_embedding)
        try:
            with generation_lock, torch.no_grad(), self._seed_scope(torch, seed, device):
                model.eval()
                generate_kwargs: dict[str, Any] = {
                    "input_ids": input_ids,
                    "max_new_tokens": int(max_tokens),
                    "do_sample": False,
                }
                if self._config.collect_logprobs:
                    generate_kwargs.update(
                        {
                            "return_dict_in_generate": True,
                            "output_scores": True,
                        }
                    )
                if attention_mask is not None:
                    generate_kwargs["attention_mask"] = attention_mask
                eos_token_id = getattr(tokenizer, "eos_token_id", None)
                pad_token_id = getattr(tokenizer, "pad_token_id", None)
                if pad_token_id is None:
                    pad_token_id = eos_token_id
                if pad_token_id is not None:
                    generate_kwargs["pad_token_id"] = pad_token_id
                if eos_token_id is not None:
                    generate_kwargs["eos_token_id"] = eos_token_id

                generated = model.generate(**generate_kwargs)
        except Exception as exc:
            raise GenerationFailed(
                f"Transformers Soft Reasoning generation failed: {exc}"
            ) from exc
        finally:
            handle.remove()

        if not applied:
            raise GenerationFailed(
                "Transformers model never exposed the configured insertion position "
                "during the initial embedding forward pass"
            )

        generated_ids = getattr(generated, "sequences", generated)
        prompt_tokens = int(input_ids.shape[-1])
        sequence = generated_ids[0]
        new_tokens = sequence[prompt_tokens:]
        token_count = int(new_tokens.shape[-1])
        text = tokenizer.decode(
            new_tokens,
            skip_special_tokens=self._config.skip_special_tokens_on_decode,
        ).strip()
        finish_reason = "length" if token_count >= max_tokens else "stop"
        base = self._runtime.runtime_capabilities()

        token_log_probabilities: tuple[float, ...] = ()
        if self._config.collect_logprobs:
            token_log_probabilities = self._extract_token_log_probabilities(
                torch=torch,
                generated=generated,
                new_tokens=new_tokens,
            )
            if len(token_log_probabilities) != token_count:
                raise GenerationFailed(
                    "Transformers runtime returned incomplete token log probabilities"
                )

        sequence_log_probability = (
            float(sum(token_log_probabilities))
            if token_log_probabilities
            else None
        )
        mean_token_log_probability = (
            sequence_log_probability / float(token_count)
            if sequence_log_probability is not None and token_count > 0
            else None
        )
        first_token_probability = (
            float(torch.exp(torch.tensor(token_log_probabilities[0])).item())
            if token_log_probabilities
            else None
        )

        return SoftGenerationOutput(
            text=text,
            token_count=token_count,
            finish_reason=finish_reason,
            model_id=base.model_id,
            runtime_engine=self.runtime_engine,
            token_log_probabilities=token_log_probabilities,
            sequence_log_probability=sequence_log_probability,
            mean_token_log_probability=mean_token_log_probability,
            first_token_probability=first_token_probability,
            metadata={
                "insertion_token_id": self._config.insertion_token_id,
                "insertion_position": position,
                "occurrence_from_end": self._config.occurrence_from_end,
                "reference_embedding_mode": self._config.reference_embedding_mode.value,
                "seed": int(seed),
                "generation_mode": "greedy",
            },
        )

    def validate_prompt_contract(self, prompt: str) -> int:
        _model, tokenizer, _lock = self._runtime.generation_components()
        encoded = self._tokenize(tokenizer, prompt)
        position = self._find_insertion_position(encoded["input_ids"])
        if self._config.require_last_position:
            last_position = int(encoded["input_ids"].shape[-1]) - 1
            if position != last_position:
                raise GenerationFailed(
                    "paper_2025 requires the Soft Reasoning marker at the final "
                    "prompt-token position"
                )
        return position

    def _tokenize(self, tokenizer: Any, prompt: str) -> Any:
        try:
            return tokenizer(
                prompt,
                return_tensors="pt",
                add_special_tokens=self._config.add_special_tokens,
            )
        except Exception as exc:
            raise GenerationFailed(
                f"Failed to tokenize prepared Soft Reasoning prompt: {exc}"
            ) from exc

    def _find_insertion_position(self, input_ids: Any) -> int:
        values = input_ids[0].detach().cpu().tolist()
        positions = [
            index
            for index, token_id in enumerate(values)
            if int(token_id) == self._config.insertion_token_id
        ]
        occurrence = self._config.occurrence_from_end
        if len(positions) < occurrence:
            raise GenerationFailed(
                "Prepared Soft Reasoning prompt does not contain the configured "
                f"insertion token {self._config.insertion_token_id} at occurrence "
                f"from end {occurrence}"
            )
        position = int(positions[-occurrence])
        if self._config.require_last_position and position != len(values) - 1:
            raise GenerationFailed(
                "paper_2025 requires the configured insertion token to be the "
                "last prompt token"
            )
        return position

    @staticmethod
    def _extract_token_log_probabilities(
        *,
        torch: Any,
        generated: Any,
        new_tokens: Any,
    ) -> tuple[float, ...]:
        scores = getattr(generated, "scores", None)
        if scores is None:
            raise GenerationFailed(
                "Transformers generation did not expose score tensors required "
                "for Soft Reasoning coherence"
            )
        token_ids = new_tokens.detach().cpu().tolist()
        if len(scores) < len(token_ids):
            raise GenerationFailed(
                "Transformers generation returned fewer score tensors than tokens"
            )
        values: list[float] = []
        for index, token_id in enumerate(token_ids):
            logits = scores[index][0]
            log_probs = torch.log_softmax(logits.float(), dim=-1)
            values.append(float(log_probs[int(token_id)].detach().cpu().item()))
        return tuple(values)

    @staticmethod
    def _embedding_device(embedding_layer: Any) -> Any:
        weight = getattr(embedding_layer, "weight", None)
        device = getattr(weight, "device", None)
        if device is None:
            raise ProviderNotAvailable(
                "Selected Transformers embedding layer does not expose a device"
            )
        return device

    @staticmethod
    def _torch() -> Any:
        try:
            import torch
        except Exception as exc:
            raise ProviderNotAvailable(
                "PyTorch is required for Transformers Soft Reasoning"
            ) from exc
        return torch

    @staticmethod
    def _seed_scope(torch: Any, seed: int, device: Any) -> Any:
        devices: list[int] = []
        if getattr(device, "type", None) == "cuda":
            index = getattr(device, "index", None)
            devices = [0 if index is None else int(index)]
        scope = torch.random.fork_rng(devices=devices, enabled=True)

        class SeededScope:
            def __enter__(self) -> None:
                scope.__enter__()
                torch.manual_seed(int(seed))
                if devices and torch.cuda.is_available():
                    torch.cuda.manual_seed_all(int(seed))
                return None

            def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
                return scope.__exit__(exc_type, exc, tb)

        return SeededScope()


__all__ = [
    "ReferenceEmbeddingMode",
    "TransformersGenerationSession",
    "TransformersSoftGenerationAdapter",
    "TransformersSoftReasoningConfig",
]
