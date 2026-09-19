"""Canonical extension execution kernel for AI Karen.

On-disk catalog discovery is owned by ``extensions.platform.core.registry``.
This package root exposes typed execution contracts, runtime registration,
lifecycle, permissions, health, and the canonical executor.
"""

from __future__ import annotations

from ai_karen_engine.extensions.contracts import (
    ExtensionCapability,
    ExtensionDependency,
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
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
from ai_karen_engine.extensions.errors import (
    ExtensionDisabledError,
    ExtensionError,
    ExtensionExecutionEngineError,
    ExtensionManifestError,
    ExtensionNotFoundError,
    ExtensionNotRegisteredError,
    ExtensionPermissionError,
    ExtensionTimeoutError,
    ExtensionValidationError,
)
from ai_karen_engine.extensions.executor import ExtensionExecutionService
from ai_karen_engine.extensions.health import ExtensionHealthMonitor
from ai_karen_engine.extensions.lifecycle import ExtensionLifecycleManager
from ai_karen_engine.extensions.permissions import ExtensionPermissionResolver
from ai_karen_engine.extensions.registry import ExtensionRegistry

__all__ = [
    "ExtensionCapability",
    "ExtensionDependency",
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
    "ExtensionNotFoundError",
    "ExtensionNotRegisteredError",
    "ExtensionDisabledError",
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
