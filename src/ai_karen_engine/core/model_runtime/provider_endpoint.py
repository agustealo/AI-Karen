from __future__ import annotations

"""Canonical provider endpoint contract for runtime selection."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ai_karen_engine.core.model_runtime.runtime_engine import (
    EndpointKind,
    EndpointProtocol,
    Locality,
    RuntimeEngine,
)


class ProviderEndpointType(str, Enum):
    BUILTIN_TRANSFORMERS = "builtin_transformers"
    BUILTIN_VLLM = "builtin_vllm"
    OPENAI_COMPATIBLE = "openai_compatible"
    REMOTE_API = "remote_api"


class ProviderEndpointStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProviderEndpoint:
    provider_id: str
    display_name: str
    endpoint_type: ProviderEndpointType
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    enabled: bool = True
    builtin: bool = False
    tenant_scoped: bool = True
    timeout_seconds: float = 30.0
    supports_streaming: bool = False
    supports_embeddings: bool = False
    supports_models_endpoint: bool = False
    fallback_eligible: bool = True
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    default_model: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    kind: EndpointKind = field(default=EndpointKind.LOCAL_ENDPOINT)
    protocol: EndpointProtocol = field(default=EndpointProtocol.OPENAI_COMPATIBLE)
    runtime_engine: RuntimeEngine = field(default=RuntimeEngine.CUSTOM)
    locality: Locality = field(default=Locality.LOCAL)


BUILTIN_PROVIDER_ENDPOINTS: tuple[ProviderEndpoint, ...] = (
    ProviderEndpoint(
        provider_id="builtin_transformers",
        display_name="Transformers",
        endpoint_type=ProviderEndpointType.BUILTIN_TRANSFORMERS,
        builtin=True,
        tenant_scoped=False,
        supports_streaming=False,
        supports_embeddings=True,
        fallback_eligible=False,
        kind=EndpointKind.LOCAL_ENDPOINT,
        protocol=EndpointProtocol.NATIVE,
        runtime_engine=RuntimeEngine.TRANSFORMERS,
        locality=Locality.LOCAL,
        capabilities=(
            "text_generation",
            "chat_completion",
            "embedding",
            "reranking",
            "classification",
            "sentiment",
            "summarization",
            "translation",
            "vlm_helper",
            "ocr_helper",
        ),
        default_model="auto",
    ),
    ProviderEndpoint(
        provider_id="builtin_vllm",
        display_name="vLLM",
        endpoint_type=ProviderEndpointType.BUILTIN_VLLM,
        builtin=True,
        tenant_scoped=False,
        supports_streaming=True,
        supports_models_endpoint=True,
        fallback_eligible=True,
        kind=EndpointKind.LOCAL_ENDPOINT,
        protocol=EndpointProtocol.OPENAI_COMPATIBLE,
        runtime_engine=RuntimeEngine.VLLM,
        locality=Locality.LOCAL,
        capabilities=("text_generation", "chat_completion", "streaming_text"),
        default_model="auto",
    ),
)

