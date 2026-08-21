"""
Production Inference Services Factory
Comprehensive factory for initializing and wiring all inference runtime services.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class InferenceServiceConfig:
    """Configuration for inference services."""

    def __init__(
        self,
        # Runtime enablement
        enable_local_gguf: bool = False,
        enable_transformers: bool = True,
        enable_core_helpers: bool = True,
        # Local GGUF settings
        local_gguf_n_ctx: int = 2048,
        local_gguf_n_batch: int = 512,
        local_gguf_n_gpu_layers: int = 0,
        local_gguf_n_threads: Optional[int] = None,
        # Transformers settings
        transformers_device: str = "auto",
        transformers_torch_dtype: str = "auto",
        transformers_quantization: Optional[str] = None,
        transformers_use_flash_attention: bool = False,
        # Model store settings
        enable_model_store: bool = True,
        model_store_db_path: str = "~/.kari/models/model_store.db",
        # Performance settings
        auto_select_optimal_runtime: bool = True,
    ):
        self.enable_local_gguf = enable_local_gguf
        self.enable_transformers = enable_transformers
        self.enable_core_helpers = enable_core_helpers

        self.local_gguf_n_ctx = local_gguf_n_ctx
        self.local_gguf_n_batch = local_gguf_n_batch
        self.local_gguf_n_gpu_layers = local_gguf_n_gpu_layers
        self.local_gguf_n_threads = local_gguf_n_threads

        self.transformers_device = transformers_device
        self.transformers_torch_dtype = transformers_torch_dtype
        self.transformers_quantization = transformers_quantization
        self.transformers_use_flash_attention = transformers_use_flash_attention

        self.enable_model_store = enable_model_store
        self.model_store_db_path = model_store_db_path

        self.auto_select_optimal_runtime = auto_select_optimal_runtime


class InferenceServiceFactory:
    """
    Factory for creating and wiring inference services.

    This factory ensures all inference runtimes (Transformers, Core Helpers)
    are properly initialized, configured, and wired together for production use.
    """

    def __init__(self, config: Optional[InferenceServiceConfig] = None):
        self.config = config or InferenceServiceConfig()
        self._services = {}
        self._runtimes = {}
        logger.info("InferenceServiceFactory initialized")

    def create_local_gguf_runtime(self, model_path: Optional[str] = None):
        """Create and configure the local GGUF runtime."""
        if not self.config.enable_local_gguf:
            logger.info("Local GGUF runtime disabled by configuration")
            return None

        try:
            from ai_karen_engine.inference.local_gguf_runtime import LocalGGUFRuntime

            runtime = LocalGGUFRuntime(
                model_path=model_path,
                n_ctx=self.config.local_gguf_n_ctx,
                n_batch=self.config.local_gguf_n_batch,
                n_gpu_layers=self.config.local_gguf_n_gpu_layers,
                n_threads=self.config.local_gguf_n_threads,
            )

            self._runtimes["local_gguf"] = runtime
            logger.info("Local GGUF runtime created successfully")
            return runtime

        except ImportError as e:
            logger.warning(f"Local GGUF runtime unavailable: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create Local GGUF runtime: {e}")
            return None

    def create_transformers_runtime(self, model_path: Optional[str] = None):
        """Create and configure Transformers runtime."""
        if not self.config.enable_transformers:
            logger.info("Transformers runtime disabled by configuration")
            return None

        try:
            from ai_karen_engine.inference.transformers_runtime import TransformersRuntime

            # Default fallback model path if none provided
            if not model_path:
                # Try to find a local instructor model - prioritize verified working models
                default_paths = [
                    "models/transformers/Qwen--Qwen3.5-0.8B",
                    "models/transformers/deepseek-ai--DeepSeek-R1-Distill-Qwen-1.5B",
                ]
                for p in default_paths:
                    if Path(p).exists():
                        model_path = p
                        break

            runtime = TransformersRuntime(
                model_path=model_path,
                device=self.config.transformers_device,
                torch_dtype=self.config.transformers_torch_dtype,
                quantization=self.config.transformers_quantization,
                use_flash_attention=self.config.transformers_use_flash_attention,
            )

            # Pre-warm if we have a model path
            if model_path and hasattr(runtime, "warm"):
                logger.info(f"Initiating pre-warm for Transformers fallback: {model_path}")
                # Pre-warm is threaded in runtime.__init__ if model_path is passed, 
                # but we call it explicitly here just to be sure.
                # runtime.warm(model_path) 

            self._runtimes["transformers"] = runtime
            logger.info("Transformers runtime created successfully")
            return runtime

        except ImportError as e:
            logger.warning(f"Transformers runtime unavailable (transformers not installed): {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create Transformers runtime: {e}")
            return None

    def create_core_helpers_runtime(self):
        """Create and configure core helpers runtime."""
        if not self.config.enable_core_helpers:
            logger.info("Core helpers runtime disabled by configuration")
            return None

        try:
            from ai_karen_engine.inference.core_helpers_runtime import CoreHelpersRuntime

            runtime = CoreHelpersRuntime()

            self._runtimes["core_helpers"] = runtime
            logger.info("Core helpers runtime created successfully")
            return runtime

        except Exception as e:
            logger.error(f"Failed to create core helpers runtime: {e}")
            return None

    def create_model_store(self):
        """Create and configure unified model store."""
        if not self.config.enable_model_store:
            logger.info("Model store disabled by configuration")
            return None

        try:
            from ai_karen_engine.inference.model_store import ModelStore

            store = ModelStore(db_path=self.config.model_store_db_path)

            self._services["model_store"] = store
            logger.info("Model store created successfully")
            return store

        except Exception as e:
            logger.error(f"Failed to create model store: {e}")
            return None

    def get_available_runtimes(self) -> List[str]:
        """
        Get list of available (successfully initialized) runtimes.

        Returns:
            List of runtime names that are available
        """
        return list(self._runtimes.keys())

    def select_optimal_runtime(self, model_format: str) -> Optional[str]:
        """
        Select the optimal runtime for a given model format.

        Args:
            model_format: Model format (gguf, safetensors, etc.)

        Returns:
            Runtime name or None
        """
        if not self.config.auto_select_optimal_runtime:
            return None

        # Format-to-runtime mapping
        runtime_preferences = {
            "gguf": ["transformers"], # Use Transformers if GGUF is provided, or rely on other providers
            "safetensors": ["transformers"],
            "fp16": ["transformers"],
            "bf16": ["transformers"],
            "int8": ["transformers"],
            "int4": ["transformers"],
        }

        preferred_runtimes = runtime_preferences.get(model_format.lower(), [])
        available_runtimes = self.get_available_runtimes()

        # Return first available preferred runtime
        for runtime in preferred_runtimes:
            if runtime in available_runtimes:
                logger.info(
                    f"Selected {runtime} as optimal runtime for {model_format} format"
                )
                return runtime

        # Fallback to any available runtime
        if available_runtimes:
            fallback = available_runtimes[0]
            logger.info(
                f"Using fallback runtime {fallback} for {model_format} format"
            )
            return fallback

        logger.warning(f"No runtime available for {model_format} format")
        return None

    def create_all_runtimes(self) -> Dict[str, Any]:
        """
        Create all inference runtimes.

        This is the main entry point for full inference system initialization.

        Returns:
            Dictionary of all created runtimes
        """
        logger.info("Creating all inference runtimes")

        # Create runtimes (without loading models yet)
        if self.config.enable_local_gguf:
            self.create_local_gguf_runtime()
        self.create_transformers_runtime()
        self.create_core_helpers_runtime()

        # Create model store
        self.create_model_store()

        logger.info(
            f"Inference runtimes created: {list(self._runtimes.keys())}"
        )
        return self._runtimes

    def get_runtime(self, runtime_name: str):
        """Get a runtime by name."""
        return self._runtimes.get(runtime_name)

    def get_service(self, service_name: str):
        """Get a service by name."""
        return self._services.get(service_name)

    def get_all_runtimes(self) -> Dict[str, Any]:
        """Get all created runtimes."""
        return self._runtimes.copy()

    def get_all_services(self) -> Dict[str, Any]:
        """Get all created services."""
        return self._services.copy()

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on inference services.

        Returns:
            Dictionary with health status of all services
        """
        health = {
            "available_runtimes": list(self._runtimes.keys()),
            "runtime_count": len(self._runtimes),
        }

        # Check each runtime
        for runtime_name, runtime in self._runtimes.items():
            try:
                if hasattr(runtime, "health_check"):
                    health[runtime_name] = runtime.health_check()
                else:
                    health[runtime_name] = {"status": "available"}
            except Exception as e:
                health[runtime_name] = {"status": "error", "error": str(e)}

        # Check model store
        model_store = self.get_service("model_store")
        if model_store:
            try:
                health["model_store"] = {
                    "status": "available",
                    "model_count": len(model_store.list_models()),
                }
            except Exception as e:
                health["model_store"] = {"status": "error", "error": str(e)}

        return health


