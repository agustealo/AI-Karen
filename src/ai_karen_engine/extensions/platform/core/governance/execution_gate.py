"""
Execution gate for governed plugins.

Implements the closure contract:

    manifest validation
    -> registration
    -> permission resolution
    -> RBAC eligibility
    -> execution gate
    -> audit
    -> result validation

Every invocation must pass through this gate. Nothing is executed implicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.extensions.platform.core.governance.manifest_validator import (
    GovernanceValidationResult,
    PluginManifestValidator,
)
from ai_karen_engine.extensions.platform.core.governance.permission_resolver import (
    PermissionResolutionResult,
    PluginPermissionResolver,
)
from ai_karen_engine.extensions.platform.core.governance.plugin_audit import (
    PluginAuditEvent,
    PluginAuditLogger,
)
from ai_karen_engine.extensions.platform.core.governance.schema_validator import (
    PluginSchemaValidator,
)
from ai_karen_engine.extensions.platform.core.governance.versioning import (
    PluginVersionCompatibility,
    PluginVersionPolicy,
)

logger = logging.getLogger("kari.plugin_governance.gate")


class ExecutionGateStatus(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"


@dataclass
class ExecutionGateResult:
    status: ExecutionGateStatus
    plugin_id: str
    plugin_version: str
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    permission_set: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "permission_set": list(self.permission_set),
            "validation_errors": list(self.validation_errors),
            "validation_warnings": list(self.validation_warnings),
            "metadata": dict(self.metadata),
            "evaluated_at": self.evaluated_at.isoformat(),
        }


class PluginExecutionGate:
    """Enforces the full governance closure contract before plugin execution.

    The gate never calls the plugin directly. It only decides whether the
    invocation is allowed and returns the resolved execution context.
    """

    def __init__(
        self,
        manifest_validator: Optional[PluginManifestValidator] = None,
        permission_resolver: Optional[PluginPermissionResolver] = None,
        schema_validator: Optional[PluginSchemaValidator] = None,
        audit_logger: Optional[PluginAuditLogger] = None,
        version_policy: Optional[PluginVersionPolicy] = None,
        policy_provider: Optional[Any] = None,
    ):
        self.manifest_validator = manifest_validator or PluginManifestValidator()
        self.permission_resolver = permission_resolver or PluginPermissionResolver(
            policy_provider=policy_provider
        )
        self.schema_validator = schema_validator or PluginSchemaValidator()
        self.audit_logger = audit_logger or PluginAuditLogger()
        self.version_policy = version_policy or PluginVersionPolicy()
        self.policy_provider = policy_provider

    def evaluate(
        self,
        manifest: ExtensionManifest,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_roles: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
        input_payload: Optional[Dict[str, Any]] = None,
        policy_grants: Optional[Dict[str, Any]] = None,
    ) -> ExecutionGateResult:
        plugin_id = manifest.name
        plugin_version = manifest.version
        result = ExecutionGateResult(
            status=ExecutionGateStatus.ALLOWED,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        # Stage 1: manifest validation
        manifest_result = self.manifest_validator.validate(manifest)
        result.validation_errors.extend(manifest_result.errors)
        result.validation_warnings.extend(manifest_result.warnings)
        if not manifest_result.valid:
            result.status = ExecutionGateStatus.BLOCKED
            result.metadata["stage"] = "manifest_validation"
            self.audit_logger.log(
                PluginAuditEvent(
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    stage="manifest_validation",
                    outcome="blocked",
                    error_code="invalid_manifest",
                    detail="; ".join(manifest_result.errors),
                )
            )
            return result

        # Stage 2: version compatibility / deprecation
        compat = self.version_policy.check_compatibility(manifest)
        if not compat.compatible:
            result.status = ExecutionGateStatus.BLOCKED
            result.validation_errors.extend(compat.errors)
            result.metadata["stage"] = "version_compatibility"
            self.audit_logger.log(
                PluginAuditEvent(
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    stage="version_compatibility",
                    outcome="blocked",
                    error_code="version_incompatible",
                    detail="; ".join(compat.errors),
                )
            )
            return result
        result.validation_warnings.extend(compat.warnings)

        # Stage 3: permission resolution + RBAC
        perm_result = self.permission_resolver.resolve(
            manifest,
            tenant_id=tenant_id,
            user_id=user_id,
            user_roles=user_roles,
            policy_grants=policy_grants,
        )
        if not perm_result.allowed:
            result.status = ExecutionGateStatus.DENIED
            result.validation_errors.extend(perm_result.denied_permissions)
            result.validation_errors.extend(perm_result.missing_permissions)
            result.metadata["stage"] = "permission_resolution"
            self.audit_logger.log(
                PluginAuditEvent(
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    stage="permission_resolution",
                    outcome="denied",
                    error_code="permission_denied",
                    detail="; ".join(perm_result.denied_permissions + perm_result.missing_permissions),
                )
            )
            return result

        result.permission_set = list(set(perm_result.granted_permissions))
        result.validation_warnings.extend(perm_result.resolution_notes)

        # Stage 4: input schema validation
        if input_payload is not None:
            schema_errors = self.schema_validator.validate_input(manifest, input_payload)
            if schema_errors:
                result.status = ExecutionGateStatus.BLOCKED
                result.validation_errors.extend(schema_errors)
                result.metadata["stage"] = "input_schema_validation"
                self.audit_logger.log(
                    PluginAuditEvent(
                        plugin_id=plugin_id,
                        plugin_version=plugin_version,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        correlation_id=correlation_id,
                        stage="input_schema_validation",
                        outcome="blocked",
                        error_code="invalid_input",
                        detail="; ".join(schema_errors),
                    )
                )
                return result

        # Stage 5: finalize
        result.metadata["stage"] = "execution_gate"
        result.metadata["granted_permissions"] = result.permission_set
        result.metadata["correlation_id"] = correlation_id

        self.audit_logger.log(
            PluginAuditEvent(
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                tenant_id=tenant_id,
                user_id=user_id,
                correlation_id=correlation_id,
                stage="execution_gate",
                outcome="allowed",
                permission_set=result.permission_set,
                detail=f"Execution allowed with {len(result.permission_set)} granted permissions",
            )
        )

        return result

    def evaluate_output(
        self,
        manifest: ExtensionManifest,
        output_payload: Any,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> ExecutionGateResult:
        plugin_id = manifest.name
        plugin_version = manifest.version
        result = ExecutionGateResult(
            status=ExecutionGateStatus.ALLOWED,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        schema_errors = self.schema_validator.validate_output(manifest, output_payload)
        if schema_errors:
            result.status = ExecutionGateStatus.BLOCKED
            result.validation_errors.extend(schema_errors)
            result.metadata["stage"] = "output_schema_validation"
            self.audit_logger.log(
                PluginAuditEvent(
                    plugin_id=plugin_id,
                    plugin_version=plugin_version,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    stage="output_schema_validation",
                    outcome="blocked",
                    error_code="invalid_output",
                    detail="; ".join(schema_errors),
                )
            )
            return result

        result.metadata["stage"] = "output_validation"
        self.audit_logger.log(
            PluginAuditEvent(
                plugin_id=plugin_id,
                plugin_version=plugin_version,
                tenant_id=tenant_id,
                user_id=user_id,
                correlation_id=correlation_id,
                stage="output_validation",
                outcome="allowed",
                detail="Output schema validation passed",
            )
        )
        return result


__all__ = ["ExecutionGateStatus", "ExecutionGateResult", "PluginExecutionGate"]
