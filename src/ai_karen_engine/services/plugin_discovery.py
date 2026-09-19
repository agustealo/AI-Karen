"""Canonical local-first plugin discovery and registry authority."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest

logger = logging.getLogger(__name__)
_PluginRecord = Dict[str, Any]


class PluginRegistry:
    """Own filesystem discovery, validation, registration state, and indices."""

    def __init__(
        self,
        marketplace_path: Optional[Path] = None,
        core_plugins_path: Optional[Path] = None,
    ) -> None:
        canonical = Path("src/ai_karen_engine/extensions/plugins")
        self.marketplace_path = marketplace_path or canonical
        self.core_plugins_path = core_plugins_path or canonical
        self.extensions_core_path = canonical
        self.legacy_marketplace_path = Path("plugin_marketplace")
        self.legacy_core_plugins_path = Path("src/ai_karen_engine/plugins")
        self.plugins: Dict[str, _PluginRecord] = {}
        self.plugins_by_category: Dict[str, List[str]] = {}
        self.plugins_by_type: Dict[str, List[str]] = {}
        self.excluded_paths = {
            "__pycache__",
            ".git",
            ".pytest_cache",
            "node_modules",
            ".artifacts",
        }
        self.metrics: Dict[str, Any] = {
            "plugins_discovered": 0,
            "plugins_validated": 0,
            "plugins_registered": 0,
            "validation_errors": 0,
            "last_discovery": None,
        }

    async def discover_plugins(
        self, force_refresh: bool = False
    ) -> Dict[str, _PluginRecord]:
        """Discover manifests from configured local roots without duplicate records.

        Operational state owned by the registry must survive a filesystem refresh.
        In particular, an administrator-disabled plugin must not be silently
        re-enabled merely because its manifest was rediscovered.
        """
        preserved_states: Dict[str, str] = {}
        if force_refresh:
            preserved_states = {
                name: str(metadata.get("status"))
                for name, metadata in self.plugins.items()
                if metadata.get("status") == "disabled"
            }
            self.plugins.clear()
            self.plugins_by_category.clear()
            self.plugins_by_type.clear()

        roots = (
            self.marketplace_path,
            self.core_plugins_path,
            self.extensions_core_path,
            self.legacy_marketplace_path,
            self.legacy_core_plugins_path,
        )
        discovered: Dict[str, _PluginRecord] = {}
        seen: set[str] = set()
        for root in roots:
            if not root.exists():
                continue
            resolved = str(root.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            discovered.update(await self._discover_in_path(root))

        for name, state in preserved_states.items():
            if name in discovered:
                discovered[name]["status"] = state
                discovered[name]["last_updated"] = datetime.now(timezone.utc)

        self.plugins.update(discovered)
        self._update_indices()
        self.metrics["plugins_discovered"] = len(discovered)
        self.metrics["last_discovery"] = datetime.now(timezone.utc).isoformat()
        logger.info("Discovered %d plugins", len(discovered))
        return discovered

    async def _discover_in_path(self, root: Path) -> Dict[str, _PluginRecord]:
        discovered: Dict[str, _PluginRecord] = {}
        for directory in root.iterdir():
            if (
                not directory.is_dir()
                or directory.name.startswith(".")
                or directory.name in self.excluded_paths
            ):
                continue
            manifest_path = directory / "plugin_manifest.json"
            if not manifest_path.exists():
                continue
            metadata = await self._load_plugin_metadata(manifest_path)
            if metadata is None:
                continue
            manifest = metadata["manifest"]
            discovered[manifest.name] = metadata
        return discovered

    async def _load_plugin_metadata(
        self, manifest_path: Path
    ) -> Optional[_PluginRecord]:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Plugin manifest must be a JSON object")
            manifest = ExtensionManifest.from_dict(raw)
            return {
                "manifest": manifest,
                "path": manifest_path.parent,
                "status": "discovered",
                "checksum": self._checksum(manifest_path.parent),
                "error_message": None,
                "dependencies_resolved": False,
                "compatibility_checked": False,
                "last_updated": datetime.now(timezone.utc),
            }
        except Exception:
            logger.exception("Failed to load plugin manifest %s", manifest_path)
            return None

    def _checksum(self, directory: Path) -> str:
        digest = hashlib.sha256()
        files = list(directory.rglob("*.py"))
        manifest = directory / "plugin_manifest.json"
        if manifest.exists():
            files.append(manifest)
        for path in sorted(files):
            if any(part in self.excluded_paths for part in path.parts):
                continue
            if path.is_file():
                digest.update(path.read_bytes())
        return digest.hexdigest()

    async def validate_plugin(self, plugin_name: str) -> bool:
        """Validate one dictionary-backed registry record consistently."""
        metadata = self.plugins.get(plugin_name)
        if metadata is None:
            logger.error("Plugin %s not found", plugin_name)
            return False
        try:
            checks = (
                self._validate_plugin_files,
                self._validate_plugin_module,
                self._validate_dependencies,
                self._validate_compatibility,
            )
            for check in checks:
                if not await check(metadata):
                    raise ValueError(f"{check.__name__} failed")
            metadata.update(
                status="validated",
                error_message=None,
                dependencies_resolved=True,
                compatibility_checked=True,
                last_updated=datetime.now(timezone.utc),
            )
            self.metrics["plugins_validated"] += 1
            return True
        except Exception as exc:
            metadata.update(
                status="error",
                error_message=str(exc),
                last_updated=datetime.now(timezone.utc),
            )
            self.metrics["validation_errors"] += 1
            logger.error("Plugin validation failed for %s: %s", plugin_name, exc)
            return False

    async def _validate_plugin_files(self, metadata: _PluginRecord) -> bool:
        directory = Path(metadata["path"])
        return (
            (directory / "plugin_manifest.json").exists()
            and (directory / "handler.py").exists()
        )

    async def _validate_plugin_module(self, metadata: _PluginRecord) -> bool:
        """Verify that the declared handler entrypoint can be imported."""
        try:
            directory = Path(metadata["path"])
            manifest = metadata["manifest"]
            init_path = directory / "__init__.py"
            handler_path = directory / "handler.py"
            if not init_path.exists() or not handler_path.exists():
                return False
            package_name = f"plugin_{manifest.name.replace('-', '_').replace('.', '_')}"
            spec = importlib.util.spec_from_file_location(
                package_name,
                init_path,
                submodule_search_locations=[str(directory)],
            )
            if spec is None or spec.loader is None:
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)
            handler = importlib.import_module(f"{package_name}.handler")
            entrypoint = manifest.entrypoint or "run"
            if ":" in entrypoint:
                module_name, attr_name = entrypoint.split(":", 1)
                return module_name == "handler" and hasattr(handler, attr_name)
            return hasattr(handler, entrypoint)
        except Exception:
            logger.exception(
                "Plugin module validation failed for %s", metadata.get("path")
            )
            return False

    async def _validate_dependencies(self, metadata: _PluginRecord) -> bool:
        manifest = metadata["manifest"]
        dependencies = getattr(manifest.dependencies, "plugins", []) or []
        missing = [name for name in dependencies if name not in self.plugins]
        if missing:
            logger.error(
                "Plugin %s has missing dependencies: %s",
                manifest.name,
                ", ".join(missing),
            )
            return False
        return True

    async def _validate_compatibility(self, metadata: _PluginRecord) -> bool:
        """Honor optional legacy compatibility metadata when it exists."""
        manifest = metadata["manifest"]
        compatibility = getattr(manifest, "compatibility", None)
        if compatibility is None:
            return True
        if hasattr(compatibility, "model_dump"):
            compatibility = compatibility.model_dump()
        if not isinstance(compatibility, dict):
            return True
        platforms = compatibility.get("os_platforms", []) or []
        if platforms and platform.system().lower() not in {
            str(value).lower() for value in platforms
        }:
            return False
        for package in compatibility.get("required_packages", []) or []:
            try:
                importlib.import_module(str(package))
            except ImportError:
                return False
        return True

    async def register_plugin(self, plugin_name: str) -> bool:
        metadata = self.plugins.get(plugin_name)
        if metadata is None or metadata.get("status") != "validated":
            return False
        metadata["status"] = "registered"
        metadata["last_updated"] = datetime.now(timezone.utc)
        self.metrics["plugins_registered"] += 1
        self._update_indices()
        return True

    def _update_indices(self) -> None:
        self.plugins_by_category.clear()
        self.plugins_by_type.clear()
        for name, metadata in self.plugins.items():
            manifest = metadata.get("manifest")
            if manifest is None:
                continue
            category = str(getattr(manifest, "category", "general") or "general")
            plugin_type = str(getattr(manifest, "plugin_type", None) or category)
            self.plugins_by_category.setdefault(category, []).append(name)
            self.plugins_by_type.setdefault(plugin_type, []).append(name)

    def get_plugin(self, plugin_name: str) -> Optional[_PluginRecord]:
        return self.plugins.get(plugin_name)

    def get_all_plugins(self) -> List[_PluginRecord]:
        return list(self.plugins.values())

    def get_plugins_by_category(self, category: str) -> List[_PluginRecord]:
        return [
            self.plugins[name]
            for name in self.plugins_by_category.get(category, [])
            if name in self.plugins
        ]

    def get_plugins_by_type(self, plugin_type: str) -> List[_PluginRecord]:
        return [
            self.plugins[name]
            for name in self.plugins_by_type.get(plugin_type, [])
            if name in self.plugins
        ]

    def get_plugins_by_status(self, status: str) -> List[_PluginRecord]:
        return [
            metadata
            for metadata in self.plugins.values()
            if metadata.get("status") == status
        ]

    def get_registry_stats(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        for metadata in self.plugins.values():
            status = str(metadata.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1
            manifest = metadata.get("manifest")
            if manifest is None:
                continue
            category = str(getattr(manifest, "category", "general") or "general")
            plugin_type = str(getattr(manifest, "plugin_type", None) or category)
            by_category[category] = by_category.get(category, 0) + 1
            by_type[plugin_type] = by_type.get(plugin_type, 0) + 1
        return {
            "total_plugins": len(self.plugins),
            "by_status": by_status,
            "by_type": by_type,
            "by_category": by_category,
            "metrics": dict(self.metrics),
        }


_plugin_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


async def initialize_plugin_registry(
    marketplace_path: Optional[Path] = None,
    core_plugins_path: Optional[Path] = None,
    auto_discover: bool = True,
) -> PluginRegistry:
    global _plugin_registry
    _plugin_registry = PluginRegistry(marketplace_path, core_plugins_path)
    if auto_discover:
        await _plugin_registry.discover_plugins()
    return _plugin_registry


__all__ = [
    "PluginRegistry",
    "get_plugin_registry",
    "initialize_plugin_registry",
]
