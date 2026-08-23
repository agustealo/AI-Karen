from __future__ import annotations

"""Compatibility wrapper for the retired discovery engine.

The real discovery authority now lives in
``ai_karen_engine.core.model_runtime.model_discovery_service``.
This module remains only so legacy imports keep working while the rest of the
codebase migrates.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.model_runtime.model_discovery_service import (
    DiscoveryProgress,
    DiscoveryStatus,
    ModelDiscoveryService,
    ModelSummary,
    get_model_discovery_service,
    initialize_model_discovery_service,
)


class ModelType(str, Enum):
    LOCAL_GGUF = "local_gguf"
    TRANSFORMERS = "transformers"
    STABLE_DIFFUSION = "stable-diffusion"
    HUGGINGFACE = "huggingface"
    ONNX = "onnx"
    TENSORRT = "tensorrt"
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    UNKNOWN = "unknown"


class ModalityType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"


class ModelStatus(str, Enum):
    AVAILABLE = "available"
    LOADING = "loading"
    ERROR = "error"
    INCOMPATIBLE = "incompatible"
    MISSING_DEPENDENCIES = "missing_dependencies"


class ModelCategory(str, Enum):
    LANGUAGE = "language"
    VISION = "vision"
    AUDIO = "audio"
    MULTIMODAL = "multimodal"
    EMBEDDING = "embedding"
    CLASSIFICATION = "classification"


class ModelSpecialization(str, Enum):
    CHAT = "chat"
    CODE = "code"
    REASONING = "reasoning"
    CREATIVE = "creative"
    MEDICAL = "medical"
    LEGAL = "legal"
    TECHNICAL = "technical"
    GENERAL = "general"


@dataclass
class Modality:
    type: ModalityType
    input_supported: bool
    output_supported: bool
    formats: List[str]
    max_size: Optional[int] = None
    resolution_limits: Optional[Dict[str, int]] = None


@dataclass
class ResourceRequirements:
    min_ram_gb: float = 0.0
    recommended_ram_gb: float = 0.0
    min_vram_gb: Optional[float] = None
    recommended_vram_gb: Optional[float] = None
    cpu_cores: int = 1
    gpu_required: bool = False
    disk_space_gb: float = 0.0
    supported_platforms: List[str] = field(default_factory=list)


@dataclass
class ModelMetadata:
    name: str
    display_name: str
    description: str = ""
    version: str = ""
    author: str = ""
    license: str = ""
    context_length: int = 0
    parameter_count: Optional[int] = None
    quantization: Optional[str] = None
    architecture: Optional[str] = None
    training_data: Optional[str] = None
    supported_formats: List[str] = field(default_factory=list)
    use_cases: List[str] = field(default_factory=list)
    language_support: List[str] = field(default_factory=list)
    specialized_domains: List[str] = field(default_factory=list)
    performance_metrics: Optional[Dict[str, Any]] = None
    config_source: Optional[str] = None


@dataclass
class ModelInfo:
    id: str
    name: str
    display_name: str
    type: ModelType
    path: str
    size: int
    modalities: List[Modality]
    capabilities: List[str]
    requirements: ResourceRequirements
    status: ModelStatus
    metadata: ModelMetadata
    category: ModelCategory
    specialization: List[ModelSpecialization]
    tags: List[str]
    last_updated: float
    checksum: Optional[str] = None
    config_files: List[str] = field(default_factory=list)


class ModelDiscoveryEngine:
    """Legacy-compatible wrapper around the core model discovery service."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._service = get_model_discovery_service()

    async def discover_all_models(self) -> List[ModelSummary]:
        return await self._service.discover_all_models()

    def list_all_models(self) -> List[ModelSummary]:
        return self._service.get_all_models()

    def find_model(self, model_name: str) -> Optional[ModelSummary]:
        return self._service.get_model(model_name)

    def search_models(self, *args: Any, **kwargs: Any) -> List[ModelSummary]:
        return self._service.search_models(*args, **kwargs)

    def get_discovery_statistics(self) -> Dict[str, Any]:
        return self._service.get_discovery_statistics()

    def get_discovery_progress(self) -> DiscoveryProgress:
        return self._service.get_discovery_progress()

    async def get_recommended_models(self, *args: Any, **kwargs: Any):
        return await self._service.get_recommended_models(*args, **kwargs)

    async def refresh_model_discovery(self) -> DiscoveryProgress:
        return await self._service.refresh_model_discovery()


def list_models() -> List[ModelSummary]:
    return get_model_discovery_service().get_all_models()


def get_model_info(model_name: str) -> Optional[ModelSummary]:
    return get_model_discovery_service().get_model(model_name)


def get_model_discovery_engine() -> ModelDiscoveryEngine:
    return ModelDiscoveryEngine()


__all__ = [
    "DiscoveryProgress",
    "DiscoveryStatus",
    "ModelCategory",
    "ModelDiscoveryEngine",
    "ModelInfo",
    "ModelMetadata",
    "ModelSpecialization",
    "ModelStatus",
    "ModelSummary",
    "ModelType",
    "Modality",
    "ModalityType",
    "ResourceRequirements",
    "get_model_discovery_engine",
    "get_model_info",
    "list_models",
    "initialize_model_discovery_service",
]
