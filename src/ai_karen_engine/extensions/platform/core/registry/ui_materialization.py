"""Governed UI materialization pipeline.

The extension registry is the sole authority for which plugins may surface UI.
Filesystem content is used only as an artifact source after a plugin has been
registered and its discovery metadata has passed validation. The pipeline never
falls back to discovering operational plugin truth directly from disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.extensions.platform.core.registry.plugin_registry import get_registry

logger = logging.getLogger("kari.ui_materialization")


class UIArtifact:
    """Generated UI artifact metadata."""

    def __init__(
        self,
        artifact_type: str,
        plugin_id: str,
        source_path: Path,
        target_path: Path,
        content_hash: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.artifact_type = artifact_type
        self.plugin_id = plugin_id
        self.source_path = source_path
        self.target_path = target_path
        self.content_hash = content_hash
        self.metadata = metadata or {}
        self.generated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "plugin_id": self.plugin_id,
            "source_path": str(self.source_path),
            "target_path": str(self.target_path),
            "content_hash": self.content_hash,
            "metadata": self.metadata,
            "generated_at": self.generated_at.isoformat(),
        }


class UIMaterializationPipeline:
    """Materialize frontend artifacts for governed, validated extensions only."""

    ICON_PATTERN = r"^(.+?)---([a-z]+?)(?:--([a-z]+?))?_(\d{2})\.(svg|png|jpg|jpeg)$"
    SUPPORTED_ARTIFACT_TYPES = ["icon", "component", "manifest_entry", "menu_config"]

    def __init__(
        self,
        extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
        artifacts_dir: Optional[str] = None,
        plugins_ui_dir: Optional[str] = None,
    ) -> None:
        self.extensions_dir = Path(extensions_dir)
        self.artifacts_dir = (
            Path(artifacts_dir) if artifacts_dir else self.extensions_dir / ".artifacts"
        )
        self.plugins_ui_dir = (
            Path(plugins_ui_dir)
            if plugins_ui_dir
            else Path("src/ui_launchers/Karen-AI-Theme/src/plugin_repo")
        )
        self.registry = None
        self._artifact_cache: Dict[str, UIArtifact] = {}

        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.plugins_ui_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "UI materialization initialized: extensions=%s artifacts=%s ui=%s",
            self.extensions_dir,
            self.artifacts_dir,
            self.plugins_ui_dir,
        )

    def _get_registry(self):
        if self.registry is None:
            try:
                self.registry = get_registry()
            except Exception:
                logger.exception("Extension registry unavailable for UI materialization")
                return None
        return self.registry

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return getattr(value, "value", value)

    @classmethod
    def _to_dict(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return dict(model_dump())
        as_dict = getattr(value, "dict", None)
        if callable(as_dict):
            return dict(as_dict())
        if hasattr(value, "__dict__"):
            return {
                key: cls._enum_value(item)
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        return {}

    @classmethod
    def _provides_ui(cls, plugin: Any, metadata: Any) -> bool:
        capabilities = cls._to_dict(getattr(plugin, "capabilities", None))
        if not capabilities:
            capabilities = cls._to_dict(getattr(metadata, "capabilities", None))
        return bool(capabilities.get("provides_ui", False))

    async def discover_ui_plugins(self) -> List[Dict[str, Any]]:
        """Return only UI plugins admitted by the governed extension registry.

        No filesystem discovery fallback is permitted. If registry state is not
        available, the truthful result is an empty governed catalog rather than
        an inferred list of whatever happens to exist on disk.
        """

        registry = self._get_registry()
        if registry is None:
            logger.warning("UI discovery unavailable because extension registry is unavailable")
            return []

        plugins: List[Any] = []
        try:
            list_all = getattr(registry, "list_all_extensions", None)
            if callable(list_all):
                plugins = list(await list_all())
        except Exception:
            logger.exception("Failed to read persisted extensions for UI discovery")
            return []

        if not plugins:
            list_loaded = getattr(registry, "list_extensions", None)
            if callable(list_loaded):
                try:
                    plugins = list(list_loaded())
                except Exception:
                    logger.exception("Failed to read loaded extensions for UI discovery")
                    return []

        if not plugins:
            logger.info("No governed extensions available for UI materialization")
            return []

        ui_plugins = await self._process_registry_plugins(plugins)
        logger.info("Discovered %d governed UI-capable plugins", len(ui_plugins))
        return ui_plugins

    async def _process_registry_plugins(self, plugins: List[Any]) -> List[Dict[str, Any]]:
        registry = self._get_registry()
        if registry is None:
            return []

        get_metadata = getattr(registry, "get_metadata", None)
        if not callable(get_metadata):
            logger.error("Extension registry does not expose discovery metadata")
            return []

        ui_plugins: List[Dict[str, Any]] = []
        for plugin in plugins:
            plugin_id = str(getattr(plugin, "name", "") or "").strip()
            if not plugin_id:
                continue

            metadata = get_metadata(plugin_id)
            if metadata is None:
                logger.warning(
                    "Skipping UI plugin %s because governed discovery metadata is missing",
                    plugin_id,
                )
                continue
            if not bool(getattr(metadata, "is_valid", False)):
                logger.warning(
                    "Skipping UI plugin %s because discovery validation failed: %s",
                    plugin_id,
                    getattr(metadata, "validation_errors", []),
                )
                continue
            if not self._provides_ui(plugin, metadata):
                continue

            plugin_dir = Path(getattr(metadata, "directory", ""))
            manifest_path = Path(getattr(metadata, "manifest_path", ""))
            if not plugin_dir.exists() or not manifest_path.exists():
                logger.warning(
                    "Skipping UI plugin %s because canonical artifact source is missing",
                    plugin_id,
                )
                continue

            try:
                with manifest_path.open("r", encoding="utf-8") as handle:
                    manifest_data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                logger.exception("Failed to read canonical manifest for UI plugin %s", plugin_id)
                continue

            ui_config = manifest_data.get("ui")
            if not isinstance(ui_config, dict) or not ui_config:
                logger.warning(
                    "Skipping UI plugin %s because validated manifest has no UI contract",
                    plugin_id,
                )
                continue

            source_path = str(ui_config.get("source_path") or "ui")
            ui_component_dir = plugin_dir / source_path
            entry_file_name = str(ui_config.get("entry_file") or "PluginPage.tsx")
            entry_candidate = plugin_dir / entry_file_name
            if not entry_candidate.exists():
                entry_candidate = ui_component_dir / Path(entry_file_name).name
            has_component = entry_candidate.exists() and entry_candidate.is_file()

            capabilities = self._to_dict(getattr(plugin, "capabilities", None))
            if not capabilities:
                capabilities = self._to_dict(getattr(metadata, "capabilities", None))

            ui_plugins.append(
                {
                    "plugin_id": plugin_id,
                    "display_name": getattr(plugin, "display_name", None)
                    or getattr(metadata, "display_name", None)
                    or plugin_id,
                    "version": getattr(plugin, "version", None)
                    or getattr(metadata, "version", None),
                    "status": self._enum_value(getattr(plugin, "status", None)),
                    "category": getattr(metadata, "category", None),
                    "registry_validated": True,
                    "validation_errors": [],
                    "capabilities": capabilities,
                    "has_component": has_component,
                    "component_path": str(entry_candidate) if has_component else None,
                    "menu_config": ui_config.get("menu", []),
                    "icons": self._discover_plugin_icons(plugin_dir, plugin_id),
                    "ui_config": ui_config,
                    "plugin_dir": str(plugin_dir),
                    "manifest_path": str(manifest_path),
                }
            )

        return ui_plugins

    def _discover_plugin_icons(
        self, plugin_dir: Path, plugin_id: str
    ) -> List[Dict[str, Any]]:
        icons: List[Dict[str, Any]] = []
        pattern = re.compile(self.ICON_PATTERN)

        for file_path in plugin_dir.rglob("*"):
            if not file_path.is_file():
                continue
            match = pattern.match(file_path.name)
            if not match or match.group(1) != plugin_id:
                continue
            icons.append(
                {
                    "filename": file_path.name,
                    "path": str(file_path),
                    "plugin_id": match.group(1),
                    "placement": match.group(2),
                    "subplacement": match.group(3),
                    "order": int(match.group(4)),
                    "extension": match.group(5),
                    "relative_path": str(file_path.relative_to(plugin_dir)),
                }
            )

        return icons

    async def materialize_all(self) -> Dict[str, Any]:
        logger.info("Starting governed UI materialization")
        ui_plugins = await self.discover_ui_plugins()
        generated: List[Dict[str, Any]] = []
        updated: List[Dict[str, Any]] = []
        removed: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for plugin_ui in ui_plugins:
            try:
                result = await self.materialize_plugin(plugin_ui)
                generated.extend(result["generated"])
                updated.extend(result["updated"])
                removed.extend(result["removed"])
            except Exception as exc:
                logger.exception(
                    "Failed to materialize governed UI plugin %s",
                    plugin_ui["plugin_id"],
                )
                errors.append(
                    {"plugin_id": plugin_ui["plugin_id"], "error": str(exc)}
                )

        removed.extend(await self.cleanup_stale_artifacts(ui_plugins))
        import_map = await self.generate_import_map(ui_plugins)
        return {
            "status": "success" if not errors else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "plugins_processed": len(ui_plugins),
            "artifacts_generated": len(generated),
            "artifacts_updated": len(updated),
            "artifacts_removed": len(removed),
            "errors": errors,
            "import_map": import_map,
        }

    async def materialize_plugin(self, plugin_ui: Dict[str, Any]) -> Dict[str, Any]:
        if not plugin_ui.get("registry_validated"):
            raise ValueError("refusing to materialize unvalidated UI plugin metadata")

        generated: List[Dict[str, Any]] = []
        updated: List[Dict[str, Any]] = []
        removed: List[Dict[str, Any]] = []

        if plugin_ui.get("icons"):
            icon_results = await self._materialize_icons(plugin_ui)
            generated.extend(icon_results["generated"])
            updated.extend(icon_results["updated"])

        if plugin_ui.get("has_component") and plugin_ui.get("component_path"):
            source_ok = await self._materialize_ui_source(plugin_ui)
            if not source_ok:
                raise RuntimeError(
                    f"failed to materialize UI source for {plugin_ui['plugin_id']}"
                )
            component_result = await self._materialize_component(plugin_ui)
            if component_result:
                target = (
                    generated
                    if component_result["action"] == "generated"
                    else updated
                )
                target.append(component_result["artifact"])

        if plugin_ui.get("menu_config"):
            menu_result = await self._materialize_menu_config(plugin_ui)
            if menu_result:
                generated.append(menu_result["artifact"])

        return {
            "plugin_id": plugin_ui["plugin_id"],
            "generated": generated,
            "updated": updated,
            "removed": removed,
        }

    async def _materialize_icons(
        self, plugin_ui: Dict[str, Any]
    ) -> Dict[str, List[Dict[str, Any]]]:
        generated: List[Dict[str, Any]] = []
        updated: List[Dict[str, Any]] = []
        plugin_id = plugin_ui["plugin_id"]
        icon_output_dir = self.artifacts_dir / "icons" / plugin_id
        icon_output_dir.mkdir(parents=True, exist_ok=True)

        for icon in plugin_ui.get("icons", []):
            source_path = Path(icon["path"])
            if not source_path.exists():
                logger.warning("Icon source disappeared: %s", source_path)
                continue
            content_hash = self._calculate_file_hash(source_path)
            target_path = icon_output_dir / icon["filename"]
            existing_hash = (
                self._calculate_file_hash(target_path) if target_path.exists() else None
            )
            if existing_hash == content_hash:
                continue

            shutil.copy2(source_path, target_path)
            artifact = UIArtifact(
                artifact_type="icon",
                plugin_id=plugin_id,
                source_path=source_path,
                target_path=target_path,
                content_hash=content_hash,
                metadata=icon,
            )
            payload = artifact.to_dict()
            (generated if existing_hash is None else updated).append(payload)
            self._artifact_cache[str(target_path)] = artifact

        return {"generated": generated, "updated": updated}

    async def _materialize_component(
        self, plugin_ui: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        plugin_id = plugin_ui["plugin_id"]
        component_path = Path(plugin_ui["component_path"])
        if not component_path.exists():
            return None

        content_hash = self._calculate_file_hash(component_path)
        target_path = self.artifacts_dir / "components" / f"{plugin_id}.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        existing_content = None
        if target_path.exists():
            try:
                with target_path.open("r", encoding="utf-8") as handle:
                    existing_content = json.load(handle)
            except (OSError, json.JSONDecodeError):
                existing_content = None

        artifact_data = {
            "plugin_id": plugin_id,
            "component_path": str(component_path),
            "display_name": plugin_ui.get("display_name") or plugin_id,
            "version": plugin_ui.get("version"),
            "status": plugin_ui.get("status"),
            "category": plugin_ui.get("category"),
            "registry_validated": True,
            "generated_at": datetime.utcnow().isoformat(),
            "content_hash": content_hash,
        }
        comparable_existing = dict(existing_content or {})
        comparable_existing.pop("generated_at", None)
        comparable_new = dict(artifact_data)
        comparable_new.pop("generated_at", None)
        if comparable_existing == comparable_new:
            return None

        with target_path.open("w", encoding="utf-8") as handle:
            json.dump(artifact_data, handle, indent=2)

        artifact = UIArtifact(
            artifact_type="component",
            plugin_id=plugin_id,
            source_path=component_path,
            target_path=target_path,
            content_hash=content_hash,
            metadata=artifact_data,
        )
        self._artifact_cache[str(target_path)] = artifact
        return {
            "action": "generated" if existing_content is None else "updated",
            "artifact": artifact.to_dict(),
        }

    async def _materialize_ui_source(self, plugin_ui: Dict[str, Any]) -> bool:
        plugin_id = plugin_ui["plugin_id"]
        plugin_dir = Path(plugin_ui["plugin_dir"])
        manifest_path = Path(plugin_ui["manifest_path"])
        ui_config = plugin_ui.get("ui_config", {})
        source_dir = plugin_dir / str(ui_config.get("source_path") or "ui")
        if not source_dir.exists():
            logger.error(
                "Validated UI contract source is missing for %s: %s",
                plugin_id,
                source_dir,
            )
            return False

        target_dir = self.plugins_ui_dir / plugin_id.replace("_", "-")
        target_dir.mkdir(parents=True, exist_ok=True)
        allowed_suffixes = {".tsx", ".jsx", ".ts", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg"}

        try:
            for file_path in source_dir.rglob("*"):
                if not file_path.is_file() or file_path.suffix.lower() not in allowed_suffixes:
                    continue
                relative_path = file_path.relative_to(source_dir)
                destination = target_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if (
                    not destination.exists()
                    or self._calculate_file_hash(file_path)
                    != self._calculate_file_hash(destination)
                ):
                    shutil.copy2(file_path, destination)

            destination_manifest = target_dir / "manifest.json"
            if (
                not destination_manifest.exists()
                or self._calculate_file_hash(manifest_path)
                != self._calculate_file_hash(destination_manifest)
            ):
                shutil.copy2(manifest_path, destination_manifest)
            return True
        except Exception:
            logger.exception("Failed to materialize UI source for %s", plugin_id)
            return False

    async def _materialize_menu_config(
        self, plugin_ui: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        menu_config = plugin_ui.get("menu_config", [])
        if not menu_config:
            return None

        plugin_id = plugin_ui["plugin_id"]
        target_path = self.artifacts_dir / "menus" / f"{plugin_id}.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_data = {
            "plugin_id": plugin_id,
            "display_name": plugin_ui.get("display_name") or plugin_id,
            "menus": menu_config,
            "icons": plugin_ui.get("icons", []),
            "registry_validated": True,
        }
        content_hash = hashlib.sha256(
            json.dumps(artifact_data, sort_keys=True).encode("utf-8")
        ).hexdigest()

        existing_hash = None
        if target_path.exists():
            try:
                with target_path.open("r", encoding="utf-8") as handle:
                    existing_data = json.load(handle)
                existing_hash = hashlib.sha256(
                    json.dumps(existing_data, sort_keys=True).encode("utf-8")
                ).hexdigest()
            except (OSError, json.JSONDecodeError):
                existing_hash = None

        if existing_hash == content_hash:
            return None

        with target_path.open("w", encoding="utf-8") as handle:
            json.dump(artifact_data, handle, indent=2)

        artifact = UIArtifact(
            artifact_type="menu_config",
            plugin_id=plugin_id,
            source_path=Path(plugin_ui["manifest_path"]),
            target_path=target_path,
            content_hash=content_hash,
            metadata=artifact_data,
        )
        self._artifact_cache[str(target_path)] = artifact
        return {"artifact": artifact.to_dict()}

    async def generate_import_map(
        self, ui_plugins: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        import_map: Dict[str, str] = {}
        for plugin in ui_plugins:
            if not plugin.get("registry_validated") or not plugin.get("has_component"):
                continue
            component_path = plugin.get("component_path")
            if not component_path:
                continue

            plugin_id = plugin["plugin_id"]
            normalized_id = plugin_id.lower().replace("_", "-")
            component_name = Path(component_path).stem
            import_path = f"@/plugin_repo/{normalized_id}/{component_name}"
            import_map[normalized_id] = import_path
            import_map[plugin_id] = import_path

        return import_map

    async def cleanup_stale_artifacts(
        self, active_plugins: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        removed: List[Dict[str, Any]] = []
        active_ids = {
            plugin["plugin_id"]
            for plugin in active_plugins
            if plugin.get("registry_validated")
        }

        icons_dir = self.artifacts_dir / "icons"
        if icons_dir.exists():
            for plugin_dir in icons_dir.iterdir():
                if not plugin_dir.is_dir() or plugin_dir.name in active_ids:
                    continue
                for artifact_file in plugin_dir.rglob("*"):
                    if artifact_file.is_file():
                        removed.append(
                            {
                                "artifact_type": "icons",
                                "plugin_id": plugin_dir.name,
                                "path": str(artifact_file),
                                "action": "removed",
                            }
                        )
                shutil.rmtree(plugin_dir, ignore_errors=True)

        for artifact_type in ("components", "menus"):
            type_dir = self.artifacts_dir / artifact_type
            if not type_dir.exists():
                continue
            for artifact_file in type_dir.glob("*.json"):
                plugin_id = artifact_file.stem
                if plugin_id in active_ids:
                    continue
                removed.append(
                    {
                        "artifact_type": artifact_type,
                        "plugin_id": plugin_id,
                        "path": str(artifact_file),
                        "action": "removed",
                    }
                )
                artifact_file.unlink(missing_ok=True)

        return removed

    @staticmethod
    def _calculate_file_hash(file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def get_artifact_status(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {
            "artifacts_dir": str(self.artifacts_dir),
            "artifact_types": {},
            "total_artifacts": 0,
        }

        directory_map = {
            "icon": self.artifacts_dir / "icons",
            "component": self.artifacts_dir / "components",
            "manifest_entry": self.artifacts_dir / "manifest_entry",
            "menu_config": self.artifacts_dir / "menus",
        }
        for artifact_type in self.SUPPORTED_ARTIFACT_TYPES:
            type_dir = directory_map[artifact_type]
            if not type_dir.exists():
                status["artifact_types"][artifact_type] = {"count": 0, "artifacts": []}
                continue
            artifacts = [str(path) for path in type_dir.rglob("*") if path.is_file()]
            status["artifact_types"][artifact_type] = {
                "count": len(artifacts),
                "artifacts": artifacts[:10],
            }
            status["total_artifacts"] += len(artifacts)

        return status


_pipeline_instance: Optional[UIMaterializationPipeline] = None


def get_ui_pipeline(
    extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
    artifacts_dir: Optional[str] = None,
    plugins_ui_dir: Optional[str] = None,
) -> UIMaterializationPipeline:
    """Return the singleton governed UI materialization pipeline."""

    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = UIMaterializationPipeline(
            extensions_dir=extensions_dir,
            artifacts_dir=artifacts_dir,
            plugins_ui_dir=plugins_ui_dir,
        )
    return _pipeline_instance
