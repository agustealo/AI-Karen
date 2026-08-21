"""
Plugin Registry and Discovery Service.

This service manages plugin metadata, discovery, validation, and registration
for the AI Karen engine plugin system.
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Union
import uuid
import importlib.util
import hashlib

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class PluginStatus(str, Enum):
    """Plugin status enumeration."""
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    REGISTERED = "registered"
    LOADED = "loaded"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class PluginType(str, Enum):
    """Plugin type enumeration."""
    CORE = "core"
    AUTOMATION = "automation"
    AI = "ai"
    INTEGRATION = "integration"
    EXAMPLE = "example"
    CUSTOM = "custom"


@dataclass
class PluginDependency:
    """Plugin dependency specification."""
    name: str
    version: Optional[str] = None
    optional: bool = False
    min_version: Optional[str] = None
    max_version: Optional[str] = None


@dataclass
class PluginCompatibility:
    """Plugin compatibility requirements."""
    python_version: Optional[str] = None
    karen_version: Optional[str] = None
    os_platforms: List[str] = field(default_factory=list)
    required_packages: List[str] = field(default_factory=list)


class PluginManifest(BaseModel):
    """Plugin manifest model for validation."""
    model_config = ConfigDict(extra="allow")
    
    # Basic plugin information
    name: str
    version: str
    description: str
    author: str
    license: str = "MIT"
    
    # Plugin configuration
    plugin_api_version: str = "1.0"
    plugin_type: PluginType = PluginType.CUSTOM
    module: Optional[str] = None
    entry_point: str = "run"
    entrypoint: Optional[str] = None
    
    # Security and permissions
    required_roles: List[str] = Field(default_factory=lambda: ["user"])
    trusted_ui: bool = False
    enable_external_workflow: bool = False
    sandbox_required: bool = True
    
    # Dependencies and compatibility
    dependencies: List[Dict[str, Any]] = Field(default_factory=list)
    compatibility: Dict[str, Any] = Field(default_factory=dict)
    
    # Metadata
    tags: List[str] = Field(default_factory=list)
    category: str = "general"
    intent: Optional[str] = None
    
    @field_validator('plugin_api_version')
    @classmethod
    def validate_api_version(cls, v):
        """Validate plugin API version."""
        supported_versions = ["1.0", "1.1"]
        if v not in supported_versions:
            raise ValueError(f"Unsupported plugin API version: {v}")
        return v


@dataclass
class PluginMetadata:
    """Complete plugin metadata."""
    manifest: PluginManifest
    path: Path
    status: PluginStatus = PluginStatus.DISCOVERED
    error_message: Optional[str] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)
    checksum: Optional[str] = None
    load_time: Optional[float] = None
    dependencies_resolved: bool = False
    compatibility_checked: bool = False


class PluginRegistry:
    """
    Plugin registry for managing plugin discovery, validation, and metadata.
    """
    
    def __init__(self, marketplace_path: Optional[Path] = None, core_plugins_path: Optional[Path] = None):
        """Initialize plugin registry."""
        # Canonical extension/plugin layout.
        self.marketplace_path = marketplace_path or Path("src/ai_karen_engine/extensions/plugins")
        self.core_plugins_path = core_plugins_path or Path("src/ai_karen_engine/extensions/plugins")
        self.extensions_core_path = Path("src/ai_karen_engine/extensions/plugins")

        # Legacy discovery roots kept for in-repo compatibility during migration.
        self.legacy_marketplace_path = Path("plugin_marketplace")
        self.legacy_core_plugins_path = Path("src/ai_karen_engine/plugins")
        
        # Plugin storage
        self.plugins: Dict[str, PluginMetadata] = {}
        self.plugins_by_category: Dict[str, List[str]] = {}
        self.plugins_by_type: Dict[PluginType, List[str]] = {}
        
        # Discovery settings
        self.auto_discovery = True
        self.discovery_patterns = ["**/plugin_manifest.json"]
        self.excluded_paths = {"__pycache__", ".git", ".pytest_cache", "node_modules"}
        
        # Validation settings
        self.strict_validation = True
        self.require_manifest = True
        
        # Metrics
        self.metrics = {
            "plugins_discovered": 0,
            "plugins_validated": 0,
            "plugins_registered": 0,
            "validation_errors": 0,
            "last_discovery": None
        }
    
    async def discover_plugins(self, force_refresh: bool = False) -> Dict[str, PluginMetadata]:
        """
        Discover plugins in configured paths.
        
        Args:
            force_refresh: Force rediscovery of all plugins
            
        Returns:
            Dictionary of discovered plugin metadata
        """
        logger.info("Starting plugin discovery...")
        
        if force_refresh:
            self.plugins.clear()
            self.plugins_by_category.clear()
            self.plugins_by_type.clear()
        
        discovered_plugins = {}
        
        discovery_roots = [
            (self.marketplace_path, None),  # infer from manifest
            (self.core_plugins_path, PluginType.CORE),
            (self.extensions_core_path, PluginType.CORE),
            (self.legacy_marketplace_path, None),
            (self.legacy_core_plugins_path, PluginType.CORE),
        ]
        seen_roots = set()
        for root_path, plugin_type in discovery_roots:
            if not root_path.exists():
                logger.debug(f"Discovery root does not exist: {root_path}")
                continue
            
            normalized = str(root_path.resolve())
            if normalized in seen_roots:
                continue
            
            seen_roots.add(normalized)
            logger.info(f"Discovering plugins in: {normalized}")
            root_plugins = await self._discover_in_path(root_path, plugin_type=plugin_type)
            logger.info(f"Found {len(root_plugins)} plugins in {normalized}")
            discovered_plugins.update(root_plugins)
        
        # Update registry
        self.plugins.update(discovered_plugins)
        self._update_indices()
        
        # Update metrics
        self.metrics["plugins_discovered"] = len(discovered_plugins)
        self.metrics["last_discovery"] = datetime.utcnow()
        
        logger.info(f"Discovered {len(discovered_plugins)} plugins")
        return discovered_plugins
    
    async def _discover_in_path(self, base_path: Path, plugin_type: Optional[PluginType] = None) -> Dict[str, PluginMetadata]:
        """Discover plugins in a specific path."""
        discovered = {}
        
        logger.debug(f"Scanning for plugins in: {base_path}")
        
        # Optimized discovery: only look at immediate subdirectories first.
        # Most plugins are at base_path/plugin-name/plugin_manifest.json
        try:
            if not base_path.exists():
                return {}
                
            for item in base_path.iterdir():
                if not item.is_dir() or item.name in self.excluded_paths or item.name.startswith("."):
                    continue
                
                manifest_path = item / "plugin_manifest.json"
                if manifest_path.exists():
                    try:
                        plugin_metadata = await self._load_plugin_metadata(manifest_path, plugin_type)
                        if plugin_metadata:
                            logger.info(f"Successfully loaded plugin: {plugin_metadata.manifest.name}")
                            discovered[plugin_metadata.manifest.name] = plugin_metadata
                    except Exception as e:
                        logger.error(f"Failed to load plugin from {manifest_path}: {e}")
                        # Create error metadata
                        error_metadata = PluginMetadata(
                            manifest=PluginManifest(
                                name=f"error_{item.name}",
                                version="0.0.0",
                                description="Failed to load plugin",
                                author="unknown",
                                module="unknown"
                            ),
                            path=item,
                            status=PluginStatus.ERROR,
                            error_message=str(e)
                        )
                        discovered[error_metadata.manifest.name] = error_metadata
        except Exception as e:
            logger.error(f"Error scanning directory {base_path}: {e}")
        
        return discovered
    
    async def _load_plugin_metadata(self, manifest_path: Path, default_type: Optional[PluginType] = None) -> Optional[PluginMetadata]:
        """Load plugin metadata from manifest file."""
        try:
            # Read manifest
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)

            # Normalize legacy / canonical entrypoint fields.
            if 'entrypoint' in manifest_data and 'entry_point' not in manifest_data:
                manifest_data['entry_point'] = manifest_data['entrypoint']
            
            # Set default plugin type if not specified
            if 'plugin_type' not in manifest_data and default_type:
                manifest_data['plugin_type'] = default_type.value
            
            # Validate manifest
            try:
                manifest = PluginManifest(**manifest_data)
            except Exception as ve:
                logger.error(f"Manifest validation failed for {manifest_path}: {ve}")
                # Log the data for debugging
                logger.debug(f"Manifest data: {manifest_data}")
                return None
            
            # Calculate checksum
            checksum = await self._calculate_plugin_checksum(manifest_path.parent)
            
            # Create metadata
            metadata = PluginMetadata(
                manifest=manifest,
                path=manifest_path.parent,
                status=PluginStatus.DISCOVERED,
                checksum=checksum
            )
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to load plugin metadata from {manifest_path}: {e}")
            return None
    
    async def _calculate_plugin_checksum(self, plugin_path: Path) -> str:
        """Calculate checksum for plugin files. Optimized to skip junk."""
        hasher = hashlib.sha256()
        
        # Include all Python files and manifest, but skip junk directories
        for file_path in sorted(plugin_path.rglob("*.py")):
            if any(excluded in file_path.parts for excluded in self.excluded_paths):
                continue
            if file_path.is_file():
                hasher.update(file_path.read_bytes())
        
        manifest_path = plugin_path / "plugin_manifest.json"
        if manifest_path.exists():
            hasher.update(manifest_path.read_bytes())
        
        return hasher.hexdigest()
    
    async def validate_plugin(self, plugin_name: str) -> bool:
        """
        Validate a discovered plugin.
        
        Args:
            plugin_name: Name of the plugin to validate
            
        Returns:
            True if validation successful, False otherwise
        """
        if plugin_name not in self.plugins:
            logger.error(f"Plugin {plugin_name} not found in registry")
            return False
        
        metadata = self.plugins[plugin_name]
        
        try:
            # Basic manifest validation (already done during discovery)
            if metadata.status == PluginStatus.ERROR:
                return False
            
            # Check plugin files exist
            if not await self._validate_plugin_files(metadata):
                metadata.status = PluginStatus.ERROR
                metadata.error_message = "Required plugin files missing"
                return False
            
            # Validate module can be imported
            if not await self._validate_plugin_module(metadata):
                metadata.status = PluginStatus.ERROR
                metadata.error_message = "Plugin module cannot be imported"
                return False
            
            # Check dependencies
            if not await self._validate_dependencies(metadata):
                metadata.status = PluginStatus.ERROR
                metadata.error_message = "Plugin dependencies not satisfied"
                return False
            
            # Check compatibility
            if not await self._validate_compatibility(metadata):
                metadata.status = PluginStatus.ERROR
                metadata.error_message = "Plugin compatibility requirements not met"
                return False
            
            # Update status
            metadata.status = PluginStatus.VALIDATED
            metadata.dependencies_resolved = True
            metadata.compatibility_checked = True
            metadata.last_updated = datetime.utcnow()
            
            self.metrics["plugins_validated"] += 1
            logger.info(f"Plugin {plugin_name} validated successfully")
            return True
            
        except Exception as e:
            logger.error(f"Plugin validation failed for {plugin_name}: {e}")
            metadata.status = PluginStatus.ERROR
            metadata.error_message = str(e)
            self.metrics["validation_errors"] += 1
            return False
    
    async def _validate_plugin_files(self, metadata: PluginMetadata) -> bool:
        """Validate required plugin files exist."""
        plugin_path = metadata.path
        
        # Check manifest exists
        manifest_path = plugin_path / "plugin_manifest.json"
        if not manifest_path.exists():
            return False
        
        # Check handler file exists
        handler_path = plugin_path / "handler.py"
        if not handler_path.exists():
            return False
        
        # Check __init__.py exists
        init_path = plugin_path / "__init__.py"
        if not init_path.exists():
            logger.warning(f"Plugin {metadata.manifest.name} missing __init__.py")
        
        return True
    
    async def _validate_plugin_module(self, metadata: PluginMetadata) -> bool:
        """Validate plugin module can be imported."""
        try:
            plugin_path = metadata.path
            package_name = f"plugin_{metadata.manifest.name.replace('-', '_').replace('.', '_')}"
            init_path = plugin_path / "__init__.py"
            handler_path = plugin_path / "handler.py"
            entrypoint = getattr(metadata.manifest, "entry_point", None) or "run"

            if not init_path.exists() or not handler_path.exists():
                return False

            package_spec = importlib.util.spec_from_file_location(
                package_name,
                init_path,
                submodule_search_locations=[str(plugin_path)],
            )

            if package_spec is None or package_spec.loader is None:
                return False

            package_module = importlib.util.module_from_spec(package_spec)
            sys.modules[package_name] = package_module
            package_spec.loader.exec_module(package_module)

            handler_module = importlib.import_module(f"{package_name}.handler")

            if ":" in entrypoint:
                module_name, attr_name = entrypoint.split(":", 1)
                if module_name != "handler" or not hasattr(handler_module, attr_name):
                    logger.error(
                        "Plugin %s missing entrypoint: %s",
                        metadata.manifest.name,
                        entrypoint,
                    )
                    return False
            elif not hasattr(handler_module, entrypoint):
                logger.error(
                    "Plugin %s missing entry point: %s",
                    metadata.manifest.name,
                    entrypoint,
                )
                return False

            return True

        except Exception as e:
            logger.error(f"Module validation failed for {metadata.manifest.name}: {e}")
            return False
    
    async def _validate_dependencies(self, metadata: PluginMetadata) -> bool:
        """Validate plugin dependencies."""
        for dep_data in metadata.manifest.dependencies:
            try:
                dep = PluginDependency(**dep_data)
                
                # Check if dependency plugin exists
                if dep.name not in self.plugins:
                    if not dep.optional:
                        logger.error(f"Required dependency {dep.name} not found for plugin {metadata.manifest.name}")
                        return False
                    continue
                
                # Check version compatibility if specified
                dep_plugin = self.plugins[dep.name]
                if dep.version and dep_plugin.manifest.version != dep.version:
                    logger.error(f"Dependency version mismatch for {dep.name}")
                    return False
                
            except Exception as e:
                logger.error(f"Dependency validation failed: {e}")
                return False
        
        return True
    
    async def _validate_compatibility(self, metadata: PluginMetadata) -> bool:
        """Validate plugin compatibility requirements."""
        try:
            compat_data = metadata.manifest.compatibility
            if not compat_data:
                return True
            
            compatibility = PluginCompatibility(**compat_data)
            
            # Check Python version
            if compatibility.python_version:
                current_version = f"{sys.version_info.major}.{sys.version_info.minor}"
                if current_version != compatibility.python_version:
                    logger.warning(f"Python version mismatch for {metadata.manifest.name}")
            
            # Check OS platform
            if compatibility.os_platforms:
                import platform
                current_os = platform.system().lower()
                if current_os not in [p.lower() for p in compatibility.os_platforms]:
                    logger.error(f"OS platform {current_os} not supported by {metadata.manifest.name}")
                    return False
            
            # Check required packages
            for package in compatibility.required_packages:
                try:
                    importlib.import_module(package)
                except ImportError:
                    logger.error(f"Required package {package} not available for {metadata.manifest.name}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Compatibility validation failed: {e}")
            return False
    
    async def register_plugin(self, plugin_name: str) -> bool:
        """
        Register a validated plugin.
        
        Args:
            plugin_name: Name of the plugin to register
            
        Returns:
            True if registration successful, False otherwise
        """
        if plugin_name not in self.plugins:
            logger.error(f"Plugin {plugin_name} not found in registry")
            return False
        
        metadata = self.plugins[plugin_name]
        
        if metadata.status != PluginStatus.VALIDATED:
            logger.error(f"Plugin {plugin_name} must be validated before registration")
            return False
        
        try:
            # Update status
            metadata.status = PluginStatus.REGISTERED
            metadata.last_updated = datetime.utcnow()
            
            # Update indices
            self._update_indices()
            
            self.metrics["plugins_registered"] += 1
            logger.info(f"Plugin {plugin_name} registered successfully")
            return True
            
        except Exception as e:
            logger.error(f"Plugin registration failed for {plugin_name}: {e}")
            metadata.status = PluginStatus.ERROR
            metadata.error_message = str(e)
            return False
    
    def _update_indices(self):
        """Update plugin indices for fast lookup."""
        self.plugins_by_category.clear()
        self.plugins_by_type.clear()
        
        for plugin_name, metadata in self.plugins.items():
            # Index by category
            category = metadata.manifest.category
            if category not in self.plugins_by_category:
                self.plugins_by_category[category] = []
            self.plugins_by_category[category].append(plugin_name)
            
            # Index by type
            plugin_type = metadata.manifest.plugin_type
            if plugin_type not in self.plugins_by_type:
                self.plugins_by_type[plugin_type] = []
            self.plugins_by_type[plugin_type].append(plugin_name)
    
    def get_plugin(self, plugin_name: str) -> Optional[PluginMetadata]:
        """Get plugin metadata by name."""
        return self.plugins.get(plugin_name)
    
    def get_plugins_by_category(self, category: str) -> List[PluginMetadata]:
        """Get plugins by category."""
        plugin_names = self.plugins_by_category.get(category, [])
        return [self.plugins[name] for name in plugin_names]
    
    def get_plugins_by_type(self, plugin_type: PluginType) -> List[PluginMetadata]:
        """Get plugins by type."""
        plugin_names = self.plugins_by_type.get(plugin_type, [])
        return [self.plugins[name] for name in plugin_names]
    
    def get_plugins_by_status(self, status: PluginStatus) -> List[PluginMetadata]:
        """Get plugins by status."""
        return [metadata for metadata in self.plugins.values() if metadata.status == status]
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        stats = {
            "total_plugins": len(self.plugins),
            "by_status": {},
            "by_type": {},
            "by_category": {},
            "metrics": self.metrics.copy()
        }
        
        # Count by status
        for metadata in self.plugins.values():
            status = metadata.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
        
        # Count by type
        for plugin_type, plugin_names in self.plugins_by_type.items():
            stats["by_type"][plugin_type.value] = len(plugin_names)
        
        # Count by category
        for category, plugin_names in self.plugins_by_category.items():
            stats["by_category"][category] = len(plugin_names)
        
        return stats


# Global registry instance
_plugin_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """Get global plugin registry instance."""
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


async def initialize_plugin_registry(
    marketplace_path: Optional[Path] = None,
    core_plugins_path: Optional[Path] = None,
    auto_discover: bool = True
) -> PluginRegistry:
    """
    Initialize and optionally populate the plugin registry.
    
    Args:
        marketplace_path: Path to plugin marketplace
        core_plugins_path: Path to core plugins
        auto_discover: Whether to automatically discover plugins
        
    Returns:
        Initialized plugin registry
    """
    global _plugin_registry
    _plugin_registry = PluginRegistry(marketplace_path, core_plugins_path)
    
    if auto_discover:
        await _plugin_registry.discover_plugins()
    
    return _plugin_registry
