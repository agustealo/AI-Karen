"""
LLM Provider Registry

Manages registration, discovery, and health monitoring of LLM providers.
Enhanced with model orchestrator integration, schema validation, and integrity verification.
"""

import hashlib
import inspect
import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, Union, cast
import asyncio
import threading

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None

try:
    import jsonschema
    from jsonschema import validate, ValidationError

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    validate = None
    ValidationError = Exception

from ai_karen_engine.integrations.llm_utils import LLMProviderBase
from importlib import import_module
from ai_karen_engine.routing.types import RouteRequest
from ai_karen_engine.config.llm_provider_config import (
    get_provider_class_module,
    get_provider_config_manager,
    resolve_provider_class_name,
    resolve_provider_name,
)
from ai_karen_engine.config.provider_execution_resolver import (
    ProviderExecutionSpec,
    resolve_provider_execution,
)

logger = logging.getLogger("kari.llm_registry")


@dataclass
class ProviderRegistration:
    """Provider registration information."""

    name: str
    provider_class: str
    description: str
    supports_streaming: bool = False
    supports_embeddings: bool = False
    requires_api_key: bool = False
    default_model: str = ""
    health_status: str = "unknown"  # unknown, healthy, unhealthy
    last_health_check: Optional[float] = None
    error_message: Optional[str] = None


@dataclass
class ModelEntry:
    """Model registry entry with enhanced metadata."""

    model_id: str
    library: str
    revision: str
    installed_at: str
    install_path: str
    files: List[Dict[str, Union[str, int]]]
    total_size: int
    pinned: bool = False
    last_accessed: Optional[str] = None
    license_accepted: Optional[Dict[str, str]] = None
    compatibility: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class RegistryValidationError(Exception):
    """Registry validation error."""

    pass


class RegistryIntegrityError(Exception):
    """Registry integrity verification error."""

    pass


class RegistryWatcher(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):  # type: ignore[misc]
    """File system watcher for registry changes."""

    def __init__(self, registry: "LLMRegistry"):
        self.registry = registry
        self.logger = logging.getLogger("kari.registry_watcher")

    def on_modified(self, event: Any) -> None:
        """Handle registry file modifications."""
        if not WATCHDOG_AVAILABLE:
            return
        if not event.is_directory and str(event.src_path).endswith("llm_registry.json"):
            self.logger.info(f"Registry file modified: {event.src_path}")
            try:
                # Reload registry and update LLM settings
                self.registry._load_registry()
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    self.logger.debug(
                        "No running event loop available for registry update; deferred"
                    )
                else:
                    loop.create_task(self.registry.update_llm_settings())
            except Exception as ex:
                self.logger.error(f"Failed to handle registry change: {ex}")


