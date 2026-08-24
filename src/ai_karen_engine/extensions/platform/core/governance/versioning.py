"""
Version compatibility and deprecation rules for governed plugins.

Enforces:
- Manifest version semver compatibility with engine minimum version
- Deprecation date checks
- Removal date enforcement
- Version mismatch safe handling
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.extensions.platform.core.governance.manifest_schema import (
    DeprecationInfo,
)

logger = logging.getLogger("kari.plugin_governance.versioning")

SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?$"
)


@dataclass
class VersionCompatibility:
    compatible: bool
    engine_version: str
    plugin_version: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compatible": self.compatible,
            "engine_version": self.engine_version,
            "plugin_version": self.plugin_version,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


class PluginVersionPolicy:
    """Evaluates plugin version compatibility and deprecation status."""

    def __init__(self, engine_version: str = "0.5.0"):
        self.engine_version = engine_version
        self._parsed_engine = self._parse_semver(engine_version)

    def check_compatibility(self, manifest: ExtensionManifest) -> VersionCompatibility:
        compat = VersionCompatibility(
            compatible=True,
            engine_version=self.engine_version,
            plugin_version=manifest.version,
        )

        engine_min = getattr(manifest, "kari_min_version", None) or "0.4.0"
        if not self._is_version_compatible(self.engine_version, engine_min):
            compat.compatible = False
            compat.errors.append(
                f"Plugin requires kari_min_version={engine_min} but engine is {self.engine_version}"
            )

        dep = self._coerce_deprecation(manifest)
        if dep.deprecated:
            if dep.removal_date and dep.removal_date <= datetime.utcnow():
                compat.compatible = False
                compat.errors.append(
                    f"Plugin {manifest.name} is deprecated and removal_date {dep.removal_date.isoformat()} has passed"
                )
            else:
                compat.warnings.append(
                    f"Plugin {manifest.name} is deprecated"
                    + (f" (removal date: {dep.removal_date.date()})" if dep.removal_date else "")
                )

        if dep.deprecated and dep.replacement_plugin_id:
            compat.warnings.append(
                f"Deprecated plugin replacement: {dep.replacement_plugin_id}"
            )

        return compat

    def _is_version_compatible(self, current: str, minimum: str) -> bool:
        current_parts = self._parse_semver(current)
        minimum_parts = self._parse_semver(minimum)
        if not current_parts or not minimum_parts:
            return True

        cur_major, cur_minor, _ = current_parts
        min_major, min_minor, _ = minimum_parts

        if cur_major != min_major:
            return cur_major > min_major

        return cur_minor >= min_minor

    def _parse_semver(self, version: str) -> Optional[Tuple[int, int, int]]:
        match = SEMVER_PATTERN.match(version)
        if not match:
            return None
        return int(match.group("major")), int(match.group("minor")), int(match.group("patch"))

    def _coerce_deprecation(self, manifest: ExtensionManifest) -> DeprecationInfo:
        raw = manifest.model_dump()
        gov_raw = raw.get("governance") or {}
        if isinstance(gov_raw, dict):
            dep_raw = gov_raw.get("deprecation") or {}
            if isinstance(dep_raw, dict):
                return DeprecationInfo(**dep_raw)
        return DeprecationInfo()


@dataclass
class PluginVersionCompatibility:
    """Compatibility check result used by the execution gate."""

    compatible: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compatible": self.compatible,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


__all__ = ["VersionCompatibility", "PluginVersionPolicy", "PluginVersionCompatibility"]
