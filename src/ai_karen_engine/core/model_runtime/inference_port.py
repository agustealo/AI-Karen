from __future__ import annotations

"""Core-owned inference port shared by reasoning, recall, and memory services."""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Protocol, Sequence, runtime_checkable

from ai_karen_engine.core.model_runtime.provider_contracts import ProviderNotAvailable


@dataclass(frozen=True)
class InferenceRequest:
    messages: Sequence[Mapping[str, str]]
    preferred_provider: str | None = None
    preferred_model: str | None = None
    max_tokens: int = 512
    temperature: float = 0.2
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class InferenceResponse:
    text: str
    provider: str | None = None
    model: str | None = None
    metadata: Mapping[str, Any] | None = None


@runtime_checkable
class InferencePort(Protocol):
    async def generate(self, request: InferenceRequest) -> InferenceResponse: ...


class ModelManagerInferencePort:
    """Default Core adapter to the canonical ModelManager authority."""

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        from ai_karen_engine.core.model_runtime.model_manager import get_model_manager

        manager = get_model_manager()
        context: Dict[str, Any] = {}
        if request.preferred_provider:
            context["preferred_provider"] = request.preferred_provider
        response = await manager.generate_chat(
            [dict(message) for message in request.messages],
            context=context,
            stream=False,
            model=request.preferred_model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        text = str(response or "").strip()
        if not text:
            raise ProviderNotAvailable("Inference port returned empty model output")
        selection = manager.select_provider("chat_completion", context=context)
        return InferenceResponse(
            text=text,
            provider=selection.provider_id if selection else None,
            model=request.preferred_model or (selection.model if selection else None),
            metadata=dict(request.metadata or {}),
        )


_default_inference_port: InferencePort | None = None


def get_inference_port() -> InferencePort:
    global _default_inference_port
    if _default_inference_port is None:
        _default_inference_port = ModelManagerInferencePort()
    return _default_inference_port


def set_inference_port(port: InferencePort | None) -> None:
    """Composition hook for tests or alternate runtime implementations."""
    global _default_inference_port
    _default_inference_port = port
