"""
Model Library Service

Provides comprehensive model management capabilities including:
- Model discovery and metadata management
- Download management with progress tracking
- Integration with existing model registry
- Predefined model configurations

This service extends the existing model registry to support remote model repositories
and provides a unified interface for model management operations.
"""

import json
import logging
import os
import hashlib
import requests
import time
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from urllib.parse import urlparse
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("kari.model_library_service")

@dataclass
class ModelInfo:
    """Model information structure."""
    id: str
    name: str
    provider: str
    size: int
    description: str
    capabilities: List[str]
    status: str  # 'available', 'downloading', 'local', 'error'
    download_progress: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    local_path: Optional[str] = None
    download_url: Optional[str] = None
    checksum: Optional[str] = None
    disk_usage: Optional[int] = None  # Actual disk usage in bytes
    last_used: Optional[float] = None  # Timestamp of last usage
    download_date: Optional[float] = None  # Timestamp when downloaded

@dataclass
class DownloadTask:
    """Download task information."""
    task_id: str
    model_id: str
    url: str
    filename: str
    total_size: int
    downloaded_size: int
    progress: float
    status: str  # 'pending', 'downloading', 'completed', 'failed', 'cancelled'
    error_message: Optional[str] = None
    start_time: Optional[float] = None
    estimated_time_remaining: Optional[float] = None

@dataclass
class ModelMetadata:
    """Detailed model metadata."""
    parameters: str
    quantization: str
    memory_requirement: str
    context_length: int
    license: str
    tags: List[str]
    architecture: Optional[str] = None
    training_data: Optional[str] = None
    performance_metrics: Optional[Dict[str, Any]] = None

