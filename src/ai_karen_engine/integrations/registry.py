"""
Provider and Runtime Registry System

This module implements a tiered registry system that separates providers (where models come from)
from runtimes (how models execute). This enables flexible model management with intelligent
routing and compatibility matching.

Key Features:
- Extensible provider registration (OpenAI, Gemini, DeepSeek, HuggingFace, etc.)
- Runtime registry for different execution engines (local GGUF, Transformers)
- Compatibility matching between models and runtimes
- Health monitoring and capability detection
- Thread-safe operations with instance caching
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union

logger = logging.getLogger(__name__)


def _get_runtime_endpoints():
    """Return central service endpoints if available."""
    try:
        from ai_karen_engine.config.runtime import get_runtime_settings

        return get_runtime_settings().endpoints
    except Exception:
        return None

# -----------------------------
# Data Models
# -----------------------------


@dataclass
class ProviderSpec:
    """Specification for a model provider (where models come from)."""

    name: str
    requires_api_key: bool
    description: str = ""
    category: str = "LLM"  # LLM, embedding, multimodal, etc.

    # Optional discovery function to fetch available models
    discover: Optional[Callable[[], List[Dict[str, Any]]]] = None

    # Optional validation function for API keys/configuration
    validate: Optional[Callable[[Dict[str, Any]], bool]] = None

    # Fallback model list when discovery fails
    fallback_models: List[Dict[str, Any]] = field(default_factory=list)

    # Provider capabilities
    capabilities: Set[str] = field(
        default_factory=set
    )  # streaming, embeddings, vision, etc.

    # Health check function
    health_check: Optional[Callable[[], Dict[str, Any]]] = None

    # Initialization requirements
    required_env_vars: List[str] = field(default_factory=list)
    required_dependencies: List[str] = field(default_factory=list)
    required_files: List[str] = field(default_factory=list)

    # Error handling configuration
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout_seconds: float = 30.0

    # Health monitoring configuration
    health_check_interval: int = 60
    health_check_timeout: float = 10.0

    # Fallback configuration
    fallback_priority: int = 50
    can_fallback_to: List[str] = field(default_factory=list)

    # Recovery configuration
    auto_recovery_enabled: bool = True
    recovery_check_interval: int = 300


@dataclass
class RuntimeSpec:
    """Specification for a model runtime (how models execute)."""

    name: str
    description: str = ""

    # Model families this runtime supports (llama, mistral, qwen, phi, etc.)
    family: List[str] = field(default_factory=list)

    # Model formats this runtime supports (gguf, safetensors, fp16, etc.)
    supports: List[str] = field(default_factory=list)

    # Function to load/initialize a model in this runtime
    load: Optional[Callable[[Dict[str, Any]], Any]] = None

    # Health check function
    health: Optional[Callable[[], Dict[str, Any]]] = None

    # Resource requirements and capabilities
    requires_gpu: bool = False
    memory_efficient: bool = False
    supports_streaming: bool = False
    supports_batching: bool = False

    # Performance characteristics
    startup_time: str = "medium"  # fast, medium, slow
    throughput: str = "medium"  # low, medium, high

    # Priority for selection (higher = preferred)
    priority: int = 50


@dataclass
class ModelMetadata:
    """Metadata for a specific model."""

    id: str
    name: str
    provider: str
    family: str = ""  # llama, mistral, qwen, etc.
    format: str = ""  # gguf, safetensors, etc.
    size: Optional[int] = None  # Size in bytes
    parameters: Optional[str] = None  # 7B, 13B, etc.
    quantization: Optional[str] = None  # Q4_K_M, fp16, etc.
    context_length: Optional[int] = None
    capabilities: Set[str] = field(default_factory=set)
    local_path: Optional[str] = None
    download_url: Optional[str] = None
    license: Optional[str] = None
    description: str = ""


@dataclass
class HealthStatus:
    """Health status for providers and runtimes."""

    status: str  # healthy, unhealthy, unknown, degraded
    last_check: Optional[float] = None
    error_message: Optional[str] = None
    response_time: Optional[float] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InitializationResult:
    """Result of provider initialization."""

    provider_name: str
    success: bool
    error_message: Optional[str] = None
    missing_dependencies: List[str] = field(default_factory=list)
    configuration_issues: List[str] = field(default_factory=list)
    initialization_time: float = 0.0
    instance: Optional[Any] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of configuration validation."""

    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_env_vars: List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)


@dataclass
class ProviderDiagnostics:
    """Detailed diagnostic information for a provider."""

    name: str
    status: str
    health_score: float
    last_successful_request: Optional[datetime]
    error_count: int
    configuration: Dict[str, Any]
    capabilities: List[str]
    models: List[str]
    dependencies: Dict[str, bool]
    initialization_result: Optional[InitializationResult] = None


# -----------------------------
# Registry Implementation
# -----------------------------


