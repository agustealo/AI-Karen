"""Enhanced HuggingFace discovery and training-compatibility service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import uuid

try:
    from huggingface_hub import HfApi
    HF_AVAILABLE = True
except Exception:  # pragma: no cover
    HfApi = None
    HF_AVAILABLE = False


@dataclass
class TrainingFilters:
    supports_fine_tuning: bool = True
    supports_lora: bool = False
    supports_full_training: bool = False
    min_parameters: Optional[str] = None
    max_parameters: Optional[str] = None
    memory_requirements: Optional[int] = None
    training_frameworks: List[str] = field(default_factory=list)


@dataclass
class TrainableModel:
    id: str
    name: str
    tags: List[str]
    downloads: int
    likes: int
    family: str = ""
    parameters: Optional[str] = None
    supports_fine_tuning: bool = False
    supports_lora: bool = False
    supports_full_training: bool = False
    training_complexity: str = "unknown"
    memory_requirements: int = 4
    training_frameworks: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._infer_training_capabilities()

    def _extract_parameter_count(self, text: str) -> Optional[float]:
        if not text:
            return None
        t = text.strip().upper()
        try:
            if t.endswith("B"):
                return float(t[:-1])
            if t.endswith("M"):
                return float(t[:-1]) / 1000.0
            return None
        except Exception:
            return None

    def _infer_training_capabilities(self) -> None:
        p = self._extract_parameter_count(self.parameters or "")
        family = (self.family or "").lower()
        tags = {t.lower() for t in self.tags}
        if family in {"llama", "gpt", "mistral", "qwen"} or "transformers" in tags or "pytorch" in tags:
            self.supports_fine_tuning = True
            self.supports_lora = True
            self.training_frameworks = ["transformers", "peft"]
        if p is not None:
            if p <= 2:
                self.training_complexity = "easy"
                self.memory_requirements = 4
                self.supports_full_training = True
            elif p <= 13:
                self.training_complexity = "medium"
                self.memory_requirements = 16
                self.supports_full_training = True
            else:
                self.training_complexity = "hard"
                self.memory_requirements = 40
                self.supports_full_training = False


@dataclass
class CompatibilityReport:
    is_compatible: bool
    compatibility_score: float
    supported_operations: List[str]
    hardware_requirements: Dict[str, Any]
    framework_compatibility: Dict[str, bool]
    warnings: List[str]
    recommendations: List[str]


@dataclass
class EnhancedDownloadJob:
    id: str
    model_id: str
    status: str
    progress: float
    selected_artifacts: List[str]
    conversion_needed: bool
    post_download_actions: List[str]
    compatibility_report: Optional[CompatibilityReport] = None


class EnhancedHuggingFaceService:
    def __init__(self) -> None:
        self.api = HfApi() if HF_AVAILABLE and HfApi else None
        self._compatibility_cache: Dict[str, CompatibilityReport] = {}

    def search_trainable_models(self, query: str, filters: Optional[TrainingFilters] = None, limit: int = 20) -> List[TrainableModel]:
        filters = filters or TrainingFilters()
        if not self.api:
            return []
        raw_models = list(self.api.list_models(search=query, task="text-generation", library="transformers", limit=limit))
        out: List[TrainableModel] = []
        for m in raw_models:
            model = TrainableModel(
                id=getattr(m, "id", ""),
                name=getattr(m, "id", ""),
                tags=list(getattr(m, "tags", []) or []),
                downloads=int(getattr(m, "downloads", 0) or 0),
                likes=int(getattr(m, "likes", 0) or 0),
                family=(getattr(m, "id", "").split('/')[0] if getattr(m, "id", "") else ""),
                parameters=self._infer_parameters_from_id(getattr(m, "id", "")),
            )
            if filters.supports_fine_tuning and not model.supports_fine_tuning:
                continue
            if filters.supports_lora and not model.supports_lora:
                continue
            if filters.memory_requirements and model.memory_requirements > filters.memory_requirements:
                continue
            out.append(model)
        return out[:limit]

    def _infer_parameters_from_id(self, model_id: str) -> Optional[str]:
        for token in ["70b", "34b", "13b", "7b", "3b", "1.3b", "117m"]:
            if token in model_id.lower():
                return token.upper()
        return None

    def get_model_info(self, model_id: str) -> Any:
        if self.api:
            try:
                return self.api.model_info(model_id)
            except Exception:
                pass
        class _Info:  # lightweight fallback
            config = {}
            files = []
            license = "unknown"
        return _Info()

    def _estimate_hardware_requirements(self, model_info: Any) -> Dict[str, Any]:
        files = getattr(model_info, "files", []) or []
        total_size = sum(int((f.get("size") if isinstance(f, dict) else getattr(f, "size", 0)) or 0) for f in files)
        gb = total_size / (1024**3)
        return {
            "model_size_gb": gb,
            "min_gpu_memory": 16 if gb >= 10 else 8,
            "gpu_required": gb >= 8,
            "multi_gpu_beneficial": gb >= 16,
        }

    def _select_training_artifacts(self, files: List[Dict[str, Any]], _compat: Any) -> List[str]:
        names = [f.get("rfilename", "") for f in files if isinstance(f, dict)]
        selected = []
        if any(n.endswith('.safetensors') for n in names):
            selected.extend([n for n in names if n.endswith('.safetensors')])
        elif any(n.endswith('.bin') for n in names):
            selected.extend([n for n in names if n.endswith('.bin')])
        selected.extend([n for n in names if n.endswith('.json')])
        return list(dict.fromkeys(selected))

    def _needs_conversion(self, files: List[Dict[str, Any]]) -> bool:
        names = [f.get("rfilename", "") for f in files if isinstance(f, dict)]
        return any(n.endswith('.bin') for n in names) and not any(n.endswith('.safetensors') for n in names)

    def check_training_compatibility(self, model_id: str) -> CompatibilityReport:
        if model_id in self._compatibility_cache:
            return self._compatibility_cache[model_id]

        model_info = self.get_model_info(model_id)
        files = getattr(model_info, "files", []) or []
        hw = self._estimate_hardware_requirements(model_info)
        is_compatible = bool(files) if files else False
        score = 0.8 if is_compatible else 0.0
        report = CompatibilityReport(
            is_compatible=is_compatible,
            compatibility_score=score,
            supported_operations=["fine_tuning", "lora"] if is_compatible else [],
            hardware_requirements=hw,
            framework_compatibility={"transformers": True, "peft": True},
            warnings=[] if is_compatible else ["Model metadata unavailable or incomplete"],
            recommendations=["Use SafeTensors format for optimal training"] if is_compatible else ["Verify model availability and metadata"],
        )
        self._compatibility_cache[model_id] = report
        return report

    def _start_enhanced_download(self, _job: EnhancedDownloadJob) -> None:
        return None

    def download_with_training_setup(self, model_id: str, setup_training: bool = True, training_config: Optional[Dict[str, Any]] = None) -> EnhancedDownloadJob:
        comp = self.check_training_compatibility(model_id)
        info = self.get_model_info(model_id)
        files = getattr(info, "files", []) or []
        selected = self._select_training_artifacts(files, comp)
        job = EnhancedDownloadJob(
            id=str(uuid.uuid4()),
            model_id=model_id,
            status="downloading",
            progress=0.0,
            selected_artifacts=selected,
            conversion_needed=self._needs_conversion(files),
            post_download_actions=["register_with_model_store"] + (["setup_training_environment"] if setup_training else []),
            compatibility_report=comp,
        )
        self._start_enhanced_download(job)
        return job


_service: Optional[EnhancedHuggingFaceService] = None


def get_enhanced_huggingface_service() -> EnhancedHuggingFaceService:
    global _service
    if _service is None:
        _service = EnhancedHuggingFaceService()
    return _service


__all__ = [
    "HF_AVAILABLE",
    "HfApi",
    "TrainingFilters",
    "TrainableModel",
    "CompatibilityReport",
    "EnhancedDownloadJob",
    "EnhancedHuggingFaceService",
    "get_enhanced_huggingface_service",
]