class ModelDownloadManager:
    """Manages model downloads with progress tracking and resumption."""
    
    def __init__(self, download_dir: str = "models/downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.active_downloads: Dict[str, DownloadTask] = {}
        self.download_threads: Dict[str, threading.Thread] = {}
        self.executor = ThreadPoolExecutor(max_workers=3)
        self._lock = threading.Lock()
    
    def download_model(self, model_id: str, url: str, filename: str, 
                      progress_callback: Optional[Callable] = None) -> DownloadTask:
        """Initiate model download with progress tracking."""
        task_id = f"{model_id}_{int(time.time())}"
        
        # Create download task
        task = DownloadTask(
            task_id=task_id,
            model_id=model_id,
            url=url,
            filename=filename,
            total_size=0,
            downloaded_size=0,
            progress=0.0,
            status='pending',
            start_time=time.time()
        )
        
        with self._lock:
            self.active_downloads[task_id] = task
        
        # Start download in background
        thread = threading.Thread(
            target=self._download_worker,
            args=(task, progress_callback)
        )
        thread.daemon = True
        thread.start()
        
        self.download_threads[task_id] = thread
        
        return task
    
    def _download_worker(self, task: DownloadTask, progress_callback: Optional[Callable] = None):
        """Worker function for downloading models."""
        try:
            task.status = 'downloading'
            
            # Get file size
            response = requests.head(task.url, timeout=30)
            if response.status_code == 200:
                task.total_size = int(response.headers.get('content-length', 0))
            
            # Download file with progress tracking
            download_path = self.download_dir / task.filename
            temp_path = download_path.with_suffix('.tmp')
            
            # Check for existing partial download
            if temp_path.exists():
                task.downloaded_size = temp_path.stat().st_size
                headers = {'Range': f'bytes={task.downloaded_size}-'}
            else:
                headers = {}
            
            response = requests.get(task.url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            # Open file for writing (append if resuming)
            mode = 'ab' if temp_path.exists() else 'wb'
            
            with open(temp_path, mode) as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        task.downloaded_size += len(chunk)
                        
                        # Update progress
                        if task.total_size > 0:
                            task.progress = (task.downloaded_size / task.total_size) * 100
                            
                            # Estimate time remaining
                            elapsed = time.time() - task.start_time
                            if task.progress > 0:
                                total_estimated = elapsed * (100 / task.progress)
                                task.estimated_time_remaining = total_estimated - elapsed
                        
                        # Call progress callback
                        if progress_callback:
                            progress_callback(task)
                        
                        # Check for cancellation
                        if task.status == 'cancelled':
                            return
            
            # Move completed file to final location
            download_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.rename(download_path)
            
            task.status = 'completed'
            task.progress = 100.0
            
            logger.info(f"Successfully downloaded {task.model_id} to {download_path}")
            
        except Exception as e:
            task.status = 'failed'
            task.error_message = str(e)
            logger.error(f"Failed to download {task.model_id}: {e}")
        
        finally:
            # Clean up
            with self._lock:
                if task.task_id in self.download_threads:
                    del self.download_threads[task.task_id]
    
    def cancel_download(self, task_id: str) -> bool:
        """Cancel active download."""
        with self._lock:
            if task_id in self.active_downloads:
                task = self.active_downloads[task_id]
                task.status = 'cancelled'
                return True
        return False
    
    def get_download_status(self, task_id: str) -> Optional[DownloadTask]:
        """Get download task status."""
        with self._lock:
            return self.active_downloads.get(task_id)
    
    def cleanup_completed_downloads(self):
        """Clean up completed download tasks."""
        with self._lock:
            completed_tasks = [
                task_id for task_id, task in self.active_downloads.items()
                if task.status in ['completed', 'failed', 'cancelled']
            ]
            
            for task_id in completed_tasks:
                if task_id in self.active_downloads:
                    del self.active_downloads[task_id]

class ModelMetadataService:
    """Manages model metadata and capabilities information."""
    
    def __init__(self, cache_dir: str = "models/metadata_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_cache: Dict[str, ModelMetadata] = {}
        self.predefined_models = self._load_predefined_models()
    
    def _load_predefined_models(self) -> Dict[str, Dict[str, Any]]:
        """Load predefined model configurations."""
        return {
            "default-lightweight-model": {
                "id": "default-lightweight-model",
                "name": "Default Lightweight Chat Model",
                "provider": "local_gguf",
                "size": 520000000,  # ~520MB
                "description": "A compact Qwen3 language model optimized for chat applications with efficient quantization for fast local inference.",
                "capabilities": ["text-generation", "chat", "local-inference", "low-memory"],
                "metadata": ModelMetadata(
                    parameters="0.6B",
                    quantization="Q4_K_M",
                    memory_requirement="~1GB",
                    context_length=32768,
                    license="Apache 2.0",
                    tags=["chat", "small", "efficient", "quantized", "default"],
                    architecture="Qwen3",
                    training_data="Qwen pretraining and instruction-tuning corpus",
                    performance_metrics={
                        "inference_speed": "fast",
                        "memory_efficiency": "high",
                        "quality_score": "good"
                    }
                ),
                "download_url": "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf",
                "filename": "Qwen3-0.6B-Q4_K_M.gguf",
                "checksum": "sha256:placeholder_checksum_for_validation"
            },
            "default-instruct-model": {
                "id": "default-instruct-model",
                "name": "Default Instruct Model",
                "provider": "local_gguf",
                "size": 669000000,
                "description": "A compact model fine-tuned for instruction following with efficient quantization.",
                "capabilities": ["text-generation", "instruction-following", "local-inference", "low-memory"],
                "metadata": ModelMetadata(
                    parameters="1.1B",
                    quantization="Q4_K_M",
                    memory_requirement="~1GB",
                    context_length=2048,
                    license="Apache 2.0",
                    tags=["instruct", "small", "efficient", "quantized", "default"],
                    architecture="Llama",
                    training_data="General purpose instruction datasets",
                    performance_metrics={
                        "inference_speed": "fast",
                        "memory_efficiency": "high",
                        "instruction_following": "good"
                    }
                ),
                "download_url": "https://huggingface.co/TinyLlama/TinyLlama-1.1B-Instruct-v0.1-GGUF/resolve/main/tinyllama-1.1b-instruct-v0.1.Q4_K_M.gguf",
                "filename": "tinyllama-1.1b-instruct-v0.1.Q4_K_M.gguf",
                "checksum": "sha256:placeholder_checksum_for_validation"
            }
        }
    
    def get_model_metadata(self, model_id: str) -> Optional[ModelMetadata]:
        """Get comprehensive model metadata."""
        # Check cache first
        if model_id in self.metadata_cache:
            return self.metadata_cache[model_id]
        
        # Check predefined models
        if model_id in self.predefined_models:
            metadata = self.predefined_models[model_id]["metadata"]
            self.metadata_cache[model_id] = metadata
            return metadata
        
        # Try to load from cache file
        cache_file = self.cache_dir / f"{model_id}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                metadata = ModelMetadata(**data)
                self.metadata_cache[model_id] = metadata
                return metadata
            except Exception as e:
                logger.warning(f"Failed to load cached metadata for {model_id}: {e}")
        
        return None
    
    def update_metadata_cache(self, model_id: str, metadata: ModelMetadata):
        """Update metadata cache."""
        self.metadata_cache[model_id] = metadata
        
        # Save to cache file
        cache_file = self.cache_dir / f"{model_id}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump(asdict(metadata), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metadata cache for {model_id}: {e}")
    
    def get_predefined_models(self) -> Dict[str, Dict[str, Any]]:
        """Get all predefined model configurations."""
        return self.predefined_models.copy()

class ModelLibraryService:
    """Core service for model management operations."""
    
    def __init__(self, registry_path: str = "model_registry.json"):
        self.registry_path = Path(registry_path)
        self.download_manager = ModelDownloadManager()
        self.metadata_service = ModelMetadataService()
        self.models_dir = Path("models")
        self.models_dir.mkdir(exist_ok=True)
        
        # Load existing registry
        self.registry = self._load_registry()
        
        # Model cache with invalidation tracking
        self._model_cache: Dict[str, List[ModelInfo]] = {}
        self._cache_timestamp: Optional[float] = None
        self._cache_ttl: int = 300  # 5 minutes default TTL
        self._registry_mtime: Optional[float] = None
        self._models_dir_mtime: Optional[float] = None
        self._cache_lock = threading.Lock()
    
    def _load_registry(self) -> Dict[str, Any]:
        """Load existing model registry and extend with download metadata."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r') as f:
                    data = json.load(f)
                
                # Handle both old list format and new dict format
                if isinstance(data, list):
                    # Convert old format to new format
                    registry = {
                        "models": data,
                        "repositories": [
                            {
                                "name": "huggingface",
                                "baseUrl": "https://huggingface.co",
                                "type": "gguf"
                            }
                        ]
                    }
                else:
                    registry = data
                
                # Ensure required keys exist
                if "models" not in registry:
                    registry["models"] = []
                if "repositories" not in registry:
                    registry["repositories"] = []
                
                return registry
                
            except Exception as e:
                logger.error(f"Failed to load model registry: {e}")
                return {"models": [], "repositories": []}
        else:
            return {"models": [], "repositories": []}
    
    def _save_registry(self):
        """Save model registry to file."""
        try:
            with open(self.registry_path, 'w') as f:
                json.dump(self.registry, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save model registry: {e}")
    
    def get_available_models(self, force_refresh: bool = False) -> List[ModelInfo]:
        """Get all available models (local + remote) with caching."""
        with self._cache_lock:
            # Check if cache is valid and not forced refresh
            if not force_refresh and self._is_cache_valid():
                cached_models = self._model_cache.get("all")
                if cached_models:
                    logger.debug(f"Returning {len(cached_models)} models from cache")
                    return cached_models.copy()
            
            # Cache is invalid or refresh forced, rebuild
            logger.info("Rebuilding model cache...")
            models = self._build_model_list()
            
            # Update cache
            self._model_cache["all"] = models
            self._cache_timestamp = time.time()
            self._update_cache_mtimes()
            
            logger.info(f"Model cache updated with {len(models)} models")
            return models.copy()
    
    def _is_cache_valid(self) -> bool:
        """Check if the current cache is still valid."""
        if not self._cache_timestamp or "all" not in self._model_cache:
            return False
        
        # Check TTL
        if time.time() - self._cache_timestamp > self._cache_ttl:
            logger.debug("Cache expired due to TTL")
            return False
        
        # Check if registry file has been modified
        try:
            if self.registry_path.exists():
                current_registry_mtime = self.registry_path.stat().st_mtime
                if self._registry_mtime is None or current_registry_mtime > self._registry_mtime:
                    logger.debug("Cache invalidated due to registry file change")
                    return False
        except Exception as e:
            logger.warning(f"Failed to check registry mtime: {e}")
            return False
        
        # Check if models directory has been modified
        try:
            if self.models_dir.exists():
                current_models_mtime = self._get_directory_mtime(self.models_dir)
                if self._models_dir_mtime is None or current_models_mtime > self._models_dir_mtime:
                    logger.debug("Cache invalidated due to models directory change")
                    return False
        except Exception as e:
            logger.warning(f"Failed to check models directory mtime: {e}")
            return False
        
        return True
    
    def _get_directory_mtime(self, directory: Path) -> float:
        """Get the most recent modification time in a directory tree."""
        max_mtime = 0.0
        try:
            for item in directory.rglob("*"):
                if item.is_file():
                    try:
                        mtime = item.stat().st_mtime
                        max_mtime = max(max_mtime, mtime)
                    except (OSError, IOError):
                        continue
        except Exception:
            pass
        return max_mtime
    
    def _update_cache_mtimes(self):
        """Update cached modification times."""
        try:
            if self.registry_path.exists():
                self._registry_mtime = self.registry_path.stat().st_mtime
        except Exception:
            self._registry_mtime = None
        
        try:
            if self.models_dir.exists():
                self._models_dir_mtime = self._get_directory_mtime(self.models_dir)
        except Exception:
            self._models_dir_mtime = None
    
    def _build_model_list(self) -> List[ModelInfo]:
        """Build the complete model list from registry and predefined models."""
        models = []
        
        # Add local models from registry
        for model_data in self.registry["models"]:
            model_info = self._create_model_info_from_registry(model_data)
            if model_info:
                models.append(model_info)
        
        # Add predefined models that aren't already local
        predefined = self.metadata_service.get_predefined_models()
        local_model_ids = {model.id for model in models}
        
        for model_id, model_data in predefined.items():
            if model_id not in local_model_ids:
                model_info = self._create_model_info_from_predefined(model_data)
                models.append(model_info)
        
        return models
    
    def get_available_models_fast(self, force_refresh: bool = False) -> List[ModelInfo]:
        """Get all available models with optimized disk usage calculation and caching."""
        with self._cache_lock:
            # Check if cache is valid and not forced refresh
            if not force_refresh and self._is_cache_valid():
                cached_models = self._model_cache.get("fast")
                if cached_models:
                    logger.debug(f"Returning {len(cached_models)} models from fast cache")
                    return cached_models.copy()
            
            # Cache is invalid or refresh forced, rebuild
            logger.info("Rebuilding fast model cache...")
            models = self._build_model_list_fast()
            
            # Update cache
            self._model_cache["fast"] = models
            self._cache_timestamp = time.time()
            self._update_cache_mtimes()
            
            logger.info(f"Fast model cache updated with {len(models)} models")
            return models.copy()
    
    def _build_model_list_fast(self) -> List[ModelInfo]:
        """Build the complete model list with fast disk usage calculation."""
        models = []
        
        # Add local models from registry with fast disk usage calculation
        for model_data in self.registry["models"]:
            model_info = self._create_model_info_from_registry_fast(model_data)
            if model_info:
                models.append(model_info)
        
        # Add predefined models that aren't already local
        predefined = self.metadata_service.get_predefined_models()
        local_model_ids = {model.id for model in models}
        
        for model_id, model_data in predefined.items():
            if model_id not in local_model_ids:
                model_info = self._create_model_info_from_predefined(model_data)
                models.append(model_info)
        
        return models
    
    def _create_model_info_from_registry(self, model_data: Dict[str, Any]) -> Optional[ModelInfo]:
        """Create ModelInfo from registry data."""
        try:
            model_id = model_data.get("id", model_data.get("name", ""))
            if not model_id:
                return None
            
            # Check if model file exists
            model_path = Path(model_data.get("path", ""))
            status = "local" if model_path.exists() else "error"
            
            # Get size if available
            size = 0
            disk_usage = None
            if model_path.exists():
                try:
                    if model_path.is_file():
                        size = model_path.stat().st_size
                        disk_usage = size
                    else:
                        # Calculate directory size recursively
                        total_size = 0
                        for f in model_path.rglob('*'):
                            if f.is_file():
                                try:
                                    total_size += f.stat().st_size
                                except (OSError, IOError):
                                    continue
                        size = total_size
                        disk_usage = total_size
                except Exception:
                    pass
            
            # Get metadata
            metadata_obj = self.metadata_service.get_model_metadata(model_id)
            metadata = asdict(metadata_obj) if metadata_obj else {}
            
            # Get additional usage information
            download_info = model_data.get("downloadInfo", {})
            
            return ModelInfo(
                id=model_id,
                name=model_data.get("name", model_id),
                provider=model_data.get("provider", model_data.get("type", "unknown")),
                size=size,
                description=metadata.get("description", f"Local model: {model_id}"),
                capabilities=model_data.get("capabilities", []),
                status=status,
                metadata=metadata,
                local_path=str(model_path) if model_path.exists() else None,
                disk_usage=disk_usage,
                last_used=model_data.get("last_used"),
                download_date=download_info.get("downloadDate")
            )
            
        except Exception as e:
            logger.error(f"Failed to create model info from registry data: {e}")
            return None
    
    def _create_model_info_from_registry_fast(self, model_data: Dict[str, Any]) -> Optional[ModelInfo]:
        """Create ModelInfo from registry data with fast disk usage calculation."""
        try:
            model_id = model_data.get("id", model_data.get("name", ""))
            if not model_id or not model_id.strip():
                return None
            
            # Check if model file exists
            model_path = Path(model_data.get("path", ""))
            status = "local" if model_path.exists() else "error"
            
            # Fast size calculation - only for files, skip directory recursion
            size = 0
            disk_usage = None
            if model_path.exists():
                try:
                    if model_path.is_file():
                        size = model_path.stat().st_size
                        disk_usage = size
                    else:
                        # For directories, use cached size or estimate
                        cached_size = model_data.get("cached_size")
                        if cached_size:
                            size = cached_size
                            disk_usage = cached_size
                        else:
                            # Skip expensive directory scanning, use 0
                            size = 0
                            disk_usage = 0
                except Exception:
                    pass
            
            # Get metadata (cached)
            metadata_obj = self.metadata_service.get_model_metadata(model_id)
            metadata = asdict(metadata_obj) if metadata_obj else {}
            
            # Get additional usage information
            download_info = model_data.get("downloadInfo", {})
            
            return ModelInfo(
                id=model_id,
                name=model_data.get("name", model_id),
                provider=model_data.get("provider", model_data.get("type", "unknown")),
                size=size,
                description=metadata.get("description", f"Local model: {model_id}"),
                capabilities=model_data.get("capabilities", []),
                status=status,
                metadata=metadata,
                local_path=str(model_path) if model_path.exists() else None,
                disk_usage=disk_usage,
                last_used=model_data.get("last_used"),
                download_date=download_info.get("downloadDate")
            )
            
        except Exception as e:
            logger.error(f"Failed to create model info from registry data: {e}")
            return None
    
    def _create_model_info_from_predefined(self, model_data: Dict[str, Any]) -> ModelInfo:
        """Create ModelInfo from predefined model data."""
        metadata_obj = model_data.get("metadata")
        metadata = asdict(metadata_obj) if metadata_obj else {}
        
        return ModelInfo(
            id=model_data["id"],
            name=model_data["name"],
            provider=model_data["provider"],
            size=model_data["size"],
            description=model_data["description"],
            capabilities=model_data["capabilities"],
            status="available",
            metadata=metadata,
            download_url=model_data.get("download_url"),
            checksum=model_data.get("checksum")
        )
    
    def download_model(self, model_id: str) -> Optional[DownloadTask]:
        """Initiate model download."""
        # Get model info from predefined models
        predefined = self.metadata_service.get_predefined_models()
        
        if model_id not in predefined:
            logger.error(f"Model {model_id} not found in predefined models")
            return None
        
        model_data = predefined[model_id]
        download_url = model_data.get("download_url")
        filename = model_data.get("filename")
        
        if not download_url or not filename:
            logger.error(f"Download URL or filename not available for {model_id}")
            return None
        
        # Start download
        task = self.download_manager.download_model(
            model_id=model_id,
            url=download_url,
            filename=filename,
            progress_callback=self._download_progress_callback
        )
        
        return task
    
    def _download_progress_callback(self, task: DownloadTask):
        """Callback for download progress updates."""
        logger.debug(f"Download progress for {task.model_id}: {task.progress:.1f}%")
        
        # When download completes, add to registry
        if task.status == 'completed':
            self._add_downloaded_model_to_registry(task)
    
    def _add_downloaded_model_to_registry(self, task: DownloadTask):
        """Add successfully downloaded model to registry."""
        try:
            # Get predefined model data
            predefined = self.metadata_service.get_predefined_models()
            model_data = predefined.get(task.model_id)
            
            if not model_data:
                logger.error(f"Predefined data not found for {task.model_id}")
                return
            
            # Create registry entry
            download_path = self.download_manager.download_dir / task.filename
            final_path = self.models_dir / "local-gguf" / task.filename
            
            # Move file to final location
            final_path.parent.mkdir(parents=True, exist_ok=True)
            download_path.rename(final_path)
            
            # Add to registry
            registry_entry = {
                "id": task.model_id,
                "name": model_data["name"],
                "path": str(final_path),
                "type": "gguf",
                "source": "downloaded",
                "provider": model_data["provider"],
                "size": model_data["size"],
                "capabilities": model_data["capabilities"],
                "metadata": asdict(model_data["metadata"]),
                "downloadInfo": {
                    "url": model_data["download_url"],
                    "checksum": model_data.get("checksum"),
                    "downloadDate": time.time()
                }
            }
            
            # Check if model already exists in registry
            existing_index = None
            for i, existing_model in enumerate(self.registry["models"]):
                if existing_model.get("id") == task.model_id:
                    existing_index = i
                    break
            
            if existing_index is not None:
                self.registry["models"][existing_index] = registry_entry
            else:
                self.registry["models"].append(registry_entry)
            
            self._save_registry()
            
            # Invalidate cache since we added a new model
            self._invalidate_cache()
            
            logger.info(f"Added {task.model_id} to model registry and invalidated cache")
            
        except Exception as e:
            logger.error(f"Failed to add downloaded model to registry: {e}")
    
    def get_download_status(self, task_id: str) -> Optional[DownloadTask]:
        """Get download progress."""
        return self.download_manager.get_download_status(task_id)
    
    def cancel_download(self, task_id: str) -> bool:
        """Cancel download."""
        return self.download_manager.cancel_download(task_id)
    
    def delete_model(self, model_id: str) -> bool:
        """Remove local model."""
        try:
            # Find model in registry
            model_index = None
            model_data = None
            
            for i, model in enumerate(self.registry["models"]):
                if model.get("id") == model_id:
                    model_index = i
                    model_data = model
                    break
            
            if model_index is None:
                logger.error(f"Model {model_id} not found in registry")
                return False
            
            # Delete model file
            model_path = Path(model_data["path"])
            if model_path.exists():
                if model_path.is_file():
                    model_path.unlink()
                else:
                    # Remove directory and contents
                    import shutil
                    shutil.rmtree(model_path)
                
                logger.info(f"Deleted model files for {model_id}")
            
            # Remove from registry
            del self.registry["models"][model_index]
            self._save_registry()
            
            # Invalidate cache since we removed a model
            self._invalidate_cache()
            
            logger.info(f"Removed {model_id} from registry and invalidated cache")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete model {model_id}: {e}")
            return False
    
    def get_model_info(self, model_id: str) -> Optional[ModelInfo]:
        """Get detailed information about a specific model."""
        models = self.get_available_models()
        for model in models:
            if model.id == model_id:
                return model
        return None
    
    def refresh_model_cache(self) -> Dict[str, Any]:
        """Force refresh the model cache and return cache statistics."""
        with self._cache_lock:
            old_count = len(self._model_cache.get("all", []))

            # Clear cache before rebuilding outside the lock path to avoid deadlock.
            self._model_cache.clear()
            self._cache_timestamp = None

        models = self.get_available_models(force_refresh=True)

        with self._cache_lock:
            return {
                "cache_refreshed": True,
                "timestamp": self._cache_timestamp,
                "old_model_count": old_count,
                "new_model_count": len(models),
                "cache_keys": list(self._model_cache.keys())
            }
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the current cache state."""
        with self._cache_lock:
            return {
                "cache_valid": self._is_cache_valid(),
                "cache_timestamp": self._cache_timestamp,
                "cache_age_seconds": time.time() - self._cache_timestamp if self._cache_timestamp else None,
                "cache_ttl_seconds": self._cache_ttl,
                "cached_model_count": len(self._model_cache.get("all", [])),
                "cache_keys": list(self._model_cache.keys()),
                "registry_mtime": self._registry_mtime,
                "models_dir_mtime": self._models_dir_mtime
            }
    
    def set_cache_ttl(self, ttl_seconds: int):
        """Set the cache time-to-live in seconds."""
        with self._cache_lock:
            self._cache_ttl = max(30, ttl_seconds)  # Minimum 30 seconds
            logger.info(f"Cache TTL set to {self._cache_ttl} seconds")
    
    def _invalidate_cache(self):
        """Invalidate the current cache."""
        with self._cache_lock:
            self._model_cache.clear()
            self._cache_timestamp = None
            logger.debug("Model cache invalidated")
    
    def validate_checksum(self, file_path: Path, expected_checksum: str) -> bool:
        """Validate file checksum with enhanced security."""
        if not expected_checksum or expected_checksum.startswith("placeholder"):
            logger.info(f"Skipping checksum validation for {file_path} (placeholder checksum)")
            return True  # Skip validation for placeholder checksums
        
        try:
            # Parse checksum format (algorithm:hash)
            if ":" not in expected_checksum:
                logger.warning(f"Invalid checksum format: {expected_checksum}")
                return False
            
            hash_type, expected_hash = expected_checksum.split(":", 1)
            hash_type = hash_type.lower()
            
            # Support multiple hash algorithms
            if hash_type == "sha256":
                hasher = hashlib.sha256()
            elif hash_type == "sha1":
                hasher = hashlib.sha1()
            elif hash_type == "md5":
                hasher = hashlib.md5()
            elif hash_type == "sha512":
                hasher = hashlib.sha512()
            else:
                logger.warning(f"Unsupported hash type: {hash_type}")
                return False

            # Validate file exists and is readable
            if not file_path.exists():
                logger.error(f"File not found for checksum validation: {file_path}")
                return False
            
            if not file_path.is_file():
                logger.error(f"Path is not a file: {file_path}")
                return False
            
            # Calculate hash with progress logging for large files
            file_size = file_path.stat().st_size
            bytes_read = 0
            
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)  # 64KB chunks for better performance
                    if not chunk:
                        break
                    hasher.update(chunk)
                    bytes_read += len(chunk)
                    
                    # Log progress for large files (>100MB)
                    if file_size > 100 * 1024 * 1024 and bytes_read % (10 * 1024 * 1024) == 0:
                        progress = (bytes_read / file_size) * 100
                        logger.debug(f"Checksum validation progress: {progress:.1f}%")
            
            actual_hash = hasher.hexdigest().lower()
            expected_hash = expected_hash.lower()
            
            is_valid = actual_hash == expected_hash
            
            if is_valid:
                logger.info(f"Checksum validation passed for {file_path}")
            else:
                logger.error(f"Checksum validation failed for {file_path}")
                logger.error(f"Expected: {expected_hash}")
                logger.error(f"Actual: {actual_hash}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Failed to validate checksum for {file_path}: {e}")
            return False
    
    def get_model_disk_usage(self, model_id: str) -> Optional[int]:
        """Get actual disk usage for a local model."""
        try:
            # Find model in registry
            model_data = None
            for model in self.registry["models"]:
                if model.get("id") == model_id:
                    model_data = model
                    break
            
            if not model_data:
                return None
            
            model_path = Path(model_data["path"])
            if not model_path.exists():
                return None
            
            # Calculate disk usage
            if model_path.is_file():
                return model_path.stat().st_size
            elif model_path.is_dir():
                # Calculate directory size recursively
                total_size = 0
                for file_path in model_path.rglob('*'):
                    if file_path.is_file():
                        try:
                            total_size += file_path.stat().st_size
                        except (OSError, IOError):
                            continue
                return total_size
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to calculate disk usage for {model_id}: {e}")
            return None
    
    def get_available_disk_space(self) -> int:
        """Get available disk space in the models directory."""
        try:
            usage = shutil.disk_usage(self.models_dir)
            return usage.free
        except Exception as e:
            logger.error(f"Failed to get available disk space: {e}")
            return 0
    
    def get_total_models_disk_usage(self) -> int:
        """Get total disk usage of all local models."""
        total_usage = 0
        for model in self.registry["models"]:
            model_id = model.get("id")
            if model_id:
                usage = self.get_model_disk_usage(model_id)
                if usage:
                    total_usage += usage
        return total_usage
    
    def update_model_status(self, model_id: str, status: str, **kwargs) -> bool:
        """Update model status and additional metadata."""
        try:
            # Find model in registry
            model_index = None
            for i, model in enumerate(self.registry["models"]):
                if model.get("id") == model_id:
                    model_index = i
                    break
            
            if model_index is None:
                logger.error(f"Model {model_id} not found in registry")
                return False
            
            # Update status
            self.registry["models"][model_index]["status"] = status
            
            # Update additional metadata
            for key, value in kwargs.items():
                self.registry["models"][model_index][key] = value
            
            # Update last modified timestamp
            self.registry["models"][model_index]["last_modified"] = time.time()
            
            self._save_registry()
            logger.info(f"Updated model {model_id} status to {status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update model status for {model_id}: {e}")
            return False
    
    def mark_model_used(self, model_id: str) -> bool:
        """Mark a model as recently used."""
        return self.update_model_status(model_id, "local", last_used=time.time())
    
    def get_model_usage_stats(self, model_id: str) -> Dict[str, Any]:
        """Get usage statistics for a model."""
        try:
            # Find model in registry
            model_data = None
            for model in self.registry["models"]:
                if model.get("id") == model_id:
                    model_data = model
                    break
            
            if not model_data:
                return {}
            
            stats = {
                "disk_usage": self.get_model_disk_usage(model_id),
                "last_used": model_data.get("last_used"),
                "download_date": model_data.get("downloadInfo", {}).get("downloadDate"),
                "status": model_data.get("status", "unknown")
            }
            
            # Calculate usage frequency (placeholder for future implementation)
            stats["usage_frequency"] = "unknown"
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get usage stats for {model_id}: {e}")
            return {}
    
    def validate_model_integrity(self, model_id: str) -> Dict[str, Any]:
        """Validate model file integrity and return validation results."""
        try:
            # Find model in registry
            model_data = None
            for model in self.registry["models"]:
                if model.get("id") == model_id:
                    model_data = model
                    break
            
            if not model_data:
                return {"valid": False, "error": "Model not found in registry"}
            
            model_path = Path(model_data["path"])
            if not model_path.exists():
                return {"valid": False, "error": "Model file not found"}
            
            validation_result = {
                "valid": True,
                "file_exists": True,
                "file_size": model_path.stat().st_size if model_path.is_file() else None,
                "checksum_valid": None,
                "permissions_ok": os.access(model_path, os.R_OK),
                "last_modified": model_path.stat().st_mtime
            }
            
            # Validate checksum if available
            expected_checksum = model_data.get("downloadInfo", {}).get("checksum")
            if expected_checksum and not expected_checksum.startswith("placeholder"):
                validation_result["checksum_valid"] = self.validate_checksum(model_path, expected_checksum)
                if not validation_result["checksum_valid"]:
                    validation_result["valid"] = False
                    validation_result["error"] = "Checksum validation failed"
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Failed to validate model integrity for {model_id}: {e}")
            return {"valid": False, "error": str(e)}
    
    def get_detailed_disk_usage(self, model_id: str) -> Dict[str, Any]:
        """Get detailed disk usage information for a model."""
        try:
            # Find model in registry
            model_data = None
            for model in self.registry["models"]:
                if model.get("id") == model_id:
                    model_data = model
                    break
            
            if not model_data:
                return {"error": "Model not found"}
            
            model_path = Path(model_data["path"])
            if not model_path.exists():
                return {"error": "Model file not found", "path": str(model_path)}
            
            result = {
                "model_id": model_id,
                "path": str(model_path),
                "exists": True
            }
            
            if model_path.is_file():
                stat = model_path.stat()
                result.update({
                    "type": "file",
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024**2), 2),
                    "size_gb": round(stat.st_size / (1024**3), 2),
                    "last_modified": stat.st_mtime,
                    "permissions": oct(stat.st_mode)[-3:]
                })
            elif model_path.is_dir():
                # Calculate directory size recursively
                total_size = 0
                file_count = 0
                for file_path in model_path.rglob('*'):
                    if file_path.is_file():
                        try:
                            file_size = file_path.stat().st_size
                            total_size += file_size
                            file_count += 1
                        except (OSError, IOError):
                            continue
                
                result.update({
                    "type": "directory",
                    "size_bytes": total_size,
                    "size_mb": round(total_size / (1024**2), 2),
                    "size_gb": round(total_size / (1024**3), 2),
                    "file_count": file_count,
                    "permissions": oct(model_path.stat().st_mode)[-3:]
                })
            
            # Add reported size comparison
            reported_size = model_data.get("size", 0)
            if reported_size > 0:
                result["reported_size_bytes"] = reported_size
                result["reported_size_mb"] = round(reported_size / (1024**2), 2)
                result["reported_size_gb"] = round(reported_size / (1024**3), 2)
                result["size_difference_bytes"] = result["size_bytes"] - reported_size
                result["size_difference_percent"] = round(
                    (result["size_difference_bytes"] / reported_size) * 100, 2
                ) if reported_size > 0 else 0
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get detailed disk usage for {model_id}: {e}")
            return {"error": str(e)}
    
    def update_model_last_used(self, model_id: str) -> bool:
        """Update the last used timestamp for a model."""
        return self.update_model_status(model_id, "local", last_used=time.time())
    
    def get_model_status_history(self, model_id: str) -> List[Dict[str, Any]]:
        """Get status change history for a model (placeholder for future implementation)."""
        try:
            # Find model in registry
            model_data = None
            for model in self.registry["models"]:
                if model.get("id") == model_id:
                    model_data = model
                    break
            
            if not model_data:
                return []
            
            # For now, return basic status information
            # In the future, this could track status changes over time
            history = []
            
            # Add download event if available
            download_info = model_data.get("downloadInfo", {})
            if download_info.get("downloadDate"):
                history.append({
                    "timestamp": download_info["downloadDate"],
                    "status": "downloaded",
                    "event": "Model downloaded successfully",
                    "details": {
                        "url": download_info.get("url"),
                        "size": model_data.get("size")
                    }
                })
            
            # Add last used event if available
            if model_data.get("last_used"):
                history.append({
                    "timestamp": model_data["last_used"],
                    "status": "used",
                    "event": "Model accessed",
                    "details": {}
                })
            
            # Sort by timestamp (most recent first)
            history.sort(key=lambda x: x["timestamp"], reverse=True)
            
            return history
            
        except Exception as e:
            logger.error(f"Failed to get status history for {model_id}: {e}")
            return []
    
    def validate_model_before_use(self, model_id: str) -> Dict[str, Any]:
        """Validate model before use and update status accordingly."""
        try:
            validation_result = self.validate_model_integrity(model_id)
            
            # Update model status based on validation
            if validation_result.get("valid", False):
                self.update_model_status(model_id, "local", last_validated=time.time())
                logger.info(f"Model {model_id} validation passed")
            else:
                self.update_model_status(model_id, "error", 
                                       last_validated=time.time(),
                                       validation_error=validation_result.get("error"))
                logger.warning(f"Model {model_id} validation failed: {validation_result.get('error')}")
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Failed to validate model before use {model_id}: {e}")
            return {"valid": False, "error": str(e)}
    
    def get_models_by_status(self, status: str) -> List[ModelInfo]:
        """Get all models with a specific status."""
        all_models = self.get_available_models()
        return [model for model in all_models if model.status == status]
    
    def get_local_models_summary(self) -> Dict[str, Any]:
        """Get summary information about local models."""
        try:
            local_models = self.get_models_by_status("local")
            
            total_size = sum(model.disk_usage or model.size for model in local_models)
            total_count = len(local_models)
            
            # Group by provider
            by_provider = {}
            for model in local_models:
                provider = model.provider
                if provider not in by_provider:
                    by_provider[provider] = {"count": 0, "size": 0}
                by_provider[provider]["count"] += 1
                by_provider[provider]["size"] += model.disk_usage or model.size
            
            # Find recently used models
            recently_used = []
            for model in local_models:
                if model.last_used:
                    recently_used.append({
                        "id": model.id,
                        "name": model.name,
                        "last_used": model.last_used
                    })
            
            recently_used.sort(key=lambda x: x["last_used"], reverse=True)
            recently_used = recently_used[:5]  # Top 5 recently used
            
            return {
                "total_models": total_count,
                "total_size_bytes": total_size,
                "total_size_gb": round(total_size / (1024**3), 2),
                "by_provider": by_provider,
                "recently_used": recently_used,
                "available_space_bytes": self.get_available_disk_space(),
                "available_space_gb": round(self.get_available_disk_space() / (1024**3), 2)
            }
            
        except Exception as e:
            logger.error(f"Failed to get local models summary: {e}")
            return {"error": str(e)}
    
    def cleanup_orphaned_files(self) -> Dict[str, Any]:
        """Clean up orphaned model files that are not in the registry."""
        try:
            cleanup_result = {
                "files_removed": [],
                "space_freed_bytes": 0,
                "errors": []
            }
            
            # Get all registered model paths
            registered_paths = set()
            for model in self.registry["models"]:
                model_path = Path(model.get("path", ""))
                if model_path.exists():
                    registered_paths.add(model_path.resolve())
            
            # Scan models directory for orphaned files
            if self.models_dir.exists():
                for file_path in self.models_dir.rglob('*'):
                    if file_path.is_file() and file_path.resolve() not in registered_paths:
                        # Check if it's a model file (by extension)
                        if file_path.suffix.lower() in ['.gguf', '.bin', '.safetensors', '.pt', '.pth']:
                            try:
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                cleanup_result["files_removed"].append({
                                    "path": str(file_path),
                                    "size": file_size
                                })
                                cleanup_result["space_freed_bytes"] += file_size
                                logger.info(f"Removed orphaned model file: {file_path}")
                            except Exception as e:
                                cleanup_result["errors"].append({
                                    "path": str(file_path),
                                    "error": str(e)
                                })
            
            cleanup_result["space_freed_gb"] = round(
                cleanup_result["space_freed_bytes"] / (1024**3), 2
            )
            
            return cleanup_result
            
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned files: {e}")
            return {"error": str(e)}
    
    def scan_model_security(self, model_id: str) -> Dict[str, Any]:
        """Perform comprehensive security scan on a model file."""
        try:
            # Find model in registry
            model_data = None
            for model in self.registry["models"]:
                if model.get("id") == model_id:
                    model_data = model
                    break
            
            if not model_data:
                return {"error": "Model not found in registry"}
            
            model_path = Path(model_data["path"])
            if not model_path.exists():
                return {"error": "Model file not found"}
            
            scan_result = {
                "model_id": model_id,
                "scan_timestamp": time.time(),
                "file_path": str(model_path),
                "security_checks": {},
                "warnings": [],
                "errors": [],
                "overall_status": "unknown"
            }
            
            # 1. File integrity check
            try:
                stat = model_path.stat()
                scan_result["security_checks"]["file_integrity"] = {
                    "exists": True,
                    "readable": os.access(model_path, os.R_OK),
                    "size": stat.st_size,
                    "permissions": oct(stat.st_mode)[-3:],
                    "last_modified": stat.st_mtime
                }
                
                # Check for suspicious permissions
                if stat.st_mode & 0o111:  # Executable bit set
                    scan_result["warnings"].append("Model file has executable permissions")
                
            except Exception as e:
                scan_result["errors"].append(f"File integrity check failed: {e}")
                scan_result["security_checks"]["file_integrity"] = {"error": str(e)}
            
            # 2. Checksum validation
            try:
                expected_checksum = model_data.get("downloadInfo", {}).get("checksum")
                if expected_checksum and not expected_checksum.startswith("placeholder"):
                    checksum_valid = self.validate_checksum(model_path, expected_checksum)
                    scan_result["security_checks"]["checksum"] = {
                        "expected": expected_checksum,
                        "valid": checksum_valid
                    }
                    
                    if not checksum_valid:
                        scan_result["errors"].append("Checksum validation failed - file may be corrupted or tampered")
                else:
                    scan_result["security_checks"]["checksum"] = {
                        "status": "skipped",
                        "reason": "No checksum available"
                    }
                    scan_result["warnings"].append("No checksum available for validation")
                    
            except Exception as e:
                scan_result["errors"].append(f"Checksum validation failed: {e}")
                scan_result["security_checks"]["checksum"] = {"error": str(e)}
            
            # 3. File format validation
            try:
                file_extension = model_path.suffix.lower()
                expected_extensions = ['.gguf', '.bin', '.safetensors', '.pt', '.pth']
                
                scan_result["security_checks"]["file_format"] = {
                    "extension": file_extension,
                    "expected_extensions": expected_extensions,
                    "valid_extension": file_extension in expected_extensions
                }
                
                if file_extension not in expected_extensions:
                    scan_result["warnings"].append(f"Unexpected file extension: {file_extension}")
                
                # Basic file header check for GGUF files
                if file_extension == '.gguf':
                    with open(model_path, 'rb') as f:
                        header = f.read(4)
                        if header == b'GGUF':
                            scan_result["security_checks"]["file_format"]["header_valid"] = True
                        else:
                            scan_result["security_checks"]["file_format"]["header_valid"] = False
                            scan_result["warnings"].append("GGUF file header is invalid")
                            
            except Exception as e:
                scan_result["errors"].append(f"File format validation failed: {e}")
                scan_result["security_checks"]["file_format"] = {"error": str(e)}
            
            # 4. Size validation
            try:
                actual_size = model_path.stat().st_size
                expected_size = model_data.get("size", 0)
                
                scan_result["security_checks"]["size_validation"] = {
                    "actual_size": actual_size,
                    "expected_size": expected_size,
                    "size_match": abs(actual_size - expected_size) < (expected_size * 0.1)  # 10% tolerance
                }
                
                if expected_size > 0:
                    size_diff_percent = abs(actual_size - expected_size) / expected_size * 100
                    if size_diff_percent > 10:
                        scan_result["warnings"].append(f"File size differs from expected by {size_diff_percent:.1f}%")
                        
            except Exception as e:
                scan_result["errors"].append(f"Size validation failed: {e}")
                scan_result["security_checks"]["size_validation"] = {"error": str(e)}
            
            # 5. Path traversal check
            try:
                resolved_path = model_path.resolve()
                models_dir_resolved = self.models_dir.resolve()
                
                scan_result["security_checks"]["path_security"] = {
                    "within_models_dir": str(resolved_path).startswith(str(models_dir_resolved)),
                    "resolved_path": str(resolved_path),
                    "models_dir": str(models_dir_resolved)
                }
                
                if not str(resolved_path).startswith(str(models_dir_resolved)):
                    scan_result["errors"].append("Model file is outside the designated models directory")
                    
            except Exception as e:
                scan_result["errors"].append(f"Path security check failed: {e}")
                scan_result["security_checks"]["path_security"] = {"error": str(e)}
            
            # 6. Quarantine check (check if file is in quarantine)
            try:
                quarantine_markers = ['.quarantine', '.suspicious', '.blocked']
                is_quarantined = any(marker in str(model_path) for marker in quarantine_markers)
                
                scan_result["security_checks"]["quarantine_status"] = {
                    "quarantined": is_quarantined,
                    "markers_checked": quarantine_markers
                }
                
                if is_quarantined:
                    scan_result["errors"].append("Model file appears to be quarantined")
                    
            except Exception as e:
                scan_result["errors"].append(f"Quarantine check failed: {e}")
                scan_result["security_checks"]["quarantine_status"] = {"error": str(e)}
            
            # Determine overall status
            if len(scan_result["errors"]) > 0:
                scan_result["overall_status"] = "failed"
            elif len(scan_result["warnings"]) > 0:
                scan_result["overall_status"] = "warning"
            else:
                scan_result["overall_status"] = "passed"
            
            # Update model status based on scan results
            if scan_result["overall_status"] == "failed":
                self.update_model_status(model_id, "error", 
                                       security_scan_failed=True,
                                       last_security_scan=time.time())
            else:
                self.update_model_status(model_id, "local", 
                                       last_security_scan=time.time(),
                                       security_scan_status=scan_result["overall_status"])
            
            logger.info(f"Security scan completed for {model_id}: {scan_result['overall_status']}")
            return scan_result
            
        except Exception as e:
            logger.error(f"Failed to perform security scan for {model_id}: {e}")
            return {"error": str(e)}
    
    def quarantine_model(self, model_id: str, reason: str) -> bool:
        """Quarantine a model by moving it to a quarantine directory."""
        try:
            # Find model in registry
            model_data = None
            model_index = None
            for i, model in enumerate(self.registry["models"]):
                if model.get("id") == model_id:
                    model_data = model
                    model_index = i
                    break
            
            if not model_data:
                logger.error(f"Model {model_id} not found in registry")
                return False
            
            model_path = Path(model_data["path"])
            if not model_path.exists():
                logger.error(f"Model file not found: {model_path}")
                return False
            
            # Create quarantine directory
            quarantine_dir = self.models_dir / "quarantine"
            quarantine_dir.mkdir(exist_ok=True)
            
            # Move file to quarantine with timestamp
            timestamp = int(time.time())
            quarantine_filename = f"{model_id}_{timestamp}_{model_path.name}"
            quarantine_path = quarantine_dir / quarantine_filename
            
            # Move the file
            shutil.move(str(model_path), str(quarantine_path))
            
            # Update registry
            self.registry["models"][model_index]["status"] = "quarantined"
            self.registry["models"][model_index]["quarantine_info"] = {
                "reason": reason,
                "timestamp": timestamp,
                "original_path": str(model_path),
                "quarantine_path": str(quarantine_path)
            }
            
            self._save_registry()
            
            logger.warning(f"Model {model_id} quarantined: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to quarantine model {model_id}: {e}")
            return False
    
    def validate_model_before_download(self, model_id: str, download_url: str) -> Dict[str, Any]:
        """Validate model metadata and download source before initiating download."""
        try:
            validation_result = {
                "model_id": model_id,
                "download_url": download_url,
                "validation_timestamp": time.time(),
                "checks": {},
                "warnings": [],
                "errors": [],
                "safe_to_download": False
            }
            
            # 1. URL validation
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(download_url)
                
                validation_result["checks"]["url_validation"] = {
                    "scheme": parsed_url.scheme,
                    "hostname": parsed_url.hostname,
                    "valid_scheme": parsed_url.scheme in ['https', 'http'],
                    "has_hostname": bool(parsed_url.hostname)
                }
                
                if parsed_url.scheme not in ['https', 'http']:
                    validation_result["errors"].append(f"Invalid URL scheme: {parsed_url.scheme}")
                
                if not parsed_url.hostname:
                    validation_result["errors"].append("URL missing hostname")
                
                # Prefer HTTPS
                if parsed_url.scheme == 'http':
                    validation_result["warnings"].append("Using HTTP instead of HTTPS (less secure)")
                
                # Check for suspicious domains (basic check)
                suspicious_domains = ['bit.ly', 'tinyurl.com', 'short.link']
                if any(domain in parsed_url.hostname for domain in suspicious_domains):
                    validation_result["warnings"].append("URL uses URL shortener (potential security risk)")
                    
            except Exception as e:
                validation_result["errors"].append(f"URL validation failed: {e}")
                validation_result["checks"]["url_validation"] = {"error": str(e)}
            
            # 2. Model metadata validation
            try:
                predefined = self.metadata_service.get_predefined_models()
                if model_id in predefined:
                    model_data = predefined[model_id]
                    
                    validation_result["checks"]["metadata_validation"] = {
                        "predefined_model": True,
                        "has_checksum": bool(model_data.get("checksum")),
                        "has_size": bool(model_data.get("size")),
                        "has_description": bool(model_data.get("description"))
                    }
                    
                    if not model_data.get("checksum") or model_data.get("checksum", "").startswith("placeholder"):
                        validation_result["warnings"].append("No checksum available for integrity verification")
                    
                    if not model_data.get("size"):
                        validation_result["warnings"].append("No size information available")
                        
                else:
                    validation_result["checks"]["metadata_validation"] = {
                        "predefined_model": False
                    }
                    validation_result["warnings"].append("Model is not in predefined models list")
                    
            except Exception as e:
                validation_result["errors"].append(f"Metadata validation failed: {e}")
                validation_result["checks"]["metadata_validation"] = {"error": str(e)}
            
            # 3. Disk space check
            try:
                available_space = self.get_available_disk_space()
                predefined = self.metadata_service.get_predefined_models()
                model_size = predefined.get(model_id, {}).get("size", 0)
                
                # Require 2x the model size for safe download (temp + final)
                required_space = model_size * 2
                
                validation_result["checks"]["disk_space"] = {
                    "available_bytes": available_space,
                    "required_bytes": required_space,
                    "model_size_bytes": model_size,
                    "sufficient_space": available_space > required_space
                }
                
                if available_space <= required_space:
                    validation_result["errors"].append(f"Insufficient disk space (need {required_space}, have {available_space})")
                elif available_space < required_space * 1.5:
                    validation_result["warnings"].append("Low disk space - download may fail")
                    
            except Exception as e:
                validation_result["errors"].append(f"Disk space check failed: {e}")
                validation_result["checks"]["disk_space"] = {"error": str(e)}
            
            # 4. Network connectivity check (basic)
            try:
                import requests
                
                # Try to get headers from the download URL
                response = requests.head(download_url, timeout=10, allow_redirects=True)
                
                validation_result["checks"]["network_connectivity"] = {
                    "url_accessible": response.status_code == 200,
                    "status_code": response.status_code,
                    "content_length": response.headers.get('content-length'),
                    "content_type": response.headers.get('content-type')
                }
                
                if response.status_code != 200:
                    validation_result["errors"].append(f"Download URL not accessible (status: {response.status_code})")
                
                # Check content type
                content_type = response.headers.get('content-type', '')
                if content_type and 'text/html' in content_type:
                    validation_result["warnings"].append("URL returns HTML content (may not be a direct file link)")
                    
            except Exception as e:
                validation_result["warnings"].append(f"Network connectivity check failed: {e}")
                validation_result["checks"]["network_connectivity"] = {"error": str(e)}
            
            # Determine if safe to download
            validation_result["safe_to_download"] = len(validation_result["errors"]) == 0
            
            logger.info(f"Pre-download validation for {model_id}: {'PASSED' if validation_result['safe_to_download'] else 'FAILED'}")
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Failed to validate model before download {model_id}: {e}")
            return {"error": str(e), "safe_to_download": False}
    
    def cleanup(self):
        """Cleanup resources."""
        self.download_manager.cleanup_completed_downloads()
