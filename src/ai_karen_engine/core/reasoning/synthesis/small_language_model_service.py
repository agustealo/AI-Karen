"""
Generic Small Language Model Service for dynamic model configuration and selection.

This service provides a unified interface for working with different small language models
including default lightweight models and other compatible models. It dynamically selects the best model
based on system resources and can automatically download suitable models if needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import shutil
import tempfile
import threading
from typing import Dict, List, Optional, Any, Union, Tuple, Protocol
from dataclasses import dataclass, field
from pathlib import Path
import urllib.request
import json
import platform
import psutil
import GPUtil

try:
    from cachetools import TTLCache
except ImportError:
    class TTLCache(dict):
        """Minimal fallback TTL cache when cachetools is unavailable."""

        def __init__(self, maxsize: int, ttl: float):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._expires: Dict[Any, float] = {}

        def _purge_expired(self) -> None:
            now = time.time()
            expired = [key for key, deadline in self._expires.items() if deadline <= now]
            for key in expired:
                self._expires.pop(key, None)
                super().pop(key, None)

        def __contains__(self, key) -> bool:
            self._purge_expired()
            return super().__contains__(key)

        def __getitem__(self, key):
            self._purge_expired()
            return super().__getitem__(key)

        def get(self, key, default=None):
            self._purge_expired()
            return super().get(key, default)

        def __setitem__(self, key, value) -> None:
            self._purge_expired()
            if key not in self and len(self) >= self.maxsize:
                oldest_key = min(self._expires, key=self._expires.get)
                self._expires.pop(oldest_key, None)
                super().pop(oldest_key, None)
            self._expires[key] = time.time() + self.ttl
            super().__setitem__(key, value)

        def __len__(self) -> int:
            self._purge_expired()
            return super().__len__()

try:
    from ai_karen_engine.core.memory.signals.nlp_config import SmallLanguageModelConfig
except ImportError:
    # Create a basic config if not available
    class SmallLanguageModelConfig:
        def __init__(self, **kwargs):
            try:
                from ai_karen_engine.config.config_manager import get_config
                config = get_config()
                default_model = config.llm.default_lightweight_model_id
            except Exception:
                default_model = "default-lightweight-model"
            self.model_name = kwargs.get("model_name", default_model)
            self.max_tokens = kwargs.get("max_tokens", 150)
            self.temperature = kwargs.get("temperature", 0.7)
            self.enable_fallback = kwargs.get("enable_fallback", True)
            self.cache_size = kwargs.get("cache_size", 1000)
            self.cache_ttl = kwargs.get("cache_ttl", 1800)
            self.scaffold_max_tokens = kwargs.get("scaffold_max_tokens", 100)
            self.outline_max_tokens = kwargs.get("outline_max_tokens", 80)
            self.summary_max_tokens = kwargs.get("summary_max_tokens", 120)
            self.enabled = kwargs.get("enabled", True)

logger = logging.getLogger(__name__)


class _ChatClientProtocol(Protocol):
    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 256,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs: Any,
    ) -> str: ...

    def load_model(self, model_path: str) -> Dict[str, Any]: ...

local_model_client = None
LOCAL_MODEL_CLIENT_AVAILABLE = False


def _get_local_model_client():
    """Lazy loading of a neutral local model client."""
    global local_model_client, LOCAL_MODEL_CLIENT_AVAILABLE

    if LOCAL_MODEL_CLIENT_AVAILABLE:
        return local_model_client

    try:
        from ai_karen_engine.core.model_runtime.unavailable_provider import (
            FallbackProvider,
        )

        class _LocalModelClient:
            def __init__(self) -> None:
                self._provider = FallbackProvider()
                self._model_path: Optional[str] = None

            def load_model(self, model_path: str) -> Dict[str, Any]:
                self._model_path = model_path
                return {"status": "success"}

            def chat(
                self,
                messages: List[Dict[str, Any]],
                *,
                max_tokens: int = 256,
                temperature: float = 0.7,
                stream: bool = False,
                **kwargs: Any,
            ) -> str:
                from ai_karen_engine.core.model_runtime.model_manager import (
                    ModelManager,
                )

                return ModelManager.invoke_provider_sync(
                    self._provider,
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    **kwargs,
                )

            def health_check(self) -> Dict[str, Any]:
                status = self._provider.health_check()
                status["client"] = "fallback_local"
                status["model_path"] = self._model_path
                return status

        local_model_client = _LocalModelClient()
        LOCAL_MODEL_CLIENT_AVAILABLE = True
        return local_model_client
    except Exception as exc:
        logger.debug("Failed to initialize local model client: %s", exc)
        return None


@dataclass
class ModelInfo:
    """Information about a small language model."""
    
    name: str
    description: str
    file_size: int  # in bytes
    ram_required: int  # in bytes
    parameters: str  # e.g., "1.1B", "3B", "7B"
    quantization: str  # e.g., "Q4", "Q5"
    download_url: Optional[str] = None
    local_path: Optional[str] = None
    is_available: bool = False
    is_loaded: bool = False
    is_default: bool = False


@dataclass
class SystemResources:
    """Information about system resources."""
    
    total_ram: int  # in bytes
    available_ram: int  # in bytes
    cpu_count: int
    gpu_available: bool = False
    gpu_memory: int = 0  # in bytes
    gpu_name: str = ""
    os: str = ""
    architecture: str = ""


@dataclass
class ScaffoldResult:
    """Result of scaffolding generation."""
    
    content: str
    processing_time: float
    used_fallback: bool
    model_name: Optional[str] = None
    input_length: int = 0
    output_tokens: int = 0


@dataclass
class OutlineResult:
    """Result of outline generation."""
    
    outline: List[str]
    processing_time: float
    used_fallback: bool
    model_name: Optional[str] = None
    input_length: int = 0


@dataclass
class SummaryResult:
    """Result of context summarization."""
    
    summary: str
    processing_time: float
    used_fallback: bool
    model_name: Optional[str] = None
    input_length: int = 0
    compression_ratio: float = 0.0


@dataclass
class SmallLMHealthStatus:
    """Health status for Small Language Model service."""
    
    is_healthy: bool
    model_loaded: bool
    fallback_mode: bool
    cache_size: int
    cache_hit_rate: float
    avg_processing_time: float
    error_count: int
    last_error: Optional[str] = None
    current_model: Optional[str] = None
    available_models: List[str] = field(default_factory=list)


class SmallLanguageModelService:
    """Generic Small Language Model service with dynamic model selection."""

    LOCAL_MODEL_ALIASES = {
        "default-lightweight-model": [
            "Qwen3-0.6B-Q4_K_M.gguf",
            "Phi-3-mini-4k-instruct-q4.gguf",
            "tinyllama-1.1b-chat-v2.0.Q4_K_M.gguf",
            "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        ],
        "default-base-model": [
            "tinyllama-1.1b-chat-v2.0.Q4_K_M.gguf",
            "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        ],
    }
    
    # Registry of known models with their properties
    MODEL_REGISTRY = {
        "default-lightweight-model": ModelInfo(
            name="default-lightweight-model",
            description="Default lightweight Qwen3 chat model",
            file_size=520000000,  # ~520MB
            ram_required=1500000000,  # ~1.5GB RAM
            parameters="0.6B",
            quantization="Q4_K_M",
            download_url="https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf",
            is_default=True
        ),
        "default-base-model": ModelInfo(
            name="default-base-model",
            description="Default base model with 1.1B parameters",
            file_size=670000000,  # ~670MB
            ram_required=2000000000,  # ~2GB RAM
            parameters="1.1B",
            quantization="Q4",
            download_url="https://huggingface.co/TinyLlama/TinyLlama-1.1B/resolve/main/tinyllama-1.1b.Q4_K_M.gguf"
        ),
        "mistral-7b-instruct": ModelInfo(
            name="mistral-7b-instruct",
            description="Mistral 7B parameter instruction model",
            file_size=4100000000,  # ~4.1GB
            ram_required=8000000000,  # ~8GB RAM
            parameters="7B",
            quantization="Q4",
            download_url="https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf"
        ),
        "phi-2": ModelInfo(
            name="phi-2",
            description="Microsoft Phi-2 2.7B parameter model",
            file_size=1700000000,  # ~1.7GB
            ram_required=4000000000,  # ~4GB RAM
            parameters="2.7B",
            quantization="Q4",
            download_url="https://huggingface.co/TheBloke/phi-2-GGUF/resolve/main/phi-2.Q4_K_M.gguf"
        )
    }
    
    def __init__(self, config: Optional[SmallLanguageModelConfig] = None, models_dir: Optional[str] = None):
        self.config = config or SmallLanguageModelConfig()
        self.models_dir = Path(models_dir) if models_dir else Path("models/transformers")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.client = None
        self.current_model = None
        self.fallback_mode = False
        self.cache = TTLCache(maxsize=self.config.cache_size, ttl=self.config.cache_ttl)
        self.lock = threading.RLock()
        
        # Monitoring metrics
        self._cache_hits = 0
        self._cache_misses = 0
        self._processing_times = []
        self._error_count = 0
        self._last_error = None
        
        # Initialize service
        self._initialize()
    
    def _initialize(self):
        """Initialize Small Language Model service with model loading and fallback setup."""
        try:
            # Check system resources
            system_resources = self._get_system_resources()
            logger.info(f"System resources: RAM={system_resources.available_ram/1000000000:.1f}GB, "
                        f"GPU={system_resources.gpu_available}, "
                        f"GPU Memory={system_resources.gpu_memory/1000000000:.1f}GB")
            
            # Update model registry with local availability
            self._update_model_availability()
            
            # Select best model based on resources
            best_model = self._select_best_model(system_resources)
            
            if best_model:
                self.current_model = best_model.name
                logger.info(f"Selected model: {self.current_model}")
                
                # Initialize client
                client = _get_local_model_client()
                if client is not None:
                    self.client = client
                    
                    # Load the model
                    model_path = self._resolve_model_file_path(self.current_model)
                    if model_path.exists():
                        # Load model using client
                        load_result = self.client.load_model(str(model_path))
                        if load_result.get("status") == "success":
                            logger.info(f"Model {self.current_model} loaded successfully")
                            self.MODEL_REGISTRY[self.current_model].is_loaded = True
                        else:
                            logger.warning(f"Failed to load model {self.current_model}: {load_result.get('error')}")
                            if self.config.enable_fallback:
                                self.fallback_mode = True
                            else:
                                raise RuntimeError(f"Failed to load model {self.current_model} and fallback disabled")
                    else:
                        # Try to download the model
                        if self.MODEL_REGISTRY[self.current_model].download_url:
                            logger.info(f"Model {self.current_model} not found locally, attempting download...")
                            if self._download_model(self.current_model):
                                # Retry loading after download
                                load_result = self.client.load_model(str(model_path))
                                if load_result.get("status") == "success":
                                    logger.info(f"Model {self.current_model} loaded successfully after download")
                                    self.MODEL_REGISTRY[self.current_model].is_loaded = True
                                else:
                                    logger.warning(f"Failed to load model {self.current_model} after download: {load_result.get('error')}")
                                    if self.config.enable_fallback:
                                        self.fallback_mode = True
                                    else:
                                        raise RuntimeError(f"Failed to load model {self.current_model} after download and fallback disabled")
                            else:
                                logger.warning(f"Failed to download model {self.current_model}")
                                if self.config.enable_fallback:
                                    self.fallback_mode = True
                                else:
                                    raise RuntimeError(f"Failed to download model {self.current_model} and fallback disabled")
                        else:
                            logger.warning(f"No download URL for model {self.current_model}")
                            if self.config.enable_fallback:
                                self.fallback_mode = True
                            else:
                                raise RuntimeError(f"No download URL for model {self.current_model} and fallback disabled")
                else:
                    logger.warning("Local GGUF client not available, using fallback mode")
                    if self.config.enable_fallback:
                        self.fallback_mode = True
                    else:
                        raise RuntimeError("Local GGUF client not available and fallback disabled")
            else:
                logger.warning("No suitable model found for system resources")
                if self.config.enable_fallback:
                    self.fallback_mode = True
                else:
                    raise RuntimeError("No suitable model found for system resources and fallback disabled")
                
        except Exception as e:
            logger.error(f"Failed to initialize Small Language Model service: {e}")
            self._last_error = str(e)
            self._error_count += 1
            if self.config.enable_fallback:
                self.fallback_mode = True
                logger.info("Enabled fallback mode due to initialization failure")
            else:
                raise

    def _require_client(self) -> _ChatClientProtocol:
        """Return the active chat client or raise if unavailable."""
        client = self.client
        if client is None:
            raise RuntimeError("Small language model client is not initialized")
        return client
    
    def _get_system_resources(self) -> SystemResources:
        """Get information about system resources."""
        # Get RAM information
        ram = psutil.virtual_memory()
        
        # Get CPU information
        cpu_count = psutil.cpu_count(logical=False)
        
        # Get GPU information if available
        gpu_available = False
        gpu_memory = 0
        gpu_name = ""
        
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu_available = True
                gpu_memory = gpus[0].memoryTotal * 1024 * 1024  # Convert MB to bytes
                gpu_name = gpus[0].name
        except Exception:
            pass
        
        return SystemResources(
            total_ram=ram.total,
            available_ram=ram.available,
            cpu_count=cpu_count or 1,
            gpu_available=gpu_available,
            gpu_memory=gpu_memory,
            gpu_name=gpu_name,
            os=platform.system(),
            architecture=platform.machine()
        )
    
    def _update_model_availability(self):
        """Update model registry with local availability information."""
        for model_name, model_info in self.MODEL_REGISTRY.items():
            model_path = self._resolve_model_file_path(model_name)
            model_info.local_path = str(model_path)
            model_info.is_available = model_path.exists()
    
    def _select_best_model(self, system_resources: SystemResources) -> Optional[ModelInfo]:
        """Select the best model based on system resources."""
        # Filter models that can run on this system
        suitable_models = []
        
        for model_info in self.MODEL_REGISTRY.values():
            # Check RAM requirements
            if model_info.ram_required <= system_resources.available_ram:
                # If GPU is available, check GPU memory
                if system_resources.gpu_available:
                    if model_info.ram_required <= system_resources.gpu_memory:
                        suitable_models.append(model_info)
                else:
                    # No GPU, just use RAM
                    suitable_models.append(model_info)
        
        if not suitable_models:
            return None
        
        # Sort by parameter count (descending) - prefer larger models if resources allow
        suitable_models.sort(key=lambda m: float(m.parameters.replace("B", "")), reverse=True)
        
        # Prefer default models
        default_models = [m for m in suitable_models if m.is_default]
        if default_models:
            return default_models[0]
        
        return suitable_models[0]
    
    def _resolve_model_file_path(self, model_name: str) -> Path:
        """Return the GGUF file that should be loaded for the given model."""
        for alias in self.LOCAL_MODEL_ALIASES.get(model_name, []):
            alias_path = self.models_dir / alias
            if alias_path.exists():
                return alias_path

        base_path = self.models_dir / f"{model_name}.gguf"
        if base_path.exists():
            return base_path

        candidates = sorted(self.models_dir.glob(f"{model_name}*.gguf"))
        if candidates:
            return candidates[0]

        return base_path
    
    def _download_model(self, model_name: str) -> bool:
        """Download a model if it's not available locally."""
        if model_name not in self.MODEL_REGISTRY:
            logger.error(f"Unknown model: {model_name}")
            return False
        
        model_info = self.MODEL_REGISTRY[model_name]
        if not model_info.download_url:
            logger.error(f"No download URL for model: {model_name}")
            return False
        
        model_path = self.models_dir / f"{model_name}.gguf"
        
        try:
            logger.info(f"Downloading {model_name} from {model_info.download_url}")
            
            # Create a temporary file for downloading
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_path = temp_file.name
            
            # Download with progress reporting
            def report_progress(count, block_size, total_size):
                if total_size > 0:
                    percent = int(count * block_size * 100 / total_size)
                    if percent % 10 == 0:  # Report every 10%
                        logger.info(f"Download progress: {percent}%")
            
            urllib.request.urlretrieve(model_info.download_url, temp_path, reporthook=report_progress)
            
            # Move temporary file to final location
            shutil.move(temp_path, model_path)
            
            # Update model info
            model_info.is_available = True
            model_info.local_path = str(model_path)
            
            logger.info(f"Model {model_name} downloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to download model {model_name}: {e}")
            # Clean up temporary file if it exists
            temp_file_path = locals().get('temp_path')
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return False
    
    async def generate_scaffold(
        self, 
        text: str, 
        scaffold_type: str = "reasoning",
        max_tokens: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ScaffoldResult:
        """
        Generate fast reasoning scaffolding for given text.
        
        Args:
            text: Input text to scaffold
            scaffold_type: Type of scaffold ("reasoning", "outline", "structure", "conversation", "analysis")
            max_tokens: Maximum tokens to generate
            context: Additional context for scaffolding (conversation history, user preferences, etc.)
            
        Returns:
            ScaffoldResult with generated scaffolding content
        """
        if not text or not text.strip():
            return ScaffoldResult(
                content="",
                processing_time=0.0,
                used_fallback=True,
                input_length=0,
                output_tokens=0
            )
        
        # Check cache first
        cache_key = self._get_cache_key(f"scaffold:{scaffold_type}:{text}")
        with self.lock:
            if cache_key in self.cache:
                self._cache_hits += 1
                return self.cache[cache_key]
            self._cache_misses += 1
        
        start_time = time.time()
        max_tokens = max_tokens or self.config.scaffold_max_tokens
        
        try:
            if self.fallback_mode or not self.client or not self.current_model:
                content = await self._fallback_scaffold(text, scaffold_type, context)
                used_fallback = True
                output_tokens = len(content.split())
            else:
                content = await self._generate_scaffold_llm(text, scaffold_type, max_tokens, context)
                used_fallback = False
                output_tokens = len(content.split())
            
            processing_time = time.time() - start_time
            
            result = ScaffoldResult(
                content=content,
                processing_time=processing_time,
                used_fallback=used_fallback,
                model_name=self.current_model if not used_fallback else "fallback",
                input_length=len(text),
                output_tokens=output_tokens
            )
            
            # Cache result
            with self.lock:
                self._processing_times.append(processing_time)
                if len(self._processing_times) > 1000:
                    self._processing_times = self._processing_times[-1000:]
                self.cache[cache_key] = result
            
            return result
            
        except Exception as e:
            logger.error(f"Scaffold generation failed: {e}")
            self._error_count += 1
            self._last_error = str(e)
            
            # Fallback on error
            if not self.fallback_mode and self.config.enable_fallback:
                logger.info("Falling back to rule-based scaffolding due to error")
                content = await self._fallback_scaffold(text, scaffold_type, context)
                processing_time = time.time() - start_time
                return ScaffoldResult(
                    content=content,
                    processing_time=processing_time,
                    used_fallback=True,
                    model_name="fallback",
                    input_length=len(text),
                    output_tokens=len(content.split())
                )
            else:
                raise
    
    async def generate_outline(
        self, 
        text: str, 
        outline_style: str = "bullet",
        max_points: int = 5
    ) -> OutlineResult:
        """
        Generate conversation outline and quick scaffolding.
        
        Args:
            text: Input text to outline
            outline_style: Style of outline ("bullet", "numbered", "structured")
            max_points: Maximum number of outline points
            
        Returns:
            OutlineResult with generated outline points
        """
        if not text or not text.strip():
            return OutlineResult(
                outline=[],
                processing_time=0.0,
                used_fallback=True,
                input_length=0
            )
        
        # Check cache first
        cache_key = self._get_cache_key(f"outline:{outline_style}:{max_points}:{text}")
        with self.lock:
            if cache_key in self.cache:
                self._cache_hits += 1
                return self.cache[cache_key]
            self._cache_misses += 1
        
        start_time = time.time()
        
        try:
            if self.fallback_mode or not self.client or not self.current_model:
                outline = await self._fallback_outline(text, outline_style, max_points)
                used_fallback = True
            else:
                outline = await self._generate_outline_llm(text, outline_style, max_points)
                used_fallback = False
            
            processing_time = time.time() - start_time
            
            result = OutlineResult(
                outline=outline,
                processing_time=processing_time,
                used_fallback=used_fallback,
                model_name=self.current_model if not used_fallback else "fallback",
                input_length=len(text)
            )
            
            # Cache result
            with self.lock:
                self._processing_times.append(processing_time)
                if len(self._processing_times) > 1000:
                    self._processing_times = self._processing_times[-1000:]
                self.cache[cache_key] = result
            
            return result
            
        except Exception as e:
            logger.error(f"Outline generation failed: {e}")
            self._error_count += 1
            self._last_error = str(e)
            
            # Fallback on error
            if not self.fallback_mode and self.config.enable_fallback:
                logger.info("Falling back to rule-based outline due to error")
                outline = await self._fallback_outline(text, outline_style, max_points)
                processing_time = time.time() - start_time
                return OutlineResult(
                    outline=outline,
                    processing_time=processing_time,
                    used_fallback=True,
                    model_name="fallback",
                    input_length=len(text)
                )
            else:
                raise
    
    async def summarize_context(
        self, 
        text: str, 
        summary_type: str = "concise",
        max_tokens: Optional[int] = None
    ) -> SummaryResult:
        """
        Generate context summarization for memory management.
        
        Args:
            text: Text to summarize
            summary_type: Type of summary ("concise", "detailed", "key_points")
            max_tokens: Maximum tokens for summary
            
        Returns:
            SummaryResult with generated summary
        """
        if not text or not text.strip():
            return SummaryResult(
                summary="",
                processing_time=0.0,
                used_fallback=True,
                input_length=0,
                compression_ratio=0.0
            )
        
        # Check cache first
        cache_key = self._get_cache_key(f"summary:{summary_type}:{text}")
        with self.lock:
            if cache_key in self.cache:
                self._cache_hits += 1
                return self.cache[cache_key]
            self._cache_misses += 1
        
        start_time = time.time()
        max_tokens = max_tokens or self.config.summary_max_tokens
        
        try:
            if self.fallback_mode or not self.client or not self.current_model:
                summary = await self._fallback_summary(text, summary_type)
                used_fallback = True
            else:
                summary = await self._generate_summary_llm(text, summary_type, max_tokens)
                used_fallback = False
            
            processing_time = time.time() - start_time
            compression_ratio = len(summary) / len(text) if text else 0.0
            
            result = SummaryResult(
                summary=summary,
                processing_time=processing_time,
                used_fallback=used_fallback,
                model_name=self.current_model if not used_fallback else "fallback",
                input_length=len(text),
                compression_ratio=compression_ratio
            )
            
            # Cache result
            with self.lock:
                self._processing_times.append(processing_time)
                if len(self._processing_times) > 1000:
                    self._processing_times = self._processing_times[-1000:]
                self.cache[cache_key] = result
            
            return result
            
        except Exception as e:
            logger.error(f"Context summarization failed: {e}")
            self._error_count += 1
            self._last_error = str(e)
            
            # Fallback on error
            if not self.fallback_mode and self.config.enable_fallback:
                logger.info("Falling back to rule-based summary due to error")
                summary = await self._fallback_summary(text, summary_type)
                processing_time = time.time() - start_time
                compression_ratio = len(summary) / len(text) if text else 0.0
                return SummaryResult(
                    summary=summary,
                    processing_time=processing_time,
                    used_fallback=True,
                    model_name="fallback",
                    input_length=len(text),
                    compression_ratio=compression_ratio
                )
            else:
                raise
    
    async def _generate_scaffold_llm(
        self, 
        text: str, 
        scaffold_type: str, 
        max_tokens: int,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate scaffolding using the loaded model with enhanced prompts."""
        # Create appropriate prompt based on scaffold type with enhanced context awareness
        if scaffold_type == "reasoning":
            prompt = f"### Instruction:\n{text}\n\n### Response:\n"
        elif scaffold_type == "structure":
            prompt = f"Structure following content into logical sections: {text}\n\nStructure:"
        elif scaffold_type == "conversation":
            prompt = f"Create a conversation flow outline for discussing: {text}\n\nConversation flow:"
        elif scaffold_type == "analysis":
            prompt = f"Create an analytical framework for: {text}\n\nAnalysis framework:"
        elif scaffold_type == "fill":
            prompt = f"{text}\n\nContinue logically:"
        else:
            prompt = f"Create a structured scaffold for: {text}\n\nScaffold:"
        
        # Add context-aware enhancements if available
        if context:
            user_level = context.get("user_level", "intermediate")
            if user_level == "novice":
                prompt += "\n(Provide simple, clear steps)"
            elif user_level == "expert":
                prompt += "\n(Focus on key insights and advanced considerations)"
            
            # Add conversation history context if available
            if context.get("conversation_history"):
                prompt = f"Given ongoing conversation context, {prompt.lower()}"
        
        messages = [{"role": "user", "content": prompt}]
        client = self._require_client()
        
        # Run inference in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: client.chat(
                messages, 
                max_tokens=max_tokens,
                temperature=self.config.temperature,
                stream=False
            )
        )
        
        return response.strip() if response else ""
    
    async def _generate_outline_llm(
        self, 
        text: str, 
        outline_style: str, 
        max_points: int
    ) -> List[str]:
        """Generate outline using the loaded model with enhanced styles."""
        style_instruction = {
            "bullet": "Create a bullet point outline",
            "numbered": "Create a numbered outline", 
            "structured": "Create a structured hierarchical outline",
            "conversation_flow": "Create a conversation flow outline with natural discussion points",
            "analytical": "Create an analytical outline with logical progression",
            "exploratory": "Create an exploratory outline for investigating topic"
        }.get(outline_style, "Create an outline")
        
        # Enhanced prompt construction
        if outline_style == "conversation_flow":
            prompt = f"{style_instruction} with {max_points} discussion phases for: {text}\n\nConversation outline:"
        elif outline_style == "analytical":
            prompt = f"{style_instruction} with {max_points} analytical steps for: {text}\n\nAnalytical outline:"
        else:
            prompt = f"{style_instruction} with {max_points} main points for: {text}\n\nOutline:"
        
        messages = [{"role": "user", "content": prompt}]
        client = self._require_client()
        
        # Run inference in thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat(
                messages,
                max_tokens=self.config.outline_max_tokens,
                temperature=self.config.temperature,
                stream=False
            )
        )
        
        # Enhanced parsing for different outline styles
        if response:
            lines = response.strip().split('\n')
            outline = []
            for line in lines:
                line = line.strip()
                # More flexible parsing for different formats
                if line and (line.startswith('-') or line.startswith('•') or 
                           line.startswith('*') or line.startswith('→') or
                           any(line.startswith(f"{i}.") for i in range(1, 10)) or
                           any(line.startswith(f"Phase {i}") for i in range(1, 10)) or
                           any(line.startswith(f"Step {i}") for i in range(1, 10))):
                    # Clean up formatting while preserving meaningful prefixes
                    clean_line = line.lstrip('-•*→0123456789. ').strip()
                    # Handle "Phase" and "Step" prefixes
                    if line.startswith(("Phase", "Step")):
                        clean_line = line.strip()
                    if clean_line:
                        outline.append(clean_line)
            return outline[:max_points]
        
        return []
    
    async def _generate_summary_llm(
        self, 
        text: str, 
        summary_type: str, 
        max_tokens: int
    ) -> str:
        """Generate summary using the loaded model with enhanced types."""
        type_instruction = {
            "concise": "Summarize concisely in 2-3 sentences",
            "detailed": "Provide a comprehensive summary with key details",
            "key_points": "Extract most important key points",
            "contextual": "Summarize with focus on context and implications",
            "actionable": "Summarize with emphasis on actionable insights",
            "conversational": "Summarize in a conversational, accessible way"
        }.get(summary_type, "Summarize")
        
        # Enhanced prompt construction based on summary type
        if summary_type == "contextual":
            prompt = f"{type_instruction}: {text}\n\nContextual summary:"
        elif summary_type == "actionable":
            prompt = f"{type_instruction}: {text}\n\nActionable summary:"
        elif summary_type == "conversational":
            prompt = f"{type_instruction}: {text}\n\nConversational summary:"
        else:
            prompt = f"{type_instruction}: {text}\n\nSummary:"
        
        messages = [{"role": "user", "content": prompt}]
        client = self._require_client()
        
        # Run inference in thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.chat(
                messages,
                max_tokens=max_tokens,
                temperature=self.config.temperature,
                stream=False
            )
        )
        
        return response.strip() if response else ""
    
    async def _fallback_scaffold(self, text: str, scaffold_type: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Generate enhanced rule-based scaffolding when model is unavailable."""
        if scaffold_type == "reasoning":
            # Enhanced reasoning steps with better analysis
            sentences = text.replace('?', '.').replace('!', '.').split('.')
            sentences = [s.strip() for s in sentences if s.strip()]
            if len(sentences) > 1:
                return f"1. Analyze: {sentences[0][:60]}...\n2. Evaluate: {sentences[-1][:60]}...\n3. Synthesize findings\n4. Draw evidence-based conclusions"
            else:
                return f"1. Break down core question\n2. Identify key factors and constraints\n3. Analyze relationships and implications\n4. Formulate reasoned conclusions"
        
        elif scaffold_type == "structure":
            # Enhanced structural breakdown with better organization
            words = text.split()
            if len(words) > 15:
                return f"Overview: {' '.join(words[:7])}...\nCore Analysis: {' '.join(words[7:14])}...\nImplications: Key insights and next steps\nConclusion: Summary and recommendations"
            elif len(words) > 5:
                return f"Main Topic: {' '.join(words[:5])}...\nKey Points: Analysis and details\nSummary: Conclusions and takeaways"
            else:
                return f"Focus: {text[:100]}...\nAnalysis: Context and implications\nOutcome: Key insights"
        
        elif scaffold_type == "conversation":
            return f"Opening: Introduce topic of {text[:40]}...\nExploration: Discuss key aspects and perspectives\nDeepening: Address complexities and nuances\nSynthesis: Integrate insights and conclusions"
        
        elif scaffold_type == "analysis":
            return f"Problem Definition: {text[:50]}...\nData Gathering: Identify relevant information\nPattern Recognition: Find connections and trends\nEvaluation: Assess significance and implications\nConclusions: Synthesize findings"
        
        elif scaffold_type == "fill":
            # Enhanced continuation with better context awareness
            words = text.split()
            if words:
                last_word = words[-1]
                if "?" in text:
                    return f"To address question about '{last_word}', we should consider..."
                elif any(word in text.lower() for word in ["because", "since", "therefore"]):
                    return f"Building on '{last_word}', this leads to..."
                else:
                    return f"Continuing from '{last_word}', the logical next step involves..."
            else:
                return "The discussion continues with relevant analysis and supporting details..."
        
        else:
            # Enhanced generic scaffold with better structure
            key_words = [word for word in text.split() if len(word) > 4][:3]
            return f"Framework for {' '.join(key_words) if key_words else 'analysis'}:\n• Context: {text[:50]}...\n• Key factors and relationships\n• Implications and consequences\n• Actionable insights and next steps"
    
    async def _fallback_outline(self, text: str, outline_style: str, max_points: int) -> List[str]:
        """Generate simple rule-based outline when model is unavailable."""
        # Break text into sentences and create outline points
        sentences = text.replace('?', '.').replace('!', '.').split('.')
        sentences = [s.strip() for s in sentences if s.strip()]
        
        outline = []
        for i, sentence in enumerate(sentences[:max_points]):
            if len(sentence) > 10:  # Skip very short fragments
                # Truncate long sentences
                clean_sentence = sentence[:80] + "..." if len(sentence) > 80 else sentence
                outline.append(clean_sentence)
        
        # If we don't have enough points, add generic ones
        while len(outline) < min(3, max_points):
            if len(outline) == 0:
                outline.append("Main topic analysis")
            elif len(outline) == 1:
                outline.append("Key considerations")
            elif len(outline) == 2:
                outline.append("Conclusions and next steps")
        
        return outline
    
    async def _fallback_summary(self, text: str, summary_type: str) -> str:
        """Generate simple rule-based summary when model is unavailable."""
        # Simple extractive summarization
        sentences = text.replace('?', '.').replace('!', '.').split('.')
        sentences = [s.strip() for s in sentences if s.strip() and len(s) > 10]
        
        if not sentences:
            return "No content to summarize."
        
        if summary_type == "key_points":
            # Take first few sentences as key points
            points = sentences[:3]
            return "Key points: " + "; ".join(points)
        
        elif summary_type == "detailed":
            # Take more sentences for detailed summary
            summary_sentences = sentences[:min(5, len(sentences))]
            return " ".join(summary_sentences)
        
        else:  # concise
            # Take first and last sentence if available
            if len(sentences) == 1:
                return sentences[0]
            elif len(sentences) >= 2:
                return f"{sentences[0]} ... {sentences[-1]}"
            else:
                return sentences[0] if sentences else "Brief summary of content."
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text."""
        # Include model name and config in cache key
        config_hash = hashlib.md5(
            f"{self.current_model}_{self.config.temperature}_{self.config.max_tokens}".encode()
        ).hexdigest()[:8]
        text_hash = hashlib.md5(text.encode()).hexdigest()
        return f"smalllm:{config_hash}:{text_hash}"
    
    def get_health_status(self) -> SmallLMHealthStatus:
        """Get current health status of service."""
        with self.lock:
            cache_total = self._cache_hits + self._cache_misses
            cache_hit_rate = self._cache_hits / cache_total if cache_total > 0 else 0.0
            
            avg_processing_time = (
                sum(self._processing_times) / len(self._processing_times)
                if self._processing_times else 0.0
            )
            
            # Get list of available models
            available_models = [name for name, info in self.MODEL_REGISTRY.items() if info.is_available]
            
            return SmallLMHealthStatus(
                is_healthy=not self.fallback_mode or self.config.enable_fallback,
                model_loaded=self.current_model is not None and not self.fallback_mode,
                fallback_mode=self.fallback_mode,
                cache_size=len(self.cache),
                cache_hit_rate=cache_hit_rate,
                avg_processing_time=avg_processing_time,
                error_count=self._error_count,
                last_error=self._last_error,
                current_model=self.current_model,
                available_models=available_models
            )
    
    def get_available_models(self) -> List[ModelInfo]:
        """Get list of all available models with their information."""
        return [info for info in self.MODEL_REGISTRY.values()]
    
    def switch_model(self, model_name: str) -> bool:
        """Switch to a different model."""
        if model_name not in self.MODEL_REGISTRY:
            logger.error(f"Unknown model: {model_name}")
            return False
        
        model_info = self.MODEL_REGISTRY[model_name]
        
        # Check if model is available locally
        if not model_info.is_available:
            # Try to download the model
            if not self._download_model(model_name):
                logger.error(f"Failed to download model: {model_name}")
                return False
        
        # Load the new model
        model_path = self.models_dir / f"{model_name}.gguf"
        if self.client and model_path.exists():
            try:
                load_result = self.client.load_model(str(model_path))
                if load_result.get("status") == "success":
                    # Update current model
                    if self.current_model:
                        self.MODEL_REGISTRY[self.current_model].is_loaded = False
                    self.current_model = model_name
                    self.MODEL_REGISTRY[model_name].is_loaded = True
                    
                    # Clear cache since model changed
                    self.clear_cache()
                    
                    logger.info(f"Switched to model: {model_name}")
                    return True
                else:
                    logger.error(f"Failed to load model {model_name}: {load_result.get('error')}")
                    return False
            except Exception as e:
                logger.error(f"Error switching to model {model_name}: {e}")
                return False
        else:
            logger.error(f"Cannot switch to model {model_name}: client unavailable or model file missing")
            return False
    
    def clear_cache(self):
        """Clear service cache."""
        with self.lock:
            self.cache.clear()
            logger.info("Small Language Model service cache cleared")
    
    def reset_metrics(self):
        """Reset monitoring metrics."""
        with self.lock:
            self._cache_hits = 0
            self._cache_misses = 0
            self._processing_times = []
            self._error_count = 0
            self._last_error = None
            logger.info("Small Language Model service metrics reset")


# Factory function for easy instantiation
def get_small_language_model_service(
    config: Optional[SmallLanguageModelConfig] = None,
    models_dir: Optional[str] = None
) -> SmallLanguageModelService:
    """Factory function to create Small Language Model service instance."""
    return SmallLanguageModelService(config=config, models_dir=models_dir)
