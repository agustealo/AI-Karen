from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.config.config_asset_loaders import load_model_runtime_discovery_config

from .local_model_discovery import discover_local_model_candidates
from .model_registry_writer import write_model_registry_cache
from .model_validation import validate_model_record

logger = get_logger(__name__)


class DiscoveryStatus(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class DiscoveryProgress:
    status: DiscoveryStatus
    total_scanned: int = 0
    total_models: int = 0  # Alias for total_scanned for compatibility
    discovered_models: int = 0
    validated_models: int = 0  # For model validation tracking
    skipped_models: int = 0
    last_path: Optional[str] = None
    message: str = ""
    current_operation: str = ""
    start_time: float = 0.0
    estimated_completion: Optional[float] = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ValueWrapper:
    value: str


@dataclass(frozen=True)
class DiscoveryModality:
    type: _ValueWrapper
    input_supported: bool = True
    output_supported: bool = True
    formats: tuple[str, ...] = field(default_factory=tuple)
    max_size: Optional[int] = None


@dataclass(frozen=True)
class DiscoveryMetadata:
    parameters: Optional[dict[str, Any]] = None
    quantization: Optional[str] = None
    memory_requirement: Optional[float] = None
    context_length: Optional[int] = None
    license: Optional[str] = None
    version: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    use_cases: tuple[str, ...] = field(default_factory=tuple)
    language_support: tuple[str, ...] = field(default_factory=tuple)
    specialized_domains: tuple[str, ...] = field(default_factory=tuple)
    supported_formats: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DiscoveryRequirements:
    min_ram_gb: float = 0.0
    recommended_ram_gb: float = 0.0
    min_vram_gb: Optional[float] = None
    recommended_vram_gb: Optional[float] = None
    cpu_cores: int = 1
    gpu_required: bool = False
    disk_space_gb: float = 0.0
    supported_platforms: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ModelSummary:
    model_id: str
    name: str
    display_name: str
    path: str
    relative_path: str
    model_format: str
    artifact_kind: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    compatible_runtimes: tuple[str, ...] = field(default_factory=tuple)
    preferred_runtime: str = "openai_compatible"
    compatibility_confidence: str = "external_only"
    model_type: str = "unknown"
    architectures: tuple[str, ...] = field(default_factory=tuple)
    tokenizer_present: bool = False
    weights_present: bool = False
    metadata_files: tuple[str, ...] = field(default_factory=tuple)
    quantization: Optional[str] = None
    dtype: Optional[str] = None
    max_context: Optional[int] = None
    size_bytes: int = 0
    estimated_vram_gb: Optional[float] = None
    adapter_only: bool = False
    base_model_ref: Optional[str] = None
    runtime_visible: bool = True
    system_reserved: bool = False
    security_flags: tuple[str, ...] = field(default_factory=tuple)
    runtime_notes: tuple[str, ...] = field(default_factory=tuple)
    _status: str = "available"

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "ModelSummary":
        return cls(
            model_id=str(record.get("model_id") or record.get("path") or record.get("display_name") or ""),
            name=str(record.get("name") or record.get("display_name") or record.get("model_id") or ""),
            display_name=str(record.get("display_name") or record.get("name") or record.get("model_id") or ""),
            path=str(record.get("path") or ""),
            relative_path=str(record.get("relative_path") or ""),
            model_format=str(record.get("model_format") or "unknown"),
            artifact_kind=str(record.get("artifact_kind") or "unknown"),
            capabilities=tuple(record.get("capabilities") or ()),
            compatible_runtimes=tuple(record.get("compatible_runtimes") or ()),
            preferred_runtime=str(record.get("preferred_runtime") or "openai_compatible"),
            compatibility_confidence=str(record.get("compatibility_confidence") or "external_only"),
            model_type=str(record.get("model_type") or "unknown"),
            architectures=tuple(record.get("architectures") or ()),
            tokenizer_present=bool(record.get("tokenizer_present", False)),
            weights_present=bool(record.get("weights_present", False)),
            metadata_files=tuple(record.get("metadata_files") or ()),
            quantization=record.get("quantization"),
            dtype=record.get("dtype"),
            max_context=record.get("max_context"),
            size_bytes=int(record.get("size_bytes") or 0),
            estimated_vram_gb=record.get("estimated_vram_gb"),
            adapter_only=bool(record.get("adapter_only", False)),
            base_model_ref=record.get("base_model_ref"),
            runtime_visible=bool(record.get("runtime_visible", True)),
            system_reserved=bool(record.get("system_reserved", False)),
            security_flags=tuple(record.get("security_flags") or ()),
            runtime_notes=tuple(record.get("runtime_notes") or ()),
            _status=str(record.get("status") or "available"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capabilities"] = list(self.capabilities)
        payload["compatible_runtimes"] = list(self.compatible_runtimes)
        payload["architectures"] = list(self.architectures)
        payload["metadata_files"] = list(self.metadata_files)
        payload["security_flags"] = list(self.security_flags)
        payload["runtime_notes"] = list(self.runtime_notes)
        payload["status"] = self.status.value
        return payload

    @property
    def id(self) -> str:
        return self.model_id

    @property
    def type(self) -> _ValueWrapper:
        if "embedding" in self.capabilities:
            value = "embedding"
        elif "reranking" in self.capabilities:
            value = "reranker"
        elif self.model_format == "gguf":
            value = "local_gguf"
        elif "external_endpoint" in self.capabilities:
            value = "openai_compatible"
        else:
            value = "transformers"
        return _ValueWrapper(value)

    @property
    def category(self) -> _ValueWrapper:
        if "embedding" in self.capabilities:
            return _ValueWrapper("embedding")
        if "reranking" in self.capabilities:
            return _ValueWrapper("reranking")
        if self.model_format == "gguf":
            return _ValueWrapper("local")
        return _ValueWrapper("general")

    @property
    def modalities(self) -> list[DiscoveryModality]:
        formats = tuple(self.metadata_files)
        modality_type = "text"
        if "embedding" in self.capabilities:
            modality_type = "text"
        elif "vlm_helper" in self.capabilities:
            modality_type = "multimodal"
        return [DiscoveryModality(type=_ValueWrapper(modality_type), formats=formats)]

    @property
    def metadata(self) -> DiscoveryMetadata:
        description = " ".join(self.runtime_notes) or None
        memory_requirement = self.estimated_vram_gb
        return DiscoveryMetadata(
            quantization=self.quantization,
            memory_requirement=memory_requirement,
            context_length=self.max_context,
            description=description,
            use_cases=tuple(self.capabilities),
            supported_formats=tuple(self.compatible_runtimes),
        )

    @property
    def tags(self) -> list[str]:
        return list(self.capabilities)

    @property
    def specialization(self) -> list[_ValueWrapper]:
        specializations: list[str] = []
        if "embedding" in self.capabilities:
            specializations.append("embedding")
        if "reranking" in self.capabilities:
            specializations.append("reranking")
        if "classification" in self.capabilities:
            specializations.append("classification")
        return [_ValueWrapper(value) for value in specializations]

    @property
    def status_obj(self) -> _ValueWrapper:
        return _ValueWrapper(self._status)

    @property
    def status(self) -> _ValueWrapper:
        return _ValueWrapper(self._status)

    @property
    def size(self) -> int:
        return int(self.size_bytes)

    @property
    def requirements(self) -> DiscoveryRequirements:
        disk_space_gb = round(self.size_bytes / (1024 ** 3), 2) if self.size_bytes else 0.0
        return DiscoveryRequirements(
            recommended_vram_gb=self.estimated_vram_gb,
            disk_space_gb=disk_space_gb,
            supported_platforms=("linux", "windows", "macos"),
        )


class ModelDiscoveryService:
    """Core-owned discovery authority for local runtime metadata."""

    def __init__(self, discovery_config: Mapping[str, Any] | None = None) -> None:
        self._config = dict(discovery_config or load_model_runtime_discovery_config())
        self._models: list[ModelSummary] = []
        self._status = DiscoveryStatus.IDLE
        self._progress = DiscoveryProgress(status=DiscoveryStatus.IDLE)
        self._last_updated = 0.0
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()

    def _primary_root(self) -> Path:
        model_root = self._config.get("model_root")
        if model_root:
            return Path(str(model_root))
        roots = self._config.get("model_roots") or []
        if roots:
            return Path(str(roots[0]))
        return Path("models")

    def _scan(self) -> list[ModelSummary]:
        records = discover_local_model_candidates(self._primary_root(), self._config)
        summaries: list[ModelSummary] = []
        skipped = 0
        for record in records:
            validation = validate_model_record(record, self._config)
            if not validation.valid:
                skipped += 1
                record = dict(record)
                record["status"] = "degraded"
                record["security_flags"] = list(sorted(set(record.get("security_flags") or []) | set(validation.security_flags)))
            elif validation.warnings:
                record = dict(record)
                record["status"] = "degraded"
                record["security_flags"] = list(sorted(set(record.get("security_flags") or []) | set(validation.security_flags)))
            summaries.append(ModelSummary.from_record(record))

        summaries.sort(key=lambda item: (item.model_format, item.display_name.lower()))
        self._progress = DiscoveryProgress(
            status=DiscoveryStatus.READY if summaries else DiscoveryStatus.DEGRADED,
            total_scanned=len(records),
            discovered_models=len(summaries),
            skipped_models=skipped,
            last_path=summaries[-1].path if summaries else None,
            message="Discovery completed" if summaries else "No local models discovered",
        )
        self._status = self._progress.status
        self._last_updated = time.time()
        self._models = summaries

        try:
            write_model_registry_cache([summary.to_dict() for summary in summaries], self._config)
        except Exception as exc:  # pragma: no cover - cache persistence is best-effort
            logger.debug("Model registry cache write skipped: %s", exc)

        return summaries

    async def discover_all_models(self, force_refresh: bool = False) -> list[ModelSummary]:
        with self._lock:
            if self._models and not force_refresh:
                return list(self._models)
            self._status = DiscoveryStatus.SCANNING
            self._progress = DiscoveryProgress(status=DiscoveryStatus.SCANNING)

        return self._scan()

    def get_all_models(self, force_refresh: bool = False) -> list[ModelSummary]:
        if self._models and not force_refresh:
            return list(self._models)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.discover_all_models(force_refresh=force_refresh))
        
        # If in an event loop but models are empty, do a synchronous blocking scan
        # (This avoids returning empty if the background scan hasn't run yet)
        if not self._models:
             return self._scan()
        return list(self._models)

    async def get_all_models_async(self, force_refresh: bool = False) -> list[ModelSummary]:
        if self._models and not force_refresh:
            return list(self._models)
        return await self.discover_all_models(force_refresh=force_refresh)

    async def get_models_async(
        self,
        *,
        model_format: str | None = None,
        runtime: str | None = None,
        capability: str | None = None,
    ) -> list[ModelSummary]:
        models = await self.get_all_models_async()
        if model_format:
            model_format = model_format.lower()
            models = [item for item in models if item.model_format.lower() == model_format]
        if runtime:
            runtime = runtime.lower()
            # Handle aliases for filtering
            target_runtimes = {runtime}
            if runtime == "builtin_transformers":
                target_runtimes.add("transformers_direct")
            
            models = [item for item in models if any(rt.lower() in target_runtimes for rt in item.compatible_runtimes)]
        if runtime in {"vllm", "transformers_direct", "builtin_transformers"}:
            models = [item for item in models if item.runtime_visible and item.weights_present]
        if capability:
            capability = capability.lower()
            models = [item for item in models if capability in {entry.lower() for entry in item.capabilities}]
        return models

    def get_models(
        self,
        *,
        model_format: str | None = None,
        runtime: str | None = None,
        capability: str | None = None,
    ) -> list[ModelSummary]:
        models = self.get_all_models()
        if model_format:
            model_format = model_format.lower()
            models = [item for item in models if item.model_format.lower() == model_format]
        if runtime:
            runtime = runtime.lower()
            # Handle aliases for filtering
            target_runtimes = {runtime}
            if runtime == "builtin_transformers":
                target_runtimes.add("transformers_direct")
            
            models = [item for item in models if any(rt.lower() in target_runtimes for rt in item.compatible_runtimes)]
        if runtime in {"vllm", "transformers_direct", "builtin_transformers"}:
            models = [item for item in models if item.runtime_visible and item.weights_present]
        if capability:
            capability = capability.lower()
            models = [item for item in models if capability in {entry.lower() for entry in item.capabilities}]
        return models

    def get_model(self, model_id: str) -> Optional[ModelSummary]:
        model_id = str(model_id or "").strip()
        if not model_id:
            return None
        for model in self.get_all_models():
            if model.model_id == model_id or model.name == model_id or model.display_name == model_id:
                return model
        return None

    def search_models(
        self,
        query: str = "",
        category: str | None = None,
        model_type: str | None = None,
        modality: str | None = None,
        specialization: str | None = None,
        tags: Iterable[str] | None = None,
        max_size_gb: float | None = None,
    ) -> list[ModelSummary]:
        query = str(query or "").strip().lower()
        tags = {str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()}
        models = self.get_all_models()

        def matches(model: ModelSummary) -> bool:
            haystack = " ".join(
                [
                    model.model_id,
                    model.name,
                    model.display_name,
                    model.model_format,
                    model.artifact_kind,
                    " ".join(model.capabilities),
                    " ".join(model.security_flags),
                ]
            ).lower()
            if query and query not in haystack:
                return False
            if category and model.category.value.lower() != str(category).lower():
                return False
            if model_type and model.type.value.lower() != str(model_type).lower():
                return False
            if modality:
                if modality.lower() not in {item.type.value.lower() for item in model.modalities}:
                    return False
            if specialization:
                if specialization.lower() not in {item.value.lower() for item in model.specialization}:
                    return False
            if tags and not tags.issubset({tag.lower() for tag in model.tags}):
                return False
            if max_size_gb is not None and (model.size_bytes / (1024 ** 3)) > max_size_gb:
                return False
            return True

        return [model for model in models if matches(model)]

    async def get_recommended_models(
        self,
        use_case: str,
        max_models: int = 5,
    ) -> list[tuple[ModelSummary, float]]:
        use_case = str(use_case or "").strip().lower()
        scored: list[tuple[ModelSummary, float]] = []
        for model in self.get_all_models():
            score = 0.5
            caps = {cap.lower() for cap in model.capabilities}
            if use_case in caps:
                score += 0.3
            if use_case and use_case in " ".join(model.runtime_notes).lower():
                score += 0.1
            scored.append((model, min(score, 1.0)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:max_models]

    async def refresh_model_discovery(self) -> DiscoveryProgress:
        async with self._async_lock:
            if self._status == DiscoveryStatus.SCANNING:
                return self._progress
                
            self._status = DiscoveryStatus.SCANNING
            self._progress = DiscoveryProgress(status=DiscoveryStatus.SCANNING, start_time=time.time())
            self._models = []
            
        # Run scan in thread pool
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._scan)
        except Exception as e:
            logger.error(f"Async model scan failed: {e}")
            self._status = DiscoveryStatus.ERROR
            self._progress = DiscoveryProgress(status=DiscoveryStatus.ERROR, message=str(e))
            
        return self._progress

    def get_discovery_progress(self) -> DiscoveryProgress:
        return self._progress

    def get_discovery_statistics(self) -> dict[str, Any]:
        models = self.get_all_models()
        by_format = Counter(model.model_format for model in models)
        by_runtime: dict[str, int] = defaultdict(int)
        by_capability: dict[str, int] = defaultdict(int)
        for model in models:
            for runtime in model.compatible_runtimes:
                by_runtime[runtime] += 1
            for capability in model.capabilities:
                by_capability[capability] += 1
        return {
            "status": self._status.value,
            "discovery_status": self._status.value,
            "total_models": len(models),
            "formats": dict(by_format),
            "runtimes": dict(by_runtime),
            "capabilities": dict(by_capability),
            "categories": dict(Counter(model.category.value for model in models)),
            "types": dict(Counter(model.type.value for model in models)),
            "specializations": dict(Counter(spec.value for model in models for spec in model.specialization)),
            "last_discovery_time": self._last_updated,
            "progress": asdict(self._progress),
        }


_MODEL_DISCOVERY_SERVICE: ModelDiscoveryService | None = None


def get_model_discovery_service() -> ModelDiscoveryService:
    global _MODEL_DISCOVERY_SERVICE
    if _MODEL_DISCOVERY_SERVICE is None:
        _MODEL_DISCOVERY_SERVICE = ModelDiscoveryService()
    return _MODEL_DISCOVERY_SERVICE


def initialize_model_discovery_service(
    discovery_config: Mapping[str, Any] | None = None,
) -> ModelDiscoveryService:
    global _MODEL_DISCOVERY_SERVICE
    _MODEL_DISCOVERY_SERVICE = ModelDiscoveryService(discovery_config)
    return _MODEL_DISCOVERY_SERVICE
