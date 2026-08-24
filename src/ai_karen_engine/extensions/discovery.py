"""
Canonical extension discovery.

Scans configured directories for manifests without importing plugin code.
Discovery is a metadata-only operation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_karen_engine.extensions.contracts import (
    ExtensionManifest,
    ExtensionLifecycleState,
    TenantScope,
)

logger = logging.getLogger("kari.extensions.discovery")


class ExtensionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str
    path: Path
    manifest: Optional[ExtensionManifest] = None
    checksum: Optional[str] = None
    is_valid: bool = False
    validation_errors: List[str] = Field(default_factory=list)


class ExtensionDiscovery:
    """Async extension discovery service.

    Discovers extensions from configured directories. Does NOT import plugin
    code during discovery. Import happens only at load/execute time.
    """

    def __init__(
        self,
        directories: Optional[List[Path]] = None,
        *,
        excluded_paths: Optional[Set[str]] = None,
    ):
        self.directories = directories or [Path("src/ai_karen_engine/extensions/plugins")]
        self.excluded_paths = excluded_paths or {"__pycache__", ".git", ".pytest_cache", "node_modules", ".venv"}

    async def discover(self, force_refresh: bool = False) -> Dict[str, ExtensionMetadata]:
        """Discover all extensions in configured directories."""
        discovered: Dict[str, ExtensionMetadata] = {}

        for directory in self.directories:
            if not directory.exists():
                logger.debug("Discovery directory does not exist: %s", directory)
                continue

            for manifest_path in directory.rglob("plugin_manifest.json"):
                extension_dir = manifest_path.parent
                if any(excluded in extension_dir.parts for excluded in self.excluded_paths):
                    continue
                if extension_dir.name.startswith("."):
                    continue

                metadata = await self._load_metadata(manifest_path)
                if metadata is not None:
                    if metadata.plugin_id not in discovered:
                        discovered[metadata.plugin_id] = metadata
                    continue

            for manifest_path in directory.rglob("extension_manifest.json"):
                extension_dir = manifest_path.parent
                if any(excluded in extension_dir.parts for excluded in self.excluded_paths):
                    continue
                if extension_dir.name.startswith("."):
                    continue

                metadata = await self._load_metadata(manifest_path)
                if metadata is not None:
                    if metadata.plugin_id not in discovered:
                        discovered[metadata.plugin_id] = metadata

        logger.info("Discovered %d extensions", len(discovered))
        return discovered

    async def _load_metadata(self, manifest_path: Path) -> Optional[ExtensionMetadata]:
        """Load manifest metadata without importing plugin code."""
        extension_dir = manifest_path.parent

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read manifest %s: %s", manifest_path, exc)
            return None

        try:
            manifest = ExtensionManifest(**raw)
        except Exception as exc:
            return ExtensionMetadata(
                plugin_id=raw.get("id") or raw.get("name") or extension_dir.name,
                version=raw.get("version", "0.0.0"),
                path=extension_dir,
                is_valid=False,
                validation_errors=[str(exc)],
            )

        checksum = await self._checksum(extension_dir)
        return ExtensionMetadata(
            plugin_id=manifest.id,
            version=manifest.version,
            path=extension_dir,
            manifest=manifest,
            checksum=checksum,
            is_valid=True,
        )

    async def _checksum(self, extension_dir: Path) -> str:
        """Calculate deterministic checksum of extension source."""
        hasher = hashlib.sha256()
        for path in sorted(extension_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(extension_dir)
                if any(part in self.excluded_paths for part in rel.parts):
                    continue
                hasher.update(str(rel).encode())
                hasher.update(b":")
                try:
                    hasher.update(path.read_bytes())
                except OSError:
                    pass
        return hasher.hexdigest()

    def validate_manifest(self, manifest: ExtensionManifest) -> List[str]:
        """Validate manifest fields. Returns list of errors (empty if valid)."""
        errors: List[str] = []

        if not manifest.id:
            errors.append("manifest.id is required")
        if not manifest.name:
            errors.append("manifest.name is required")
        if not manifest.version:
            errors.append("manifest.version is required")
        if not manifest.entrypoint:
            errors.append("manifest.entrypoint is required")

        if manifest.tenant_scope == TenantScope.GLOBAL:
            errors.append("tenant_scope=global is forbidden; use single or multi with explicit tenant allowlist")

        if manifest.tenant_scope == TenantScope.MULTI and not manifest.allowed_tenant_ids:
            errors.append("Multi-tenant plugin must declare allowed_tenant_ids")

        if manifest.requires_network and not manifest.capabilities:
            errors.append("requires_network=true requires at least one capability declaration")

        return errors

    def validate_discovery(self, metadata: ExtensionMetadata) -> List[str]:
        """Validate discovered extension metadata."""
        if metadata.manifest is None:
            return ["manifest missing or invalid"]

        errors = list(metadata.validation_errors)
        errors.extend(self.validate_manifest(metadata.manifest))
        return errors


__all__ = ["ExtensionDiscovery", "ExtensionMetadata"]
