"""
Plugin Governance Package

Provides manifest validation, permission resolution, execution gating,
schema enforcement, audit events, and version compatibility rules for
governed plugins.
"""

from __future__ import annotations

from .manifest_schema import (
    AuditRequirements,
    DeprecationInfo,
    NetworkAccessRequirement,
    PluginGovernanceManifest,
    SecretAccessRequirement,
    SideEffectClassification,
    TenantIsolation,
)
from .manifest_validator import (
    GovernanceValidationResult,
    PluginManifestValidator,
)
from .permission_resolver import (
    PermissionResolutionResult,
    PluginPermissionResolver,
)
from .execution_gate import (
    PluginExecutionGate,
)
from .plugin_audit import (
    PluginAuditEvent,
    PluginAuditLogger,
)
from .schema_validator import (
    PluginSchemaValidator,
)
from .versioning import (
    PluginVersionCompatibility,
    PluginVersionPolicy,
)

__all__ = [
    "AuditRequirements",
    "DeprecationInfo",
    "NetworkAccessRequirement",
    "PluginGovernanceManifest",
    "SecretAccessRequirement",
    "SideEffectClassification",
    "TenantIsolation",
    "GovernanceValidationResult",
    "PluginManifestValidator",
    "PermissionResolutionResult",
    "PluginPermissionResolver",
    "PluginExecutionGate",
    "PluginAuditEvent",
    "PluginAuditLogger",
    "PluginSchemaValidator",
    "PluginVersionCompatibility",
    "PluginVersionPolicy",
]
