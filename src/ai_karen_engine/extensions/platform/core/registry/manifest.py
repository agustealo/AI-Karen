"""
Extension data models and schemas - re-exported from canonical manifest.

All ExtensionManifest, ExtensionStatus, and related types are defined in
the canonical manifest module. This file re-exports them for backward
compatibility with existing imports in the registry package.
"""

from ai_karen_engine.extensions.platform.core.manifest import (
    ExtensionCapabilities,
    ExtensionConfigSchema,
    ExtensionContext,
    ExtensionDependencies,
    ExtensionManifest,
    ExtensionManifestAPI,
    ExtensionPermissions,
    ExtensionRecord,
    ExtensionResources,
    ExtensionStatus,
    ExtensionUIConfig,
    ExtensionAPIConfig,
    ExtensionBackgroundTask,
    ExtensionMarketplaceInfo,
    HookContext,
    NAME_PATTERN,
    SEMVER_PATTERN,
)

__all__ = [
    "ExtensionStatus",
    "ExtensionCapabilities",
    "ExtensionDependencies",
    "ExtensionPermissions",
    "ExtensionResources",
    "ExtensionUIConfig",
    "ExtensionAPIConfig",
    "ExtensionBackgroundTask",
    "ExtensionMarketplaceInfo",
    "ExtensionManifest",
    "ExtensionContext",
    "ExtensionRecord",
    "ExtensionManifestAPI",
    "HookContext",
    "NAME_PATTERN",
    "SEMVER_PATTERN",
]
