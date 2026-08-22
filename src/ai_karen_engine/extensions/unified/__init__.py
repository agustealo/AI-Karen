"""
Unified Extension System (DEPRECATED)

This module provides a unified extension system that consolidates the best features
from both platform/core and runtime systems, eliminating duplication and providing
a single source of truth for extension management.

DEPRECATED: This is migration residue. The canonical extension platform is
extensions/platform/. New code must import from extensions/platform/ directly.
See ARCHITECTURE.md for the canonical extension topology.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "extensions/unified is deprecated. Use extensions/platform/ directly.",
    DeprecationWarning,
    stacklevel=2,
)

from .core import (
    ExtensionRegistry,
    ExtensionLoader,
    ExtensionPermissions,
    ExtensionPermissionType,
    ExtensionHealthMonitor,
    HealthStatus,
    HealthSeverity,
    ExtensionLifecycleManager,
    ExtensionLifecycleState,
    ExtensionConfig,
    ExtensionConfigManager,
    ExtensionService,
    ExtensionServiceResult,
    ExtensionExecutionSubstrate,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)

__all__ = [
    "ExtensionRegistry",
    "ExtensionLoader",
    "ExtensionPermissions",
    "ExtensionPermissionType",
    "ExtensionHealthMonitor",
    "HealthStatus",
    "HealthSeverity",
    "ExtensionLifecycleManager",
    "ExtensionLifecycleState",
    "ExtensionConfig",
    "ExtensionConfigManager",
    "ExtensionService",
    "ExtensionServiceResult",
    "ExtensionExecutionSubstrate",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
]
