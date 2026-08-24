"""
Canonical extension kernel for AI Karen.

This package owns the full extension lifecycle:
  manifest -> discovery -> registry -> lifecycle -> execution -> audit -> health

No other module should bypass this kernel to load or execute extensions.
"""

from __future__ import annotations

from ai_karen_engine.extensions.contracts import (
    ExtensionCapability,
    ExtensionDependency,
    ExtensionExecutionRequest,
    ExtensionExecutionContext,
    ExtensionExecutionResult,
    ExtensionHealth,
    ExtensionHealthRecord,
    ExtensionLifecycleState,
    ExtensionManifest,
    ExtensionPermissionGrant,
    ExtensionRegistration,
    ResponseSource,
    SideEffectLevel,
    TenantScope,
)
from ai_karen_engine.extensions.discovery import ExtensionDiscovery, ExtensionMetadata
from ai_karen_engine.extensions.errors import (
    ExtensionError,
    ExtensionNotFoundError,
    ExtensionNotRegisteredError,
    ExtensionDisabledError,
    ExtensionManifestError,
    ExtensionValidationError,
    ExtensionPermissionError,
    ExtensionTimeoutError,
    ExtensionExecutionEngineError,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService
from ai_karen_engine.extensions.health import ExtensionHealthMonitor, ExtensionHealthRecord
from ai_karen_engine.extensions.lifecycle import ExtensionLifecycleManager
from ai_karen_engine.extensions.manifest import ExtensionManifestLoader
from ai_karen_engine.extensions.permissions import ExtensionPermissionResolver
from ai_karen_engine.extensions.registry import ExtensionRegistry

__all__ = [
    "ExtensionCapability",
    "ExtensionDependency",
    "ExtensionDiscovery",
    "ExtensionError",
    "ExtensionExecutionEngineError",
    "ExtensionExecutionRequest",
    "ExtensionExecutionContext",
    "ExtensionExecutionResult",
    "ExtensionHealth",
    "ExtensionHealthMonitor",
    "ExtensionHealthRecord",
    "ExtensionLifecycleManager",
    "ExtensionLifecycleState",
    "ExtensionManifest",
    "ExtensionManifestError",
    "ExtensionManifestLoader",
    "ExtensionMetadata",
    "ExtensionNotFoundError",
    "ExtensionNotRegisteredError",
    "ExtensionDisabledError",
    "ExtensionExecutionError",
    "ExtensionTimeoutError",
    "ExtensionPermissionError",
    "ExtensionPermissionGrant",
    "ExtensionPermissionResolver",
    "ExtensionRegistration",
    "ExtensionRegistry",
    "ExtensionValidationError",
    "ResponseSource",
    "SideEffectLevel",
    "TenantScope",
]
