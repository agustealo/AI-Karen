"""Compatibility exports for non-authoritative extension host types.

Execution, loading, lifecycle, registry and routing authority live outside this
package in ``PluginService`` / ``PluginKernel``. This package retains only data
contracts and the thin host manager compatibility facade.
"""

from __future__ import annotations

from importlib import import_module

from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    ExtensionContext,
    ExtensionManifest,
    HookContext,
    HookPoint,
)
from ai_karen_engine.extensions.platform.core.host.config import (
    ExtensionConfigManager,
    ExtensionHostConfig,
)
from ai_karen_engine.extensions.platform.core.host.models import (
    ExtensionCapabilities,
    ExtensionPermissions,
    ExtensionRBAC,
    ExtensionRecord,
    ExtensionResources,
    ExtensionStatus,
)

__all__ = [
    "ExtensionBase",
    "ExtensionCapabilities",
    "ExtensionConfigManager",
    "ExtensionContext",
    "ExtensionHostConfig",
    "ExtensionManager",
    "ExtensionManifest",
    "ExtensionPermissions",
    "ExtensionRBAC",
    "ExtensionRecord",
    "ExtensionResources",
    "ExtensionStatus",
    "HookContext",
    "HookPoint",
]


def __getattr__(name: str):
    if name == "ExtensionManager":
        return import_module(
            "ai_karen_engine.extensions.platform.core.host.manager"
        ).ExtensionManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
