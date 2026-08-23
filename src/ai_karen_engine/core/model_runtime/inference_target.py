"""Canonical inference target metadata model."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.model_runtime.runtime_engine import (
    EndpointKind,
    EndpointProtocol,
    Locality,
    RuntimeEngine,
)


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Structured capability declaration for an inference target."""

    chat: bool = True
    streaming: bool = False
    responses_api: bool = False
    tools: bool = False
    structured_output: bool = False
    vision: bool = False
    embeddings: bool = False
    reasoning: bool = False
    json_schema: bool = False
    max_context: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chat": self.chat,
            "streaming": self.streaming,
            "responses_api": self.responses_api,
            "tools": self.tools,
            "structured_output": self.structured_output,
            "vision": self.vision,
            "embeddings": self.embeddings,
            "reasoning": self.reasoning,
            "json_schema": self.json_schema,
            "max_context": self.max_context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CapabilityDescriptor:
        return cls(
            chat=data.get("chat", True),
            streaming=data.get("streaming", False),
            responses_api=data.get("responses_api", False),
            tools=data.get("tools", False),
            structured_output=data.get("structured_output", False),
            vision=data.get("vision", False),
            embeddings=data.get("embeddings", False),
            reasoning=data.get("reasoning", False),
            json_schema=data.get("json_schema", False),
            max_context=data.get("max_context"),
        )


@dataclass(frozen=True)
class InferenceTarget:
    """Canonical inference target descriptor.

    This replaces ad-hoc provider dictionaries with a structured contract.
    """

    target_id: str
    kind: EndpointKind
    protocol: EndpointProtocol
    provider_name: str
    runtime_engine: RuntimeEngine
    base_url: Optional[str] = None
    model_id: Optional[str] = None
    locality: Locality = Locality.LOCAL
    health: str = "unknown"
    capabilities: CapabilityDescriptor = field(default_factory=CapabilityDescriptor)
    priority: int = 50
    metadata: Dict[str, Any] = field(default_factory=dict)

    def supports_capability(self, capability: str) -> bool:
        """Check if target supports a specific capability."""
        cap_map = {
            "chat": self.capabilities.chat,
            "streaming": self.capabilities.streaming,
            "responses_api": self.capabilities.responses_api,
            "tools": self.capabilities.tools,
            "structured_output": self.capabilities.structured_output,
            "vision": self.capabilities.vision,
            "embeddings": self.capabilities.embeddings,
            "reasoning": self.capabilities.reasoning,
            "json_schema": self.capabilities.json_schema,
        }
        return bool(cap_map.get(capability, False))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "kind": self.kind.value,
            "protocol": self.protocol.value,
            "provider_name": self.provider_name,
            "runtime_engine": self.runtime_engine.value,
            "base_url": self.base_url,
            "model_id": self.model_id,
            "locality": self.locality.value,
            "health": self.health,
            "capabilities": self.capabilities.to_dict(),
            "priority": self.priority,
            "metadata": self.metadata,
        }
