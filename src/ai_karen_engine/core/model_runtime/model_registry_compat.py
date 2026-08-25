from __future__ import annotations

"""Core-owned compatibility contracts for legacy model inventory consumers.

This module is intentionally thin. Runtime/provider authority remains in
ProviderRegistryService; these data contracts exist only to remove Core's import
dependency on the old integration registry during convergence.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ai_karen_engine.core.model_runtime.runtime_registry_adapter import (
    RuntimeRegistryAdapter,
    get_registry,
)


@dataclass
class ModelMetadata:
    id: str
    name: str
    provider: str
    family: str = ""
    format: str = ""
    size: Optional[int] = None
    parameters: Optional[str] = None
    quantization: Optional[str] = None
    context_length: Optional[int] = None
    capabilities: Set[str] = field(default_factory=set)
    local_path: Optional[str] = None
    download_url: Optional[str] = None
    license: Optional[str] = None
    description: str = ""


@dataclass
class ProviderSpec:
    name: str
    requires_api_key: bool
    description: str = ""
    category: str = "LLM"
    capabilities: Set[str] = field(default_factory=set)


@dataclass
class RuntimeSpec:
    name: str
    description: str = ""
    family: List[str] = field(default_factory=list)
    supports: List[str] = field(default_factory=list)
    requires_gpu: bool = False
    memory_efficient: bool = False
    supports_streaming: bool = False
    supports_batching: bool = False
    priority: int = 50


@dataclass
class HealthStatus:
    status: str
    last_check: Optional[float] = None
    error_message: Optional[str] = None
    response_time: Optional[float] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "HealthStatus",
    "ModelMetadata",
    "ProviderSpec",
    "RuntimeRegistryAdapter",
    "RuntimeSpec",
    "get_registry",
]
