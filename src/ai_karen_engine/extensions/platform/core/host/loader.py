"""
Extension Loader - Discovers and loads extensions from the extensions directory.

This module handles the discovery, validation, and loading of extensions from the
unified extensions directory structure.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional
import json
import logging

from ai_karen_engine.extensions.platform.core.host.base import ExtensionBase, ExtensionContext
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from .config import ExtensionConfigManager
from .dependency_resolver import DependencyResolver
from .errors import (
    ExtensionLoadError,
    ExtensionValidationError,
    ExtensionManifestError,
    ExtensionNotFoundError,
)
from .utils.validation import validate_manifest

logger = logging.getLogger(__name__)


class ExtensionLoader:
    """
    Discovers and loads extensions from the extensions directory.

    Handles:
    - Extension discovery in the extensions directory
    - Manifest validation
    - Dynamic import of extension modules
    - Instantiation of extension classes
    - Error isolation during loading
    """
    def __init__(
        self,
        extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
        config_manager: Optional[ExtensionConfigManager] = None,
    ):
        """
        Initialize the extension loader.

        Args:
            extensions_dir: Path to the extensions directory
            config_manager: Optional configuration manager for extension settings
        """
        self.extensions_dir = Path(extensions_dir)
        self.config_manager = config_manager or ExtensionConfigManager()
        self._loaded_extensions: Dict[str, ExtensionBase] = {}
        self._discovered_paths: Dict[str, Path] = {}
        self.dependency_resolver = DependencyResolver()

        # Ensure the extensions directory exists
        if not self.extensions_dir.exists():
            logger.warning(
                f"Extensions directory {self.extensions_dir} does not exist, creating it"
            )
            self.extensions_dir.mkdir(parents=True, exist_ok=True)

    def discover_extensions(self) -> List[str]:
        """
        Discover all extension directories in the extensions directory.

        Returns:
            List of extension directory names
        """
        if not self.extensions_dir.exists():
            logger.warning(f"Extensions directory {self.extensions_dir} does not exist")
            return []

        self._discovered_paths.clear()
        discovered_ids: List[str] = []

        for item in self.extensions_dir.rglob("*"):
            if not item.is_dir() or item.name.startswith("_"):
                continue

            manifest_file = self._find_manifest_file(item)
            if not manifest_file:
                continue

            extension_id = self._get_extension_id(item, manifest_file)
            if extension_id in self._discovered_paths:
                continue

            self._discovered_paths[extension_id] = item
            discovered_ids.append(extension_id)

        logger.info(f"Discovered {len(discovered_ids)} extensions: {discovered_ids}")
        return discovered_ids

    def load_manifest(self, extension_name: str) -> ExtensionManifest:
        """
        Load and validate the manifest for an extension.

        Args:
            extension_name: Name of the extension

        Returns:
            ExtensionManifest object

        Raises:
            ExtensionNotFoundError: If extension directory doesn't exist
            ExtensionManifestError: If manifest file is missing or invalid
            ExtensionValidationError: If manifest validation fails
        """
        extension_dir = self._resolve_extension_dir(extension_name)

        if extension_dir is None or not extension_dir.exists():
            raise ExtensionNotFoundError(
                f"Extension directory {extension_dir} does not exist"
            )

        manifest_file = self._find_manifest_file(extension_dir)

        if manifest_file is None or not manifest_file.exists():
            raise ExtensionManifestError(
                f"Manifest file not found for extension {extension_name}"
            )

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ExtensionManifestError(
                f"Invalid JSON in manifest file for extension {extension_name}: {e}"
            )
        except Exception as e:
            raise ExtensionManifestError(
                f"Error reading manifest file for extension {extension_name}: {e}"
            )

        if self._is_legacy_plugin_manifest(manifest_data):
            expected_manifest = (
                "plugin_manifest.json"
                if "plugins" in set(extension_dir.parts)
                else "extension_manifest.json"
            )
            raise ExtensionManifestError(
                f"Extension {extension_name} still uses the legacy plugin manifest/runtime contract. "
                f"Migrate it to {expected_manifest} and a class-based ExtensionBase entrypoint before loading."
            )

        # Validate the manifest
        try:
            validate_manifest(manifest_data)
        except ExtensionValidationError as e:
            raise ExtensionValidationError(
                f"Manifest validation failed for extension {extension_name}: {e}"
            )

        # Create ExtensionManifest object
        try:
            manifest = ExtensionManifest.from_file(manifest_file)
        except Exception as e:
            raise ExtensionManifestError(
                f"Error creating ExtensionManifest object for {extension_name}: {e}"
            )

        return manifest

    def _find_manifest_file(self, extension_dir: Path) -> Optional[Path]:
        for manifest_name in self._manifest_name_candidates(extension_dir):
            manifest_file = extension_dir / manifest_name
            if manifest_file.exists():
                return manifest_file
        return None

    def _manifest_name_candidates(self, extension_dir: Path) -> List[str]:
        path_parts = set(extension_dir.parts)
        if "sys_extensions" in path_parts:
            return [
                "extension_manifest.json",
                "plugin_manifest.json",
                "extension.json",
                "manifest.json",
            ]
        return [
            "plugin_manifest.json",
            "extension_manifest.json",
            "extension.json",
            "manifest.json",
        ]

    def _resolve_extension_dir(self, extension_name: str) -> Optional[Path]:
        if extension_name in self._discovered_paths:
            return self._discovered_paths[extension_name]

        for item in self.extensions_dir.rglob("*"):
            if not item.is_dir() or item.name.startswith("_"):
                continue
            manifest_file = self._find_manifest_file(item)
            if not manifest_file:
                continue
            extension_id = self._get_extension_id(item, manifest_file)
            self._discovered_paths.setdefault(extension_id, item)
            self._discovered_paths.setdefault(item.name, item)

        return self._discovered_paths.get(extension_name)

    def _get_extension_id(self, extension_dir: Path, manifest_file: Path) -> str:
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            return manifest_data.get("name") or extension_dir.name
        except Exception:
            return extension_dir.name

    def _is_legacy_plugin_manifest(self, manifest_data: Dict[str, object]) -> bool:
        return any(
            key in manifest_data
            for key in (
                "plugin_api_version",
                "entry_point",
                "module",
                "intent",
                "plugin_type",
            )
        )

    def load_extension(self, extension_name: str) -> ExtensionBase:
        """
        Load an extension by name.

        Args:
            extension_name: Name of the extension to load

        Returns:
            ExtensionBase instance

        Raises:
            ExtensionNotFoundError: If extension directory doesn't exist
            ExtensionManifestError: If manifest file is missing or invalid
            ExtensionValidationError: If manifest validation fails
            ExtensionLoadError: If extension module or class cannot be loaded
        """
        if extension_name in self._loaded_extensions:
            logger.debug(
                f"Extension {extension_name} already loaded, returning cached instance"
            )
            return self._loaded_extensions[extension_name]

        # Load and validate manifest
        manifest = self.load_manifest(extension_name)

        # Load the extension module
        extension_dir = self._resolve_extension_dir(extension_name)
        if extension_dir is None:
            raise ExtensionNotFoundError(
                f"Extension directory for {extension_name} does not exist"
            )
        handler_file = extension_dir / "handler.py"

        if not handler_file.exists():
            raise ExtensionLoadError(
                f"Handler file not found for extension {extension_name}"
            )

        try:
            # Calculate the package name if possible
            # Extensions are expected to be in src/ai_karen_engine/extensions/plugins/<name>
            # which maps to package ai_karen_engine.extensions.plugins.<name>
            
            try:
                rel_path = handler_file.relative_to(Path("src").absolute() if Path("src").is_absolute() else Path("src"))
                package_parts = list(rel_path.parent.parts)
                package_name = ".".join(package_parts)
                module_fullname = f"{package_name}.handler"
            except ValueError:
                # Fallback if not in src/
                module_fullname = f"{extension_name}_handler"

            # Load the module
            spec = importlib.util.spec_from_file_location(
                module_fullname, handler_file
            )
            if spec is None or spec.loader is None:
                raise ExtensionLoadError(
                    f"Could not load module spec for extension {extension_name}"
                )

            module = importlib.util.module_from_spec(spec)
            # Ensure __package__ is set for relative imports
            module.__package__ = ".".join(module_fullname.split(".")[:-1])
            spec.loader.exec_module(module)

            # Get the extension class
            if not manifest.entrypoint:
                raise ExtensionLoadError(
                    f"Extension {extension_name} has no entrypoint defined"
                )

            entrypoint_parts = manifest.entrypoint.split(":")
            if len(entrypoint_parts) != 2:
                raise ExtensionLoadError(
                    f"Invalid entrypoint format: {manifest.entrypoint}"
                )

            module_name, class_name = entrypoint_parts

            if module_name != "handler":
                raise ExtensionLoadError(
                    f"Entrypoint module must be 'handler', got '{module_name}'"
                )

            if not hasattr(module, class_name):
                raise ExtensionLoadError(
                    f"Class {class_name} not found in extension module"
                )

            extension_class = getattr(module, class_name)

            # Verify it's a subclass of ExtensionBase
            if not issubclass(extension_class, ExtensionBase):
                raise ExtensionLoadError(
                    f"Extension class {class_name} does not inherit from ExtensionBase"
                )

            # Get extension-specific configuration
            extension_config = self.config_manager.get_extension_config(extension_name)
            extension_context = ExtensionContext(
                plugin_router=None,
                db_session=None,
                app_instance=None,
                extension_dir=extension_dir,
                config=extension_config,
            )

            # Create the extension instance
            extension_instance = extension_class(manifest, extension_context)

            # Store the loaded extension
            self._loaded_extensions[extension_name] = extension_instance

            logger.info(f"Successfully loaded extension {extension_name}")
            return extension_instance

        except Exception as e:
            if isinstance(e, ExtensionLoadError):
                raise
            raise ExtensionLoadError(f"Error loading extension {extension_name}: {e}")
        finally:
            # Remove the extension directory from Python path
            if str(extension_dir) in sys.path:
                sys.path.remove(str(extension_dir))

    def load_all_extensions(self) -> Dict[str, ExtensionBase]:
        """
        Load all discovered extensions in dependency order.

        Returns:
            Dictionary mapping extension names to ExtensionBase instances

        Raises:
            ExtensionLoadError: If any extension fails to load
        """
        extensions = {}
        extension_names = self.discover_extensions()

        # Load all manifests first for dependency resolution
        manifests = {}
        for extension_name in extension_names:
            try:
                manifest = self.load_manifest(extension_name)
                manifests[extension_name] = manifest
            except Exception as e:
                logger.error(f"Failed to load manifest for {extension_name}: {e}")
                continue

        # Resolve loading order using dependency resolver
        try:
            loading_order = self.dependency_resolver.resolve_loading_order(manifests)
            logger.info(f"Determined loading order: {loading_order}")
        except Exception as e:
            logger.warning(
                f"Failed to resolve loading order, using discovery order: {e}"
            )
            loading_order = extension_names

        # Load extensions in resolved order
        for extension_name in loading_order:
            try:
                extension = self.load_extension(extension_name)
                extensions[extension_name] = extension
                logger.info(f"Loaded extension {extension_name} successfully")
            except Exception as e:
                logger.error(f"Failed to load extension {extension_name}: {e}")
                # Continue loading other extensions

        # Check version compatibility after all extensions are loaded
        self._check_version_compatibility(manifests)

        return extensions

    def _check_version_compatibility(
        self, manifests: Dict[str, ExtensionManifest]
    ) -> None:
        """
        Check version compatibility between loaded extensions.

        Args:
            manifests: Dictionary of extension manifests
        """
        try:
            warnings = self.dependency_resolver.check_version_compatibility(manifests)
            if warnings:
                for warning in warnings:
                    logger.warning(f"Version compatibility warning: {warning}")
        except Exception as e:
            logger.error(f"Failed to check version compatibility: {e}")

    def reload_extension(self, extension_name: str) -> ExtensionBase:
        """
        Reload an extension that was previously loaded.

        Args:
            extension_name: Name of the extension to reload

        Returns:
            ExtensionBase instance

        Raises:
            ExtensionLoadError: If extension cannot be reloaded
        """
        if extension_name in self._loaded_extensions:
            del self._loaded_extensions[extension_name]

        return self.load_extension(extension_name)

    def get_loaded_extensions(self) -> Dict[str, ExtensionBase]:
        """
        Get all currently loaded extensions.

        Returns:
            Dictionary mapping extension names to ExtensionBase instances
        """
        return self._loaded_extensions.copy()

    def is_extension_loaded(self, extension_name: str) -> bool:
        """
        Check if an extension is currently loaded.

        Args:
            extension_name: Name of the extension to check

        Returns:
            True if extension is loaded, False otherwise
        """
        return extension_name in self._loaded_extensions
