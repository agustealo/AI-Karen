"""OpenAI-compatible endpoint adapter with capability discovery."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.model_runtime.runtime_engine import (
    EndpointKind,
    EndpointProtocol,
    Locality,
    RuntimeEngine,
)
from ai_karen_engine.core.model_runtime.inference_target import (
    CapabilityDescriptor,
    InferenceTarget,
)

logger = logging.getLogger(__name__)


@dataclass
class OpenAICompatibleAdapter:
    """Adapter for OpenAI-compatible inference endpoints.

    Supports LM Studio, vLLM, SGLang, llama.cpp, Ollama, TensorRT-LLM,
    and any other server exposing an OpenAI-compatible API.
    """

    target_id: str
    base_url: str
    runtime_engine: RuntimeEngine
    provider_name: str = "local"
    kind: EndpointKind = EndpointKind.LOCAL_ENDPOINT
    protocol: EndpointProtocol = EndpointProtocol.OPENAI_COMPATIBLE
    locality: Locality = Locality.LOCAL
    api_key: Optional[str] = None
    timeout_seconds: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_inference_target(
        self,
        capabilities: Optional[CapabilityDescriptor] = None,
        health: str = "unknown",
        priority: int = 50,
    ) -> InferenceTarget:
        """Convert to canonical InferenceTarget."""
        return InferenceTarget(
            target_id=self.target_id,
            kind=self.kind,
            protocol=self.protocol,
            provider_name=self.provider_name,
            runtime_engine=self.runtime_engine,
            base_url=self.base_url,
            locality=self.locality,
            health=health,
            capabilities=capabilities or CapabilityDescriptor(),
            priority=priority,
            metadata=self.metadata,
        )

    def discover_capabilities(self) -> CapabilityDescriptor:
        """Probe the endpoint for capabilities."""
        capabilities = CapabilityDescriptor()

        try:
            import httpx

            with httpx.Client(timeout=self.timeout_seconds) as client:
                models_url = self.base_url.rstrip("/") + "/models"
                resp = client.get(models_url)
                if resp.status_code == 200:
                    capabilities.chat = True
                    data = resp.json()
                    if "data" in data and data["data"]:
                        capabilities.embeddings = any(
                            "embed" in str(m.get("id", "")).lower() for m in data["data"]
                        )

                health_url = self.base_url.rstrip("/") + "/health"
                resp = client.get(health_url)
                if resp.status_code == 200:
                    pass
        except Exception as exc:
            logger.debug("Capability discovery failed for %s: %s", self.target_id, exc)

        return capabilities

    def check_health(self) -> str:
        """Check endpoint health."""
        try:
            import httpx

            with httpx.Client(timeout=self.timeout_seconds) as client:
                health_url = self.base_url.rstrip("/") + "/health"
                resp = client.get(health_url)
                if resp.status_code == 200:
                    return "healthy"
                return "degraded"
        except Exception as exc:
            logger.debug("Health check failed for %s: %s", self.target_id, exc)
            return "unavailable"


def create_local_endpoint(
    runtime_engine: RuntimeEngine,
    base_url: str,
    target_id: Optional[str] = None,
    provider_name: str = "local",
) -> OpenAICompatibleAdapter:
    """Factory for local OpenAI-compatible endpoints."""
    return OpenAICompatibleAdapter(
        target_id=target_id or f"{runtime_engine.value}-endpoint",
        base_url=base_url,
        runtime_engine=runtime_engine,
        provider_name=provider_name,
        kind=EndpointKind.LOCAL_ENDPOINT,
        locality=Locality.LOCAL,
    )


def create_cloud_endpoint(
    runtime_engine: RuntimeEngine,
    base_url: str,
    provider_name: str,
    target_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> OpenAICompatibleAdapter:
    """Factory for cloud OpenAI-compatible endpoints."""
    return OpenAICompatibleAdapter(
        target_id=target_id or f"{provider_name}-endpoint",
        base_url=base_url,
        runtime_engine=runtime_engine,
        provider_name=provider_name,
        kind=EndpointKind.CLOUD_PROVIDER,
        protocol=EndpointProtocol.OPENAI_COMPATIBLE,
        locality=Locality.CLOUD,
        api_key=api_key,
    )
