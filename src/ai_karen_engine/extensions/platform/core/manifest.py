"""
Unified Extension Manifest for Prompt-First Plugin System.

This module provides the canonical ExtensionManifest definition that combines
fields from both base.py and manifest.py, resolving the type conflict and
adding prompt-first capabilities.

The manifest supports:
- Prompt-first plugin development (system/user prompt templates)
- Typed prompt contract references (DEFAULT, CUSTOM, NONE)
- Full lifecycle management (install, uninstall, enable, disable, update, restore)
- UI materialization via icon naming conventions
- Marketplace integration with metadata
- RBAC and permissions
- Dependencies and version management
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Constants
SEMVER_PATTERN = (
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
NAME_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"


# Enums
class ExtensionStatus(str, Enum):
    """Extension status enumeration."""

    INACTIVE = "inactive"
    LOADING = "loading"
    ACTIVE = "active"
    ERROR = "error"
    UNLOADING = "unloading"
    INSTALLING = "installing"
    UNINSTALLING = "uninstalling"
    UPDATING = "updating"
    RESTORING = "restoring"


class HookPoint(str, Enum):
    """Standard hook points for KARI extensions."""

    PRE_INTENT_DETECTION = "pre_intent_detection"
    PRE_MEMORY_RETRIEVAL = "pre_memory_retrieval"
    POST_MEMORY_RETRIEVAL = "post_memory_retrieval"
    PRE_LLM_PROMPT = "pre_llm_prompt"
    POST_LLM_RESULT = "post_llm_result"
    POST_RESPONSE = "post_response"


class Permission(str, Enum):
    """Standard permissions for extensions."""

    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    TOOL_ACCESS = "tool_access"
    USER_DATA_READ = "user_data_read"
    USER_DATA_WRITE = "user_data_write"
    SYSTEM_CONFIG_READ = "system_config_read"
    SYSTEM_CONFIG_WRITE = "system_config_write"


class ExtensionRole(str, Enum):
    """Standard roles for extension RBAC."""

    SYSTEM = "system"
    ADMIN = "admin"
    DEVELOPER = "developer"
    USER = "user"
    GUEST = "guest"


class PromptMode(str, Enum):
    """Prompt contract mode for extensions."""

    DEFAULT = "default"
    CUSTOM = "custom"
    NONE = "none"


# Prompt-First Models
class PromptTemplateConfig(BaseModel):
    """Configuration for prompt templates."""

    variables: List[str] = Field(default_factory=list)
    required_variables: List[str] = Field(default_factory=list)
    optional_variables: List[str] = Field(default_factory=list)


class ExtensionPromptFiles(BaseModel):
    """Prompt file configuration for an extension."""

    system: Optional[str] = None
    user: Optional[str] = None
    templates: Dict[str, str] = Field(default_factory=dict)
    templates_config: Dict[str, PromptTemplateConfig] = Field(default_factory=dict)
    prompt_first: bool = True
    mode: PromptMode = PromptMode.DEFAULT
    contract_id: Optional[str] = None
    action_contracts: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    allowed_overrides: List[str] = Field(default_factory=list)


# Capability Models
class ExtensionCapabilities(BaseModel):
    """Extension capability declarations."""

    provides_ui: bool = False
    provides_api: bool = False
    provides_background_tasks: bool = False
    provides_webhooks: bool = False
    prompt_first: bool = True
    allowed_prompt_overrides: List[str] = Field(default_factory=list)


class ExtensionDependencies(BaseModel):
    """Extension dependency declarations."""

    plugins: List[str] = Field(default_factory=list)
    extensions: List[str] = Field(default_factory=list)
    system_services: List[str] = Field(default_factory=list)


class ExtensionPermissions(BaseModel):
    """Extension permission declarations (unified)."""

    # Host permissions (from base.py)
    memory_read: bool = False
    memory_write: bool = False
    tools: List[str] = Field(default_factory=list)
    user_data_read: bool = False
    user_data_write: bool = False
    system_config_read: bool = False
    system_config_write: bool = False

    # Registry permissions (from manifest.py)
    data_access: List[str] = Field(default_factory=list)
    plugin_access: List[str] = Field(default_factory=list)
    system_access: List[str] = Field(default_factory=list)
    network_access: List[str] = Field(default_factory=list)


class ExtensionResources(BaseModel):
    """Extension resource limits."""

    max_memory_mb: int = 256
    max_cpu_percent: int = 10
    max_disk_mb: int = 100
    enforcement_action: str = "default"


class ExtensionRBAC(BaseModel):
    """Role-based access control configuration for an extension."""

    allowed_roles: List[ExtensionRole] = Field(default_factory=list)
    default_enabled: bool = True


class ExtensionConfigSchema(BaseModel):
    """Schema for extension configuration."""

    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)
    additional_properties: bool = True


# UI and API Configuration
class ExtensionUIConfig(BaseModel):
    """Extension UI configuration."""

    control_room_pages: List[Dict[str, Any]] = Field(default_factory=list)
    hook_zones: List[Dict[str, Any]] = Field(default_factory=list)


class ExtensionAPIConfig(BaseModel):
    """Extension API configuration."""

    endpoints: List[Dict[str, Any]] = Field(default_factory=list)


class ExtensionBackgroundTask(BaseModel):
    """Extension background task configuration."""

    name: str
    schedule: str
    function: str


# Marketplace Models
class ExtensionMarketplaceInfo(BaseModel):
    """Extension marketplace metadata."""

    price: str = "free"
    support_url: Optional[str] = None
    documentation_url: Optional[str] = None
    screenshots: List[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    downloads: int = 0
    rating: float = 0.0
    reviews_count: int = 0


# Unified Extension Manifest
class ExtensionManifest(BaseModel):
    """
    Unified extension manifest combining fields from base.py and manifest.py.

    This is the canonical manifest definition for the prompt-first plugin system.
    All extensions should use this manifest format.
    """

    # Canonical ExtensionManifest uses strict validation.
    # Unknown fields must be rejected at the boundary; legacy normalization
    # happens explicitly in from_dict() before model creation.
    model_config = ConfigDict(extra="forbid")

    # Basic metadata (from manifest.py)
    name: str = Field(pattern=NAME_PATTERN, min_length=1, max_length=50)
    version: str = Field(pattern=SEMVER_PATTERN)
    display_name: str
    description: str
    author: str
    license: str
    category: str
    tags: List[str] = Field(default_factory=list)

    # API compatibility
    api_version: str = "1.0"
    kari_min_version: str = Field(default="0.4.0", pattern=SEMVER_PATTERN)

    # Entry point (from base.py) - optional for prompt-first plugins
    entrypoint: Optional[str] = None

    # Capabilities and configuration
    # Permissions and resources are REQUESTED declarations from the extension.
    # They are not runtime grants. RuntimePolicy decides what is actually granted.
    capabilities: ExtensionCapabilities = Field(default_factory=ExtensionCapabilities)
    dependencies: ExtensionDependencies = Field(default_factory=ExtensionDependencies)
    permissions: ExtensionPermissions = Field(default_factory=ExtensionPermissions)
    resources: ExtensionResources = Field(default_factory=ExtensionResources)
    rbac: ExtensionRBAC = Field(default_factory=ExtensionRBAC)

    # Hook points (from base.py)
    hook_points: List[HookPoint] = Field(default_factory=list)

    # Prompt files (from base.py) - critical for prompt-first
    prompt_files: ExtensionPromptFiles = Field(default_factory=ExtensionPromptFiles)

    # Configuration schema (from base.py)
    config_schema: Optional[ExtensionConfigSchema] = None

    # UI and API configuration (from manifest.py)
    ui: ExtensionUIConfig = Field(default_factory=ExtensionUIConfig)
    api: ExtensionAPIConfig = Field(default_factory=ExtensionAPIConfig)
    background_tasks: List[ExtensionBackgroundTask] = Field(default_factory=list)

    # Marketplace metadata (from manifest.py)
    marketplace: ExtensionMarketplaceInfo = Field(
        default_factory=ExtensionMarketplaceInfo
    )

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, v: Optional[str]) -> Optional[str]:
        """Validate that entrypoint is in format 'module:ClassName' if provided."""
        if v and ":" not in v:
            raise ValueError("Entrypoint must be in format 'module:ClassName'")
        return v

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "ExtensionManifest":
        """Load manifest from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtensionManifest":
        """
        Create manifest from dictionary with explicit compatibility translation.

        Legacy fields are normalized into the canonical schema before validation.
        Unknown fields are stripped with a warning; the canonical schema is strict.
        """
        allowed_keys = {
            "name",
            "version",
            "display_name",
            "description",
            "author",
            "license",
            "category",
            "tags",
            "api_version",
            "kari_min_version",
            "entrypoint",
            "capabilities",
            "dependencies",
            "permissions",
            "resources",
            "rbac",
            "hook_points",
            "prompt_files",
            "config_schema",
            "ui",
            "api",
            "background_tasks",
            "marketplace",
        }

        legacy_keys = {
            "plugin_api_version",
            "plugin_type",
            "entry_point",
            "module",
            "intent",
            "required_roles",
            "trusted_ui",
            "enable_external_workflow",
            "prompt_mode",
            "prompt_contract_id",
            "action_prompt_contracts",
            "allowed_prompt_overrides",
            "default_enabled",
        }

        normalized: Dict[str, Any] = {}
        stripped: List[str] = []
        for key, value in data.items():
            if key in allowed_keys:
                normalized[key] = value
            elif key in legacy_keys:
                continue
            else:
                stripped.append(key)

        if stripped:
            logger.warning(
                "Stripped unknown manifest fields: %s. "
                "Legacy fields must be mapped before validation.",
                stripped,
            )

        if "plugin_api_version" in data or "plugin_type" in data:
            normalized.setdefault("name", data.get("name", ""))
            normalized.setdefault("version", data.get("version", "1.0.0"))
            normalized.setdefault("display_name", data.get("display_name", data.get("name", "").replace("-", " ").title()))
            normalized.setdefault("description", data.get("description", ""))
            normalized.setdefault("author", data.get("author", "Unknown"))
            normalized.setdefault("license", data.get("license", "unknown"))
            normalized.setdefault("category", data.get("category", data.get("plugin_type", "general")))
            normalized.setdefault("tags", data.get("tags", []))
            normalized.setdefault("api_version", data.get("api_version", data.get("plugin_api_version", "1.0")))
            normalized.setdefault("kari_min_version", data.get("kari_min_version", "0.4.0"))
            normalized.setdefault("entrypoint", data.get("entry_point"))
            normalized.setdefault("capabilities", {
                "provides_ui": bool(data.get("trusted_ui")),
                "provides_api": False,
                "provides_background_tasks": bool(data.get("enable_external_workflow")),
                "provides_webhooks": False,
                "prompt_first": True,
                "allowed_prompt_overrides": data.get("allowed_prompt_overrides", []),
            })
            normalized.setdefault("prompt_files", {
                "prompt_first": True,
                "mode": data.get("prompt_mode", PromptMode.DEFAULT.value),
                "contract_id": data.get("prompt_contract_id"),
                "action_contracts": data.get("action_prompt_contracts", {}),
                "allowed_overrides": data.get("allowed_prompt_overrides", []),
            })
            normalized.setdefault("rbac", {
                "allowed_roles": data.get("required_roles", []),
                "default_enabled": data.get("default_enabled", True),
            })

        return cls(**normalized)

    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to dictionary."""
        return self.model_dump()


# Runtime Record Models
@dataclass
class ExtensionContext:
    """Context provided to extensions during initialization."""

    plugin_router: Any  # PluginRouter instance
    db_session: Any  # Database session
    app_instance: Any  # FastAPI app instance
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    extension_dir: Optional[Path] = None
    config: Optional[Dict[str, Any]] = None


@dataclass
class ExtensionRecord:
    """Runtime record of a loaded extension."""

    manifest: ExtensionManifest
    instance: Any  # BaseExtension instance
    status: ExtensionStatus
    directory: Path
    loaded_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert record to dictionary for serialization."""
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "status": self.status.value,
            "directory": str(self.directory),
            "loaded_at": self.loaded_at.isoformat() if self.loaded_at else None,
            "error_message": self.error_message,
            "manifest": self.manifest.to_dict(),
        }


