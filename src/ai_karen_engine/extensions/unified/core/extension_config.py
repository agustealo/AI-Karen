"""
Unified Extension Configuration

Provides configuration management for extensions with schema validation,
hot-reload support, and environment integration.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import datetime

from ...platform.core.manifest import ExtensionManifest
from ..database_models import ExtensionConfig as ExtensionConfigModel

logger = logging.getLogger(__name__)


@dataclass
class ExtensionConfig:
    """Extension configuration with validation."""

    extension_id: str
    key: str
    value: Any
    config_type: str = "string"
    description: Optional[str] = None
    required: bool = False
    default_value: Optional[Any] = None
    validation_rules: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "extension_id": self.extension_id,
            "key": self.key,
            "value": self.value,
            "config_type": self.config_type,
            "description": self.description,
            "required": self.required,
            "default_value": self.default_value,
            "validation_rules": self.validation_rules,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtensionConfig":
        """Create from dictionary."""
        return cls(
            extension_id=data["extension_id"],
            key=data["key"],
            value=data["value"],
            config_type=data.get("config_type", "string"),
            description=data.get("description"),
            required=data.get("required", False),
            default_value=data.get("default_value"),
            validation_rules=data.get("validation_rules", {}),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else None,
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else None,
        )


class ExtensionConfigManager:
    """Unified extension configuration manager."""

    def __init__(self, registry=None):
        self.registry = registry
        self._config: Dict[str, Dict[str, ExtensionConfig]] = {}
        self._config_schema: Dict[str, Dict[str, Any]] = {}
        self._environment_overrides: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

        # Hot reload support
        self._watchers: Dict[str, asyncio.Task] = {}
        self._reload_callbacks: Dict[str, List[callable]] = {}

        # Environment prefix for config variables
        self.env_prefix = "EXTENSION_"

    async def initialize(self) -> None:
        """Initialize the configuration manager."""
        # Load existing configurations
        await self._load_configurations()

        # Load environment overrides
        self._load_environment_overrides()

        # Start config watchers
        await self._start_config_watchers()

        logger.info("Extension configuration manager initialized")

    async def get_config(self, extension_id: str, key: str, default: Any = None) -> Any:
        """Get configuration value for an extension."""
        async with self._lock:
            # Check environment override first
            env_key = f"{self.env_prefix}{extension_id.upper()}_{key.upper()}"
            env_value = os.getenv(env_key)
            if env_value is not None:
                return self._parse_env_value(env_value)

            # Check stored config
            if extension_id in self._config and key in self._config[extension_id]:
                return self._config[extension_id][key].value

            # Check default value
            if (
                extension_id in self._config_schema
                and key in self._config_schema[extension_id]
            ):
                schema = self._config_schema[extension_id][key]
                return schema.get("default_value", default)

            return default

    async def set_config(
        self, extension_id: str, key: str, value: Any, description: Optional[str] = None
    ) -> bool:
        """Set configuration value for an extension."""
        async with self._lock:
            # Validate value against schema
            if (
                extension_id in self._config_schema
                and key in self._config_schema[extension_id]
            ):
                schema = self._config_schema[extension_id][key]
                if not self._validate_value(value, schema):
                    logger.error(f"Invalid value for config {key}: {value}")
                    return False

            # Create or update config
            if extension_id not in self._config:
                self._config[extension_id] = {}

            config = ExtensionConfig(
                extension_id=extension_id,
                key=key,
                value=value,
                description=description,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            self._config[extension_id][key] = config

            # Save to database
            await self._save_config(config)

            # Notify reload callbacks
            await self._notify_reload_callbacks(extension_id)

            logger.info(f"Set config: {extension_id}.{key} = {value}")
            return True

    async def get_all_config(self, extension_id: str) -> Dict[str, Any]:
        """Get all configuration values for an extension."""
        async with self._lock:
            config_dict = {}

            # Get stored configs
            if extension_id in self._config:
                for key, config in self._config[extension_id].items():
                    config_dict[key] = config.value

            # Get defaults from schema
            if extension_id in self._config_schema:
                for key, schema in self._config_schema[extension_id].items():
                    if key not in config_dict and "default_value" in schema:
                        config_dict[key] = schema["default_value"]

            # Apply environment overrides
            if extension_id in self._environment_overrides:
                for key, value in self._environment_overrides[extension_id].items():
                    config_dict[key] = value

            return config_dict

    async def delete_config(self, extension_id: str, key: str) -> bool:
        """Delete a configuration value."""
        async with self._lock:
            if extension_id in self._config and key in self._config[extension_id]:
                del self._config[extension_id][key]

                # Remove from database
                await self._delete_config_from_db(extension_id, key)

                # Notify reload callbacks
                await self._notify_reload_callbacks(extension_id)

                logger.info(f"Deleted config: {extension_id}.{key}")
                return True

            return False

    async def load_config_schema(
        self, extension_id: str, schema: Dict[str, Any]
    ) -> None:
        """Load configuration schema for an extension."""
        async with self._lock:
            self._config_schema[extension_id] = schema

            # Validate existing configs against new schema
            if extension_id in self._config:
                for key, config in self._config[extension_id].items():
                    if key in schema:
                        if not self._validate_value(config.value, schema[key]):
                            logger.warning(
                                f"Config {key} value invalid after schema update"
                            )

    async def validate_config(
        self, extension_id: str, config: Dict[str, Any]
    ) -> List[str]:
        """Validate configuration against schema."""
        errors = []

        if extension_id not in self._config_schema:
            return ["No schema found for extension"]

        schema = self._config_schema[extension_id]

        for key, value in config.items():
            if key in schema:
                if not self._validate_value(value, schema[key]):
                    errors.append(f"Invalid value for {key}: {value}")
            else:
                errors.append(f"Unknown config key: {key}")

        # Check required fields
        for key, schema_def in schema.items():
            if schema_def.get("required", False) and key not in config:
                errors.append(f"Required config missing: {key}")

        return errors

    async def register_reload_callback(
        self, extension_id: str, callback: callable
    ) -> None:
        """Register a callback for config reloads."""
        if extension_id not in self._reload_callbacks:
            self._reload_callbacks[extension_id] = []
        self._reload_callbacks[extension_id].append(callback)
        logger.info(f"Registered reload callback for: {extension_id}")

    async def start_hot_reload(self, extension_id: str, config_path: Path) -> None:
        """Start hot reload for an extension's config file."""
        if extension_id in self._watchers:
            logger.warning(f"Hot reload already started for: {extension_id}")
            return

        async def watch_config():
            try:
                last_modified = (
                    config_path.stat().st_mtime if config_path.exists() else 0
                )

                while True:
                    await asyncio.sleep(1)  # Check every second

                    if config_path.exists():
                        current_modified = config_path.stat().st_mtime
                        if current_modified > last_modified:
                            logger.info(f"Config file changed: {config_path}")

                            # Reload config
                            await self._load_config_file(extension_id, config_path)

                            # Notify callbacks
                            await self._notify_reload_callbacks(extension_id)

                            last_modified = current_modified
            except Exception as e:
                logger.error(f"Error watching config file: {e}")

        self._watchers[extension_id] = asyncio.create_task(watch_config())
        logger.info(f"Started hot reload for: {extension_id}")

    async def stop_hot_reload(self, extension_id: str) -> None:
        """Stop hot reload for an extension."""
        if extension_id in self._watchers:
            self._watchers[extension_id].cancel()
            del self._watchers[extension_id]
            logger.info(f"Stopped hot reload for: {extension_id}")

    async def _load_configurations(self) -> None:
        """Load all configurations from database."""
        if self.registry:
            # This would typically load from database
            # For now, initialize with empty config
            pass

        logger.info("Loaded configurations from database")

    def _load_environment_overrides(self) -> None:
        """Load environment variable overrides."""
        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                # Parse key: EXTENSION_EXTENSIONID_KEY
                parts = key[len(self.env_prefix) :].split("_", 1)
                if len(parts) == 2:
                    extension_id = parts[0].lower()
                    config_key = parts[1].lower()

                    if extension_id not in self._environment_overrides:
                        self._environment_overrides[extension_id] = {}

                    self._environment_overrides[extension_id][config_key] = (
                        self._parse_env_value(value)
                    )

    def _parse_env_value(self, value: str) -> Any:
        """Parse environment variable value based on expected type."""
        # Try to parse as JSON first
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

        # Try to parse as boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"

        # Try to parse as number
        try:
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            pass

        # Return as string
        return value

    def _validate_value(self, value: Any, schema: Dict[str, Any]) -> bool:
        """Validate value against schema."""
        value_type = schema.get("type", "string")

        # Type validation
        if value_type == "string" and not isinstance(value, str):
            return False
        elif value_type == "integer" and not isinstance(value, int):
            return False
        elif value_type == "number" and not isinstance(value, (int, float)):
            return False
        elif value_type == "boolean" and not isinstance(value, bool):
            return False
        elif value_type == "array" and not isinstance(value, list):
            return False
        elif value_type == "object" and not isinstance(value, dict):
            return False

        # Validation rules
        if "validation_rules" in schema:
            rules = schema["validation_rules"]

            # Min/max validation
            if "min" in rules and value < rules["min"]:
                return False
            if "max" in rules and value > rules["max"]:
                return False

            # Pattern validation
            if "pattern" in rules and isinstance(value, str):
                import re

                if not re.match(rules["pattern"], value):
                    return False

            # Enum validation
            if "enum" in rules and value not in rules["enum"]:
                return False

        return True

    async def _save_config(self, config: ExtensionConfig) -> None:
        """Save configuration to database."""
        # This would typically save to database
        # For now, just log the action
        logger.debug(f"Saving config: {config.extension_id}.{config.key}")

    async def _delete_config_from_db(self, extension_id: str, key: str) -> None:
        """Delete configuration from database."""
        # This would typically delete from database
        # For now, just log the action
        logger.debug(f"Deleting config: {extension_id}.{key}")

    async def _load_config_file(self, extension_id: str, config_path: Path) -> None:
        """Load configuration from file."""
        try:
            with open(config_path, "r") as f:
                if config_path.suffix.lower() == ".json":
                    config = json.load(f)
                elif config_path.suffix.lower() == ".yaml":
                    import yaml

                    config = yaml.safe_load(f)
                else:
                    logger.error(
                        f"Unsupported config file format: {config_path.suffix}"
                    )
                    return

            # Apply configuration
            for key, value in config.items():
                await self.set_config(extension_id, key, value)

            logger.info(f"Loaded config from: {config_path}")

        except Exception as e:
            logger.error(f"Error loading config file: {e}")

    async def _notify_reload_callbacks(self, extension_id: str) -> None:
        """Notify all reload callbacks for an extension."""
        if extension_id in self._reload_callbacks:
            for callback in self._reload_callbacks[extension_id]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback()
                    else:
                        callback()
                except Exception as e:
                    logger.error(f"Error in reload callback: {e}")

    async def _start_config_watchers(self) -> None:
        """Start config file watchers for all extensions."""
        # This would typically start watchers for all extensions
        # For now, just log the action
        logger.info("Started config watchers")