# Global factory instance
_global_factory: Optional[InferenceServiceFactory] = None


def get_inference_service_factory(
    config: Optional[InferenceServiceConfig] = None,
) -> InferenceServiceFactory:
    """
    Get or create global inference service factory.

    Args:
        config: Optional configuration for the factory

    Returns:
        InferenceServiceFactory instance
    """
    global _global_factory

    if _global_factory is None:
        _global_factory = InferenceServiceFactory(config)
        logger.info("Global inference service factory created")

    return _global_factory


def get_local_gguf_runtime():
    """Get or create global local GGUF runtime."""
    factory = get_inference_service_factory()
    runtime = factory.get_runtime("local_gguf")

    if runtime is None:
        runtime = factory.create_local_gguf_runtime()

    return runtime


def get_transformers_runtime():
    """Get or create global Transformers runtime."""
    factory = get_inference_service_factory()
    runtime = factory.get_runtime("transformers")

    if runtime is None:
        runtime = factory.create_transformers_runtime()

    return runtime


def get_model_store():
    """Get or create global model store."""
    factory = get_inference_service_factory()
    store = factory.get_service("model_store")

    if store is None:
        store = factory.create_model_store()

    return store


__all__ = [
    "InferenceServiceConfig",
    "InferenceServiceFactory",
    "get_inference_service_factory",
    "get_local_gguf_runtime",
    "get_transformers_runtime",
    "get_model_store",
]
