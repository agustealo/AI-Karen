from __future__ import annotations

"""Provider-neutral runtime contracts owned by the Core AI Machine.

Concrete integrations may implement these contracts, but Core never imports an
integration package to describe model execution failures or provider behavior.
"""

from typing import Any, Iterator, List, Protocol, Union, runtime_checkable


class LLMError(RuntimeError):
    """Base error for provider-neutral model execution failures."""


class ProviderNotAvailable(LLMError):
    """The selected provider/runtime cannot currently execute the request."""


class GenerationFailed(LLMError):
    """The provider was selected but generation failed."""


class EmbeddingFailed(LLMError):
    """The provider was selected but embedding generation failed."""


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

    def warm_cache(self) -> None:
        try:
            self.generate_text("hello", max_tokens=1)
        except Exception:
            return
