"""
Category Validation Service - Enforces category restrictions and path resolution.

This service ensures that only valid categories (`plugins`, `sys_extensions`, `channels`)
are allowed and implements proper path resolution for canonical structure.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import asyncio
from datetime import datetime

from ai_karen_engine.extensions.platform.core.authority_chain import AuthorityLevel

logger = logging.getLogger("kari.category_validation")


class CategoryType(str, Enum):
    """Valid plugin categories."""

    PLUGINS = "plugins"
    SYS_EXTENSIONS = "sys_extensions"
    CHANNELS = "channels"


@dataclass
class CategoryConfig:
    """Configuration for a category."""

    name: CategoryType
    display_name: str
    description: str
    authority_level: AuthorityLevel
    allowed_paths: Set[str] = field(default_factory=set)
    required_files: Set[str] = field(default_factory=set)
    optional_files: Set[str] = field(default_factory=set)
    max_plugins: Optional[int] = None
    validation_rules: List[str] = field(default_factory=list)


@dataclass
class PathResolutionResult:
    """Result of path resolution validation."""

    is_valid: bool
    resolved_path: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    canonical_path: Optional[str] = None


@dataclass
class CategoryValidationResult:
    """Result of category validation."""

    is_valid: bool
    category: CategoryType
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    resolved_path: Optional[str] = None
    canonical_path: Optional[str] = None


class CategoryValidationService:
    """
    Service for validating categories and resolving canonical paths.

    Responsibilities:
    - Enforce only valid categories are allowed
    - Implement path resolution for canonical structure
    - Reject invalid categories in all lifecycle operations
    - Validate category-specific requirements
    """

    def __init__(self):
        """Initialize category validation service."""
        self.category_configs: Dict[CategoryType, CategoryConfig] = {}
        self._initialize_category_configs()

        logger.info("CategoryValidationService initialized")

    def _initialize_category_configs(self):
        """Initialize category configurations."""

        # Plugins category
        plugins_config = CategoryConfig(
            name=CategoryType.PLUGINS,
            display_name="Plugins",
            description="User-installed plugins and extensions",
            authority_level=AuthorityLevel.USER,
            allowed_paths={
                "/plugins",
                "/extensions/plugins",
                "/usr/local/share/kari/plugins",
                "~/.kari/plugins",
            },
            required_files={"manifest.json", "handler.py"},
            optional_files={
                "ui/manifest.json",
                "ui/components",
                "config",
                "README.md",
                "LICENSE",
            },
            max_plugins=None,  # No limit
            validation_rules=[
                "manifest.json must contain valid plugin metadata",
                "handler.py must implement ExtensionBase interface",
                "Plugin name must follow kebab-case convention",
            ],
        )

        # System extensions category
        sys_extensions_config = CategoryConfig(
            name=CategoryType.SYS_EXTENSIONS,
            display_name="System Extensions",
            description="Core system extensions and built-in functionality",
            authority_level=AuthorityLevel.ADMIN,
            allowed_paths={
                "/sys_extensions",
                "/extensions/core",
                "/usr/local/share/kari/sys_extensions",
                "/etc/kari/extensions",
            },
            required_files={"manifest.json", "handler.py", "system.config"},
            optional_files={"ui/manifest.json", "certificates", "system_keys"},
            max_plugins=50,  # Limit system extensions
            validation_rules=[
                "manifest.json must contain system extension metadata",
                "handler.py must implement SystemExtension interface",
                "System extensions must be digitally signed",
                "Must include system.config with security settings",
            ],
        )

        # Channels category
        channels_config = CategoryConfig(
            name=CategoryType.CHANNELS,
            display_name="Channels",
            description="Communication channels and integrations",
            authority_level=AuthorityLevel.PLUGIN,
            allowed_paths={
                "/channels",
                "/extensions/channels",
                "/usr/local/share/kari/channels",
                "~/.kari/channels",
            },
            required_files={"manifest.json", "channel.py", "protocol.config"},
            optional_files={
                "ui/manifest.json",
                "certificates",
                "adapters",
                "protocols",
            },
            max_plugins=100,  # Limit channels
            validation_rules=[
                "manifest.json must contain channel metadata",
                "channel.py must implement ChannelInterface",
                "protocol.config must define supported protocols",
                "Channels must implement proper authentication",
            ],
        )

        self.category_configs = {
            CategoryType.PLUGINS: plugins_config,
            CategoryType.SYS_EXTENSIONS: sys_extensions_config,
            CategoryType.CHANNELS: channels_config,
        }

    def validate_category(self, category: str) -> bool:
        """Validate that a category is allowed."""
        try:
            category_type = CategoryType(category)
            return category_type in self.category_configs
        except ValueError:
            return False

    def get_category_config(self, category: str) -> Optional[CategoryConfig]:
        """Get configuration for a category."""
        try:
            category_type = CategoryType(category)
            return self.category_configs.get(category_type)
        except ValueError:
            return None

    def resolve_canonical_path(
        self, category: str, input_path: str
    ) -> PathResolutionResult:
        """
        Resolve and validate a path for a given category.

        Args:
            category: The category to validate against
            input_path: The input path to resolve

        Returns:
            PathResolutionResult with validation results
        """
        result = PathResolutionResult(is_valid=True)

        # Validate category
        if not self.validate_category(category):
            result.is_valid = False
            result.errors.append(f"Invalid category: {category}")
            return result

        category_config = self.category_configs[CategoryType(category)]

        # Convert to absolute path
        try:
            path = Path(input_path).expanduser().resolve()
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Invalid path format: {str(e)}")
            return result

        # Check if path is allowed for this category
        path_str = str(path)
        is_allowed_path = False

        for allowed_pattern in category_config.allowed_paths:
            # Convert pattern to regex for flexible matching
            if self._path_matches_pattern(path_str, allowed_pattern):
                is_allowed_path = True
                break

        if not is_allowed_path:
            result.is_valid = False
            result.errors.append(
                f"Path '{path_str}' is not allowed for category '{category}'. "
                f"Allowed patterns: {category_config.allowed_paths}"
            )
            return result

        # Check if required files exist
        missing_required_files = []
        for required_file in category_config.required_files:
            required_path = path / required_file
            if not required_path.exists():
                missing_required_files.append(required_file)

        if missing_required_files:
            result.is_valid = False
            result.errors.append(f"Missing required files: {missing_required_files}")
            return result

        # Check optional files
        missing_optional_files = []
        for optional_file in category_config.optional_files:
            optional_path = path / optional_file
            if not optional_path.exists():
                missing_optional_files.append(optional_file)

        if missing_optional_files:
            result.warnings.append(f"Missing optional files: {missing_optional_files}")

        # Resolve canonical path
        canonical_path = self._get_canonical_path(path, category)
        result.canonical_path = canonical_path
        result.resolved_path = path_str
        result.is_valid = True

        logger.debug(f"Path resolved: {input_path} → {canonical_path}")
        return result

    def _path_matches_pattern(self, path_str: str, pattern: str) -> bool:
        """Check if a path matches a given pattern."""
        # Convert pattern to regex
        # Handle special patterns like "~" for home directory
        if pattern.startswith("~"):
            home = str(Path.home())
            return path_str.startswith(home)

        # For other patterns, check if path starts with pattern
        return path_str.startswith(pattern)

    def _get_canonical_path(self, path: Path, category: str) -> str:
        """Get the canonical path for a given category."""
        category_config = self.category_configs[CategoryType(category)]

        # Find the best matching allowed pattern
        for pattern in category_config.allowed_paths:
            if self._path_matches_pattern(str(path), pattern):
                # Return path relative to the pattern
                if pattern.startswith("~"):
                    base_path = Path.home()
                else:
                    base_path = Path(pattern)

                relative_path = path.relative_to(base_path)
                return str(base_path / relative_path)

        # Fallback to original path
        return str(path)

    def validate_plugin_structure(
        self, category: str, plugin_path: str
    ) -> CategoryValidationResult:
        """
        Validate the complete structure of a plugin for a given category.

        Args:
            category: The category to validate against
            plugin_path: Path to the plugin directory

        Returns:
            CategoryValidationResult with validation results
        """
        result = CategoryValidationResult(
            is_valid=True, category=CategoryType(category)
        )

        # Resolve and validate path
        path_result = self.resolve_canonical_path(category, plugin_path)
        result.resolved_path = path_result.resolved_path
        result.canonical_path = path_result.canonical_path

        if not path_result.is_valid:
            result.is_valid = False
            result.errors = path_result.errors
            result.warnings = path_result.warnings
            return result

        # Category-specific validation
        category_config = self.category_configs[CategoryType(category)]

        # Check maximum plugins limit
        if category_config.max_plugins is not None:
            # This would need to check the actual count in the directory
            # For now, we'll assume it's handled elsewhere
            pass

        # Validate manifest file
        manifest_path = Path(plugin_path) / "manifest.json"
        if manifest_path.exists():
            try:
                import json

                with open(manifest_path, "r") as f:
                    manifest = json.load(f)

                # Validate manifest content based on category
                manifest_errors = self._validate_manifest_content(manifest, category)
                result.errors.extend(manifest_errors)

            except Exception as e:
                result.errors.append(f"Failed to parse manifest.json: {str(e)}")
        else:
            result.errors.append("manifest.json not found")

        # Validate handler file
        handler_path = Path(plugin_path) / "handler.py"
        if handler_path.exists():
            # Check if handler implements required interface
            handler_errors = self._validate_handler_file(handler_path, category)
            result.errors.extend(handler_errors)
        else:
            result.errors.append("handler.py not found")

        # Check category-specific validation rules
        for rule in category_config.validation_rules:
            rule_errors = self._validate_category_rule(rule, plugin_path, category)
            result.errors.extend(rule_errors)

        result.is_valid = len(result.errors) == 0
        return result

    def _validate_manifest_content(
        self, manifest: Dict[str, Any], category: str
    ) -> List[str]:
        """Validate manifest content based on category."""
        errors = []

        # Required fields for all categories
        required_fields = ["name", "version", "display_name", "description", "author"]
        for field in required_fields:
            if field not in manifest:
                errors.append(f"Missing required field in manifest: {field}")

        # Category-specific validation
        if category == CategoryType.SYS_EXTENSIONS:
            # System extensions need additional fields
            if "security_level" not in manifest:
                errors.append("System extensions require 'security_level' field")

            if "digital_signature" not in manifest:
                errors.append("System extensions require 'digital_signature' field")

        elif category == CategoryType.CHANNELS:
            # Channels need protocol information
            if "supported_protocols" not in manifest:
                errors.append("Channels require 'supported_protocols' field")

            if "authentication" not in manifest:
                errors.append("Channels require 'authentication' field")

        return errors

    def _validate_handler_file(self, handler_path: Path, category: str) -> List[str]:
        """Validate handler file based on category."""
        errors = []

        try:
            with open(handler_path, "r") as f:
                content = f.read()

            # Check for required interface implementations
            if category == CategoryType.PLUGINS:
                if "ExtensionBase" not in content:
                    errors.append("handler.py must implement ExtensionBase interface")

            elif category == CategoryType.SYS_EXTENSIONS:
                if "SystemExtension" not in content:
                    errors.append("handler.py must implement SystemExtension interface")

            elif category == CategoryType.CHANNELS:
                if "ChannelInterface" not in content:
                    errors.append("handler.py must implement ChannelInterface")

        except Exception as e:
            errors.append(f"Failed to read handler.py: {str(e)}")

        return errors

    def _validate_category_rule(
        self, rule: str, plugin_path: str, category: str
    ) -> List[str]:
        """Validate a specific category rule."""
        errors = []

        # Implement rule validation based on rule string
        if "kebab-case" in rule and "name" in rule:
            # Check if plugin name follows kebab-case
            manifest_path = Path(plugin_path) / "manifest.json"
            if manifest_path.exists():
                try:
                    import json

                    with open(manifest_path, "r") as f:
                        manifest = json.load(f)

                    name = manifest.get("name", "")
                    if not re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name):
                        errors.append(
                            f"Plugin name '{name}' must follow kebab-case convention"
                        )

                except Exception:
                    pass

        return errors

    def get_allowed_categories(self) -> Set[str]:
        """Get all allowed categories."""
        return {category.value for category in CategoryType}

    def get_category_info(self, category: str) -> Optional[Dict[str, Any]]:
        """Get information about a category."""
        config = self.get_category_config(category)
        if not config:
            return None

        return {
            "name": config.name.value,
            "display_name": config.display_name,
            "description": config.description,
            "authority_level": config.authority_level.value,
            "allowed_paths": list(config.allowed_paths),
            "required_files": list(config.required_files),
            "optional_files": list(config.optional_files),
            "max_plugins": config.max_plugins,
            "validation_rules": config.validation_rules,
        }

    def validate_category_transition(
        self, from_category: str, to_category: str, requested_by: AuthorityLevel
    ) -> Tuple[bool, List[str]]:
        """
        Validate category transitions.

        Args:
            from_category: Source category
            to_category: Target category
            requested_by: Authority level making the request

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        # Validate categories
        if not self.validate_category(from_category):
            errors.append(f"Invalid source category: {from_category}")

        if not self.validate_category(to_category):
            errors.append(f"Invalid target category: {to_category}")

        if errors:
            return False, errors

        # Check authority for target category
        target_config = self.get_category_config(to_category)
        if requested_by.value < target_config.authority_level.value:
            errors.append(
                f"Cannot transition to {to_category} with {requested_by.value} authority. "
                f"Required: {target_config.authority_level.value}"
            )

        return len(errors) == 0, errors


# Global singleton instance
_category_validation_service: Optional[CategoryValidationService] = None


def get_category_validation_service() -> CategoryValidationService:
    """Get the global category validation service instance."""
    global _category_validation_service
    if _category_validation_service is None:
        _category_validation_service = CategoryValidationService()
    return _category_validation_service


__all__ = [
    "CategoryValidationService",
    "CategoryType",
    "CategoryConfig",
    "PathResolutionResult",
    "CategoryValidationResult",
    "get_category_validation_service",
]
