"""
Unified Extension Loader

Consolidates the best features from both platform/core and runtime loader systems.
Provides comprehensive extension loading with validation, dependency resolution,
and error handling.
"""

import asyncio
import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime

from ...platform.core.manifest import ExtensionManifest
from ..database_models import ExtensionModel, ExtensionState
from ...platform.core.host.loader import ExtensionContext

logger = logging.getLogger(__name__)


@dataclass
class ExtensionLoadResult:
    """Result of extension loading operation."""

    success: bool
    extension: Optional[ExtensionModel] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    dependencies_loaded: List[str] = field(default_factory=list)


class ExtensionLoader:
    """Unified extension loader with comprehensive features."""

    def __init__(self, registry=None):
        self.registry = registry
        self.loaded_extensions: Dict[str, Any] = {}
        self.extension_paths: Dict[str, Path] = {}
        self._lock = asyncio.Lock()
        self._dependency_graph: Dict[str, Set[str]] = {}

        # Extension hooks
        self._extension_hooks: Dict[str, List[Callable]] = {}
        self._extension_events: Dict[str, List[Callable]] = {}

    async def initialize(self) -> None:
        """Initialize the loader."""
        await self._build_dependency_graph()
        logger.info("Extension loader initialized")

    async def load_extension(
        self, extension: ExtensionModel, validate: bool = True
    ) -> ExtensionLoadResult:
        """Load an extension with validation and dependency resolution."""
        async with self._lock:
            if extension.id in self.loaded_extensions:
                return ExtensionLoadResult(
                    success=True,
                    extension=extension,
                    warnings=[f"Extension {extension.name} is already loaded"],
                )

            # Validate extension if requested
            if validate:
                validation_result = await self._validate_extension(extension)
                if not validation_result.success:
                    return validation_result

                if validation_result.warnings:
                    logger.warning(
                        f"Extension {extension.name} validation warnings: {validation_result.warnings}"
                    )

            # Load dependencies first
            dependency_result = await self._load_dependencies(extension)
            if not dependency_result.success:
                return dependency_result

            try:
                # Load the extension module
                extension_module = await self._load_extension_module(extension)
                if not extension_module:
                    return ExtensionLoadResult(
                        success=False,
                        error=f"Failed to load extension module: {extension.name}",
                    )

                # Initialize extension
                init_result = await self._initialize_extension(
                    extension, extension_module
                )
                if not init_result.success:
                    return init_result

                # Register hooks and events
                await self._register_extension_hooks(extension, extension_module)

                # Track loaded extension
                self.loaded_extensions[extension.id] = extension_module
                self.extension_paths[extension.id] = Path(
                    extension.extension_path or ""
                )

                logger.info(
                    f"Successfully loaded extension: {extension.name} v{extension.version}"
                )

                return ExtensionLoadResult(
                    success=True,
                    extension=extension,
                    dependencies_loaded=dependency_result.dependencies_loaded,
                )

            except Exception as e:
                logger.error(f"Failed to load extension {extension.name}: {e}")
                return ExtensionLoadResult(
                    success=False, error=str(e), extension=extension
                )

    async def unload_extension(self, extension_id: str) -> bool:
        """Unload an extension."""
        async with self._lock:
            if extension_id not in self.loaded_extensions:
                logger.warning(f"Extension {extension_id} is not loaded")
                return False

            extension = await self.registry.get_extension(extension_id)
            if not extension:
                logger.error(f"Extension {extension_id} not found in registry")
                return False

            try:
                # Call cleanup hook if available
                await self._call_extension_hook(extension_id, "cleanup")

                # Remove from loaded extensions
                del self.loaded_extensions[extension_id]
                if extension_id in self.extension_paths:
                    del self.extension_paths[extension_id]

                logger.info(f"Successfully unloaded extension: {extension.name}")
                return True

            except Exception as e:
                logger.error(f"Failed to unload extension {extension.name}: {e}")
                return False

    async def reload_extension(self, extension_id: str) -> ExtensionLoadResult:
        """Reload an extension."""
        # First unload
        await self.unload_extension(extension_id)

        # Then load again
        extension = await self.registry.get_extension(extension_id)
        if not extension:
            return ExtensionLoadResult(success=False, error="Extension not found")

        return await self.load_extension(extension)

    async def get_loaded_extensions(self) -> List[ExtensionModel]:
        """Get list of loaded extensions."""
        if not self.registry:
            return []

        extensions = []
        for extension_id in self.loaded_extensions.keys():
            extension = await self.registry.get_extension(extension_id)
            if extension:
                extensions.append(extension)

        return extensions

    async def is_extension_loaded(self, extension_id: str) -> bool:
        """Check if extension is loaded."""
        return extension_id in self.loaded_extensions

    async def get_extension_module(self, extension_id: str) -> Optional[Any]:
        """Get the loaded extension module."""
        return self.loaded_extensions.get(extension_id)

    async def call_extension_hook(
        self, extension_id: str, hook_name: str, *args, **kwargs
    ) -> Any:
        """Call a specific hook on an extension."""
        if extension_id not in self.loaded_extensions:
            logger.warning(f"Extension {extension_id} is not loaded")
            return None

        return await self._call_extension_hook(extension_id, hook_name, *args, **kwargs)

    async def _validate_extension(
        self, extension: ExtensionModel
    ) -> ExtensionLoadResult:
        """Validate extension before loading."""
        errors = []
        warnings = []

        # Check extension state
        if extension.state not in [ExtensionState.INSTALLED, ExtensionState.ENABLED]:
            errors.append(f"Extension {extension.name} is not in a loadable state")

        # Check extension path
        if not extension.extension_path:
            errors.append(f"Extension {extension.name} has no extension path")
        else:
            path = Path(extension.extension_path)
            if not path.exists():
                errors.append(f"Extension path does not exist: {path}")
            elif not path.is_dir():
                errors.append(f"Extension path is not a directory: {path}")

        # Check manifest
        manifest = ExtensionManifest.from_dict(extension.manifest)
        manifest_errors = manifest.validate()
        errors.extend(manifest_errors)

        # Check dependencies
        for dep_name in manifest.dependencies.keys():
            dep_extension = await self.registry.get_extension_by_name(dep_name)
            if not dep_extension:
                errors.append(f"Missing dependency: {dep_name}")
            elif dep_extension.state not in [
                ExtensionState.INSTALLED,
                ExtensionState.ENABLED,
            ]:
                errors.append(f"Dependency {dep_name} is not in a loadable state")

        return ExtensionLoadResult(
            success=len(errors) == 0,
            extension=extension,
            error="\n".join(errors) if errors else None,
            warnings=warnings,
        )

    async def _load_dependencies(
        self, extension: ExtensionModel
    ) -> ExtensionLoadResult:
        """Load extension dependencies."""
        if not self.registry:
            return ExtensionLoadResult(success=True, extension=extension)

        dependencies_loaded = []
        manifest = ExtensionManifest.from_dict(extension.manifest)

        # Load dependencies in topological order
        for dep_name in manifest.dependencies.keys():
            dep_extension = await self.registry.get_extension_by_name(dep_name)
            if dep_extension and dep_extension.id not in self.loaded_extensions:
                dep_result = await self.load_extension(dep_extension, validate=False)
                if not dep_result.success:
                    return ExtensionLoadResult(
                        success=False,
                        error=f"Failed to load dependency {dep_name}: {dep_result.error}",
                        extension=extension,
                    )
                dependencies_loaded.append(dep_name)

        return ExtensionLoadResult(
            success=True, extension=extension, dependencies_loaded=dependencies_loaded
        )

    async def _load_extension_module(self, extension: ExtensionModel) -> Optional[Any]:
        """Load the extension module from file system."""
        if not extension.extension_path:
            logger.error(f"Extension {extension.name} has no extension path")
            return None

        try:
            path = Path(extension.extension_path)

            # Find the main extension file
            main_file = self._find_main_extension_file(path)
            if not main_file:
                logger.error(f"No main extension file found in {path}")
                return None

            # Load the module
            spec = importlib.util.spec_from_file_location(
                f"extension_{extension.id}", main_file
            )
            if not spec or not spec.loader:
                logger.error(f"Could not create module spec for {main_file}")
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            return module

        except Exception as e:
            logger.error(f"Failed to load extension module {extension.name}: {e}")
            return None

    def _find_main_extension_file(self, path: Path) -> Optional[Path]:
        """Find the main extension file in the given path."""
        possible_files = [
            path / "extension.py",
            path / "main.py",
            path / "__init__.py",
            path / f"{path.name}.py",
        ]

        for file_path in possible_files:
            if file_path.exists() and file_path.is_file():
                return file_path

        return None

    async def _initialize_extension(
        self, extension: ExtensionModel, module: Any
    ) -> ExtensionLoadResult:
        """Initialize the extension module."""
        try:
            # Check for initialize function
            if hasattr(module, "initialize"):
                result = await module.initialize()
                if result is False:
                    return ExtensionLoadResult(
                        success=False,
                        error="Extension initialization returned False",
                        extension=extension,
                    )

            # Create extension context
            context = ExtensionContext(
                extension_id=extension.id,
                extension_name=extension.name,
                extension_version=extension.version,
                registry=self.registry,
                logger=logger,
            )

            # Store context in module
            module._context = context

            logger.info(f"Initialized extension: {extension.name}")
            return ExtensionLoadResult(success=True, extension=extension)

        except Exception as e:
            logger.error(f"Failed to initialize extension {extension.name}: {e}")
            return ExtensionLoadResult(success=False, error=str(e), extension=extension)

    async def _register_extension_hooks(
        self, extension: ExtensionModel, module: Any
    ) -> None:
        """Register extension hooks and events."""
        manifest = ExtensionManifest.from_dict(extension.manifest)

        # Register hooks
        for hook_point in manifest.get_hook_points():
            if hasattr(module, hook_point):
                hook_func = getattr(module, hook_point)
                self._register_hook(hook_point, hook_func)

        # Register events
        for event_name in manifest.hooks.keys():
            if hasattr(module, f"on_{event_name}"):
                event_func = getattr(module, f"on_{event_name}")
                self._register_event(event_name, event_func)

    def _register_hook(self, hook_name: str, hook_func: Callable) -> None:
        """Register a hook function."""
        if hook_name not in self._extension_hooks:
            self._extension_hooks[hook_name] = []
        self._extension_hooks[hook_name].append(hook_func)

    def _register_event(self, event_name: str, event_func: Callable) -> None:
        """Register an event handler."""
        if event_name not in self._extension_events:
            self._extension_events[event_name] = []
        self._extension_events[event_name].append(event_func)

    async def _call_extension_hook(
        self, extension_id: str, hook_name: str, *args, **kwargs
    ) -> Any:
        """Call a specific hook on an extension."""
        module = self.loaded_extensions.get(extension_id)
        if not module:
            return None

        if hasattr(module, hook_name):
            hook_func = getattr(module, hook_name)
            if asyncio.iscoroutinefunction(hook_func):
                return await hook_func(*args, **kwargs)
            else:
                return hook_func(*args, **kwargs)

        return None

    async def _build_dependency_graph(self) -> None:
        """Build dependency graph for extension loading order."""
        if not self.registry:
            return

        self._dependency_graph = {}
        extensions = await self.registry.list_extensions()

        for extension in extensions:
            manifest = ExtensionManifest.from_dict(extension.manifest)
            self._dependency_graph[extension.id] = set(manifest.dependencies.keys())

    def get_loading_order(self, extension_ids: List[str]) -> List[str]:
        """Get the loading order for extensions based on dependencies."""
        # Topological sort
        visited = set()
        temp_visited = set()
        result = []

        def visit(extension_id: str):
            if extension_id in temp_visited:
                raise ValueError(f"Circular dependency detected: {extension_id}")
            if extension_id in visited:
                return

            temp_visited.add(extension_id)

            # Visit dependencies first
            for dep_id in self._dependency_graph.get(extension_id, []):
                visit(dep_id)

            temp_visited.remove(extension_id)
            visited.add(extension_id)
            result.append(extension_id)

        for extension_id in extension_ids:
            if extension_id not in visited:
                visit(extension_id)

        return result
