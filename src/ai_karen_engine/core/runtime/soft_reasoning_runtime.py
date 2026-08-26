"""Runtime-owned adapters for Soft Reasoning model-internal generation.

This module bridges an already-selected local model runtime to Core's
``SoftGenerationPort``. It does not discover providers, choose models, assemble
prompts, authorize reasoning, or perform fallback.

The Transformers adapter mirrors the Soft Reasoning paper's important execution
property: a guide vector replaces the embedding at a configured special-token
position during the initial model forward pass while generation otherwise uses
the normal token IDs and cache path.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    """Narrow surface required from an already-resolved Transformers runtime."""

    def generation_components(self) -> tuple[Any, Any, Any]: ...

    def runtime_capabilities(self) -> ModelRuntimeCapabilities: ...


@dataclass(frozen=True, slots=True)
class TransformersSoftReasoningConfig:
    """Prompt/model contract for first-token embedding insertion."""

    insertion_token_id: int
    occurrence_from_end: int = 1
    add_special_tokens: bool = False
    skip_special_tokens_on_decode: bool = True

    def __post_init__(self) -> None:
        if self.insertion_token_id < 0:
            raise ValueError("insertion_token_id must be non-negative")
        if self.occurrence_from_end <= 0:
            raise ValueError("occurrence_from_end must be positive")


class TransformersSoftGenerationAdapter:
    """First-token embedding-control adapter for a warmed Transformers runtime.

    Capability is advertised by this adapter only after the selected model
    exposes a valid input-embedding layer. The underlying Transformers provider
    remains a normal text runtime and continues to report embedding control as
    unsupported.
    """

    runtime_engine = "transformers:first_token_embedding_hook:v1"

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
            supports_logprobs=False,
            supports_first_token_embedding_control=True,
        )

    def first_token_embedding(self, prompt: str) -> Sequence[float]:
        if not prompt.strip():
            raise ValueError("prepared Soft Reasoning prompt must not be empty")
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

                generated_ids = model.generate(**generate_kwargs)
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
        return SoftGenerationOutput(
            text=text,
            token_count=token_count,
            finish_reason=finish_reason,
            model_id=base.model_id,
            runtime_engine=self.runtime_engine,
            metadata={
                "insertion_token_id": self._config.insertion_token_id,
                "insertion_position": position,
                "occurrence_from_end": self._config.occurrence_from_end,
                "seed": int(seed),
                "generation_mode": "greedy",
            },
        )

    def validate_prompt_contract(self, prompt: str) -> int:
        """Validate that the prepared prompt contains the configured marker."""
        _model, tokenizer, _lock = self._runtime.generation_components()
        encoded = self._tokenize(tokenizer, prompt)
        return self._find_insertion_position(encoded["input_ids"])

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
        return int(positions[-occurrence])

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
    "TransformersGenerationSession",
    "TransformersSoftGenerationAdapter",
    "TransformersSoftReasoningConfig",
]