class LLMRegistry:
    """Registry for managing LLM providers."""

    def __init__(
        self,
        registry_path: Optional[Path] = None,
        schema_path: Optional[Path] = None,
        llm_settings_path: Optional[Path] = None,
    ):
        """
        Initialize LLM registry.

        Args:
            registry_path: Path to registry JSON file (defaults to models/llm_registry.json)
            schema_path: Path to registry schema file (defaults to models/registry.schema.json)
            llm_settings_path: Path to LLM settings file (defaults to llm_settings.json)
        """
        self.registry_path = registry_path or Path("models/llm_registry.json")
        self.schema_path = schema_path or Path("models/registry.schema.json")
        self.llm_settings_path = llm_settings_path or Path("llm_settings.json")
        # Cache of provider instances keyed by name|model to allow multiple models per provider
        self._providers: Dict[str, LLMProviderBase] = {}
        self._registrations: Dict[str, ProviderRegistration] = {}
        self._model_entries: Dict[str, ModelEntry] = {}
        self._priorities: List[str] = [
            "builtin_vllm",
            "builtin_transformers",
            "ollama",
            "openai",
            "zai",
            "gemini",
            "deepseek",
            "huggingface",
            "copilotkit",
            "fallback",
        ]

        # Load schema for validation
        self._schema = self._load_schema()
        self._llm_settings_schema = self._load_llm_settings_schema()

        # Register built-in providers first so runtime lookups always have a canonical
        # baseline for local + cloud providers, then layer persisted registry state.
        self._register_configured_providers()

        # Load existing registry data next
        self._load_registry()

        # Ensure critical built-ins remain available (race-condition hardening).
        self.ensure_builtin_providers_registered()

    def _load_schema(self):
        """Load schema for validation."""
        return {
            "type": "object",
            "properties": {
                "providers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "provider_class": {"type": "string"},
                            "description": {"type": "string"},
                            "supports_streaming": {"type": "boolean"},
                            "supports_embeddings": {"type": "boolean"},
                            "requires_api_key": {"type": "boolean"},
                            "default_model": {"type": "string"},
                        },
                        "required": ["name", "provider_class"],
                    },
                }
            },
            "required": ["providers"],
        }

    def _load_llm_settings_schema(self):
        """Load LLM settings schema for validation."""
        return {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                "max_tokens": {"type": "integer", "minimum": 1},
                "top_p": {"type": "number", "minimum": 0, "maximum": 1},
                "stream": {"type": "boolean"},
            },
            "required": ["provider", "model"],
        }

    def _setup_registry_watcher(self):
        """Set up file system watcher for registry changes."""
        if not WATCHDOG_AVAILABLE or Observer is None or FileSystemEventHandler is None:
            logger.info("watchdog not available, registry auto-update disabled")
            self._observer = None
            return

        try:
            self._observer = Observer()
            self._watcher = RegistryWatcher(self)

            # Watch the directory containing the registry file
            watch_dir = self.registry_path.parent
            if watch_dir.exists():
                self._observer.schedule(
                    cast(Any, self._watcher),
                    str(watch_dir),
                    recursive=False,
                )
                self._observer.start()
                logger.info(f"Started registry watcher for {watch_dir}")
            else:
                logger.warning(f"Registry directory does not exist: {watch_dir}")

        except Exception as ex:
            logger.error(f"Failed to setup registry watcher: {ex}")
            self._observer = None

    def validate_registry_data(self, data: Dict[str, Any]) -> None:
        """
        Validate registry data against schema.

        Args:
            data: Registry data to validate

        Raises:
            RegistryValidationError: If validation fails
        """
        if not self._schema or not JSONSCHEMA_AVAILABLE:
            return

        try:
            if validate is None:
                return
            validate(instance=data, schema=self._schema)
        except ValidationError as ex:
            raise RegistryValidationError(f"Registry validation failed: {ex}")

    def compute_file_checksum(self, file_path: Path) -> str:
        """
        Compute SHA256 checksum of a file.

        Args:
            file_path: Path to file

        Returns:
            SHA256 checksum as hex string
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as ex:
            logger.error(f"Failed to compute checksum for {file_path}: {ex}")
            return ""

    def verify_model_integrity(self, model_key: str) -> Dict[str, Any]:
        """
        Verify integrity of a model's files against stored checksums.

        Args:
            model_key: Model registry key

        Returns:
            Dict with verification results
        """
        if model_key not in self._model_entries:
            return {
                "status": "not_found",
                "error": f"Model {model_key} not in registry",
            }

        entry = self._model_entries[model_key]
        install_path = Path(entry.install_path)

        if not install_path.exists():
            return {
                "status": "missing",
                "error": f"Install path {install_path} does not exist",
            }

        results: Dict[str, Any] = {
            "status": "verified",
            "files_checked": 0,
            "files_missing": 0,
            "files_corrupted": 0,
            "missing_files": [],
            "corrupted_files": [],
        }

        for file_info in entry.files:
            file_rel_path = str(file_info.get("path", ""))
            file_path = install_path / file_rel_path
            results["files_checked"] += 1

            if not file_path.exists():
                results["files_missing"] += 1
                results["missing_files"].append(file_rel_path)
                continue

            # Check size
            actual_size = file_path.stat().st_size
            expected_size = int(file_info.get("size", 0))

            if actual_size != expected_size:
                results["files_corrupted"] += 1
                results["corrupted_files"].append(
                    {
                        "path": file_rel_path,
                        "reason": "size_mismatch",
                        "expected_size": expected_size,
                        "actual_size": actual_size,
                    }
                )
                continue

            # Check checksum if available
            if "sha256" in file_info and file_info.get("sha256"):
                actual_checksum = self.compute_file_checksum(file_path)
                expected_checksum = str(file_info["sha256"])

                if actual_checksum != expected_checksum:
                    results["files_corrupted"] += 1
                    results["corrupted_files"].append(
                        {
                            "path": file_rel_path,
                            "reason": "checksum_mismatch",
                            "expected_checksum": expected_checksum,
                            "actual_checksum": actual_checksum,
                        }
                    )

        if results["files_missing"] > 0 or results["files_corrupted"] > 0:
            results["status"] = "corrupted"

        return results

    def atomic_registry_update(self, update_func, *args, **kwargs) -> Any:
        """
        Perform atomic registry update with backup and rollback capability.

        Args:
            update_func: Function to perform the update
            *args, **kwargs: Arguments for update function

        Returns:
            Result of update function

        Raises:
            Exception: If update fails and rollback is performed
        """
        # Create backup
        backup_path = None
        if self.registry_path.exists():
            backup_path = self.registry_path.with_suffix(".backup")
            shutil.copy2(self.registry_path, backup_path)

        try:
            # Perform update
            result = update_func(*args, **kwargs)

            # Clean up backup on success
            if backup_path and backup_path.exists():
                backup_path.unlink()

            return result

        except Exception as ex:
            # Rollback on failure
            if backup_path and backup_path.exists():
                if self.registry_path.exists():
                    self.registry_path.unlink()
                shutil.move(backup_path, self.registry_path)
                logger.error(f"Registry update failed, rolled back: {ex}")
            raise

    def add_model_entry(self, model_key: str, entry: ModelEntry) -> None:
        """
        Add or update a model entry in the registry.

        Args:
            model_key: Model registry key
            entry: Model entry data
        """

        def _update():
            # Load current registry data
            registry_data = self._load_model_registry_data()

            # Add/update entry
            entry_dict = asdict(entry)
            registry_data[model_key] = entry_dict

            # Validate updated data
            self.validate_registry_data(registry_data)

            # Save atomically
            self._save_model_registry_data(registry_data)

            # Update in-memory cache
            self._model_entries[model_key] = entry

        self.atomic_registry_update(_update)

    def remove_model_entry(self, model_key: str) -> None:
        """
        Remove a model entry from the registry.

        Args:
            model_key: Model registry key
        """

        def _update():
            # Load current registry data
            registry_data = self._load_model_registry_data()

            if model_key in registry_data:
                del registry_data[model_key]

                # Validate updated data
                self.validate_registry_data(registry_data)

                # Save atomically
                self._save_model_registry_data(registry_data)

                # Update in-memory cache
                if model_key in self._model_entries:
                    del self._model_entries[model_key]

        self.atomic_registry_update(_update)

    def _load_model_registry_data(self) -> Dict[str, Any]:
        """Load model registry data from file."""
        if not self.registry_path.exists():
            return {}

        try:
            with open(self.registry_path, "r") as f:
                data = json.load(f)

            # Handle both old and new registry formats
            if isinstance(data, list):
                # Old format - convert to new format
                new_data = {}
                for item in data:
                    if isinstance(item, dict) and "name" in item:
                        new_data[item["name"]] = item
                return new_data
            elif isinstance(data, dict):
                return data
            else:
                return {}

        except Exception as ex:
            logger.error(f"Failed to load model registry data: {ex}")
            return {}

    def _save_model_registry_data(self, data: Dict[str, Any]) -> None:
        """Save model registry data to file."""
        # Ensure directory exists
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temporary file first
        temp_path = self.registry_path.with_suffix(".tmp")

        try:
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)

            # Atomic move
            temp_path.replace(self.registry_path)

        except Exception as ex:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink()
            raise ex

    def _register_configured_providers(self):
        """Register all configured providers from the config manager."""
        try:
            config_mgr = get_provider_config_manager()
            provider_names = [provider.name for provider in config_mgr.list_providers()]
        except Exception:
            provider_names = list(self._priorities)

        for provider_name in provider_names:
            spec = resolve_provider_execution(provider_name)
            if spec is None:
                continue
            provider_class = self._get_provider_class_from_spec(spec)
            if provider_class is None:
                continue
            self.register_provider(
                spec.provider_id,
                provider_class,
                description=f"Execution adapter for {spec.display_name}",
                supports_streaming=spec.supports_streaming,
                supports_embeddings=spec.supports_embeddings,
                requires_api_key=spec.requires_api_key,
                default_model=spec.default_model or "",
            )

    def _load_registry(self):
        """Load registry from JSON file."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r") as f:
                    data = json.load(f)

                # Handle different registry formats
                if isinstance(data, list):
                    # Old format - provider registrations
                    for item in data:
                        if isinstance(item, dict) and "name" in item:
                            # Update existing registration or create new one
                            name = item["name"]
                            if name in self._registrations:
                                # Update existing registration with saved data
                                registration = self._registrations[name]
                                # Update all savable fields from JSON
                                for field in [
                                    "health_status",
                                    "last_health_check",
                                    "error_message",
                                    "supports_streaming",
                                    "default_model",
                                ]:
                                    if field in item:
                                        setattr(registration, field, item[field])
                            else:
                                # Create new registration from saved data
                                self._registrations[name] = ProviderRegistration(**item)

                elif isinstance(data, dict):
                    # New format - model entries
                    for model_key, entry_data in data.items():
                        if isinstance(entry_data, dict):
                            # Check if this is a provider registration or model entry
                            if "provider_class" in entry_data:
                                # Provider registration
                                name = entry_data.get("name", model_key)
                                if name in self._registrations:
                                    registration = self._registrations[name]
                                    registration.health_status = entry_data.get(
                                        "health_status", "unknown"
                                    )
                                    registration.last_health_check = entry_data.get(
                                        "last_health_check"
                                    )
                                    registration.error_message = entry_data.get(
                                        "error_message"
                                    )
                                    if "default_model" in entry_data:
                                        registration.default_model = entry_data[
                                            "default_model"
                                        ]
                                else:
                                    self._registrations[name] = ProviderRegistration(
                                        **entry_data
                                    )
                            elif "model_id" in entry_data:
                                # Model entry
                                try:
                                    self._model_entries[model_key] = ModelEntry(
                                        **entry_data
                                    )
                                except Exception as ex:
                                    logger.warning(
                                        f"Failed to load model entry {model_key}: {ex}"
                                    )

                logger.info(f"Loaded registry from {self.registry_path}")

            except Exception as ex:
                logger.warning(
                    f"Could not load registry from {self.registry_path}: {ex}"
                )
        else:
            logger.info(
                f"Registry file not found at {self.registry_path}, starting fresh"
            )

    def _save_registry(self):
        """Save registry to JSON file."""
        try:
            # Ensure directory exists
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert registrations to list of dicts
            data = [asdict(reg) for reg in self._registrations.values()]

            temp_path = self.registry_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(self.registry_path)

        except Exception as ex:
            logger.error(f"Could not save registry to {self.registry_path}: {ex}")

    def register_provider(
        self,
        name: str,
        provider_class: Type[LLMProviderBase],
        description: str = "",
        **kwargs,
    ):
        """
        Register a custom LLM provider.

        Args:
            name: Provider name
            provider_class: Provider class
            description: Provider description
            **kwargs: Additional registration parameters
        """
        # Thread-safe registration
        with _registry_lock:
            registration = ProviderRegistration(
                name=name,
                provider_class=provider_class.__name__,
                description=description,
                **kwargs,
            )

            self._registrations[name] = registration
            logger.info(f"Registered provider: {name}")

            # Save updated registry (don't wait for this to complete registration)
            try:
                self._save_registry()
            except Exception as e:
                logger.debug(
                    f"Registry save failed, but provider still registered: {e}"
                )

        # Ensure registration is immediately visible
        logger.info(f"Provider {name} registration completed")

    def _resolve_provider_alias(self, name: str) -> str:
        """Resolve common provider aliases to canonical registry names."""
        raw = (name or "").strip()
        if not raw:
            return raw
        if raw in self._registrations:
            return raw

        canonical = resolve_provider_name(raw)
        if canonical and canonical in self._registrations:
            return canonical

        normalized = raw.lower().replace("_", "-")
        if normalized == "local" and "builtin_vllm" in self._registrations:
            return "builtin_vllm"

        return raw

    def _get_provider_config_manager(self):
        """Lazy-load the provider config manager used to resolve credentials."""
        try:
            from ai_karen_engine.config.llm_provider_config import (
                get_provider_config_manager,
            )

            return get_provider_config_manager()
        except Exception:
            return None

    def _provider_is_configured(
        self, name: str, init_kwargs: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Return ``True`` when a provider is configured for runtime use."""
        registration = self._registrations.get(name)
        if not registration:
            return False

        if not registration.requires_api_key:
            return True

        if init_kwargs:
            direct_api_key = init_kwargs.get("api_key") or init_kwargs.get(
                "api_token"
            )
            if isinstance(direct_api_key, str):
                if direct_api_key.strip():
                    return True
            elif direct_api_key:
                return True

        config_mgr = self._get_provider_config_manager()
        if config_mgr is not None:
            try:
                provider_config = config_mgr.get_provider(name)
                if provider_config is not None:
                    return config_mgr.is_provider_configured(name)
            except Exception:
                logger.debug(
                    "Provider configuration lookup failed for %s",
                    name,
                    exc_info=True,
                )

        env_var = f"{name.upper().replace('-', '_')}_API_KEY"
        return bool(os.getenv(env_var))

    def get_provider(self, name: str, **init_kwargs) -> Optional[LLMProviderBase]:
        """
        Get provider instance by name.

        Args:
            name: Provider name
            **init_kwargs: Provider initialization arguments

        Returns:
            Provider instance or None if not found
        """
        # Thread-safe provider lookup with retry mechanism for race conditions
        max_retries = 3
        retry_delay = 0.01  # 10ms between retries

        resolved_name = self._resolve_provider_alias(name)
        spec = resolve_provider_execution(resolved_name)
        if spec is None:
            logger.error("Provider '%s' could not be resolved", name)
            return None
        if not spec.enabled:
            logger.debug("Skipping provider '%s' because it is disabled", resolved_name)
            return None

        # Auto-register local endpoints from canonical registry if not already registered
        if resolved_name not in self._registrations:
            self._register_local_endpoint_if_available(resolved_name, spec)

        for attempt in range(max_retries):
            try:
                resolved_name = self._resolve_provider_alias(name)
                if resolved_name not in self._registrations:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.error(
                            f"Provider '{name}' not registered after {max_retries} attempts"
                        )
                        return None

                registration = self._registrations[resolved_name]

                if spec.requires_api_key and not self._provider_is_configured(
                    resolved_name, init_kwargs
                ):
                    logger.debug(
                        "Skipping provider '%s' because it is not configured",
                        resolved_name,
                    )
                    with _registry_lock:
                        stale_keys = [
                            cache_key
                            for cache_key in self._providers.keys()
                            if cache_key.startswith(f"{resolved_name}|")
                        ]
                        for cache_key in stale_keys:
                            self._providers.pop(cache_key, None)
                    return None

                # Build cache key including model so different model inits are not conflated
                model_key = (
                    init_kwargs.get("model")
                    or spec.default_model
                    or registration.default_model
                    or ""
                )
                base_url_key = str(
                    init_kwargs.get("base_url") or spec.base_url or ""
                ).strip()
                cache_key = f"{resolved_name}|{model_key}|{base_url_key}"

                # Return cached instance if available, unless it is a stale failed instance
                if cache_key in self._providers:
                    cached = self._providers[cache_key]
                    init_error = getattr(cached, "initialization_error", None)
                    is_local_fallback = resolved_name in ["builtin_vllm", "builtin_transformers"]

                    if not init_error or is_local_fallback:
                        return cached

                    logger.info(
                        "Discarding stale cached provider instance for %s (model=%s) due to initialization error: %s",
                        resolved_name,
                        model_key,
                        init_error,
                    )
                    with _registry_lock:
                        self._providers.pop(cache_key, None)

                # Create new instance
                provider_class = self._get_provider_class_from_spec(spec)

                if provider_class:
                    # Use default model if not specified
                    if "model" not in init_kwargs and spec.default_model:
                        init_kwargs["model"] = spec.default_model

                    init_kwargs = self._apply_saved_provider_settings(
                        resolved_name, init_kwargs
                    )

                    if spec.adapter_class in {"OpenAIProvider", "OpenAICompatibleProvider"}:
                        init_kwargs.setdefault("provider_name", resolved_name)

                    if spec.requires_base_url and not init_kwargs.get("base_url"):
                        logger.debug(
                            "Skipping provider '%s' because base URL is missing",
                            resolved_name,
                        )
                        return None

                    if spec.requires_api_key and not self._provider_is_configured(
                        resolved_name, init_kwargs
                    ):
                        logger.debug(
                            "Skipping provider '%s' because it is not configured after settings resolution",
                            resolved_name,
                        )
                        return None

                    if spec.adapter_class == "CopilotKitProvider":
                        model_name = (
                            init_kwargs.get("model") or spec.default_model
                        )
                        provider_config = {
                            "model": model_name,
                            "base_url": init_kwargs.get("base_url"),
                            "api_key": init_kwargs.get("api_key"),
                        }
                        if model_name:
                            provider_config["models"] = {
                                "completion": model_name,
                                "chat": model_name,
                            }
                        provider = cast(Any, provider_class)(provider_config)
                    else:
                        provider = cast(Any, provider_class)(**init_kwargs)

                    # Thread-safe cache update
                    with _registry_lock:
                        self._providers[cache_key] = provider

                    logger.info(
                        f"Created provider instance: {resolved_name} (model={init_kwargs.get('model')})"
                    )
                    return provider
                else:
                    if attempt < max_retries - 1:
                        # Provider class not found, maybe still being imported
                        time.sleep(retry_delay)
                        continue
                    else:
                        logger.error(f"Provider class for '{resolved_name}' not found")
                        return None

            except Exception as ex:
                if attempt < max_retries - 1:
                    # Retry on transient errors
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(
                        f"Failed to create provider '{name}' after {max_retries} attempts: {ex}"
                    )
                    registration = self._registrations.get(resolved_name)
                    if registration:
                        registration.health_status = "unhealthy"
                        registration.last_health_check = time.time()
                        registration.error_message = str(ex)
                        try:
                            self._save_registry()
                        except Exception:
                            logger.debug(
                                "Failed to persist registry after provider error",
                                exc_info=True,
                            )
                    return None

        return None  # Should never reach here, but just in case

    def invalidate_provider_cache(self, name: str) -> None:
        """Remove cached provider instances for a provider so new config/secrets take effect."""
        canonical = self._resolve_provider_alias(name)
        prefixes = {f"{canonical}|"}
        stale_keys = [
            cache_key
            for cache_key in self._providers.keys()
            if any(cache_key.startswith(prefix) for prefix in prefixes)
        ]
        for cache_key in stale_keys:
            self._providers.pop(cache_key, None)
        if stale_keys:
            logger.info(
                "Invalidated %d cached provider instance(s) for %s",
                len(stale_keys),
                name,
            )

    def _apply_saved_provider_settings(
        self, name: str, init_kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Augment provider init args from persisted provider config and local secrets."""

        resolved = dict(init_kwargs)

        try:
            from ai_karen_engine.config.llm_provider_config import (
                get_provider_config_manager,
            )
            from ai_karen_engine.models.secret_manager import get_secret_manager
        except Exception:
            return resolved

        provider_config = get_provider_config_manager().get_provider(name)
        if not provider_config:
            return resolved

        if (
            "base_url" not in resolved
            and provider_config.endpoint
            and provider_config.endpoint.base_url
        ):
            resolved["base_url"] = provider_config.endpoint.base_url

        if (
            "timeout" not in resolved
            and provider_config.endpoint
            and provider_config.endpoint.timeout
        ):
            resolved["timeout"] = provider_config.endpoint.timeout

        if "max_retries" not in resolved and provider_config.endpoint:
            resolved["max_retries"] = provider_config.endpoint.max_retries

        if "api_key" not in resolved:
            api_key = None
            env_var = provider_config.authentication.api_key_env_var
            if env_var:
                secret_manager = get_secret_manager()
                api_key = secret_manager.get_secret(env_var) or os.getenv(env_var)
            if api_key:
                resolved["api_key"] = api_key
        
        # Apply custom authentication metadata from configuration
        if provider_config.authentication:
            if "api_key_header" not in resolved and provider_config.authentication.api_key_header:
                resolved["api_key_header"] = provider_config.authentication.api_key_header
            if "api_key_prefix" not in resolved and provider_config.authentication.api_key_prefix:
                resolved["api_key_prefix"] = provider_config.authentication.api_key_prefix
            if "custom_headers" not in resolved and provider_config.authentication.custom_headers:
                resolved["custom_headers"] = provider_config.authentication.custom_headers

        if name == "huggingface":
            if "api_key" in resolved and "api_token" not in resolved:
                resolved["api_token"] = resolved.pop("api_key")
            if "base_url" in resolved and "inference_endpoint" not in resolved:
                resolved["inference_endpoint"] = resolved.pop("base_url")

        registration = self._registrations.get(name)
        provider_class_name = registration.provider_class if registration else None
        provider_class = (
            self._get_provider_class(provider_class_name)
            if provider_class_name
            else None
        )
        if provider_class is None:
            return resolved

        try:
            signature = inspect.signature(provider_class.__init__)
        except (TypeError, ValueError):
            return resolved

        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if accepts_var_kwargs:
            return resolved

        accepted = {
            parameter_name
            for parameter_name in signature.parameters.keys()
            if parameter_name != "self"
        }
        return {key: value for key, value in resolved.items() if key in accepted}

    # -----------------------------
    # Provider selection integration
    # -----------------------------
    async def get_provider_with_routing(
        self,
        *,
        user_ctx: Dict[str, Any],
        query: str,
        task_type: str,
        khrp_step: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Resolve provider/model using canonical provider registry.

        KIRE retired: provider selection is owned by RuntimePolicy + ProviderRouter.
        This method now uses the canonical provider registry directly.
        """
        try:
            from ai_karen_engine.core.model_runtime.provider_registry_service import (
                get_provider_registry_service,
            )

            registry_service = get_provider_registry_service()
            provider_names = registry_service.get_all_provider_names()
            provider_name = provider_names[0] if provider_names else "builtin_vllm"

            provider = self.get_provider(provider_name)
            return {
                "provider_instance": provider,
                "decision": None,
                "provider_name": provider_name,
                "model_name": "auto",
            }
        except Exception as e:
            logger.error(f"Provider resolution failed: {e}")
            return {
                "provider_instance": None,
                "decision": None,
                "provider_name": "builtin_vllm",
                "model_name": "auto",
            }
        except Exception as ex:
            logger.error(f"KIRE routing failed, falling back. Error: {ex}")
            # Fallback to default provider construction
            prov = (
                self.default_chain(healthy_only=False)[0]
                if self.default_chain()
                else None
            )
            instance = self.get_provider(prov) if prov else None
            return {
                "provider_instance": instance,
                "decision": None,
                "provider_name": prov,
                "model_name": None,
            }

    def _get_provider_class(self, class_name: str) -> Optional[Type[LLMProviderBase]]:
        """Get provider class by name."""
        canonical_class_name = resolve_provider_class_name(class_name)
        module_path = get_provider_class_module(canonical_class_name)
        if not module_path:
            return None

        try:
            module = import_module(module_path)
        except Exception as exc:
            logger.error("Failed to import provider module '%s': %s", module_path, exc)
            return None

        provider_cls = getattr(module, canonical_class_name, None)
        if provider_cls is None:
            logger.error(
                "Provider class '%s' not found in module '%s'",
                canonical_class_name,
                module_path,
            )
        return provider_cls

    def _get_provider_class_from_spec(
        self, spec: Optional[ProviderExecutionSpec]
    ) -> Optional[Type[LLMProviderBase]]:
        """Import the executable provider class described by a resolver spec."""
        if spec is None:
            return None

        try:
            module = import_module(spec.adapter_module)
        except Exception as exc:
            logger.error(
                "Failed to import provider module '%s': %s", spec.adapter_module, exc
            )
            return None

        provider_cls = getattr(module, spec.adapter_class, None)
        if provider_cls is None:
            logger.error(
                "Provider class '%s' not found in module '%s'",
                spec.adapter_class,
                spec.adapter_module,
            )
        return provider_cls

    # -----------------------------
    # Local GGUF model resolution & verification
    # -----------------------------
    def _is_probably_valid_gguf(self, file_path: Path) -> bool:
        try:
            if not file_path.exists() or not file_path.is_file():
                return False
            if file_path.suffix.lower() != ".gguf":
                return False
            size = file_path.stat().st_size
            if size < 50 * 1024 * 1024:  # < 50MB unlikely to be valid model
                return False
            with open(file_path, "rb") as f:
                magic = f.read(4)
            return magic == b"GGUF"
        except Exception:
            return False

    def _find_model_entry_key_by_id(self, model_id: str) -> Optional[str]:
        for key, entry in self._model_entries.items():
            if entry.model_id == model_id:
                return key
        return None

    def list_providers(self) -> List[str]:
        """Get list of registered provider names."""
        return list(self._registrations.keys())

    def ensure_builtin_providers_registered(self) -> None:
        """Ensure all built-in providers are registered, fixing any race conditions."""
        # Thread-safe registration of missing built-in providers
        with _registry_lock:
            for provider_name in ["builtin_vllm", "builtin_transformers"]:
                spec = resolve_provider_execution(provider_name)
                if spec is None:
                    continue
                if provider_name not in self._registrations:
                    try:
                        provider_class = self._get_provider_class_from_spec(spec)
                        if provider_class is None:
                            continue
                        self.register_provider(
                            provider_name,
                            provider_class,
                            description=f"Execution adapter for {spec.display_name}",
                            supports_streaming=spec.supports_streaming,
                            supports_embeddings=spec.supports_embeddings,
                            requires_api_key=spec.requires_api_key,
                            default_model=spec.default_model or "",
                        )
                        logger.info(
                            f"Ensured built-in provider is registered: {provider_name}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to ensure built-in provider {provider_name} is registered: {e}"
                        )

        # Log final state for debugging
        logger.info(
            f"Registry state after ensuring built-in providers: {list(self._registrations.keys())}"
        )

    def _register_local_endpoint_if_available(self, provider_name: str, spec: Any) -> None:
        """Auto-register a local endpoint from canonical registry if not already registered."""
        with _registry_lock:
            if provider_name in self._registrations:
                return

            try:
                from ai_karen_engine.core.model_runtime.provider_registry_service import (
                    get_provider_registry_service,
                )
                registry_service = get_provider_registry_service()
                endpoint = registry_service.get_provider_endpoint(provider_name)
                if not endpoint:
                    return

                provider_class = self._get_provider_class_from_spec(spec)
                if provider_class is None:
                    return

                self.register_provider(
                    provider_name,
                    provider_class,
                    description=f"OpenAI-compatible endpoint: {endpoint.display_name}",
                    supports_streaming=endpoint.supports_streaming,
                    supports_embeddings=endpoint.supports_embeddings,
                    requires_api_key=spec.requires_api_key,
                    default_model=spec.default_model or "",
                )
                logger.info(
                    f"Auto-registered local endpoint: {provider_name}"
                )
            except Exception as e:
                logger.debug(
                    f"Could not auto-register local endpoint {provider_name}: {e}"
                )

    def ensure_registry_consistency(self) -> None:
        """Ensure registry consistency and fix any missing providers."""
        logger.info("Ensuring registry consistency...")

        # Ensure built-in providers are registered
        self.ensure_builtin_providers_registered()

        # Verify critical providers are available
        critical_providers = ["builtin_vllm", "builtin_transformers", "fallback"]
        for provider_name in critical_providers:
            if provider_name not in self._registrations:
                logger.warning(
                    f"Critical provider {provider_name} not found in registry"
                )
            else:
                logger.info(f"Critical provider {provider_name} is available")

        logger.info("Registry consistency check completed")

    def default_chain(self, healthy_only: bool = False) -> List[str]:
        """Return providers ordered by built-in priority.

        Parameters
        ----------
        healthy_only: bool
            If True, only include providers with health_status "healthy".
        """

        ordered: List[str] = []
        for name in self._priorities:
            if name not in self._registrations:
                continue
            if not self._provider_is_configured(name):
                continue
            if healthy_only and self._registrations[name].health_status not in (
                "healthy",
                "unknown",
            ):
                continue
            ordered.append(name)

        for name in self._registrations:
            if name in ordered:
                continue
            if not self._provider_is_configured(name):
                continue
            if healthy_only and self._registrations[name].health_status not in (
                "healthy",
                "unknown",
            ):
                continue
            ordered.append(name)

        return ordered

    def get_active(self) -> Optional[LLMProviderBase]:
        """
        Get the currently active LLM provider (first healthy provider from default chain).

        This method returns an instance of the first available healthy provider
        from the default priority chain. If no healthy providers are available,
        it falls back to the first available provider regardless of health status.

        Returns:
            LLMProviderBase instance or None if no providers are available
        """
        # Try to get first healthy provider
        chain = self.default_chain(healthy_only=True)
        if not chain:
            # Fallback to any provider if no healthy ones
            chain = self.default_chain(healthy_only=False)

        if chain:
            return self.get_provider(chain[0])
        return None

    def get_provider_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get provider registration information."""
        resolved_name = self._resolve_provider_alias(name)
        if resolved_name not in self._registrations:
            return None

        registration = self._registrations[resolved_name]
        info = asdict(registration)

        if registration.requires_api_key and not self._provider_is_configured(
            resolved_name
        ):
            self.invalidate_provider_cache(resolved_name)
            return info

        # Ensure provider is instantiated to gather runtime metadata
        provider = self._providers.get(resolved_name)
        if provider is None:
            provider = self.get_provider(resolved_name)

        if provider:
            try:
                provider_info_fn = getattr(provider, "get_provider_info", None)
                provider_info = provider_info_fn() if callable(provider_info_fn) else {}
                if isinstance(provider_info, dict):
                    info.update(provider_info)
            except Exception as ex:
                logger.warning(f"Could not get provider info for {name}: {ex}")

        return info

    def health_check(self, name: str) -> Dict[str, Any]:
        """Perform enhanced health check on a provider with model validation."""
        resolved_name = self._resolve_provider_alias(name)
        if resolved_name not in self._registrations:
            return {
                "status": "not_registered",
                "error": f"Provider '{name}' not registered",
            }

        try:
            registration = self._registrations[resolved_name]
            if registration.requires_api_key and not self._provider_is_configured(
                resolved_name
            ):
                with _registry_lock:
                    stale_keys = [
                        cache_key
                        for cache_key in self._providers.keys()
                        if cache_key.startswith(f"{resolved_name}|")
                    ]
                    for cache_key in stale_keys:
                        self._providers.pop(cache_key, None)
                return {
                    "status": "unavailable",
                    "error": f"Provider '{name}' is not configured",
                    "provider": resolved_name,
                }

            provider = self.get_provider(resolved_name)
            if not provider:
                return {
                    "status": "failed_to_create",
                    "error": "Could not create provider instance",
                }

            # Perform health check if provider supports it
            health_check_fn = getattr(provider, "health_check", None)
            if callable(health_check_fn):
                result = cast(Dict[str, Any], health_check_fn())
            else:
                # Basic health check - try to get provider info
                provider_info_fn = getattr(provider, "get_provider_info", None)
                if callable(provider_info_fn):
                    provider_info_fn()
                result = {"status": "healthy", "message": "Basic health check passed"}
            result = cast(Dict[str, Any], result)

            # Add model validation for providers with installed models (requirement 2.5)
            # Skip for local fallbacks as they are best-effort and handle their own loading
            if resolved_name in ["builtin_vllm", "builtin_transformers"]:
                provider_models = {}
            else:
                provider_models = self._get_models_for_provider(resolved_name)

            if provider_models:
                result["models"] = {
                    "total_count": len(provider_models),
                    "installed_models": list(provider_models.keys()),
                }

                # Perform basic model accessibility check
                accessible_models = 0
                model_errors = []

                for model_key, entry in list(provider_models.items())[
                    :3
                ]:  # Check first 3 models
                    try:
                        # Check if model files exist
                        install_path = Path(entry.install_path)
                        if not install_path.exists():
                            model_errors.append(f"{model_key}: install path missing")
                            continue

                        # Check if required files exist
                        missing_files = []
                        for file_info in entry.files[:5]:  # Check first 5 files
                            file_rel_path = str(file_info.get("path", ""))
                            file_path = install_path / file_rel_path
                            if not file_path.exists():
                                missing_files.append(file_rel_path)

                        if missing_files:
                            model_errors.append(
                                f"{model_key}: missing files {missing_files}"
                            )
                        else:
                            accessible_models += 1

                    except Exception as ex:
                        model_errors.append(f"{model_key}: {ex}")

                result["models"]["accessible_count"] = accessible_models
                result["models"]["accessibility_rate"] = accessible_models / len(
                    provider_models
                )

                if model_errors:
                    result["models"]["errors"] = model_errors[:5]  # Limit to 5 errors

                # Mark as degraded if less than 50% of models are accessible
                if result["models"]["accessibility_rate"] < 0.5:
                    result["status"] = "degraded"
                    existing_warnings = result.get("warnings", [])
                    warnings_list = (
                        list(existing_warnings)
                        if isinstance(existing_warnings, list)
                        else []
                    )
                    warnings_list.append("Less than 50% of models are accessible")
                    result["warnings"] = warnings_list

            # Update registration
            registration = self._registrations[name]
            registration.health_status = result.get("status", "unknown")
            registration.last_health_check = time.time()
            registration.error_message = result.get("error")

            # Save updated registry
            self._save_registry()

            return result

        except Exception as ex:
            # Update registration with error
            registration = self._registrations[name]
            registration.health_status = "unhealthy"
            registration.last_health_check = time.time()
            registration.error_message = str(ex)

            # Save updated registry
            self._save_registry()

            return {"status": "unhealthy", "error": str(ex)}

    def _get_library_for_provider(self, provider_name: str) -> Optional[str]:
        """Get the library type for a provider."""
        provider_library_map = {
            "builtin_vllm": "vllm",
            "builtin_transformers": "transformers",
            "huggingface": "transformers",
            "openai": None,  # API-based, no local models
            "gemini": None,  # API-based, no local models
            "deepseek": None,  # API-based, no local models
        }
        return provider_library_map.get(provider_name)

    def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Perform health check on all registered providers."""
        results = {}

        for name in self._registrations.keys():
            results[name] = self.health_check(name)

        return results

    def get_available_providers(self) -> List[str]:
        """Get list of configured providers that are currently healthy or unknown."""
        available = []

        for name, registration in self._registrations.items():
            if not self._provider_is_configured(name):
                continue
            if registration.health_status in ["healthy", "unknown"]:
                available.append(name)

        return available

    def auto_select_provider(
        self, requirements: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Automatically select the best available provider based on requirements.

        Args:
            requirements: Dict with keys like 'streaming', 'embeddings', 'api_key_available'

        Returns:
            Provider name or None if no suitable provider found
        """
        requirements = requirements or {}

        # Get available providers
        available = self.get_available_providers()

        # Filter by requirements
        suitable = []
        for name in available:
            registration = self._registrations[name]

            # Check streaming requirement
            if requirements.get("streaming") and not registration.supports_streaming:
                continue

            # Check embeddings requirement
            if requirements.get("embeddings") and not registration.supports_embeddings:
                continue

            # Check API key requirement
            if registration.requires_api_key and not requirements.get(
                "api_key_available", True
            ):
                continue

            suitable.append(name)

        # Return first suitable provider (could be enhanced with priority logic)
        return suitable[0] if suitable else None

    # Model entry management methods

    def get_model_entry(self, model_key: str) -> Optional[ModelEntry]:
        """Get model entry by key."""
        return self._model_entries.get(model_key)

    def list_model_entries(self) -> Dict[str, ModelEntry]:
        """Get all model entries."""
        return self._model_entries.copy()

    def update_model_access_time(self, model_key: str) -> None:
        """Update last access time for a model."""
        if model_key in self._model_entries:
            entry = self._model_entries[model_key]
            entry.last_accessed = datetime.now(timezone.utc).isoformat()
            self.add_model_entry(model_key, entry)

    def pin_model(self, model_key: str, pinned: bool = True) -> None:
        """Pin or unpin a model to protect from garbage collection."""
        if model_key in self._model_entries:
            entry = self._model_entries[model_key]
            entry.pinned = pinned
            self.add_model_entry(model_key, entry)

    def get_models_by_library(self, library: str) -> Dict[str, ModelEntry]:
        """Get all models for a specific library."""
        return {
            key: entry
            for key, entry in self._model_entries.items()
            if entry.library == library
        }

    def _get_runtime_compatibility(self, entry: ModelEntry) -> Dict[str, Any]:
        """Return normalized runtime compatibility metadata for a model entry."""
        compatibility = entry.compatibility or {}
        compatible_runtimes = {
            str(runtime).lower()
            for runtime in (compatibility.get("compatible_runtimes") or [])
        }
        preferred_runtime = str(compatibility.get("preferred_runtime") or "").lower()
        model_type = str(
            compatibility.get("model_type") or compatibility.get("artifact_kind") or ""
        ).lower()
        return {
            "compatible_runtimes": compatible_runtimes,
            "preferred_runtime": preferred_runtime,
            "model_type": model_type,
        }

    def _entry_matches_provider(self, entry: ModelEntry, provider_name: str) -> bool:
        """Return True when a model entry can be served by the provider."""
        if provider_name == "builtin_vllm":
            if entry.library == "vllm":
                return True
            compatibility = self._get_runtime_compatibility(entry)
            return (
                compatibility["model_type"] == "text_generation"
                and "vllm" in compatibility["compatible_runtimes"]
            )

        if provider_name in {"builtin_transformers", "huggingface"}:
            if entry.library == "transformers":
                return True
            compatibility = self._get_runtime_compatibility(entry)
            return (
                compatibility["model_type"] == "text_generation"
                and "transformers_direct" in compatibility["compatible_runtimes"]
            )

        provider_library = self._get_library_for_provider(provider_name)
        return bool(provider_library and entry.library == provider_library)

    def _get_models_for_provider(self, provider_name: str) -> Dict[str, ModelEntry]:
        """Get all registry entries that match a provider."""
        if provider_name == "builtin_vllm":
            return self._get_vllm_compatible_models()
            
        if provider_name == "builtin_transformers":
            return self._get_transformers_compatible_models()

        if provider_name == "fallback":
            return {
                "kari-fallback-v1": ModelEntry(
                    model_id="kari-fallback-v1",
                    library="system",
                    revision="static",
                    installed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    install_path="system",
                    files=[],
                    total_size=0,
                    pinned=True,
                    compatibility={
                        "compatible_runtimes": ["fallback"],
                        "preferred_runtime": "fallback",
                        "model_type": "text_generation",
                    },
                    metadata={},
                )
            }

        return {
            key: entry
            for key, entry in self._model_entries.items()
            if self._entry_matches_provider(entry, provider_name)
        }

    def _get_transformers_compatible_models(self) -> Dict[str, ModelEntry]:
        """Return models that can be served by builtin_transformers."""
        # Start with models explicitly in the registry
        compatible = {
            key: entry
            for key, entry in self._model_entries.items()
            if self._entry_matches_provider(entry, "builtin_transformers")
        }
        
        # Augment with discovered local models
        try:
            from ai_karen_engine.core.model_runtime.model_discovery_service import (
                get_model_discovery_service,
            )

            discovery = get_model_discovery_service()
            # Transformers can serve 'transformers' format models
            for model in discovery.get_models(runtime="transformers_direct", model_format="transformers"):
                if str(model.model_type or "").lower() != "text_generation":
                    continue
                model_key = model.model_id.replace("/", "--")
                if model_key in compatible:
                    continue
                    
                compatible[model_key] = ModelEntry(
                    model_id=model.model_id,
                    library="transformers",
                    revision="discovered",
                    installed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    install_path=model.path,
                    files=[{"path": rel, "size": 0} for rel in (model.metadata_files or [])],
                    total_size=model.size_bytes,
                    pinned=False,
                    compatibility={
                        "compatible_runtimes": list(model.compatible_runtimes),
                        "preferred_runtime": model.preferred_runtime,
                        "compatibility_confidence": model.compatibility_confidence,
                        "model_type": model.model_type,
                    },
                    metadata=model.to_dict(),
                )
        except Exception as exc:
            logger.debug("Failed to augment Transformers compatibility from discovery: %s", exc)

        return compatible

    def _get_vllm_compatible_models(self) -> Dict[str, ModelEntry]:
        """Return models that can be served by builtin_vllm."""
        compatible: Dict[str, ModelEntry] = {}

        for key, entry in self._model_entries.items():
            if entry.library == "vllm":
                compatible[key] = entry
                continue

            compatibility = entry.compatibility or {}
            compatible_runtimes = {
                str(runtime).lower() for runtime in (compatibility.get("compatible_runtimes") or [])
            }
            preferred_runtime = str(compatibility.get("preferred_runtime") or "").lower()
            model_type = str(compatibility.get("model_type") or "").lower()

            if (
                model_type == "text_generation"
                and "vllm" in compatible_runtimes
                and preferred_runtime in {"vllm", "builtin_vllm"}
            ):
                compatible[key] = entry

        try:
            from ai_karen_engine.core.model_runtime.model_discovery_service import (
                get_model_discovery_service,
            )

            discovery = get_model_discovery_service()
            for model in discovery.get_models(runtime="vllm", model_format="transformers"):
                if str(model.model_type or "").lower() != "text_generation":
                    continue
                model_key = model.model_id.replace("/", "--")
                if model_key in compatible:
                    continue
                compatible[model_key] = ModelEntry(
                    model_id=model.model_id,
                    library="vllm",
                    revision="discovered",
                    installed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    install_path=model.path,
                    files=[{"path": rel, "size": 0} for rel in (model.metadata_files or [])],
                    total_size=model.size_bytes,
                    pinned=False,
                    compatibility={
                        "compatible_runtimes": list(model.compatible_runtimes),
                        "preferred_runtime": model.preferred_runtime,
                        "compatibility_confidence": model.compatibility_confidence,
                        "model_type": model.model_type,
                    },
                    metadata=model.to_dict(),
                )
        except Exception as exc:
            logger.debug("Failed to augment vLLM compatibility from discovery: %s", exc)

        return compatible

    def get_storage_usage(self) -> Dict[str, Any]:
        """Get storage usage statistics."""
        total_size = 0
        library_sizes = {}
        model_count = len(self._model_entries)
        pinned_count = 0

        for entry in self._model_entries.values():
            total_size += entry.total_size

            if entry.library not in library_sizes:
                library_sizes[entry.library] = 0
            library_sizes[entry.library] += entry.total_size

            if entry.pinned:
                pinned_count += 1

        return {
            "total_size_bytes": total_size,
            "total_models": model_count,
            "pinned_models": pinned_count,
            "library_breakdown": library_sizes,
        }

    # Model orchestrator integration methods (requirements 2.1-2.7)

    async def update_llm_settings(self) -> None:
        """
        Update llm_settings.json automatically when models are installed.

        This method is called when the registry changes to ensure new models
        are immediately accessible through existing LLM services.
        """
        try:
            # Load current LLM settings
            current_settings = self._load_llm_settings()

            # Update provider configurations based on installed models
            updated_settings = await self._update_provider_configs(current_settings)

            # Validate updated settings against schema
            if self._llm_settings_schema:
                try:
                    if validate is None:
                        return
                    validate(
                        instance=updated_settings, schema=self._llm_settings_schema
                    )
                except ValidationError as ex:
                    logger.error(f"LLM settings validation failed: {ex}")
                    return

            # Save updated settings atomically
            await self._save_llm_settings(updated_settings)

            # Trigger service discovery for new models (requirement 2.4)
            await self._trigger_service_discovery()

            logger.info("LLM settings updated successfully")

        except Exception as ex:
            logger.error(f"Failed to update LLM settings: {ex}")

    def _load_llm_settings(self) -> Dict[str, Any]:
        """Load current LLM settings."""
        if not self.llm_settings_path.exists():
            # Return default settings
            return {
                "provider": "builtin_vllm",
                "model": "auto",
                "api_key": None,
                "base_url": None,
                "temperature": 0.7,
                "max_tokens": 2048,
                "timeout": 30,
                "max_retries": 3,
                "fallback_providers": ["builtin_transformers", "openai", "gemini", "deepseek"],
                "provider_configs": {},
            }

        try:
            with open(self.llm_settings_path, "r") as f:
                return json.load(f)
        except Exception as ex:
            logger.error(f"Failed to load LLM settings: {ex}")
            return {}

    async def _update_provider_configs(
        self, settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update provider configurations based on installed models."""
        provider_configs = settings.get("provider_configs", {})

        served_vllm_model = os.getenv(
            "KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME", "auto"
        )
        if "builtin_vllm" not in provider_configs:
            provider_configs["builtin_vllm"] = {}
        provider_configs["builtin_vllm"].pop("model_path", None)
        provider_configs["builtin_vllm"].update(
            {
                "models": [served_vllm_model],
                "context_length": int(
                    os.getenv("KAREN_BUILTIN_VLLM_MAX_MODEL_LEN", "4096")
                ),
                "base_url": os.getenv(
                    "KAREN_BUILTIN_VLLM_BASE_URL", "http://vllm:8000/v1"
                ),
                "health_url": os.getenv(
                    "KAREN_BUILTIN_VLLM_HEALTH_URL", "http://vllm:8000/health"
                ),
            }
        )
        if settings.get("provider") == "builtin_vllm":
            settings["model"] = served_vllm_model

        # Update built-in Transformers provider with local models.
        transformers_models = self._get_models_for_provider("builtin_transformers")
        transformers_model_names = [entry.model_id for entry in transformers_models.values()]
        transformers_model_path = None
        for entry in transformers_models.values():
            if transformers_model_path is None:
                transformers_model_path = str(Path(entry.install_path).parent)

        if transformers_model_names:
            if "builtin_transformers" not in provider_configs:
                provider_configs["builtin_transformers"] = {}

            provider_configs["builtin_transformers"].update(
                {
                    "models": transformers_model_names,
                    "model_path": transformers_model_path,
                    "context_length": 4096,
                }
            )

            # Update default model if not set or if current model is not available
            if settings.get("provider") == "builtin_transformers":
                current_model = settings.get("model")
                if not current_model or current_model not in transformers_model_names:
                    settings["model"] = transformers_model_names[0]

        # Update HuggingFace provider with Transformers models (requirement 2.3)
        hf_models = [
            entry.model_id
            for entry in self._get_models_for_provider("huggingface").values()
        ]

        if hf_models:
            if "huggingface" not in provider_configs:
                provider_configs["huggingface"] = {}

            provider_configs["huggingface"].update(
                {
                    "models": hf_models,
                    "base_url": "https://api-inference.huggingface.co",
                }
            )

        settings["provider_configs"] = provider_configs
        return settings

    async def _save_llm_settings(self, settings: Dict[str, Any]) -> None:
        """Save LLM settings atomically."""
        # Write to temporary file first
        temp_path = self.llm_settings_path.with_suffix(".tmp")

        try:
            with open(temp_path, "w") as f:
                json.dump(settings, f, indent=2)

            # Atomic move
            temp_path.replace(self.llm_settings_path)

        except Exception as ex:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink()
            raise ex

    async def _trigger_service_discovery(self) -> None:
        """Trigger service discovery for new models."""
        try:
            # Reload provider registrations to pick up new models
            for provider_name in self._registrations.keys():
                if provider_name in self._providers:
                    # Clear cached provider to force reload
                    del self._providers[provider_name]

            logger.info("Triggered service discovery for updated models")

        except Exception as ex:
            logger.error(f"Failed to trigger service discovery: {ex}")

    async def validate_model_accessibility(self, model_key: str) -> Dict[str, Any]:
        """
        Validate that a model is accessible through the appropriate client.

        Args:
            model_key: Model registry key

        Returns:
            Validation result with status and details
        """
        if model_key not in self._model_entries:
            return {
                "status": "not_found",
                "error": f"Model {model_key} not in registry",
            }

        entry = self._model_entries[model_key]

        try:
            # Get appropriate provider for the model's library
            if self._entry_matches_provider(entry, "builtin_vllm"):
                provider_name = "builtin_vllm"
            elif self._entry_matches_provider(entry, "builtin_transformers"):
                provider_name = "builtin_transformers"
            else:
                provider_name = self._get_provider_for_library(entry.library)
            if not provider_name:
                return {
                    "status": "no_provider",
                    "error": f"No provider available for library {entry.library}",
                }

            # Get provider instance
            provider = self.get_provider(provider_name, model=entry.model_id)
            if not provider:
                return {
                    "status": "provider_failed",
                    "error": f"Failed to create provider instance for {provider_name}",
                }

            # Perform smoke test (requirement 2.5, 2.6)
            result = await self._perform_smoke_test(provider, entry)
            return result

        except Exception as ex:
            return {"status": "validation_error", "error": str(ex)}

    def _get_provider_for_library(self, library: str) -> Optional[str]:
        """Get the appropriate provider name for a library."""
        library_provider_map = {
            "vllm": "builtin_vllm",
            "transformers": "huggingface",
            "spacy": "huggingface",  # spaCy models can be used through HF
            "sklearn": None,  # sklearn models don't use LLM providers
        }
        return library_provider_map.get(library)

    async def _perform_smoke_test(
        self, provider: LLMProviderBase, entry: ModelEntry
    ) -> Dict[str, Any]:
        """
        Perform smoke test on a model by attempting 1-token generation.

        Args:
            provider: LLM provider instance
            entry: Model entry

        Returns:
            Test result
        """
        try:
            # Load the specific model if provider supports it
            load_model_fn = getattr(provider, "load_model", None)
            if callable(load_model_fn) and entry.install_path:
                model_path = Path(entry.install_path)
                if self._entry_matches_provider(entry, "builtin_vllm"):
                    # For GGUF models, load the .gguf file
                    gguf_files = list(model_path.glob("*.gguf"))
                    if gguf_files:
                        success = bool(load_model_fn(str(gguf_files[0])))
                        if not success:
                            return {
                                "status": "unhealthy",
                                "error": f"Failed to load model from {gguf_files[0]}",
                            }
                elif self._entry_matches_provider(entry, "builtin_transformers"):
                    # For transformers models, load from directory
                    load_model_by_path_fn = getattr(
                        provider, "load_model_by_path", None
                    )
                    if callable(load_model_by_path_fn):
                        success = bool(load_model_by_path_fn(str(model_path)))
                        if not success:
                            return {
                                "status": "unhealthy",
                                "error": f"Failed to load transformers model from {model_path}",
                            }

            # Attempt basic inference with minimal tokens (requirement 2.6)
            if hasattr(provider, "generate_text"):
                from ai_karen_engine.core.model_runtime.model_manager import (
                    ModelManager,
                )

                result = await ModelManager.invoke_provider(
                    provider,
                    prompt="test",
                    max_tokens=1,
                    temperature=0.1,
                )

                if result and len(result.strip()) > 0:
                    return {
                        "status": "healthy",
                        "message": "Smoke test passed - model can generate tokens",
                        "test_output": result[:50],  # First 50 chars
                        "model_path": entry.install_path,
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "error": "Model generated empty response",
                    }
            elif hasattr(provider, "embed"):
                # Test embedding capability for embedding models
                result = provider.embed("test")
                if result and len(result) > 0:
                    return {
                        "status": "healthy",
                        "message": "Smoke test passed - model can generate embeddings",
                        "embedding_dim": len(result),
                        "model_path": entry.install_path,
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "error": "Model generated empty embedding",
                    }
            else:
                # Provider doesn't support generation - just check if it loads
                provider_info_fn = getattr(provider, "get_provider_info", None)
                provider_info = provider_info_fn() if callable(provider_info_fn) else {}
                return {
                    "status": "healthy",
                    "message": "Model loads successfully",
                    "provider_info": provider_info,
                    "model_path": entry.install_path,
                }

        except Exception as ex:
            return {
                "status": "unhealthy",
                "error": f"Smoke test failed: {ex}",
                "model_path": entry.install_path,
            }

    async def validate_all_models(self) -> Dict[str, Dict[str, Any]]:
        """
        Validate all models in the registry.

        Returns:
            Dict mapping model keys to validation results
        """
        results = {}

        for model_key in self._model_entries.keys():
            try:
                result = await self.validate_model_accessibility(model_key)
                results[model_key] = result
            except Exception as ex:
                results[model_key] = {"status": "validation_error", "error": str(ex)}

        return results

    def get_provider_health_status(self, provider_name: str) -> Dict[str, Any]:
        """
        Get comprehensive health status for a provider including model validation.

        Args:
            provider_name: Name of the provider

        Returns:
            Health status with model validation details
        """
        try:
            # Get basic provider health
            basic_health = self.health_check(provider_name)

            # Get models for this provider
            provider_models = self._get_models_for_provider(provider_name)

            # Add model count and validation summary
            basic_health["models"] = {
                "total_count": len(provider_models),
                "model_keys": list(provider_models.keys()),
            }

            # Add provider-specific validation info
            if provider_name in {"builtin_vllm", "builtin_transformers"}:
                local_models = [
                    k
                    for k, e in provider_models.items()
                    if self._entry_matches_provider(e, provider_name)
                ]
                basic_health["models"]["local_models"] = len(local_models)

                models_dir = Path("models/transformers")
                basic_health["models"]["models_directory_exists"] = models_dir.exists()
                if models_dir.exists():
                    model_files = list(models_dir.glob("*"))
                    basic_health["models"]["files_on_disk"] = len(model_files)

            elif provider_name == "huggingface":
                # Check for transformers models
                hf_models = [
                    k for k, e in provider_models.items() if self._entry_matches_provider(e, provider_name)
                ]
                basic_health["models"]["transformers_models"] = len(hf_models)

            return basic_health

        except Exception as ex:
            return {
                "status": "unhealthy",
                "error": f"Failed to get provider health: {ex}",
                "provider": provider_name,
            }

    async def validate_llm_settings_update(
        self, new_settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate that LLM settings update is valid and models are accessible.

        Args:
            new_settings: New LLM settings to validate

        Returns:
            Validation result
        """
        try:
            # Validate against schema (requirement 2.7)
            if self._llm_settings_schema:
                try:
                    if validate is None:
                        return {
                            "status": "error",
                            "error": "JSON schema validator unavailable",
                        }
                    validate(instance=new_settings, schema=self._llm_settings_schema)
                except ValidationError as ex:
                    return {
                        "status": "invalid_schema",
                        "error": f"Schema validation failed: {ex}",
                        "path": list(getattr(ex, "absolute_path", []) or []),
                    }

            # Check if specified provider exists
            provider_name = new_settings.get("provider")
            if provider_name and provider_name not in self._registrations:
                return {
                    "status": "invalid_provider",
                    "error": f"Provider '{provider_name}' is not registered",
                    "available_providers": list(self._registrations.keys()),
                }

            # Check if specified model is available for the provider
            model_name = new_settings.get("model")
            if provider_name and model_name:
                # Check if model exists in registry for this provider
                provider_models = [
                    entry.model_id
                    for entry in self._model_entries.values()
                    if self._entry_matches_provider(entry, provider_name)
                ]

                if model_name not in provider_models and provider_name in [
                    "builtin_transformers",
                    "builtin_vllm",
                    "huggingface",
                ]:
                    return {
                        "status": "model_not_found",
                        "error": f"Model '{model_name}' not found for provider '{provider_name}'",
                        "available_models": provider_models,
                    }

            # Validate provider configurations
            provider_configs = new_settings.get("provider_configs", {})
            for config_provider, config in provider_configs.items():
                if config_provider not in self._registrations:
                    return {
                        "status": "invalid_provider_config",
                        "error": f"Provider config for unknown provider: {config_provider}",
                        "available_providers": list(self._registrations.keys()),
                    }

                # Validate provider-specific config
                if config_provider in {"builtin_transformers", "builtin_vllm"}:
                    model_path = config.get("model_path")
                    if model_path and not Path(model_path).exists():
                        return {
                            "status": "invalid_model_path",
                            "error": f"Model path does not exist: {model_path}",
                            "provider": config_provider,
                        }

                elif config_provider == "huggingface":
                    models = config.get("models", [])
                    if not isinstance(models, list):
                        return {
                            "status": "invalid_models_config",
                            "error": "HuggingFace models config must be a list",
                            "provider": config_provider,
                        }

            return {"status": "valid", "message": "LLM settings validation passed"}

        except Exception as ex:
            return {
                "status": "validation_error",
                "error": f"Settings validation failed: {ex}",
            }

    async def test_model_loading_workflow(self, model_key: str) -> Dict[str, Any]:
        """
        Test complete model loading workflow including provider instantiation and inference.

        Args:
            model_key: Model registry key

        Returns:
            Comprehensive test result
        """
        if model_key not in self._model_entries:
            return {
                "status": "not_found",
                "error": f"Model {model_key} not in registry",
            }

        entry = self._model_entries[model_key]
        test_results = {
            "model_key": model_key,
            "model_id": entry.model_id,
            "library": entry.library,
            "install_path": entry.install_path,
            "tests": {},
        }

        try:
            # Test 1: File integrity check
            test_results["tests"]["file_integrity"] = self.verify_model_integrity(
                model_key
            )

            # Test 2: Provider availability
            if self._entry_matches_provider(entry, "builtin_vllm"):
                provider_name = "builtin_vllm"
            elif self._entry_matches_provider(entry, "builtin_transformers"):
                provider_name = "builtin_transformers"
            else:
                provider_name = self._get_provider_for_library(entry.library)
            if not provider_name:
                test_results["tests"]["provider_availability"] = {
                    "status": "no_provider",
                    "error": f"No provider available for library {entry.library}",
                }
                test_results["status"] = "failed"
                return test_results

            test_results["tests"]["provider_availability"] = {
                "status": "available",
                "provider": provider_name,
            }

            # Test 3: Provider instantiation
            try:
                provider = self.get_provider(provider_name)
                if provider:
                    provider_info_fn = getattr(provider, "get_provider_info", None)
                    provider_info = (
                        provider_info_fn() if callable(provider_info_fn) else {}
                    )
                    test_results["tests"]["provider_instantiation"] = {
                        "status": "success",
                        "provider_info": provider_info,
                    }
                else:
                    test_results["tests"]["provider_instantiation"] = {
                        "status": "failed",
                        "error": "Failed to create provider instance",
                    }
                    test_results["status"] = "failed"
                    return test_results
            except Exception as ex:
                test_results["tests"]["provider_instantiation"] = {
                    "status": "failed",
                    "error": str(ex),
                }
                test_results["status"] = "failed"
                return test_results

            # Test 4: Model loading (if supported)
            if hasattr(provider, "load_model") or hasattr(
                provider, "load_model_by_path"
            ):
                try:
                    model_path = Path(entry.install_path)
                    if self._entry_matches_provider(entry, "builtin_vllm"):
                        # Find GGUF file
                        gguf_files = list(model_path.glob("*.gguf"))
                        load_model_fn = getattr(provider, "load_model", None)
                        if gguf_files and callable(load_model_fn):
                            success = bool(load_model_fn(str(gguf_files[0])))
                            test_results["tests"]["model_loading"] = {
                                "status": "success" if success else "failed",
                                "model_file": str(gguf_files[0]),
                                "loaded": success,
                            }
                        else:
                            test_results["tests"]["model_loading"] = {
                                "status": "failed",
                                "error": "No GGUF files found or provider doesn't support loading",
                            }
                    elif self._entry_matches_provider(entry, "builtin_transformers"):
                        load_model_by_path_fn = getattr(
                            provider, "load_model_by_path", None
                        )
                        if callable(load_model_by_path_fn):
                            success = bool(load_model_by_path_fn(str(model_path)))
                            test_results["tests"]["model_loading"] = {
                                "status": "success" if success else "failed",
                                "model_path": str(model_path),
                                "loaded": success,
                            }
                        else:
                            test_results["tests"]["model_loading"] = {
                                "status": "skipped",
                                "reason": "Provider doesn't support explicit model loading",
                            }
                except Exception as ex:
                    test_results["tests"]["model_loading"] = {
                        "status": "failed",
                        "error": str(ex),
                    }
            else:
                test_results["tests"]["model_loading"] = {
                    "status": "skipped",
                    "reason": "Provider doesn't support model loading",
                }

            # Test 5: Smoke test (1-token generation)
            test_results["tests"]["smoke_test"] = await self._perform_smoke_test(
                provider, entry
            )

            # Determine overall status
            failed_tests = [
                name
                for name, result in test_results["tests"].items()
                if result.get("status") in ["failed", "unhealthy"]
            ]

            if not failed_tests:
                test_results["status"] = "healthy"
                test_results["message"] = "All tests passed"
            elif len(failed_tests) == 1 and "smoke_test" in failed_tests:
                test_results["status"] = "degraded"
                test_results["message"] = "Model loads but smoke test failed"
            else:
                test_results["status"] = "unhealthy"
                test_results["message"] = f"Failed tests: {failed_tests}"

            return test_results

        except Exception as ex:
            test_results["status"] = "error"
            test_results["error"] = str(ex)
            return test_results

    async def ensure_model_compatibility(self, model_key: str) -> Dict[str, Any]:
        """
        Ensure a model is compatible with its provider and can be used for inference.

        This method performs comprehensive validation including file integrity,
        provider compatibility, and basic inference testing.

        Args:
            model_key: Model registry key

        Returns:
            Compatibility check result
        """
        try:
            # Run comprehensive workflow test
            workflow_result = await self.test_model_loading_workflow(model_key)

            # Extract compatibility information
            compatibility_result = {
                "model_key": model_key,
                "compatible": workflow_result["status"] in ["healthy", "degraded"],
                "status": workflow_result["status"],
                "tests_passed": [],
                "tests_failed": [],
                "recommendations": [],
            }

            # Analyze test results
            for test_name, test_result in workflow_result.get("tests", {}).items():
                if test_result.get("status") in ["success", "healthy"]:
                    compatibility_result["tests_passed"].append(test_name)
                elif test_result.get("status") in ["failed", "unhealthy"]:
                    compatibility_result["tests_failed"].append(test_name)

            # Generate recommendations
            if "file_integrity" in compatibility_result["tests_failed"]:
                compatibility_result["recommendations"].append(
                    "Re-download the model to fix file integrity issues"
                )

            if "provider_instantiation" in compatibility_result["tests_failed"]:
                compatibility_result["recommendations"].append(
                    "Check provider configuration and dependencies"
                )

            if "model_loading" in compatibility_result["tests_failed"]:
                compatibility_result["recommendations"].append(
                    "Verify model format is compatible with provider"
                )

            if "smoke_test" in compatibility_result["tests_failed"]:
                compatibility_result["recommendations"].append(
                    "Model may be corrupted or incompatible - consider re-downloading"
                )

            return compatibility_result

        except Exception as ex:
            return {
                "model_key": model_key,
                "compatible": False,
                "status": "error",
                "error": str(ex),
                "tests_passed": [],
                "tests_failed": ["compatibility_check"],
                "recommendations": ["Contact support for assistance"],
            }

    def cleanup(self):
        """Clean up resources including file watcher."""
        if hasattr(self, "_observer") and self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Registry watcher stopped")


# Global registry instance and lock
_registry = None
_registry_lock = threading.RLock()


def get_registry() -> LLMRegistry:
    """Get global LLM registry instance."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = LLMRegistry()
            # Ensure all built-in providers are registered
            _registry.ensure_builtin_providers_registered()
            # Ensure registry consistency
            _registry.ensure_registry_consistency()
    return _registry


def register_provider(name: str, provider_class: Type[LLMProviderBase], **kwargs):
    """Register a provider in the global registry."""
    registry = get_registry()
    registry.register_provider(name, provider_class, **kwargs)


def get_provider(name: str, **init_kwargs) -> Optional[LLMProviderBase]:
    """Get provider from global registry."""
    registry = get_registry()
    return registry.get_provider(name, **init_kwargs)


def list_providers() -> List[str]:
    """List all registered providers."""
    registry = get_registry()
    return registry.list_providers()


def health_check_all() -> Dict[str, Dict[str, Any]]:
    """Health check all providers."""
    registry = get_registry()
    return registry.health_check_all()


# Expose a module-level registry instance for plugin consumers
registry = get_registry()

__all__ = [
    "LLMRegistry",
    "get_registry",
    "register_provider",
    "get_provider",
    "list_providers",
    "health_check_all",
    "registry",
]
