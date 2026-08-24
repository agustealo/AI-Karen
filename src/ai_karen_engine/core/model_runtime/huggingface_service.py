"""
HuggingFace Hub Integration Service

This module provides integration with HuggingFace Hub for model search, download,
and management. It includes advanced filtering, training compatibility detection,
and automatic integration with the local model store.

Key Features:
- Model search and browsing with advanced filtering (including training filters)
- Training compatibility detection and hardware estimation
- Download management with progress tracking and resume capability
- Automatic format detection and registration with local model store
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import HuggingFace libraries with graceful fallback
try:
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    from huggingface_hub.utils import RepositoryNotFoundError, RevisionNotFoundError
    HF_AVAILABLE = True
except ImportError:
    logger.warning("HuggingFace Hub library not available. Install with: pip install huggingface_hub")
    HfApi = None
    hf_hub_download = None
    snapshot_download = None
    RepositoryNotFoundError = Exception
    RevisionNotFoundError = Exception
    HF_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    logger.warning("Requests library not available. Install with: pip install requests")
    requests = None
    REQUESTS_AVAILABLE = False

# -----------------------------
# Data Models
# -----------------------------

@dataclass
class ModelFilters:
    """Filters for model search."""
    tags: Optional[List[str]] = None
    family: Optional[str] = None  # llama, mistral, etc.
    quantization: Optional[str] = None  # Q4_K_M, fp16, etc.
    min_downloads: Optional[int] = None
    max_size: Optional[int] = None  # in bytes
    license: Optional[str] = None
    language: Optional[str] = None
    task: Optional[str] = None  # text-generation, text-classification, etc.
    library: Optional[str] = None  # transformers, gguf, etc.
    sort_by: str = "downloads"  # downloads, created_at, updated_at
    sort_order: str = "desc"  # asc, desc

@dataclass
class TrainingFilters:
    """Filters for trainable model search."""
    supports_fine_tuning: bool = True
    supports_lora: bool = False
    supports_full_training: bool = False
    min_parameters: Optional[str] = None  # "1B", "7B", etc.
    max_parameters: Optional[str] = None
    hardware_requirements: Optional[str] = None  # "cpu", "gpu", "multi-gpu"
    training_frameworks: List[str] = field(default_factory=list)  # ["transformers", "peft"]
    memory_requirements: Optional[int] = None  # in GB

@dataclass
class HFModel:
    """HuggingFace model information."""
    id: str
    name: str
    author: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    downloads: int = 0
    likes: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    library_name: Optional[str] = None
    pipeline_tag: Optional[str] = None
    license: Optional[str] = None
    files: List[Dict[str, Any]] = field(default_factory=list)
    size: Optional[int] = None  # Total size in bytes
    
    # Inferred metadata
    family: Optional[str] = None
    parameters: Optional[str] = None
    quantization: Optional[str] = None
    format: Optional[str] = None
    
    def __post_init__(self):
        """Extract metadata from model info."""
        self._infer_metadata()
    
    def _infer_metadata(self):
        """Infer model metadata from name and tags."""
        name_lower = self.id.lower()
        
        # Infer family
        families = {
            "codellama": ["codellama", "code-llama"],
            "llama": ["llama", "alpaca", "vicuna"],
            "mistral": ["mistral", "mixtral"],
            "qwen": ["qwen", "qwen2"],
            "phi": ["phi", "phi-2", "phi-3"],
            "gemma": ["gemma"],
            "bert": ["bert", "distilbert", "roberta"],
            "gpt": ["gpt", "gpt2", "gpt-neo", "gpt-j"]
        }
        
        for family, patterns in families.items():
            if any(pattern in name_lower for pattern in patterns):
                self.family = family
                break
        
        # Infer parameters
        param_patterns = ["1b", "3b", "7b", "13b", "30b", "65b", "70b", "175b"]
        for pattern in param_patterns:
            if pattern in name_lower:
                self.parameters = pattern.upper()
                break
        
        # Infer quantization
        quant_patterns = ["q2_k", "q3_k", "q4_k_m", "q5_k_m", "q6_k", "q8_0", "iq2_m", "iq3_m", "fp16", "bf16", "int8", "int4"]
        for pattern in quant_patterns:
            if (pattern in name_lower or 
                any(pattern in tag.lower() for tag in self.tags) or
                any(pattern in f.get("rfilename", "").lower() for f in self.files)):
                self.quantization = pattern.upper()
                break
        
        # Infer format
        if any("gguf" in tag.lower() for tag in self.tags) or any(f.get("rfilename", "").endswith(".gguf") for f in self.files):
            self.format = "gguf"
        elif any("safetensors" in tag.lower() for tag in self.tags) or any(f.get("rfilename", "").endswith(".safetensors") for f in self.files):
            self.format = "safetensors"
        elif any(f.get("rfilename", "").endswith(".bin") for f in self.files):
            self.format = "bin"

@dataclass
class TrainableModel(HFModel):
    """Extended model info with training capabilities."""
    supports_fine_tuning: bool = False
    supports_lora: bool = False
    supports_full_training: bool = False
    training_frameworks: List[str] = field(default_factory=list)
    hardware_requirements: Dict[str, Any] = field(default_factory=dict)
    memory_requirements: Optional[int] = None
    training_complexity: str = "unknown"  # "easy", "medium", "hard"
    
    def __post_init__(self):
        """Infer training capabilities from model metadata."""
        super().__post_init__()
        self._infer_training_capabilities()
    
    def _infer_training_capabilities(self):
        """Infer training capabilities from model info."""
        training_friendly_families = {
            "llama", "mistral", "qwen", "phi", "gemma", "bert", "roberta", "t5", "gpt"
        }
        
        if self.family and self.family.lower() in training_friendly_families:
            self.supports_fine_tuning = True
            self.supports_lora = True
            
            if self.parameters:
                param_num = self._extract_parameter_count(self.parameters)
                if param_num and param_num <= 7:  # 7B or smaller
                    self.supports_full_training = True
        
        if any("transformers" in tag.lower() for tag in self.tags):
            self.training_frameworks.append("transformers")
        if any("peft" in tag.lower() or "lora" in tag.lower() for tag in self.tags):
            self.training_frameworks.append("peft")
        
        if self.parameters:
            param_count = self._extract_parameter_count(self.parameters)
            if param_count:
                if param_count <= 1:
                    self.hardware_requirements = {"min_gpu_memory": 4, "recommended": "cpu"}
                    self.training_complexity = "easy"
                elif param_count <= 7:
                    self.hardware_requirements = {"min_gpu_memory": 16, "recommended": "gpu"}
                    self.training_complexity = "medium"
                else:
                    self.hardware_requirements = {"min_gpu_memory": 40, "recommended": "multi-gpu"}
                    self.training_complexity = "hard"
                
                self.memory_requirements = self.hardware_requirements.get("min_gpu_memory")
    
    def _extract_parameter_count(self, param_str: str) -> Optional[float]:
        """Extract numeric parameter count from string like '7B'."""
        try:
            param_str = param_str.upper().strip()
            if param_str.endswith("B"):
                return float(param_str.replace("B", ""))
            elif param_str.endswith("M"):
                return float(param_str.replace("M", "")) / 1000
            return float(param_str)
        except:
            return None

@dataclass
class ModelInfo:
    """Detailed model information."""
    id: str
    name: str
    description: str
    tags: List[str]
    files: List[Dict[str, Any]]
    config: Dict[str, Any] = field(default_factory=dict)
    readme: str = ""
    license: Optional[str] = None
    size: int = 0
    downloads: int = 0
    likes: int = 0

@dataclass
class CompatibilityReport:
    """Model compatibility report."""
    is_compatible: bool
    compatibility_score: float  # 0.0 to 1.0
    supported_operations: List[str]
    hardware_requirements: Dict[str, Any]
    framework_compatibility: Dict[str, bool]
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

@dataclass
class DeviceCapabilities:
    """Device capabilities for optimal artifact selection."""
    has_gpu: bool = False
    gpu_memory: Optional[int] = None  # in MB
    cpu_memory: Optional[int] = None  # in MB
    supports_fp16: bool = False
    supports_int8: bool = False
    supports_int4: bool = False

@dataclass
class DownloadJob:
    """Download job information."""
    id: str
    model_id: str
    artifact: Optional[str] = None
    status: str = "queued"  # queued, downloading, completed, failed, cancelled, paused
    progress: float = 0.0
    total_size: Optional[int] = None
    downloaded_size: int = 0
    speed: Optional[float] = None  # bytes per second
    eta: Optional[float] = None  # seconds
    error: Optional[str] = None
    local_path: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    # Control flags
    _cancelled: bool = False
    _paused: bool = False
    
    # Enhanced metadata (formerly from EnhancedDownloadJob)
    compatibility_report: Optional[CompatibilityReport] = None
    selected_artifacts: List[str] = field(default_factory=list)
    conversion_needed: bool = False
    post_download_actions: List[str] = field(default_factory=list)

# -----------------------------
# HuggingFace Service Implementation
# -----------------------------

class HuggingFaceService:
    """
    Unified service for interacting with HuggingFace Hub.
    """
    
    def __init__(self, cache_dir: Optional[str] = None, token: Optional[str] = None):
        self.cache_dir = Path(cache_dir or self._get_default_cache_dir())
        self.token = token
        self._lock = threading.RLock()
        
        # Initialize HF API if available
        if HF_AVAILABLE:
            self.api = HfApi(token=token)
        else:
            self.api = None
            logger.warning("HuggingFace Hub not available - service will have limited functionality")
        
        # Download job management
        self._download_jobs: Dict[str, DownloadJob] = {}
        self._download_threads: Dict[str, threading.Thread] = {}
        
        # Compatibility cache
        self._compatibility_cache: Dict[str, CompatibilityReport] = {}
        
        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_default_cache_dir(self) -> str:
        home = Path.home()
        return str(home / ".cache" / "huggingface")
    
    # ---------- Model Search ----------
    
    def search_models(self, 
                     query: str = "",
                     filters: Optional[ModelFilters] = None,
                     limit: int = 50) -> List[HFModel]:
        if not self.api:
            return []
        
        filters = filters or ModelFilters()
        
        try:
            search_params = {
                "search": query if query else None,
                "limit": limit,
                "sort": filters.sort_by,
                "direction": -1 if filters.sort_order == "desc" else 1,
                "task": filters.task,
                "library": filters.library,
            }
            
            if filters.tags:
                search_params["tags"] = filters.tags
            
            search_params = {k: v for k, v in search_params.items() if v is not None}
            models = list(self.api.list_models(**search_params))
            
            hf_models = []
            for model in models:
                try:
                    hf_model = self._convert_to_hf_model(model)
                    if self._passes_filters(hf_model, filters):
                        hf_models.append(hf_model)
                except Exception as e:
                    logger.debug(f"Failed to convert model {getattr(model, 'id', 'unknown')}: {e}")
                    continue
            
            return hf_models
            
        except Exception as e:
            logger.error(f"Failed to search models: {e}")
            return []

    def search_trainable_models(self, 
                               query: str = "",
                               filters: Optional[TrainingFilters] = None,
                               limit: int = 50) -> List[TrainableModel]:
        if not self.api:
            return []
        
        filters = filters or TrainingFilters()
        
        try:
            search_params = {
                "search": query if query else None,
                "limit": limit * 2,
                "sort": "downloads",
                "direction": -1,
                "task": "text-generation",
                "library": "transformers"
            }
            
            training_tags = ["pytorch", "safetensors"]
            if filters.supports_lora:
                training_tags.append("peft")
            
            search_params["tags"] = training_tags
            search_params = {k: v for k, v in search_params.items() if v is not None}
            
            models = list(self.api.list_models(**search_params))
            
            trainable_models = []
            for model in models:
                try:
                    trainable_model = self._convert_to_trainable_model(model)
                    if self._passes_training_filters(trainable_model, filters):
                        trainable_models.append(trainable_model)
                        
                    if len(trainable_models) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Failed to convert model {getattr(model, 'id', 'unknown')}: {e}")
                    continue
            
            return trainable_models
            
        except Exception as e:
            logger.error(f"Failed to search trainable models: {e}")
            return []
    
    def _convert_to_hf_model(self, model) -> HFModel:
        files = []
        total_size = 0
        
        try:
            if hasattr(model, 'siblings') and model.siblings:
                for sibling in model.siblings:
                    file_info = {
                        "rfilename": sibling.rfilename,
                        "size": getattr(sibling, 'size', 0) or 0
                    }
                    files.append(file_info)
                    total_size += file_info["size"]
        except Exception:
            pass
        
        return HFModel(
            id=model.id,
            name=model.id.split("/")[-1] if "/" in model.id else model.id,
            author=model.id.split("/")[0] if "/" in model.id else None,
            description=getattr(model, 'description', None) or "",
            tags=getattr(model, 'tags', []) or [],
            downloads=getattr(model, 'downloads', 0) or 0,
            likes=getattr(model, 'likes', 0) or 0,
            created_at=getattr(model, 'created_at', None),
            updated_at=getattr(model, 'last_modified', None),
            library_name=getattr(model, 'library_name', None),
            pipeline_tag=getattr(model, 'pipeline_tag', None),
            license=getattr(model, 'license', None),
            files=files,
            size=total_size
        )

    def _convert_to_trainable_model(self, model) -> TrainableModel:
        hf_model = self._convert_to_hf_model(model)
        return TrainableModel(
            id=hf_model.id,
            name=hf_model.name,
            author=hf_model.author,
            description=hf_model.description,
            tags=hf_model.tags,
            downloads=hf_model.downloads,
            likes=hf_model.likes,
            created_at=hf_model.created_at,
            updated_at=hf_model.updated_at,
            library_name=hf_model.library_name,
            pipeline_tag=hf_model.pipeline_tag,
            license=hf_model.license,
            files=hf_model.files,
            size=hf_model.size,
            family=hf_model.family,
            parameters=hf_model.parameters,
            quantization=hf_model.quantization,
            format=hf_model.format
        )
    
    def _passes_filters(self, model: HFModel, filters: ModelFilters) -> bool:
        if filters.family and model.family != filters.family:
            return False
        if filters.quantization and model.quantization != filters.quantization:
            return False
        if filters.min_downloads and model.downloads < filters.min_downloads:
            return False
        if filters.max_size and model.size and model.size > filters.max_size:
            return False
        if filters.license and model.license != filters.license:
            return False
        return True

    def _passes_training_filters(self, model: TrainableModel, filters: TrainingFilters) -> bool:
        if filters.supports_fine_tuning and not model.supports_fine_tuning:
            return False
        if filters.supports_lora and not model.supports_lora:
            return False
        if filters.supports_full_training and not model.supports_full_training:
            return False
        
        if filters.min_parameters or filters.max_parameters:
            param_count = model._extract_parameter_count(model.parameters or "")
            if param_count:
                if filters.min_parameters:
                    min_count = model._extract_parameter_count(filters.min_parameters)
                    if min_count and param_count < min_count:
                        return False
                if filters.max_parameters:
                    max_count = model._extract_parameter_count(filters.max_parameters)
                    if max_count and param_count > max_count:
                        return False
        
        if filters.memory_requirements and model.memory_requirements:
            if model.memory_requirements > filters.memory_requirements:
                return False
        
        if filters.training_frameworks:
            if not any(fw in model.training_frameworks for fw in filters.training_frameworks):
                return False
        
        return True
    
    # ---------- Model Information ----------
    
    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        if not self.api:
            return None
        
        try:
            model = self.api.model_info(model_id)
            files = []
            total_size = 0
            
            if hasattr(model, 'siblings') and model.siblings:
                for sibling in model.siblings:
                    file_info = {
                        "rfilename": sibling.rfilename,
                        "size": getattr(sibling, 'size', 0) or 0,
                        "lfs": getattr(sibling, 'lfs', None)
                    }
                    files.append(file_info)
                    total_size += file_info["size"]
            
            config = {}
            try:
                config_content = self.api.hf_hub_download(repo_id=model_id, filename="config.json")
                with open(config_content, 'r') as f:
                    config = json.load(f)
            except Exception:
                pass
            
            readme = ""
            try:
                readme_content = self.api.hf_hub_download(repo_id=model_id, filename="README.md")
                with open(readme_content, 'r') as f:
                    readme = f.read()
            except Exception:
                pass
            
            return ModelInfo(
                id=model_id,
                name=model_id.split("/")[-1] if "/" in model_id else model_id,
                description=getattr(model, 'description', '') or '',
                tags=getattr(model, 'tags', []) or [],
                files=files,
                config=config,
                readme=readme,
                license=getattr(model, 'license', None),
                size=total_size,
                downloads=getattr(model, 'downloads', 0) or 0,
                likes=getattr(model, 'likes', 0) or 0
            )
            
        except (RepositoryNotFoundError, RevisionNotFoundError):
            return None
        except Exception as e:
            logger.error(f"Failed to get model info for {model_id}: {e}")
            return None

    # ---------- Compatibility Detection ----------

    def check_training_compatibility(self, model_id: str) -> CompatibilityReport:
        """Check training compatibility for a model."""
        if model_id in self._compatibility_cache:
            return self._compatibility_cache[model_id]
        
        try:
            model_info = self.get_model_info(model_id)
            if not model_info:
                return CompatibilityReport(False, 0.0, [], {}, {}, ["Model not found"])
            
            report = self._analyze_model_compatibility(model_info)
            self._compatibility_cache[model_id] = report
            return report
            
        except Exception as e:
            logger.error(f"Failed to check compatibility for {model_id}: {e}")
            return CompatibilityReport(False, 0.0, [], {}, {}, [f"Check failed: {str(e)}"])

    def _analyze_model_compatibility(self, model_info: ModelInfo) -> CompatibilityReport:
        supported_operations = []
        framework_compatibility = {}
        warnings = []
        recommendations = []
        compatibility_score = 0.0
        
        has_config = bool(model_info.config)
        has_safetensors = any(f["rfilename"].endswith(".safetensors") for f in model_info.files)
        has_pytorch = any(f["rfilename"].endswith(".bin") for f in model_info.files)
        
        if has_config:
            compatibility_score += 0.3
            framework_compatibility["transformers"] = True
            supported_operations.append("inference")
            
            arch = model_info.config.get("architectures", [])
            training_friendly_archs = {
                "LlamaForCausalLM", "MistralForCausalLM", "Qwen2ForCausalLM",
                "PhiForCausalLM", "GemmaForCausalLM", "BertForSequenceClassification"
            }
            
            if any(a in training_friendly_archs for a in arch):
                compatibility_score += 0.4
                supported_operations.extend(["fine_tuning", "lora"])
                framework_compatibility["peft"] = True
                
                if model_info.size < 15 * 1024 * 1024 * 1024:
                    supported_operations.append("full_training")
                    compatibility_score += 0.2
        
        if has_safetensors:
            compatibility_score += 0.1
            recommendations.append("SafeTensors format detected - optimal for training")
        elif has_pytorch:
            warnings.append("PyTorch .bin format detected - consider converting to SafeTensors")
        
        hardware_requirements = self._estimate_hardware_requirements(model_info)
        
        if model_info.license:
            if model_info.license.lower() in ["apache-2.0", "mit", "bsd"]:
                compatibility_score += 0.1
            elif "cc-by" in model_info.license.lower():
                warnings.append("Creative Commons license - check terms for commercial use")
        
        is_compatible = compatibility_score >= 0.5 and len(supported_operations) > 0
        
        return CompatibilityReport(
            is_compatible=is_compatible,
            compatibility_score=min(compatibility_score, 1.0),
            supported_operations=supported_operations,
            hardware_requirements=hardware_requirements,
            framework_compatibility=framework_compatibility,
            warnings=warnings,
            recommendations=recommendations
        )

    def _estimate_hardware_requirements(self, model_info: ModelInfo) -> Dict[str, Any]:
        size = model_info.size
        if size < 2 * 1024 * 1024 * 1024:
            return {"min_gpu_memory": 4, "gpu_required": False}
        elif size < 15 * 1024 * 1024 * 1024:
            return {"min_gpu_memory": 16, "gpu_required": True}
        else:
            return {"min_gpu_memory": 40, "gpu_required": True, "multi_gpu_beneficial": True}
    
    # ---------- Artifact Selection ----------
    
    def select_optimal_artifact(self, 
                               files: List[Dict[str, Any]], 
                               preference: str = "auto",
                               device_caps: Optional[DeviceCapabilities] = None) -> Optional[Dict[str, Any]]:
        if not files: return None
        device_caps = device_caps or self._detect_device_capabilities()
        
        gguf_files = [f for f in files if f.get("rfilename", "").endswith(".gguf")]
        safetensors_files = [f for f in files if f.get("rfilename", "").endswith(".safetensors")]
        bin_files = [f for f in files if f.get("rfilename", "").endswith(".bin")]
        
        if preference == "gguf" and gguf_files: return self._select_best_gguf(gguf_files, device_caps)
        if preference == "safetensors" and safetensors_files: return self._select_best_safetensors(safetensors_files, device_caps)
        if preference == "bin" and bin_files: return self._select_best_bin(bin_files, device_caps)
        
        if preference == "auto":
            if not device_caps.has_gpu and gguf_files: return self._select_best_gguf(gguf_files, device_caps)
            if device_caps.has_gpu and safetensors_files: return self._select_best_safetensors(safetensors_files, device_caps)
        
        return max(files, key=lambda f: f.get("size", 0))
    
    def _select_best_gguf(self, gguf_files, caps):
        quant_priority = ["Q4_K_M", "Q5_K_M", "Q3_K", "Q8_0"]
        for q in quant_priority:
            for f in gguf_files:
                if q in f["rfilename"].upper(): return f
        return max(gguf_files, key=lambda f: f["size"])

    def _select_best_safetensors(self, files, caps):
        preferred = ["model.safetensors", "pytorch_model.safetensors"]
        for p in preferred:
            for f in files:
                if f["rfilename"] == p: return f
        return max(files, key=lambda f: f["size"])

    def _select_best_bin(self, files, caps):
        for f in files:
            if f["rfilename"] == "pytorch_model.bin": return f
        return max(files, key=lambda f: f["size"])

    # ---------- Download Management ----------
    
    def download_model(self, 
                      model_id: str, 
                      artifact: Optional[str] = None,
                      preference: str = "auto",
                      device_caps: Optional[DeviceCapabilities] = None,
                      setup_training: bool = False,
                      training_config: Optional[Dict[str, Any]] = None) -> DownloadJob:
        """Start downloading a model with optional training setup."""
        job_id = f"download_{model_id.replace('/', '_')}_{int(time.time())}"
        
        # Enhanced initialization logic if training is requested
        comp_report = None
        selected_artifacts = []
        post_actions = ["register_with_model_store"]
        
        if setup_training:
            comp_report = self.check_training_compatibility(model_id)
            if comp_report.is_compatible:
                post_actions.insert(0, "setup_training_environment")
                # Add more actions based on report...

        job = DownloadJob(
            id=job_id,
            model_id=model_id,
            artifact=artifact,
            compatibility_report=comp_report,
            post_download_actions=post_actions
        )
        
        with self._lock:
            self._download_jobs[job_id] = job
        
        thread = threading.Thread(
            target=self._download_worker,
            args=(job, preference, device_caps),
            daemon=True
        )
        
        with self._lock:
            self._download_threads[job_id] = thread
        
        thread.start()
        return job
    
    def _download_worker(self, job: DownloadJob, preference: str, device_caps: Optional[DeviceCapabilities]):
        try:
            job.status = "downloading"
            job.started_at = time.time()
            
            if not job.artifact:
                info = self.get_model_info(job.model_id)
                if not info: raise Exception("Model not found")
                opt = self.select_optimal_artifact(info.files, preference, device_caps)
                if not opt: raise Exception("No artifact found")
                job.artifact = opt["rfilename"]
                job.total_size = opt["size"]
            
            if not HF_AVAILABLE: raise Exception("hf_hub not available")
            
            local_path = hf_hub_download(
                repo_id=job.model_id,
                filename=job.artifact,
                cache_dir=str(self.cache_dir),
                token=self.token
            )
            
            job.local_path = local_path
            
            # Execute post-download actions
            self._execute_post_download_actions(job)
            
            job.status = "completed"
            job.completed_at = time.time()
            job.progress = 1.0
            
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = time.time()
            logger.error(f"Download failed for {job.id}: {e}")
        finally:
            with self._lock: self._download_threads.pop(job.id, None)

    def _execute_post_download_actions(self, job: DownloadJob):
        for action in job.post_download_actions:
            try:
                if action == "register_with_model_store":
                    self._register_downloaded_model(job)
                elif action == "setup_training_environment":
                    logger.info(f"Setting up training env for {job.model_id}")
            except Exception as e:
                logger.warning(f"Action {action} failed: {e}")

    def _register_downloaded_model(self, job: DownloadJob):
        try:
            from ai_karen_engine.core.model_runtime.model_store import (
                get_model_store,
                ModelDescriptor,
            )
            info = self.get_model_info(job.model_id)
            if not info: return

            descriptor = ModelDescriptor(
                id=f"hf_{job.model_id.replace('/', '_')}",
                name=info.name,
                family=self._infer_family_from_id(job.model_id),
                format=self._infer_format_from_artifact(job.artifact),
                size=job.total_size,
                source="huggingface",
                provider="huggingface",
                local_path=job.local_path,
                download_url=f"https://huggingface.co/{job.model_id}",
                description=info.description,
                tags=set(info.tags),
                metadata={
                    "compatibility_report": job.compatibility_report.__dict__ if job.compatibility_report else {}
                }
            )
            get_model_store().register_model(descriptor)
        except Exception as e:
            logger.warning(f"Registration failed: {e}")

    def _detect_device_capabilities(self) -> DeviceCapabilities:
        caps = DeviceCapabilities()
        try:
            import torch
            caps.has_gpu = torch.cuda.is_available()
            if caps.has_gpu:
                caps.gpu_memory = torch.cuda.get_device_properties(0).total_memory // (1024*1024)
        except ImportError: pass
        return caps

    def _infer_family_from_id(self, model_id: str) -> str:
        id_l = model_id.lower()
        mapping = {"llama": ["llama"], "mistral": ["mistral"], "phi": ["phi"], "gemma": ["gemma"]}
        for fam, pats in mapping.items():
            if any(p in id_l for p in pats): return fam
        return "unknown"

    def _infer_format_from_artifact(self, artifact: Optional[str]) -> str:
        if not artifact: return "unknown"
        ext_map = {".gguf": "gguf", ".safetensors": "safetensors", ".bin": "bin"}
        for ext, fmt in ext_map.items():
            if artifact.lower().endswith(ext): return fmt
        return "unknown"

    # ---------- Job Management ----------
    
    def get_download_job(self, job_id: str) -> Optional[DownloadJob]:
        with self._lock: return self._download_jobs.get(job_id)
    
    def list_download_jobs(self, status: Optional[str] = None) -> List[DownloadJob]:
        with self._lock: jobs = list(self._download_jobs.values())
        return [j for j in jobs if j.status == status] if status else jobs
    
    def cancel_download(self, job_id: str) -> bool:
        with self._lock:
            job = self._download_jobs.get(job_id)
            if not job or job.status in ["completed", "failed", "cancelled"]: return False
            job._cancelled = True
            job.status = "cancelled"
            job.completed_at = time.time()
            return True

# ---------- Global Service ----------

_global_service: Optional[HuggingFaceService] = None
_global_service_lock = threading.RLock()

def get_huggingface_service() -> HuggingFaceService:
    global _global_service
    if _global_service is None:
        with _global_service_lock:
            if _global_service is None:
                _global_service = HuggingFaceService()
    return _global_service

# For backward compatibility with EnhancedHuggingFaceService callers
def get_enhanced_huggingface_service() -> HuggingFaceService:
    return get_huggingface_service()

# Type alias for backward compatibility
EnhancedHuggingFaceService = HuggingFaceService

# Helper for download_with_training_setup
def download_with_training_setup(model_id: str, **kwargs) -> DownloadJob:
    return get_huggingface_service().download_model(model_id, setup_training=True, **kwargs)

__all__ = [
    "HuggingFaceService",
    "get_huggingface_service",
    "get_enhanced_huggingface_service",
    "EnhancedHuggingFaceService",
    "TrainableModel",
    "TrainingFilters",
    "ModelFilters",
    "HFModel",
    "DownloadJob",
    "download_with_training_setup"
]