# API Serialization Models
class ExtensionManifestAPI(BaseModel):
    """Pydantic model for API serialization of extension manifest."""

    name: str
    version: str
    display_name: str
    description: str
    author: str
    license: str
    category: str
    tags: List[str] = []
    api_version: str = "1.0"
    kari_min_version: str = "0.4.0"
    capabilities: Dict[str, Any] = {}
    prompt_files: Dict[str, Any] = {}
    marketplace: Dict[str, Any] = {}

    model_config = ConfigDict(extra="forbid")


class ExtensionStatusAPI(BaseModel):
    """Pydantic model for API serialization of extension status."""

    name: str
    version: str
    status: str
    loaded_at: Optional[float] = None
    error_message: Optional[str] = None


# Legacy Compatibility
class HookContext:
    """Context object passed to hook handlers."""

    def __init__(
        self,
        hook_point: HookPoint,
        data: Dict[str, Any],
        user_context: Optional[Dict[str, Any]] = None,
    ):
        self.hook_point = hook_point
        self.data = data
        self.user_context = user_context or {}
        self.timestamp = datetime.utcnow().timestamp()
        self.results: Dict[str, Any] = {}

    def get_data(self, key: str, default: Any = None) -> Any:
        """Get data from the context."""
        return self.data.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        """Set data in the context."""
        self.data[key] = value

    def get_user_context(self, key: str, default: Any = None) -> Any:
        """Get user context data."""
        return self.user_context.get(key, default)

    def set_result(self, extension_id: str, result: Any) -> None:
        """Set result from an extension."""
        self.results[extension_id] = result


__all__ = [
    # Enums
    "ExtensionStatus",
    "HookPoint",
    "Permission",
    "ExtensionRole",
    "PromptMode",
    # Constants
    "SEMVER_PATTERN",
    "NAME_PATTERN",
    # Models
    "ExtensionManifest",
    "ExtensionManifestAPI",
    "ExtensionStatusAPI",
    "ExtensionRecord",
    "ExtensionContext",
    # Sub-models
    "PromptTemplateConfig",
    "ExtensionPromptFiles",
    "ExtensionCapabilities",
    "ExtensionDependencies",
    "ExtensionPermissions",
    "ExtensionResources",
    "ExtensionRBAC",
    "ExtensionConfigSchema",
    "ExtensionUIConfig",
    "ExtensionAPIConfig",
    "ExtensionBackgroundTask",
    "ExtensionMarketplaceInfo",
    # Legacy
    "HookContext",
]
