"""
Extension Discovery Service - Advanced extension discovery and registration mechanisms.

This module provides comprehensive extension discovery including:
- Recursive directory scanning
- Manifest validation and parsing
- Extension metadata extraction
- Dependency analysis
- Extension categorization and tagging
- Extension marketplace integration
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass

from ..manifest import (
    ExtensionManifest,
    ExtensionStatus,
    ExtensionCapabilities,
)
from .menu_discovery import discover_menu_contributions
from .validator import ExtensionValidator


@dataclass
class ExtensionMetadata:
    """Enhanced metadata for discovered extensions."""

    name: str
    version: str
    display_name: str
    description: str
    author: str
    category: str
    tags: List[str]
    directory: Path
    manifest_path: Path
    capabilities: ExtensionCapabilities
    dependencies: List[str]
    discovered_at: datetime
    file_hash: Optional[str] = None
    is_valid: bool = True
    validation_errors: List[str] = None
    menu_contributions: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.validation_errors is None:
            self.validation_errors = []
        if self.menu_contributions is None:
            self.menu_contributions = []


class ExtensionDiscoveryService:
    """
    Advanced extension discovery service with comprehensive scanning and validation.

    Provides:
    - Recursive directory scanning with pattern matching
    - Manifest validation and schema checking
    - Extension metadata extraction and indexing
    - Dependency analysis and conflict detection
    - Extension categorization and search
    - Marketplace integration
    """

    def __init__(
        self,
        extensions_dir: Union[str, Path],
        validator: Optional[ExtensionValidator] = None,
        enable_marketplace: bool = True,
        scan_patterns: Optional[List[str]] = None,
    ):
        """
        Initialize extension discovery service.

        Args:
            extensions_dir: Directory containing extensions
            validator: Extension validator instance
            enable_marketplace: Whether to enable marketplace integration
            scan_patterns: Custom scan patterns for extension directories
        """
        self.extensions_dir = Path(extensions_dir)
        self.validator = validator or ExtensionValidator()
        self.enable_marketplace = enable_marketplace
        self.scan_patterns = scan_patterns or ["*", "*/"]

        self.logger = logging.getLogger("extension.discovery_service")

        # Discovery cache
        self._discovered_extensions: Dict[str, ExtensionMetadata] = {}
        self._extension_index: Dict[str, List[str]] = {}
        self._dependency_graph: Dict[str, Set[str]] = {}
        self._category_index: Dict[str, List[str]] = {}

        # Ensure extensions directory exists
        self.extensions_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"Extension discovery service initialized for {self.extensions_dir}"
        )

    async def discover_extensions(
        self, force_refresh: bool = False, include_invalid: bool = False
    ) -> Dict[str, ExtensionMetadata]:
        """
        Discover all extensions in the extensions directory.

        Args:
            force_refresh: Force refresh of discovery cache
            include_invalid: Include extensions with validation errors

        Returns:
            Dictionary mapping extension names to their metadata
        """
        self.logger.info(f"Discovering extensions (force_refresh={force_refresh})")

        try:
            # Check if extensions directory exists
            if not self.extensions_dir.exists():
                self.logger.error(
                    f"Extensions directory does not exist: {self.extensions_dir}"
                )
                return {}

            # Check cache
            if not force_refresh and self._discovered_extensions:
                self.logger.debug("Returning cached extension discovery results")
                return self._discovered_extensions

            # Clear cache
            self._discovered_extensions.clear()
            self._extension_index.clear()
            self._dependency_graph.clear()
            self._category_index.clear()

            # Scan for extensions
            extension_dirs = await self._scan_extension_directories()
            self.logger.info(
                f"Found {len(extension_dirs)} potential extension directories"
            )

            # Process each extension
            for extension_dir in extension_dirs:
                try:
                    metadata = await self._analyze_extension(extension_dir)

                    if metadata or include_invalid:
                        self._discovered_extensions[metadata.name] = metadata

                        # Update indexes
                        self._update_indexes(metadata)

                        self.logger.info(
                            f"Discovered extension: {metadata.name} v{metadata.version}"
                        )
                    else:
                        self.logger.warning(
                            f"Skipping invalid extension: {extension_dir.name}"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Failed to analyze extension {extension_dir.name}: {e}"
                    )

            # Analyze dependencies
            await self._analyze_dependencies()

            # Log discovery summary
            valid_count = len(
                [ext for ext in self._discovered_extensions.values() if ext.is_valid]
            )
            invalid_count = len(self._discovered_extensions) - valid_count

            self.logger.info(
                f"Extension discovery complete: {valid_count} valid, {invalid_count} invalid"
            )

            return self._discovered_extensions

        except Exception as e:
            self.logger.error(f"Extension discovery failed: {e}")
            return {}

    async def _scan_extension_directories(self) -> List[Path]:
        """
        Scan for extension directories using configured patterns.
        Optimized to skip junk directories and avoid deep recursive scans.

        Returns:
            List of extension directory paths
        """
        extension_dirs: List[Path] = []
        seen_dirs: Set[Path] = set()

        # Directories to skip entirely during scanning
        skip_dirs = {
            "node_modules",
            "__pycache__",
            ".git",
            ".pytest_cache",
            ".artifacts",
            "venv",
            ".venv",
            "dist",
            "build",
        }

        try:
            # Start non-recursive scan for immediate subdirectories first
            # Extensions are usually organized in one level under the extensions root
            for path in self.extensions_dir.iterdir():
                if not path.is_dir() or path.name.startswith("_") or path.name in skip_dirs:
                    continue

                manifest_file = self._find_manifest_file(path)
                if manifest_file:
                    extension_dirs.append(path)
                    seen_dirs.add(path)

            # If no extensions found in top level, or if specifically needed,
            # we could fall back to a limited recursive scan, but for now 
            # we stick to the top-level for performance.
            
            return extension_dirs

        except Exception as e:
            self.logger.error(f"Failed to scan extension directories: {e}")
            return []

    async def _analyze_extension(
        self, extension_dir: Path
    ) -> Optional[ExtensionMetadata]:
        """
        Analyze an extension directory and extract metadata.

        Args:
            extension_dir: Extension directory path

        Returns:
            ExtensionMetadata or None if analysis fails
        """
        try:
            # Find manifest file
            manifest_file = self._find_manifest_file(extension_dir)
            if not manifest_file:
                self.logger.warning(f"No manifest file found in {extension_dir}")
                return None

            # Load and validate manifest
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            # Validate manifest
            is_valid, errors, warnings, field_errors = (
                self.validator.validate_manifest_enhanced(manifest_data)
            )

            # Create manifest object
            try:
                manifest = ExtensionManifest.from_dict(manifest_data)
            except Exception as e:
                self.logger.error(f"Failed to create manifest object: {e}")
                return None

            # Calculate file hash for integrity checking
            file_hash = await self._calculate_file_hash(extension_dir)

            # Create metadata
            manifest_dependencies = getattr(manifest, "dependencies", [])
            if hasattr(manifest_dependencies, "plugins"):
                normalized_dependencies = [
                    *list(getattr(manifest_dependencies, "plugins", []) or []),
                    *list(getattr(manifest_dependencies, "extensions", []) or []),
                    *list(getattr(manifest_dependencies, "system_services", []) or []),
                ]
            elif isinstance(manifest_dependencies, dict):
                normalized_dependencies = [
                    *(manifest_dependencies.get("plugins") or []),
                    *(manifest_dependencies.get("extensions") or []),
                    *(manifest_dependencies.get("system_services") or []),
                ]
            else:
                normalized_dependencies = list(manifest_dependencies or [])

            metadata = ExtensionMetadata(
                name=manifest.name,
                version=manifest.version,
                display_name=manifest.display_name,
                description=manifest.description,
                author=manifest.author,
                category=manifest.category,
                tags=getattr(manifest, "tags", []),
                directory=extension_dir,
                manifest_path=manifest_file,
                capabilities=getattr(manifest, "capabilities", ExtensionCapabilities()),
                dependencies=normalized_dependencies,
                file_hash=file_hash,
                discovered_at=datetime.now(timezone.utc),
                is_valid=is_valid,
                validation_errors=errors,
                menu_contributions=discover_menu_contributions(
                    plugin_id=manifest.name,
                    display_name=manifest.display_name,
                    extension_dir=extension_dir,
                    manifest_data=manifest_data,
                ),
            )

            # Log warnings
            for warning in warnings:
                self.logger.warning(f"Extension {manifest.name} warning: {warning}")

            return metadata

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in manifest for {extension_dir.name}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to analyze extension {extension_dir.name}: {e}")
            return None

    def _find_manifest_file(self, extension_dir: Path) -> Optional[Path]:
        """
        Find the manifest file in an extension directory.

        Args:
            extension_dir: Extension directory

        Returns:
            Path to manifest file or None
        """
        manifest_names = self._manifest_name_candidates(extension_dir)

        for manifest_name in manifest_names:
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

    async def _calculate_file_hash(self, extension_dir: Path) -> Optional[str]:
        """
        Calculate hash of all files in extension directory.

        Args:
            extension_dir: Extension directory

        Returns:
            Hash string or None
        """
        try:
            import hashlib

            hash_md5 = hashlib.md5()

            # Directories to skip entirely during hashing
            skip_dirs = {
                "node_modules",
                "__pycache__",
                ".git",
                ".pytest_cache",
                ".artifacts",
                "venv",
                ".venv",
                "dist",
                "build",
            }

            # Hash all Python and JSON files
            for file_path in extension_dir.rglob("*"):
                # Skip files in junk directories
                if any(part in skip_dirs for part in file_path.parts):
                    continue

                if file_path.is_file() and file_path.suffix in [
                    ".py",
                    ".json",
                    ".txt",
                    ".md",
                ]:
                    with open(file_path, "rb") as f:
                        hash_md5.update(f.read())

            return hash_md5.hexdigest()

        except Exception as e:
            self.logger.error(f"Failed to calculate hash for {extension_dir.name}: {e}")
            return None

    async def _analyze_dependencies(self) -> None:
        """
        Analyze dependencies between all discovered extensions.
        """
        try:
            self._dependency_graph.clear()

            for metadata in self._discovered_extensions.values():
                if metadata.is_valid:
                    # Extract dependencies from manifest
                    deps = set()
                    for dep in metadata.dependencies:
                        # Parse dependency specification
                        if "@" in dep:
                            dep_name = dep.split("@", 1)[0]
                        else:
                            dep_name = dep

                        deps.add(dep_name)

                    self._dependency_graph[metadata.name] = deps

            # Check for circular dependencies
            circular_deps = self._detect_circular_dependencies()
            if circular_deps:
                self.logger.warning(f"Circular dependencies detected: {circular_deps}")

            # Check for missing dependencies
            missing_deps = self._detect_missing_dependencies()
            if missing_deps:
                self.logger.warning(f"Missing dependencies detected: {missing_deps}")

        except Exception as e:
            self.logger.error(f"Failed to analyze dependencies: {e}")

    def _detect_circular_dependencies(self) -> List[str]:
        """
        Detect circular dependencies using depth-first search.

        Returns:
            List of extensions involved in circular dependencies
        """
        try:
            visited = set()
            rec_stack = set()

            def visit(ext_name: str, depth: int = 0) -> bool:
                if depth > 10:  # Prevent infinite recursion
                    return False

                if ext_name in rec_stack:
                    return True  # Circular dependency detected

                if ext_name in visited:
                    return False

                visited.add(ext_name)
                rec_stack.add(ext_name)

                # Visit all dependencies
                for dep in self._dependency_graph.get(ext_name, set()):
                    if visit(dep, depth + 1):
                        return True

                rec_stack.remove(ext_name)
                return False

            circular_deps = []
            for ext_name in self._dependency_graph.keys():
                if visit(ext_name):
                    circular_deps.append(ext_name)

            return circular_deps

        except Exception as e:
            self.logger.error(f"Failed to detect circular dependencies: {e}")
            return []

    def _detect_missing_dependencies(self) -> Dict[str, List[str]]:
        """
        Detect missing dependencies across all extensions.

        Returns:
            Dictionary mapping extensions to their missing dependencies
        """
        try:
            missing_deps = {}
            available_exts = set(self._discovered_extensions.keys())

            for ext_name, deps in self._dependency_graph.items():
                missing = [dep for dep in deps if dep not in available_exts]
                if missing:
                    missing_deps[ext_name] = missing

            return missing_deps

        except Exception as e:
            self.logger.error(f"Failed to detect missing dependencies: {e}")
            return {}

    def _update_indexes(self, metadata: ExtensionMetadata) -> None:
        """
        Update internal indexes for fast lookup.

        Args:
            metadata: Extension metadata
        """
        try:
            # Update extension index
            if metadata.name not in self._extension_index:
                self._extension_index[metadata.name] = []

            self._extension_index[metadata.name].append(str(metadata.directory))

            # Update category index
            if metadata.category not in self._category_index:
                self._category_index[metadata.category] = []

            if metadata.name not in self._category_index[metadata.category]:
                self._category_index[metadata.category].append(metadata.name)

        except Exception as e:
            self.logger.error(f"Failed to update indexes for {metadata.name}: {e}")

    def get_extension_metadata(
        self, extension_name: str
    ) -> Optional[ExtensionMetadata]:
        """
        Get metadata for a specific extension.

        Args:
            extension_name: Name of extension

        Returns:
            ExtensionMetadata or None if not found
        """
        return self._discovered_extensions.get(extension_name)

    def get_extensions_by_category(self, category: str) -> List[ExtensionMetadata]:
        """
        Get all extensions in a specific category.

        Args:
            category: Category name

        Returns:
            List of extension metadata
        """
        try:
            extension_names = self._category_index.get(category, [])
            return [
                self._discovered_extensions[name]
                for name in extension_names
                if name in self._discovered_extensions
            ]
        except Exception as e:
            self.logger.error(f"Failed to get extensions by category {category}: {e}")
            return []

    def get_extensions_by_tag(self, tag: str) -> List[ExtensionMetadata]:
        """
        Get all extensions with a specific tag.

        Args:
            tag: Tag name

        Returns:
            List of extension metadata
        """
        try:
            return [
                metadata
                for metadata in self._discovered_extensions.values()
                if metadata.is_valid and tag in metadata.tags
            ]
        except Exception as e:
            self.logger.error(f"Failed to get extensions by tag {tag}: {e}")
            return []

    def search_extensions(self, query: str, limit: int = 10) -> List[ExtensionMetadata]:
        """
        Search extensions by name, description, or tags.

        Args:
            query: Search query
            limit: Maximum number of results

        Returns:
            List of matching extension metadata
        """
        try:
            query_lower = query.lower()
            results = []

            for metadata in self._discovered_extensions.values():
                if not metadata.is_valid:
                    continue

                # Search in name, description, and tags
                searchable_text = f"{metadata.name} {metadata.display_name} {metadata.description} {' '.join(metadata.tags)}".lower()

                if query_lower in searchable_text:
                    results.append(metadata)

                    if len(results) >= limit:
                        break

            return results

        except Exception as e:
            self.logger.error(f"Failed to search extensions: {e}")
            return []

    def get_dependency_graph(self) -> Dict[str, Set[str]]:
        """
        Get the dependency graph for all extensions.

        Returns:
            Dictionary mapping extension names to their dependencies
        """
        return self._dependency_graph.copy()

    def get_extension_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about discovered extensions.

        Returns:
            Dictionary containing discovery statistics
        """
        try:
            total_extensions = len(self._discovered_extensions)
            valid_extensions = len(
                [ext for ext in self._discovered_extensions.values() if ext.is_valid]
            )
            categories = {}

            for metadata in self._discovered_extensions.values():
                if metadata.is_valid:
                    category = metadata.category
                    categories[category] = categories.get(category, 0) + 1

            return {
                "total_extensions": total_extensions,
                "valid_extensions": valid_extensions,
                "invalid_extensions": total_extensions - valid_extensions,
                "categories": categories,
                "discovery_timestamp": datetime.now(timezone.utc).isoformat(),
                "extension_count_by_category": categories,
            }

        except Exception as e:
            self.logger.error(f"Failed to get extension statistics: {e}")
            return {"error": str(e)}

    async def refresh_discovery(self, extension_name: Optional[str] = None) -> bool:
        """
        Refresh discovery for specific extension or all extensions.

        Args:
            extension_name: Optional extension name to refresh

        Returns:
            True if successful, False otherwise
        """
        try:
            if extension_name:
                # Remove specific extension from cache
                if extension_name in self._discovered_extensions:
                    del self._discovered_extensions[extension_name]

                # Re-discover the extension
                extension_dir = self.extensions_dir / extension_name
                if extension_dir.exists():
                    metadata = await self._analyze_extension(extension_dir)
                    if metadata:
                        self._discovered_extensions[extension_name] = metadata
                        self._update_indexes(metadata)
                        self.logger.info(f"Refreshed extension: {extension_name}")
                        return True

                return False
            else:
                # Refresh all extensions
                return await self.discover_extensions(force_refresh=True)

        except Exception as e:
            self.logger.error(f"Failed to refresh discovery: {e}")
            return False


__all__ = [
    "ExtensionDiscoveryService",
    "ExtensionMetadata",
]
