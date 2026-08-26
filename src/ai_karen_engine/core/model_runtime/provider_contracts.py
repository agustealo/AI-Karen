from __future__ import annotations

"""Provider-neutral model runtime contracts owned by Core.

Concrete integrations implement these contracts. The descriptors here are the
single backend truth for model execution capabilities and must not be inferred
by UI, reasoning strategies, or provider-specific aliases.
"""

from dataclasses import dataclass
from typing import Any, Iterator, List, Protocol, Union, runtime_checkable


class LLMError(RuntimeError):
    """Base error for provider-neutral model execution failures."""


class ProviderNotAvailable(LLMError):
    """The selected provider/runtime cannot currently execute the request."""


class GenerationFailed(LLMError):
    """The provider was selected but generation failed."""


class EmbeddingFailed(LLMError):
    """The provider was selected but embedding generation failed."""


@dataclass(frozen=True, slots=True)
class ModelRuntimeCapabilities:
    """Canonical capability descriptor for an already-resolved model runtime.

    This descriptor reports execution mechanics, not policy eligibility. Runtime
    Policy still decides whether a capability may be used for a request.
    """

    runtime_engine: str
    model_id: str
    hidden_size: int = 0
    supports_streaming: bool = False
    supports_seed: bool = False
    supports_embeddings: bool = False
    supports_logprobs: bool = False
    supports_first_token_embedding_control: bool = False

    def __post_init__(self) -> None:
        if self.hidden_size < 0:
            raise ValueError("hidden_size must be non-negative")
        if self.supports_first_token_embedding_control and self.hidden_size <= 0:
            raise ValueError(
                "first-token embedding control requires a positive hidden_size"
            )
        if not self.runtime_engine.strip():
            raise ValueError("runtime_engine must not be empty")
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")

    def supports(self, capability: str) -> bool:
        normalized = capability.strip().lower()
        mapping = {
            "streaming": self.supports_streaming,
            "seeded_generation": self.supports_seed,
            "embeddings": self.supports_embeddings,
            "logprobs": self.supports_logprobs,
            "first_token_embedding_control": self.supports_first_token_embedding_control,
            "generation_embedding_control": self.supports_first_token_embedding_control,
        }
        return bool(mapping.get(normalized, False))


@runtime_checkable
class ProviderRuntime(Protocol):
    """Minimal runtime surface consumed by Core orchestration."""

    model: str

    def generate_text(self, prompt: str, **kwargs: Any) -> str: ...

    def embed(
        self,
        text: Union[str, List[str]],
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]: ...

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]: ...

    def runtime_capabilities(self) -> ModelRuntimeCapabilities: ...


class LLMProviderBase:
    """Compatibility base for first-party runtimes without integration coupling."""

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError

    def embed(
        self,
        text: Union[str, List[str]],
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]:
        raise NotImplementedError

    def runtime_capabilities(self) -> ModelRuntimeCapabilities:
        model_id = str(getattr(self, "model", None) or getattr(self, "_model_name", "unknown"))
        runtime_engine = str(getattr(self, "provider_name", self.__class__.__name__))
        return ModelRuntimeCapabilities(
            runtime_engine=runtime_engine,
            model_id=model_id,
        )

    def warm_cache(self) -> None:
        try:
            self.generate_text("hello", max_tokens=1)
        except Exception:
            return


__all__ = [
    "EmbeddingFailed",
    "GenerationFailed",
    "LLMError",
    "LLMProviderBase",
    "ModelRuntimeCapabilities",
    "ProviderNotAvailable",
    "ProviderRuntime",
]
