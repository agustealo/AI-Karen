"""Runtime-owned preparation of the Soft Reasoning insertion token.

The paper relies on a special token whose embedding is replaced at the final
prompt position. Tokenizer/model vocabulary mutation belongs to Runtime because
it affects the active model lifecycle. This module operates only on an
already-resolved Transformers runtime and never selects or loads a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    ProviderNotAvailable,
)

DEFAULT_SOFT_REASONING_MARKER = "<|soft_reasoning|>"


@runtime_checkable
class MutableTransformersGenerationSession(Protocol):
    def generation_components(self) -> tuple[Any, Any, Any]: ...


@dataclass(frozen=True, slots=True)
class SoftReasoningMarker:
    token: str
    token_id: int
    vocabulary_resized: bool


class SoftReasoningTokenManager:
    """Ensure one stable special token exists on the resolved local model."""

    def __init__(self, token: str = DEFAULT_SOFT_REASONING_MARKER) -> None:
        token = str(token).strip()
        if not token:
            raise ValueError("Soft Reasoning marker token must not be empty")
        self._token = token

    def ensure(self, runtime: MutableTransformersGenerationSession) -> SoftReasoningMarker:
        if not isinstance(runtime, MutableTransformersGenerationSession):
            raise TypeError(
                "runtime must expose generation_components for marker preparation"
            )

        model, tokenizer, generation_lock = runtime.generation_components()
        convert = getattr(tokenizer, "convert_tokens_to_ids", None)
        if not callable(convert):
            raise ProviderNotAvailable(
                "Selected tokenizer cannot resolve Soft Reasoning special tokens"
            )

        existing_id = self._existing_token_id(tokenizer)
        if existing_id is not None:
            return SoftReasoningMarker(
                token=self._token,
                token_id=existing_id,
                vocabulary_resized=False,
            )

        add_special_tokens = getattr(tokenizer, "add_special_tokens", None)
        resize = getattr(model, "resize_token_embeddings", None)
        if not callable(add_special_tokens) or not callable(resize):
            raise ProviderNotAvailable(
                "Selected local model cannot register the Soft Reasoning insertion token"
            )

        try:
            with generation_lock:
                added = int(
                    add_special_tokens(
                        {"additional_special_tokens": [self._token]}
                    )
                    or 0
                )
                token_id = int(convert(self._token))
                if token_id < 0:
                    raise GenerationFailed(
                        "Tokenizer returned an invalid Soft Reasoning marker id"
                    )
                if added > 0:
                    resize(len(tokenizer))
        except Exception as exc:
            if isinstance(exc, (GenerationFailed, ProviderNotAvailable)):
                raise
            raise GenerationFailed(
                f"Failed to prepare Soft Reasoning marker token: {exc}"
            ) from exc

        verified_id = self._existing_token_id(tokenizer)
        if verified_id is None or verified_id != token_id:
            raise GenerationFailed(
                "Soft Reasoning marker token registration could not be verified"
            )
        return SoftReasoningMarker(
            token=self._token,
            token_id=token_id,
            vocabulary_resized=added > 0,
        )

    def _existing_token_id(self, tokenizer: Any) -> int | None:
        convert = tokenizer.convert_tokens_to_ids
        token_id = convert(self._token)
        if token_id is None:
            return None
        try:
            token_id = int(token_id)
        except (TypeError, ValueError):
            return None

        unk_id = getattr(tokenizer, "unk_token_id", None)
        if unk_id is not None and token_id == int(unk_id):
            vocabulary = getattr(tokenizer, "get_vocab", lambda: {})()
            if self._token not in vocabulary:
                return None
        vocabulary = getattr(tokenizer, "get_vocab", lambda: {})()
        if vocabulary and self._token not in vocabulary:
            return None
        return token_id if token_id >= 0 else None


__all__ = [
    "DEFAULT_SOFT_REASONING_MARKER",
    "MutableTransformersGenerationSession",
    "SoftReasoningMarker",
    "SoftReasoningTokenManager",
]
