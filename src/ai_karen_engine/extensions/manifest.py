"""
Canonical extension manifest loader.

Loads and validates the typed ExtensionManifest from a plugin directory.
No plugin code is imported during manifest loading.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from ai_karen_engine.extensions.contracts import ExtensionManifest
from ai_karen_engine.extensions.errors import ExtensionManifestError

logger = logging.getLogger("kari.extensions.manifest")


class ExtensionManifestLoader:
    """Loads canonical extension manifests from disk."""

    def __init__(self, extensions_root: Path):
        self.extensions_root = extensions_root

    def load(self, plugin_id: str) -> ExtensionManifest:
        """Load manifest for a known plugin id."""
        extension_dir = self._resolve(plugin_id)
        manifest_file = self._find_manifest(extension_dir)
        if manifest_file is None:
            raise ExtensionManifestError(f"Manifest not found for extension '{plugin_id}'")

        with open(manifest_file, "r", encoding="utf-8") as f:
            raw = json.load(f)

        try:
            return ExtensionManifest(**raw)
        except Exception as exc:
            raise ExtensionManifestError(f"Invalid manifest for '{plugin_id}': {exc}") from exc

    def _resolve(self, plugin_id: str) -> Path:
        for candidate in self.extensions_root.rglob("*"):
            if not candidate.is_dir():
                continue
            manifest_file = self._find_manifest(candidate)
            if manifest_file is None:
                continue
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if raw.get("id") == plugin_id or raw.get("name") == plugin_id:
                    return candidate
            except Exception:
                continue
        raise ExtensionManifestError(f"Extension directory not found for '{plugin_id}'")

    def _find_manifest(self, extension_dir: Path) -> Optional[Path]:
        for name in ("extension_manifest.json", "plugin_manifest.json", "manifest.json"):
            candidate = extension_dir / name
            if candidate.exists():
                return candidate
        return None


__all__ = ["ExtensionManifestLoader"]
