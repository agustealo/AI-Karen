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


# Canonical runtime inventory. Specialized Core ML runtimes remain available for
# machine capabilities, while conversational generation is owned by configured
# provider endpoints rather than a privileged built-in chat provider.
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
            "embeddings",
            "reranking",
            "classification",
            "sentiment",
            "summarization",
            "translation",
            "vlm_helper",
            "ocr_helper",
        ),
        default_model="auto",
        metadata={"role": "specialized_ml_runtime", "priority": 100},
    ),
    ProviderEndpoint(
        provider_id="lmstudio-desktop",
        display_name="LM Studio",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://localhost:1234/v1",
        builtin=False,
        tenant_scoped=False,
        timeout_seconds=60.0,
        supports_streaming=True,
        supports_embeddings=True,
        supports_models_endpoint=True,
        fallback_eligible=True,
        capabilities=(
            "text_generation",
            "chat_completion",
            "streaming",
            "responses_api",
            "tools",
            "structured_output",
            "vision",
            "embeddings",
        ),
        default_model=None,
        kind=EndpointKind.LOCAL_ENDPOINT,
        protocol=EndpointProtocol.OPENAI_COMPATIBLE,
        runtime_engine=RuntimeEngine.LMSTUDIO,
        locality=Locality.LOCAL,
        metadata={"priority": 10},
    ),
    ProviderEndpoint(
        provider_id="ollama-local",
        display_name="Ollama",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://localhost:11434/v1",
        builtin=False,
        tenant_scoped=False,
        timeout_seconds=120.0,
        supports_streaming=True,
        supports_embeddings=True,
        supports_models_endpoint=True,
        fallback_eligible=True,
        capabilities=(
            "text_generation",
            "chat_completion",
            "streaming",
            "tools",
            "embeddings",
        ),
        default_model=None,
        kind=EndpointKind.LOCAL_ENDPOINT,
        protocol=EndpointProtocol.OPENAI_COMPATIBLE,
        runtime_engine=RuntimeEngine.OLLAMA,
        locality=Locality.LOCAL,
        metadata={"priority": 20},
    ),
    ProviderEndpoint(
        provider_id="llamacpp-server",
        display_name="llama.cpp Server",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://localhost:8080/v1",
        builtin=False,
        tenant_scoped=False,
        timeout_seconds=60.0,
        supports_streaming=True,
        supports_embeddings=True,
        supports_models_endpoint=True,
        fallback_eligible=True,
        capabilities=(
            "text_generation",
            "chat_completion",
            "streaming",
            "responses_api",
            "tools",
            "structured_output",
            "vision",
            "embeddings",
        ),
        default_model=None,
        kind=EndpointKind.LOCAL_ENDPOINT,
        protocol=EndpointProtocol.OPENAI_COMPATIBLE,
        runtime_engine=RuntimeEngine.LLAMACPP,
        locality=Locality.LOCAL,
        metadata={"priority": 30},
    ),
)