class LLMRegistry:
    """
    Unified registry for providers and runtimes with intelligent compatibility matching.

    This registry separates concerns:
    - Providers: Where models come from (OpenAI API, HuggingFace Hub, local files)
    - Runtimes: How models execute (local GGUF, Transformers)
    """

    def __init__(self):
        self._providers: Dict[str, ProviderSpec] = {}
        self._runtimes: Dict[str, RuntimeSpec] = {}
        self._provider_instances: Dict[str, Dict[int, Any]] = {}
        self._runtime_instances: Dict[str, Dict[int, Any]] = {}
        self._health_status: Dict[str, HealthStatus] = {}
        self._disabled_providers: Set[str] = set()
        self._initialization_results: Dict[str, InitializationResult] = {}
        self._provider_diagnostics: Dict[str, ProviderDiagnostics] = {}
        self._lock = threading.RLock()

        # Auto-register core providers and runtimes
        self._register_core_components()

    # ---------- Provider Registration ----------

    def register_provider(self, spec: ProviderSpec) -> None:
        """Register a model provider."""
        with self._lock:
            self._providers[spec.name] = spec
            self._provider_instances.setdefault(spec.name, {})
            self._health_status[f"provider:{spec.name}"] = HealthStatus(
                status="unknown"
            )
            logger.info(f"Registered provider: {spec.name}")

    def unregister_provider(self, name: str) -> bool:
        """Unregister a provider and clean up instances."""
        with self._lock:
            if name not in self._providers:
                return False

            # Clean up instances
            instances = self._provider_instances.pop(name, {})
            for cache_key, instance in instances.items():
                self._shutdown_instance(instance, f"provider:{name}")

            # Remove from registry
            del self._providers[name]
            self._health_status.pop(f"provider:{name}", None)
            logger.info(f"Unregistered provider: {name}")
            return True

    def disable_provider(self, name: str) -> bool:
        """Mark a provider as disabled without unregistering it."""
        with self._lock:
            if name not in self._providers:
                return False
            self._disabled_providers.add(name)
            logger.info(f"Disabled provider: {name}")
            return True

    def enable_provider(self, name: str) -> bool:
        """Re-enable a previously disabled provider."""
        with self._lock:
            if name not in self._providers:
                return False
            self._disabled_providers.discard(name)
            logger.info(f"Enabled provider: {name}")
            return True

    def get_provider(self, name: str, **init_kwargs: Any) -> Optional[Any]:
        """Get or create a provider instance."""
        with self._lock:
            spec = self._providers.get(name)
            if not spec:
                logger.debug(f"Provider '{name}' not registered")
                return None

            # Cache instances by kwargs hash
            bucket = self._provider_instances.setdefault(name, {})
            try:
                cache_key = hash(frozenset(init_kwargs.items()))
            except TypeError:
                cache_key = hash(repr(sorted(init_kwargs.items())))

            if cache_key not in bucket:
                # Create new instance - this would be implemented by specific providers
                logger.debug(
                    f"Creating provider instance '{name}' with kwargs={init_kwargs}"
                )
                # For now, return the spec itself as a placeholder
                bucket[cache_key] = spec

            return bucket[cache_key]

    def initialize_all_providers(self) -> Dict[str, InitializationResult]:
        """Initialize all registered providers with comprehensive error handling."""
        logger.info("Starting comprehensive provider initialization...")
        results = {}

        # First, run dependency check
        try:
            from .dependency_checker import DependencyChecker

            dep_checker = DependencyChecker(self)
            dep_report = dep_checker.check_all_dependencies()
            logger.info(f"Dependency check complete: {dep_report.overall_status}")
        except Exception as e:
            logger.warning(f"Dependency check failed: {e}")
            dep_report = None

        with self._lock:
            for provider_name, spec in self._providers.items():
                if provider_name in self._disabled_providers:
                    logger.info(f"Skipping disabled provider: {provider_name}")
                    continue

                start_time = time.time()
                result = self._initialize_single_provider(
                    provider_name, spec, dep_report
                )
                result.initialization_time = time.time() - start_time

                results[provider_name] = result
                self._initialization_results[provider_name] = result

                # Log result
                if result.success:
                    logger.info(
                        f"✓ Provider '{provider_name}' initialized successfully in {result.initialization_time:.2f}s"
                    )
                    if result.warnings:
                        for warning in result.warnings:
                            logger.warning(f"  Warning: {warning}")
                else:
                    logger.error(
                        f"✗ Provider '{provider_name}' initialization failed: {result.error_message}"
                    )
                    if result.missing_dependencies:
                        logger.error(
                            f"  Missing dependencies: {', '.join(result.missing_dependencies)}"
                        )
                        # Provide installation guidance
                        if dep_report and provider_name in dep_report.provider_status:
                            dep_status = dep_report.provider_status[provider_name]
                            logger.info(
                                f"  Installation guide:\n{dep_status.installation_guide}"
                            )
                    if result.configuration_issues:
                        logger.error(
                            f"  Configuration issues: {', '.join(result.configuration_issues)}"
                        )

        # Summary with recommendations
        successful = sum(1 for r in results.values() if r.success)
        total = len(results)
        logger.info(
            f"Provider initialization complete: {successful}/{total} providers initialized successfully"
        )

        if dep_report and dep_report.global_recommendations:
            logger.info("Global recommendations:")
            for rec in dep_report.global_recommendations:
                logger.info(f"  • {rec}")

        return results

    def _initialize_single_provider(
        self, provider_name: str, spec: ProviderSpec, dep_report=None
    ) -> InitializationResult:
        """Initialize a single provider with comprehensive error handling."""
        result = InitializationResult(provider_name=provider_name, success=False)

        try:
            logger.debug(f"Initializing provider: {provider_name}")

            # Step 1: Use dependency report if available
            if dep_report and provider_name in dep_report.provider_status:
                dep_status = dep_report.provider_status[provider_name]
                if not dep_status.all_dependencies_met:
                    result.missing_dependencies = dep_status.missing_required
                    result.error_message = f"Missing required dependencies: {', '.join(dep_status.missing_required)}"
                    # Add fallback suggestions
                    if dep_status.fallback_suggestions:
                        result.warnings.extend(
                            [
                                f"Fallback suggestion: {suggestion}"
                                for suggestion in dep_status.fallback_suggestions
                            ]
                        )
                    return result
            else:
                # Fallback to manual dependency checking
                missing_deps = []
                for dep in spec.required_dependencies:
                    try:
                        __import__(dep)
                    except ImportError:
                        missing_deps.append(dep)

                if missing_deps:
                    result.missing_dependencies = missing_deps
                    result.error_message = (
                        f"Missing required dependencies: {', '.join(missing_deps)}"
                    )
                    return result

            # Step 2: Check required environment variables
            missing_env_vars = []
            for env_var in spec.required_env_vars:
                if not os.getenv(env_var):
                    missing_env_vars.append(env_var)

            if missing_env_vars:
                result.configuration_issues.extend(
                    [f"Missing environment variable: {var}" for var in missing_env_vars]
                )
                result.error_message = f"Missing required environment variables: {', '.join(missing_env_vars)}"
                return result

            # Step 3: Check required files
            missing_files = []
            for file_path in spec.required_files:
                if not Path(file_path).exists():
                    missing_files.append(file_path)

            if missing_files:
                result.configuration_issues.extend(
                    [f"Missing required file: {file}" for file in missing_files]
                )
                result.error_message = (
                    f"Missing required files: {', '.join(missing_files)}"
                )
                return result

            # Step 4: Validate configuration if validator exists
            if spec.validate:
                try:
                    config = self._get_provider_config(provider_name)
                    if not spec.validate(config):
                        result.configuration_issues.append(
                            "Configuration validation failed"
                        )
                        result.error_message = (
                            "Provider configuration validation failed"
                        )
                        return result
                except Exception as e:
                    result.configuration_issues.append(
                        f"Configuration validation error: {str(e)}"
                    )
                    result.error_message = f"Configuration validation error: {str(e)}"
                    return result

            # Step 5: Attempt to create provider instance
            try:
                instance = self._create_provider_instance(provider_name, spec)
                if instance:
                    result.instance = instance
                    result.success = True
                    logger.debug(
                        f"Provider '{provider_name}' instance created successfully"
                    )
                else:
                    result.error_message = "Failed to create provider instance"
                    return result
            except Exception as e:
                result.error_message = f"Provider instance creation failed: {str(e)}"
                logger.debug(
                    f"Provider '{provider_name}' instance creation failed: {traceback.format_exc()}"
                )
                return result

            # Step 6: Perform initial health check
            try:
                health_result = self.health_check(f"provider:{provider_name}")
                if health_result.status == "unhealthy":
                    result.warnings.append(
                        f"Initial health check failed: {health_result.error_message}"
                    )
            except Exception as e:
                result.warnings.append(f"Initial health check error: {str(e)}")

            # Step 7: Test model discovery if available
            if spec.discover:
                try:
                    models = spec.discover()
                    if not models and not spec.fallback_models:
                        result.warnings.append(
                            "No models discovered and no fallback models available"
                        )
                    else:
                        logger.debug(
                            f"Provider '{provider_name}' discovered {len(models)} models"
                        )
                except Exception as e:
                    result.warnings.append(f"Model discovery failed: {str(e)}")

            result.success = True
            return result

        except Exception as e:
            result.error_message = f"Unexpected initialization error: {str(e)}"
            logger.error(
                f"Unexpected error initializing provider '{provider_name}': {traceback.format_exc()}"
            )
            return result

    def _get_provider_config(self, provider_name: str) -> Dict[str, Any]:
        """Get configuration for a provider from environment variables."""
        config = {}

        # Common configuration patterns
        api_key_vars = [
            f"{provider_name.upper()}_API_KEY",
            f"{provider_name.upper()}_KEY",
            f"API_KEY_{provider_name.upper()}",
        ]

        for var in api_key_vars:
            value = os.getenv(var)
            if value:
                config["api_key"] = value
                break

        # Provider-specific configurations
        endpoints = _get_runtime_endpoints()
        if provider_name == "openai":
            config.update(
                {
                    "api_key": os.getenv("OPENAI_API_KEY", ""),
                    "base_url": os.getenv(
                        "OPENAI_BASE_URL",
                        endpoints.openai_base_url if endpoints else "https://api.openai.com/v1",
                    ),
                    "organization": os.getenv("OPENAI_ORGANIZATION", ""),
                }
            )
        elif provider_name == "gemini":
            config.update(
                {
                    "api_key": os.getenv(
                        "GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", "")
                    ),
                    "base_url": os.getenv(
                        "GEMINI_BASE_URL",
                        endpoints.gemini_base_url if endpoints else "https://generativelanguage.googleapis.com/v1beta",
                    ),
                }
            )
        elif provider_name == "deepseek":
            config.update(
                {
                    "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
                    "base_url": os.getenv(
                        "DEEPSEEK_BASE_URL",
                        endpoints.deepseek_base_url if endpoints else "https://api.deepseek.com/v1",
                    ),
                }
            )
        elif provider_name == "huggingface":
            config.update(
                {
                    "api_key": os.getenv(
                        "HUGGINGFACE_API_KEY", os.getenv("HF_TOKEN", "")
                    ),
                    "base_url": os.getenv(
                        "HUGGINGFACE_BASE_URL",
                        endpoints.huggingface_base_url if endpoints else "https://api-inference.huggingface.co",
                    ),
                    "cache_dir": os.getenv("HF_CACHE_DIR", ""),
                }
            )

        return config

    def _create_provider_instance(
        self, provider_name: str, spec: ProviderSpec
    ) -> Optional[Any]:
        """Create an instance of a provider."""
        try:
            # This is a placeholder - actual provider instances would be created
            # by importing and instantiating the specific provider classes
            config = self._get_provider_config(provider_name)

            # For now, we'll return the spec with config attached
            # In a real implementation, this would create actual provider instances
            instance = {
                "spec": spec,
                "config": config,
                "provider_name": provider_name,
                "created_at": datetime.now(),
            }

            return instance

        except Exception as e:
            logger.error(
                f"Failed to create provider instance for '{provider_name}': {e}"
            )
            return None

    def validate_provider_config(self, provider_name: str) -> ValidationResult:
        """Validate provider configuration including dependencies and API keys."""
        result = ValidationResult(valid=True)

        spec = self._providers.get(provider_name)
        if not spec:
            result.valid = False
            result.errors.append(f"Provider '{provider_name}' not registered")
            return result

        # Check environment variables
        for env_var in spec.required_env_vars:
            if not os.getenv(env_var):
                result.missing_env_vars.append(env_var)
                result.errors.append(f"Missing environment variable: {env_var}")

        # Check dependencies
        for dep in spec.required_dependencies:
            try:
                __import__(dep)
            except ImportError:
                result.errors.append(f"Missing dependency: {dep}")

        # Check files
        for file_path in spec.required_files:
            if not Path(file_path).exists():
                result.missing_files.append(file_path)
                result.errors.append(f"Missing file: {file_path}")

        # Validate configuration
        if spec.validate:
            try:
                config = self._get_provider_config(provider_name)
                if not spec.validate(config):
                    result.errors.append("Configuration validation failed")
            except Exception as e:
                result.errors.append(f"Configuration validation error: {str(e)}")

        result.valid = len(result.errors) == 0
        return result

    def get_provider_diagnostics(
        self, provider_name: str
    ) -> Optional[ProviderDiagnostics]:
        """Get detailed diagnostic information for a provider."""
        spec = self._providers.get(provider_name)
        if not spec:
            return None

        health_status = self.get_health_status(f"provider:{provider_name}")
        init_result = self._initialization_results.get(provider_name)

        # Calculate health score
        health_score = 0.0
        if health_status:
            if health_status.status == "healthy":
                health_score = 1.0
            elif health_status.status == "degraded":
                health_score = 0.5
            elif health_status.status == "unknown":
                health_score = 0.3

        # Get configuration (sanitized)
        config = self._get_provider_config(provider_name)
        sanitized_config = {}
        for key, value in config.items():
            if "key" in key.lower() or "token" in key.lower():
                sanitized_config[key] = "***" if value else ""
            else:
                sanitized_config[key] = value

        # Get models
        models = []
        if spec.discover:
            try:
                discovered = spec.discover()
                models = [
                    model.get("id", model.get("name", "unknown"))
                    for model in discovered
                ]
            except Exception:
                models = [
                    model.get("id", model.get("name", "unknown"))
                    for model in spec.fallback_models
                ]
        else:
            models = [
                model.get("id", model.get("name", "unknown"))
                for model in spec.fallback_models
            ]

        # Check dependencies
        dependencies = {}
        for dep in spec.required_dependencies:
            try:
                __import__(dep)
                dependencies[dep] = True
            except ImportError:
                dependencies[dep] = False

        return ProviderDiagnostics(
            name=provider_name,
            status=health_status.status if health_status else "unknown",
            health_score=health_score,
            last_successful_request=None,  # Would be tracked in real implementation
            error_count=0,  # Would be tracked in real implementation
            configuration=sanitized_config,
            capabilities=list(spec.capabilities),
            models=models,
            dependencies=dependencies,
            initialization_result=init_result,
        )

    def repair_provider(self, provider_name: str) -> InitializationResult:
        """Attempt to repair a failed provider by re-initializing dependencies."""
        logger.info(f"Attempting to repair provider: {provider_name}")

        spec = self._providers.get(provider_name)
        if not spec:
            return InitializationResult(
                provider_name=provider_name,
                success=False,
                error_message=f"Provider '{provider_name}' not registered",
            )

        # Clear any cached instances
        self._provider_instances.pop(provider_name, {})

        # Re-initialize the provider
        start_time = time.time()
        result = self._initialize_single_provider(provider_name, spec)
        result.initialization_time = time.time() - start_time

        # Update stored results
        self._initialization_results[provider_name] = result

        if result.success:
            logger.info(f"✓ Provider '{provider_name}' repaired successfully")
            # Re-enable if it was disabled
            self._disabled_providers.discard(provider_name)
        else:
            logger.error(
                f"✗ Provider '{provider_name}' repair failed: {result.error_message}"
            )

        return result

    def get_installation_guidance(self, provider_name: str) -> Dict[str, Any]:
        """Get installation guidance for a provider."""
        try:
            from .dependency_checker import DependencyChecker

            dep_checker = DependencyChecker(self)
            dep_status = dep_checker.check_provider_dependencies(provider_name)

            return {
                "provider_name": provider_name,
                "dependencies_met": dep_status.all_dependencies_met,
                "missing_required": dep_status.missing_required,
                "missing_optional": dep_status.missing_optional,
                "installation_guide": dep_status.installation_guide,
                "fallback_suggestions": dep_status.fallback_suggestions,
            }
        except Exception as e:
            logger.error(
                f"Error getting installation guidance for {provider_name}: {e}"
            )
            return {"provider_name": provider_name, "error": str(e)}

    def get_system_dependency_report(self) -> Dict[str, Any]:
        """Get comprehensive system dependency report."""
        try:
            from .dependency_checker import DependencyChecker

            dep_checker = DependencyChecker(self)
            report = dep_checker.check_all_dependencies()

            return {
                "overall_status": report.overall_status,
                "provider_count": len(report.provider_status),
                "ready_providers": [
                    name
                    for name, status in report.provider_status.items()
                    if status.all_dependencies_met
                ],
                "providers_with_issues": [
                    name
                    for name, status in report.provider_status.items()
                    if not status.all_dependencies_met
                ],
                "global_recommendations": report.global_recommendations,
                "quick_setup_commands": report.quick_setup_commands,
                "system_info": report.system_info,
            }
        except Exception as e:
            logger.error(f"Error getting system dependency report: {e}")
            return {"error": str(e)}

    # ---------- Runtime Registration ----------

    def register_runtime(self, spec: RuntimeSpec) -> None:
        """Register a model runtime."""
        with self._lock:
            self._runtimes[spec.name] = spec
            self._runtime_instances.setdefault(spec.name, {})
            self._health_status[f"runtime:{spec.name}"] = HealthStatus(status="unknown")
            logger.info(f"Registered runtime: {spec.name}")

    def unregister_runtime(self, name: str) -> bool:
        """Unregister a runtime and clean up instances."""
        with self._lock:
            if name not in self._runtimes:
                return False

            # Clean up instances
            instances = self._runtime_instances.pop(name, {})
            for cache_key, instance in instances.items():
                self._shutdown_instance(instance, f"runtime:{name}")

            # Remove from registry
            del self._runtimes[name]
            self._health_status.pop(f"runtime:{name}", None)
            logger.info(f"Unregistered runtime: {name}")
            return True

    def get_runtime(self, name: str, **init_kwargs: Any) -> Optional[Any]:
        """Get or create a runtime instance."""
        with self._lock:
            spec = self._runtimes.get(name)
            if not spec:
                logger.debug(f"Runtime '{name}' not registered")
                return None

            # Cache instances by kwargs hash
            bucket = self._runtime_instances.setdefault(name, {})
            try:
                cache_key = hash(frozenset(init_kwargs.items()))
            except TypeError:
                cache_key = hash(repr(sorted(init_kwargs.items())))

            if cache_key not in bucket:
                logger.debug(
                    f"Creating runtime instance '{name}' with kwargs={init_kwargs}"
                )
                # For now, return the spec itself as a placeholder
                bucket[cache_key] = spec

            return bucket[cache_key]

    # ---------- Compatibility Matching ----------

    def compatible_runtimes(self, model_meta: ModelMetadata) -> List[str]:
        """Find compatible runtimes for a given model."""
        compatible = []

        with self._lock:
            for runtime_name, runtime_spec in self._runtimes.items():
                if self._is_compatible(model_meta, runtime_spec):
                    compatible.append(runtime_name)

        # Sort by priority (higher priority first)
        compatible.sort(key=lambda name: self._runtimes[name].priority, reverse=True)
        return compatible

    def _is_compatible(self, model: ModelMetadata, runtime: RuntimeSpec) -> bool:
        """Check if a model is compatible with a runtime."""
        # Check format compatibility
        if model.format and model.format not in runtime.supports:
            return False

        # Check family compatibility
        if model.family and runtime.family and model.family not in runtime.family:
            return False

        return True

    def optimal_runtime(
        self, model_meta: ModelMetadata, requirements: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Select the optimal runtime for a model based on requirements."""
        requirements = requirements or {}
        compatible = self.compatible_runtimes(model_meta)

        if not compatible:
            return None

        # Filter by requirements
        filtered = []
        for runtime_name in compatible:
            runtime_spec = self._runtimes[runtime_name]

            # Check GPU requirement
            if (
                requirements.get("requires_gpu", False)
                and not runtime_spec.requires_gpu
            ):
                continue

            # Check memory efficiency requirement
            if (
                requirements.get("memory_efficient", False)
                and not runtime_spec.memory_efficient
            ):
                continue

            # Check streaming requirement
            if (
                requirements.get("streaming", False)
                and not runtime_spec.supports_streaming
            ):
                continue

            # Check performance requirements
            if (
                requirements.get("high_throughput", False)
                and runtime_spec.throughput != "high"
            ):
                continue

            if (
                requirements.get("fast_startup", False)
                and runtime_spec.startup_time != "fast"
            ):
                continue

            filtered.append(runtime_name)

        # Return highest priority runtime that meets requirements
        return filtered[0] if filtered else compatible[0]

    # ---------- Health Monitoring ----------

    def health_check(self, component: str) -> HealthStatus:
        """Perform health check on a provider or runtime."""
        with self._lock:
            start_time = time.time()

            try:
                if component.startswith("provider:"):
                    provider_name = component[9:]  # Remove "provider:" prefix
                    spec = self._providers.get(provider_name)
                    if not spec:
                        return HealthStatus(
                            status="not_found",
                            error_message=f"Provider {provider_name} not registered",
                        )

                    if spec.health_check:
                        result = spec.health_check()
                        status = HealthStatus(
                            status=result.get("status", "unknown"),
                            last_check=time.time(),
                            error_message=result.get("error"),
                            response_time=time.time() - start_time,
                            capabilities=result.get("capabilities", {}),
                        )
                    else:
                        status = HealthStatus(
                            status="healthy",
                            last_check=time.time(),
                            response_time=time.time() - start_time,
                        )

                elif component.startswith("runtime:"):
                    runtime_name = component[8:]  # Remove "runtime:" prefix
                    spec = self._runtimes.get(runtime_name)
                    if not spec:
                        return HealthStatus(
                            status="not_found",
                            error_message=f"Runtime {runtime_name} not registered",
                        )

                    if spec.health:
                        result = spec.health()
                        status = HealthStatus(
                            status=result.get("status", "unknown"),
                            last_check=time.time(),
                            error_message=result.get("error"),
                            response_time=time.time() - start_time,
                            capabilities=result.get("capabilities", {}),
                        )
                    else:
                        status = HealthStatus(
                            status="healthy",
                            last_check=time.time(),
                            response_time=time.time() - start_time,
                        )

                else:
                    return HealthStatus(
                        status="invalid",
                        error_message=f"Invalid component: {component}",
                    )

                self._health_status[component] = status
                return status

            except Exception as e:
                status = HealthStatus(
                    status="unhealthy",
                    last_check=time.time(),
                    error_message=str(e),
                    response_time=time.time() - start_time,
                )
                self._health_status[component] = status
                return status

    def health_check_all(self) -> Dict[str, HealthStatus]:
        """Perform health check on all registered components."""
        results = {}

        # Check all providers
        for provider_name in self._providers:
            results[f"provider:{provider_name}"] = self.health_check(
                f"provider:{provider_name}"
            )

        # Check all runtimes
        for runtime_name in self._runtimes:
            results[f"runtime:{runtime_name}"] = self.health_check(
                f"runtime:{runtime_name}"
            )

        return results

    def get_unhealthy_components(self) -> Dict[str, HealthStatus]:
        """Get all components that are currently unhealthy."""
        unhealthy = {}
        all_health = self.health_check_all()

        for component, status in all_health.items():
            if status.status in ["unhealthy", "degraded"]:
                unhealthy[component] = status

        return unhealthy

    def get_healthy_providers(self, category: Optional[str] = None) -> List[str]:
        """Get list of healthy providers, optionally filtered by category."""
        healthy_providers = []

        for provider_name in self._providers:
            if category:
                spec = self._providers[provider_name]
                if spec.category != category:
                    continue

            health = self.get_health_status(f"provider:{provider_name}")
            if health is None or health.status in ["healthy", "unknown"]:
                healthy_providers.append(provider_name)

        return healthy_providers

    def get_healthy_runtimes(self) -> List[str]:
        """Get list of healthy runtimes."""
        healthy_runtimes = []

        for runtime_name in self._runtimes:
            health = self.get_health_status(f"runtime:{runtime_name}")
            if health is None or health.status in ["healthy", "unknown"]:
                healthy_runtimes.append(runtime_name)

        return healthy_runtimes

    def monitor_health_continuously(self, interval_seconds: int = 60) -> None:
        """Start continuous health monitoring in a background thread."""
        import threading
        import time

        def health_monitor():
            while True:
                try:
                    self.health_check_all()
                    time.sleep(interval_seconds)
                except Exception as e:
                    logger.error(f"Health monitoring error: {e}")
                    time.sleep(interval_seconds)

        monitor_thread = threading.Thread(target=health_monitor, daemon=True)
        monitor_thread.start()
        logger.info(
            f"Started continuous health monitoring with {interval_seconds}s interval"
        )

    def get_health_status(self, component: str) -> Optional[HealthStatus]:
        """Get cached health status for a component."""
        return self._health_status.get(component)

    # ---------- Listing and Discovery ----------

    def list_providers(
        self, category: Optional[str] = None, healthy_only: bool = False
    ) -> List[str]:
        """List registered providers."""
        with self._lock:
            providers = []
            for name, spec in self._providers.items():
                if name in self._disabled_providers:
                    continue
                if category and spec.category != category:
                    continue

                if healthy_only:
                    health = self._health_status.get(f"provider:{name}")
                    if health and health.status not in ["healthy", "unknown"]:
                        continue

                providers.append(name)

            return providers

    def list_llm_providers(self, healthy_only: bool = False) -> List[str]:
        """List only LLM providers (excludes UI frameworks like CopilotKit)."""
        return self.list_providers(category="LLM", healthy_only=healthy_only)

    def list_runtimes(self, healthy_only: bool = False) -> List[str]:
        """List registered runtimes."""
        with self._lock:
            runtimes = []
            for name in self._runtimes:
                if healthy_only:
                    health = self._health_status.get(f"runtime:{name}")
                    if health and health.status not in ["healthy", "unknown"]:
                        continue

                runtimes.append(name)

            return runtimes

    def get_provider_spec(self, name: str) -> Optional[ProviderSpec]:
        """Get provider specification."""
        return self._providers.get(name)

    def get_runtime_spec(self, name: str) -> Optional[RuntimeSpec]:
        """Get runtime specification."""
        return self._runtimes.get(name)

    # ---------- Model Listing ----------

    def list_models(self, provider: str) -> List[ModelMetadata]:
        """
        List available models for a specific provider.

        Args:
            provider: Name of provider

        Returns:
            List of ModelMetadata objects for provider's models
        """
        spec = self._providers.get(provider)
        if not spec:
            logger.warning(f"Provider '{provider}' not found in registry")
            return []

        models = []

        # Try to discover models dynamically
        if spec.discover:
            try:
                discovered = spec.discover()
                for model_dict in discovered:
                    models.append(
                        ModelMetadata(
                            id=model_dict.get("id", model_dict.get("name", "unknown")),
                            name=model_dict.get(
                                "name", model_dict.get("id", "Unknown")
                            ),
                            provider=provider,
                            family=model_dict.get("family", ""),
                            format=model_dict.get("format", ""),
                            parameters=model_dict.get("parameters"),
                            context_length=model_dict.get("context_length"),
                            capabilities=set(model_dict.get("capabilities", [])),
                            local_path=model_dict.get("local_path"),
                            download_url=model_dict.get("download_url"),
                            license=model_dict.get("license"),
                            description=model_dict.get("description", ""),
                        )
                    )
            except Exception as e:
                logger.debug(f"Model discovery failed for {provider}: {e}")

        # Add fallback models if discovery failed or returned no models
        if not models and spec.fallback_models:
            for model_dict in spec.fallback_models:
                models.append(
                    ModelMetadata(
                        id=model_dict.get("id", model_dict.get("name", "unknown")),
                        name=model_dict.get("name", model_dict.get("id", "Unknown")),
                        provider=provider,
                        family=model_dict.get("family", ""),
                        format=model_dict.get("format", ""),
                        parameters=model_dict.get("parameters"),
                        context_length=model_dict.get("context_length"),
                        capabilities=set(model_dict.get("capabilities", [])),
                        local_path=model_dict.get("local_path"),
                        download_url=model_dict.get("download_url"),
                        license=model_dict.get("license"),
                        description=model_dict.get("description", ""),
                    )
                )

        return models

    def get_provider_instance(self, provider: str) -> Optional[Any]:
        """
        Get provider instance for health checks and model testing.

        Args:
            provider: Name of provider

        Returns:
            Provider instance or None
        """
        spec = self._providers.get(provider)
        if not spec:
            logger.warning(f"Provider '{provider}' not found in registry")
            return None

        # Get or create provider instance
        instance = self.get_provider(provider)
        return instance

    # ---------- Internal Methods ----------

    def _register_core_components(self) -> None:
        """Register core providers and runtimes."""
        try:
            self._register_core_providers()
            self._register_core_runtimes()
        except Exception as e:
            logger.warning(f"Failed to register core components: {e}")

    def _register_core_providers(self) -> None:
        """Register core model providers."""
        # OpenAI Provider
        openai_spec = ProviderSpec(
            name="openai",
            requires_api_key=True,
            description="OpenAI GPT models via API",
            category="LLM",
            capabilities={"streaming", "embeddings", "function_calling", "vision"},
            discover=self._discover_openai_models,
            validate=self._validate_openai_key,
            health_check=self._health_check_openai,
            required_env_vars=["OPENAI_API_KEY"],
            required_dependencies=["openai"],
            fallback_priority=90,
            can_fallback_to=["gemini", "deepseek", "huggingface"],
            fallback_models=[
                {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "family": "gpt",
                    "capabilities": ["text", "vision"],
                },
                {
                    "id": "gpt-4o-mini",
                    "name": "GPT-4o Mini",
                    "family": "gpt",
                    "capabilities": ["text"],
                },
                {
                    "id": "gpt-3.5-turbo",
                    "name": "GPT-3.5 Turbo",
                    "family": "gpt",
                    "capabilities": ["text"],
                },
            ],
        )
        self.register_provider(openai_spec)

        # Gemini Provider - only register if API key is available
        if os.getenv("GEMINI_API_KEY"):
            gemini_spec = ProviderSpec(
                name="gemini",
                requires_api_key=True,
                description="Google Gemini models via API",
                category="LLM",
                capabilities={"streaming", "embeddings", "vision"},
                discover=self._discover_gemini_models,
                validate=self._validate_gemini_key,
                health_check=self._health_check_gemini,
                required_env_vars=["GEMINI_API_KEY"],
                required_dependencies=["google-generativeai"],
                fallback_priority=85,
                can_fallback_to=["openai", "deepseek", "huggingface"],
                fallback_models=[
                    {
                        "id": "gemini-1.5-pro",
                        "name": "Gemini 1.5 Pro",
                        "family": "gemini",
                        "capabilities": ["text", "vision"],
                    },
                    {
                        "id": "gemini-1.5-flash",
                        "name": "Gemini 1.5 Flash",
                        "family": "gemini",
                        "capabilities": ["text", "vision"],
                    },
                ],
            )
            self.register_provider(gemini_spec)
        else:
            logger.debug(
                "Gemini API key not found, skipping Gemini provider registration"
            )

        # DeepSeek Provider
        deepseek_spec = ProviderSpec(
            name="deepseek",
            requires_api_key=True,
            description="DeepSeek models optimized for coding and reasoning",
            category="LLM",
            capabilities={"streaming", "function_calling"},
            discover=self._discover_deepseek_models,
            validate=self._validate_deepseek_key,
            health_check=self._health_check_deepseek,
            required_env_vars=["DEEPSEEK_API_KEY"],
            required_dependencies=["openai"],  # DeepSeek uses OpenAI-compatible API
            fallback_priority=80,
            can_fallback_to=["openai", "gemini", "huggingface"],
            fallback_models=[
                {
                    "id": "deepseek-chat",
                    "name": "DeepSeek Chat",
                    "family": "deepseek",
                    "capabilities": ["text", "code"],
                },
                {
                    "id": "deepseek-coder",
                    "name": "DeepSeek Coder",
                    "family": "deepseek",
                    "capabilities": ["code"],
                },
            ],
        )
        self.register_provider(deepseek_spec)

        # HuggingFace Provider
        huggingface_spec = ProviderSpec(
            name="huggingface",
            requires_api_key=False,  # Can work without API key for downloading models
            description="HuggingFace Hub model download service (NOT an LLM provider)",
            category="DOWNLOAD_SERVICE",  # Changed from "LLM" to avoid listing as LLM provider
            capabilities={"model_download", "storage"},
            discover=None,  # No model discovery - it's a download service
            validate=self._validate_huggingface_key,
            health_check=self._health_check_huggingface,
            required_dependencies=["transformers", "torch"],
            fallback_models=[],  # No fallback models - not an LLM provider
        )
        self.register_provider(huggingface_spec)

        # Local Provider (for local model files)
        local_spec = ProviderSpec(
            name="local",
            requires_api_key=False,
            description="Local model files (GGUF, safetensors, etc.)",
            category="LLM",
            capabilities={"local_execution", "privacy"},
            discover=self._discover_local_models,
            health_check=self._health_check_local,
            required_dependencies=[],
            fallback_priority=60,
            can_fallback_to=[],
            fallback_models=[],  # Will be populated by scanning local files
        )
        self.register_provider(local_spec)

        # CopilotKit Provider (UI Framework - NOT an LLM provider)
        copilotkit_spec = ProviderSpec(
            name="copilotkit",
            requires_api_key=False,
            description="CopilotKit UI framework for AI-powered interfaces",
            category="UI_FRAMEWORK",  # Separate category to exclude from LLM lists
            capabilities={"ui_integration", "code_assistance", "contextual_help"},
            fallback_models=[],  # No models - it's a UI framework
            discover=None,  # No model discovery - it's a UI framework
        )
        self.register_provider(copilotkit_spec)

    def _register_core_runtimes(self) -> None:
        """Register core model runtimes."""
        try:
            from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
                TransformersRuntime,
            )
            from ai_karen_engine.core.model_runtime.providers.core_helpers_runtime import (
                CoreHelpersRuntime,
            )

            # Local GGUF Runtime
            if LocalGGUFRuntime and LocalGGUFRuntime.is_available():
                local_gguf_spec = RuntimeSpec(
                    name="local_gguf",
                    description="Local GGUF runtime for compatible models",
                    family=["llama", "mistral", "qwen", "phi", "gemma", "codellama"],
                    supports=["gguf"],
                    requires_gpu=False,
                    memory_efficient=True,
                    supports_streaming=True,
                    supports_batching=False,
                    startup_time="fast",
                    throughput="medium",
                    priority=80,  # High priority for GGUF models
                    load=lambda kwargs: LocalGGUFRuntime(**kwargs),
                    health=lambda: {
                        "status": "healthy",
                        "message": "Local GGUF runtime available",
                    },
                )
                self.register_runtime(local_gguf_spec)

            # Transformers Runtime
            if TransformersRuntime and TransformersRuntime.is_available():
                transformers_spec = RuntimeSpec(
                    name="transformers",
                    description="HuggingFace Transformers runtime for safetensors models",
                    family=["llama", "mistral", "qwen", "phi", "gemma", "bert", "gpt"],
                    supports=["safetensors", "fp16", "bf16", "int8", "int4"],
                    requires_gpu=False,  # Can run on CPU
                    memory_efficient=False,
                    supports_streaming=True,
                    supports_batching=True,
                    startup_time="medium",
                    throughput="medium",
                    priority=60,
                    load=lambda kwargs: TransformersRuntime(**kwargs),
                    health=lambda: {
                        "status": "healthy",
                        "message": "Transformers runtime available",
                    },
                )
                self.register_runtime(transformers_spec)

            # Core Helpers Runtime (for degraded mode)
            if CoreHelpersRuntime and CoreHelpersRuntime.is_available():
                core_helpers_spec = RuntimeSpec(
                    name="core_helpers",
                    description="Lightweight models for degraded mode (default model, DistilBERT, spaCy)",
                    family=["small_llm", "distilbert"],
                    supports=["gguf", "safetensors"],
                    requires_gpu=False,
                    memory_efficient=True,
                    supports_streaming=False,
                    supports_batching=False,
                    startup_time="fast",
                    throughput="low",
                    priority=10,  # Lowest priority, fallback only
                    load=lambda kwargs: CoreHelpersRuntime(**kwargs),
                    health=lambda: {
                        "status": "healthy",
                        "message": "Core helpers runtime available",
                    },
                )
                self.register_runtime(core_helpers_spec)

        except Exception as e:
            logger.warning(f"Failed to register runtime implementations: {e}")

    def _shutdown_instance(self, instance: Any, component_name: str) -> None:
        """Gracefully shutdown an instance."""
        try:
            if hasattr(instance, "shutdown"):
                if inspect.iscoroutinefunction(instance.shutdown):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(instance.shutdown())
                    except RuntimeError:
                        asyncio.run(instance.shutdown())
                else:
                    instance.shutdown()
                logger.info(f"Shutdown {component_name} instance")
        except Exception as e:
            logger.warning(f"Error shutting down {component_name}: {e}")

    # ---------- Provider Discovery and Validation Methods ----------

    def _discover_openai_models(self) -> List[Dict[str, Any]]:
        """Discover available OpenAI models."""
        try:
            # This would normally make an API call to OpenAI
            # For now, return enhanced fallback models
            return [
                {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "family": "gpt",
                    "capabilities": ["text", "vision", "function_calling"],
                    "context_length": 128000,
                    "parameters": "Unknown",
                },
                {
                    "id": "gpt-4o-mini",
                    "name": "GPT-4o Mini",
                    "family": "gpt",
                    "capabilities": ["text", "function_calling"],
                    "context_length": 128000,
                    "parameters": "Unknown",
                },
                {
                    "id": "gpt-3.5-turbo",
                    "name": "GPT-3.5 Turbo",
                    "family": "gpt",
                    "capabilities": ["text", "function_calling"],
                    "context_length": 16385,
                    "parameters": "Unknown",
                },
            ]
        except Exception as e:
            logger.warning(f"OpenAI model discovery failed: {e}")
            return []

    def _validate_openai_key(self, config: Dict[str, Any]) -> bool:
        """Validate OpenAI API key."""
        try:
            api_key = config.get("api_key", "")
            if not api_key or not api_key.startswith("sk-"):
                return False

            # Basic format validation - real validation would make API call
            return len(api_key) > 20 and api_key.startswith("sk-")
        except Exception as e:
            logger.warning(f"OpenAI key validation failed: {e}")
            return False

    def _health_check_openai(self) -> Dict[str, Any]:
        """Health check for OpenAI provider."""
        try:
            # This would normally make a test API call
            return {
                "status": "healthy",
                "message": "OpenAI provider available",
                "capabilities": {"streaming": True, "embeddings": True, "vision": True},
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _discover_gemini_models(self) -> List[Dict[str, Any]]:
        """Discover available Gemini models."""
        try:
            return [
                {
                    "id": "gemini-1.5-pro",
                    "name": "Gemini 1.5 Pro",
                    "family": "gemini",
                    "capabilities": ["text", "vision", "code"],
                    "context_length": 2000000,
                    "parameters": "Unknown",
                },
                {
                    "id": "gemini-1.5-flash",
                    "name": "Gemini 1.5 Flash",
                    "family": "gemini",
                    "capabilities": ["text", "vision", "code"],
                    "context_length": 1000000,
                    "parameters": "Unknown",
                },
            ]
        except Exception as e:
            logger.warning(f"Gemini model discovery failed: {e}")
            return []

    def _validate_gemini_key(self, config: Dict[str, Any]) -> bool:
        """Validate Gemini API key."""
        try:
            api_key = config.get("api_key", "")
            # Basic format validation for Google API keys
            return bool(api_key and len(api_key) > 20)
        except Exception as e:
            logger.warning(f"Gemini key validation failed: {e}")
            return False

    def _health_check_gemini(self) -> Dict[str, Any]:
        """Health check for Gemini provider."""
        try:
            return {
                "status": "healthy",
                "message": "Gemini provider available",
                "capabilities": {"streaming": True, "vision": True, "code": True},
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _discover_deepseek_models(self) -> List[Dict[str, Any]]:
        """Discover available DeepSeek models."""
        try:
            return [
                {
                    "id": "deepseek-chat",
                    "name": "DeepSeek Chat",
                    "family": "deepseek",
                    "capabilities": ["text", "code", "reasoning"],
                    "context_length": 32768,
                    "parameters": "67B",
                },
                {
                    "id": "deepseek-coder",
                    "name": "DeepSeek Coder",
                    "family": "deepseek",
                    "capabilities": ["code", "reasoning"],
                    "context_length": 16384,
                    "parameters": "33B",
                },
            ]
        except Exception as e:
            logger.warning(f"DeepSeek model discovery failed: {e}")
            return []

    def _validate_deepseek_key(self, config: Dict[str, Any]) -> bool:
        """Validate DeepSeek API key."""
        try:
            api_key = config.get("api_key", "")
            # Basic format validation
            return bool(api_key and len(api_key) > 20)
        except Exception as e:
            logger.warning(f"DeepSeek key validation failed: {e}")
            return False

    def _health_check_deepseek(self) -> Dict[str, Any]:
        """Health check for DeepSeek provider."""
        try:
            return {
                "status": "healthy",
                "message": "DeepSeek provider available",
                "capabilities": {"streaming": True, "code": True, "reasoning": True},
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _discover_huggingface_models(self) -> List[Dict[str, Any]]:
        """Discover available HuggingFace models."""
        try:
            return [
                {
                    "id": "microsoft/DialoGPT-large",
                    "name": "DialoGPT Large",
                    "family": "gpt",
                    "format": "safetensors",
                    "capabilities": ["text", "conversation"],
                    "parameters": "774M",
                },
                {
                    "id": "microsoft/DialoGPT-medium",
                    "name": "DialoGPT Medium",
                    "family": "gpt",
                    "format": "safetensors",
                    "capabilities": ["text", "conversation"],
                    "parameters": "355M",
                },
            ]
        except Exception as e:
            logger.warning(f"HuggingFace model discovery failed: {e}")
            return []

    def _validate_huggingface_key(self, config: Dict[str, Any]) -> bool:
        """Validate HuggingFace API key (optional)."""
        try:
            api_key = config.get("api_key", "")
            # HuggingFace keys are optional for many models
            if not api_key:
                return True  # Valid to not have a key
            # Basic format validation for HF tokens
            return bool(api_key and len(api_key) > 10)
        except Exception as e:
            logger.warning(f"HuggingFace key validation failed: {e}")
            return True  # Default to valid since key is optional

    def _health_check_huggingface(self) -> Dict[str, Any]:
        """Health check for HuggingFace provider."""
        try:
            return {
                "status": "healthy",
                "message": "HuggingFace provider available",
                "capabilities": {"local_execution": True, "model_download": True},
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _discover_local_models(self) -> List[Dict[str, Any]]:
        """Discover local model files."""
        try:
            models = []

            # Scan model directories using absolute paths
            model_dirs = [
                Path("/app/models/local-gguf"),  # GGUF models for local runtime
                Path("/app/models/stable-diffusion"),  # Diffusion models
                # Note: transformers models are handled by separate runtime, not scanned here
            ]

            for model_dir in model_dirs:
                if model_dir.exists():
                    # Scan for GGUF files
                    for gguf_file in model_dir.rglob("*.gguf"):
                        # Skip duplicates
                        model_id = gguf_file.stem
                        if any(m.get("id") == model_id for m in models):
                            continue
                        models.append(
                            {
                                "id": gguf_file.stem,
                                "name": gguf_file.stem.replace("-", " ").title(),
                                "family": "llama",  # Better family detection
                                "format": "gguf",
                                "local_path": str(gguf_file),
                                "capabilities": ["text"],
                                "size": gguf_file.stat().st_size
                                if gguf_file.exists()
                                else None,
                            }
                        )

            logger.info(
                f"Discovered {len(models)} local models: {[m['id'] for m in models]}"
            )
            return models
        except Exception as e:
            logger.warning(f"Local model discovery failed: {e}")
            return []

    def _health_check_local(self) -> Dict[str, Any]:
        """Health check for local provider."""
        try:
            return {
                "status": "healthy",
                "message": "Local provider available",
                "capabilities": {"local_execution": True, "privacy": True},
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# -----------------------------
# Global Registry Instance
# -----------------------------

_global_registry: Optional[LLMRegistry] = None
_global_lock = threading.RLock()


def get_registry() -> LLMRegistry:
    """Get the global LLM registry instance."""
    global _global_registry
    if _global_registry is None:
        with _global_lock:
            if _global_registry is None:
                _global_registry = LLMRegistry()
    return _global_registry


def initialize_registry() -> LLMRegistry:
    """Initialize a fresh global registry."""
    global _global_registry
    with _global_lock:
        _global_registry = LLMRegistry()
    return _global_registry


# Convenience functions
def register_provider(spec: ProviderSpec) -> None:
    """Register a provider in the global registry."""
    get_registry().register_provider(spec)


def register_runtime(spec: RuntimeSpec) -> None:
    """Register a runtime in the global registry."""
    get_registry().register_runtime(spec)


def compatible_runtimes(model_meta: ModelMetadata) -> List[str]:
    """Find compatible runtimes for a model."""
    return get_registry().compatible_runtimes(model_meta)


def optimal_runtime(
    model_meta: ModelMetadata, requirements: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Select optimal runtime for a model."""
    return get_registry().optimal_runtime(model_meta, requirements)


__all__ = [
    "ProviderSpec",
    "RuntimeSpec",
    "ModelMetadata",
    "HealthStatus",
    "InitializationResult",
    "ValidationResult",
    "ProviderDiagnostics",
    "LLMRegistry",
    "get_registry",
    "initialize_registry",
    "register_provider",
    "register_runtime",
    "compatible_runtimes",
    "optimal_runtime",
]
