"""
Permission resolution and RBAC binding for governed plugins.

Permissions are granted by policy, never inferred from plugin code.
This module resolves the effective permission set for a plugin invocation
by intersecting:
  - manifest-declared permissions
  - RBAC role membership
  - tenant isolation constraints
  - runtime policy grants
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from ai_karen_engine.extensions.platform.core.manifest import (
    ExtensionManifest,
    ExtensionPermissions,
    ExtensionRBAC,
    ExtensionRole,
)
from ai_karen_engine.extensions.platform.core.governance.manifest_schema import (
    TenantIsolation,
    SecretAccessRequirement,
    NetworkAccessRequirement,
)

logger = logging.getLogger("kari.plugin_governance.permissions")


@dataclass
class PermissionResolutionResult:
    allowed: bool
    granted_permissions: List[str] = field(default_factory=list)
    denied_permissions: List[str] = field(default_factory=list)
    missing_permissions: List[str] = field(default_factory=list)
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    resolution_notes: List[str] = field(default_factory=list)
    resolved_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "granted_permissions": list(self.granted_permissions),
            "denied_permissions": list(self.denied_permissions),
            "missing_permissions": list(self.missing_permissions),
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "roles": list(self.roles),
            "resolution_notes": list(self.resolution_notes),
            "resolved_at": self.resolved_at.isoformat(),
        }


class PluginPermissionResolver:
    """Resolves plugin permissions from manifest, RBAC, tenant, and policy.

    This resolver never grants permissions implicitly. Every permission in
    the manifest must be explicitly mapped to a policy grant or role allowance.
    """

    def __init__(self, policy_provider: Optional[Any] = None):
        self.policy_provider = policy_provider
        self._role_permissions: Dict[str, Set[str]] = self._default_role_permissions()

    def resolve(
        self,
        manifest: ExtensionManifest,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_roles: Optional[List[str]] = None,
        policy_grants: Optional[Dict[str, Any]] = None,
    ) -> PermissionResolutionResult:
        result = PermissionResolutionResult(
            allowed=False,
            tenant_id=tenant_id,
            user_id=user_id,
            roles=list(user_roles or []),
        )

        permissions = self._coerce_permissions(manifest)
        rbac = self._coerce_rbac(manifest)
        tenant = self._coerce_tenant(manifest)
        secrets = self._coerce_secrets(manifest)
        network = self._coerce_network(manifest)

        self._check_tenant_isolation(manifest, tenant, tenant_id, result)
        if not result.allowed:
            return result

        self._check_rbac_eligibility(manifest, rbac, user_roles or [], result)
        if not result.allowed:
            return result

        self._resolve_permissions(manifest, permissions, policy_grants or {}, result)
        self._check_secret_access(manifest, secrets, policy_grants or {}, result)
        self._check_network_access(manifest, network, policy_grants or {}, result)

        result.allowed = len(result.denied_permissions) == 0 and len(result.missing_permissions) == 0
        return result

    def _check_tenant_isolation(
        self,
        manifest: ExtensionManifest,
        tenant: TenantIsolation,
        tenant_id: Optional[str],
        result: PermissionResolutionResult,
    ) -> None:
        if tenant.scope == TenantIsolation.TenantScope.GLOBAL:
            result.resolution_notes.append("Global tenant scope is forbidden by governance")
            result.denied_permissions.append("tenant:global")
            return

        if tenant.scope == TenantIsolation.TenantScope.MULTI:
            if tenant_id not in tenant.allowed_tenant_ids:
                result.resolution_notes.append(
                    f"Tenant {tenant_id} not in allowed_tenant_ids"
                )
                result.denied_permissions.append("tenant:access")
                return

        if tenant.scope == TenantIsolation.TenantScope.SINGLE:
            if not tenant_id:
                result.resolution_notes.append("Single-tenant plugin requires tenant_id")
                result.denied_permissions.append("tenant:identify")
                return

        result.tenant_id = tenant_id
        result.resolution_notes.append(f"Tenant isolation check passed for scope={tenant.scope.value}")

    def _check_rbac_eligibility(
        self,
        manifest: ExtensionManifest,
        rbac: ExtensionRBAC,
        user_roles: List[str],
        result: PermissionResolutionResult,
    ) -> None:
        if not rbac.allowed_roles:
            result.resolution_notes.append("No allowed_roles declared; plugin is guest-only")
            result.allowed = False
            result.denied_permissions.append("rbac:no_roles")
            return

        user_role_set = set(user_roles)
        allowed_role_set = {role.value for role in rbac.allowed_roles}

        if not allowed_role_set.intersection(user_role_set):
            result.resolution_notes.append(
                f"User roles {user_roles} do not intersect allowed roles {rbac.allowed_roles}"
            )
            result.denied_permissions.append("rbac:denied")
            result.allowed = False
            return

        result.resolution_notes.append(
            f"RBAC eligibility confirmed for roles {user_roles}"
        )

    def _resolve_permissions(
        self,
        manifest: ExtensionManifest,
        permissions: ExtensionPermissions,
        policy_grants: Dict[str, Any],
        result: PermissionResolutionResult,
    ) -> None:
        declared = self._collect_declared_permissions(manifest, permissions)
        granted = set(policy_grants.get("permissions", []))
        explicit_deny = set(policy_grants.get("denied_permissions", []))

        for perm in declared:
            if perm in explicit_deny:
                result.denied_permissions.append(perm)
                result.resolution_notes.append(f"Permission explicitly denied by policy: {perm}")
            elif perm in granted:
                result.granted_permissions.append(perm)
                result.resolution_notes.append(f"Permission granted by policy: {perm}")
            else:
                result.missing_permissions.append(perm)
                result.resolution_notes.append(f"Permission not granted by policy: {perm}")

    def _check_secret_access(
        self,
        manifest: ExtensionManifest,
        secrets: SecretAccessRequirement,
        policy_grants: Dict[str, Any],
        result: PermissionResolutionResult,
    ) -> None:
        allowed_secrets = set(policy_grants.get("allowed_secrets", []))
        declared_secrets = set(secrets.required_secrets)

        for secret in declared_secrets:
            if secret not in allowed_secrets:
                result.denied_permissions.append(f"secret:{secret}")
                result.resolution_notes.append(f"Secret access denied by policy: {secret}")

        if secrets.allow_runtime_resolution:
            result.resolution_notes.append(
                "Plugin requests runtime secret resolution; requires explicit policy grant"
            )
            if "secret:runtime_resolution" not in allowed_secrets:
                result.denied_permissions.append("secret:runtime_resolution")

    def _check_network_access(
        self,
        manifest: ExtensionManifest,
        network: NetworkAccessRequirement,
        policy_grants: Dict[str, Any],
        result: PermissionResolutionResult,
    ) -> None:
        allowed_domains = set(policy_grants.get("allowed_network_domains", []))
        allowed_ports = set(policy_grants.get("allowed_network_ports", []))

        if network.allow_external:
            if not network.allowed_domains:
                result.denied_permissions.append("network:external")
                result.resolution_notes.append(
                    "External network access requires allowed_domains declaration"
                )
                return

            for domain in network.allowed_domains:
                if domain not in allowed_domains:
                    result.denied_permissions.append(f"network:domain:{domain}")
                    result.resolution_notes.append(
                        f"Network domain not allowed by policy: {domain}"
                    )

        for port in network.allowed_ports:
            if port not in allowed_ports:
                result.denied_permissions.append(f"network:port:{port}")
                result.resolution_notes.append(
                    f"Network port not allowed by policy: {port}"
                )

    def _collect_declared_permissions(self, manifest: ExtensionManifest, permissions: ExtensionPermissions) -> List[str]:
        declared: List[str] = []

        if permissions.memory_read:
            declared.append("memory:read")
        if permissions.memory_write:
            declared.append("memory:write")
        if permissions.user_data_read:
            declared.append("user_data:read")
        if permissions.user_data_write:
            declared.append("user_data:write")
        if permissions.system_config_read:
            declared.append("system_config:read")
        if permissions.system_config_write:
            declared.append("system_config:write")
        for tool in permissions.tools:
            declared.append(f"tool:{tool}")
        for access in permissions.data_access:
            declared.append(f"data_access:{access}")
        for access in permissions.plugin_access:
            declared.append(f"plugin_access:{access}")
        for access in permissions.system_access:
            declared.append(f"system_access:{access}")
        for access in permissions.network_access:
            declared.append(f"network_access:{access}")

        return declared

    def _coerce_permissions(self, manifest: ExtensionManifest) -> ExtensionPermissions:
        if isinstance(manifest.permissions, ExtensionPermissions):
            return manifest.permissions
        return ExtensionPermissions()

    def _coerce_rbac(self, manifest: ExtensionManifest) -> ExtensionRBAC:
        if isinstance(manifest.rbac, ExtensionRBAC):
            return manifest.rbac
        return ExtensionRBAC()

    def _coerce_tenant(self, manifest: ExtensionManifest) -> TenantIsolation:
        raw = manifest.model_dump()
        gov_raw = raw.get("governance") or {}
        if isinstance(gov_raw, dict):
            tenant_raw = gov_raw.get("tenant") or {}
            if isinstance(tenant_raw, dict):
                return TenantIsolation(**tenant_raw)
        return TenantIsolation()

    def _coerce_secrets(self, manifest: ExtensionManifest) -> SecretAccessRequirement:
        raw = manifest.model_dump()
        gov_raw = raw.get("governance") or {}
        if isinstance(gov_raw, dict):
            secrets_raw = gov_raw.get("secrets") or {}
            if isinstance(secrets_raw, dict):
                return SecretAccessRequirement(**secrets_raw)
        return SecretAccessRequirement()

    def _coerce_network(self, manifest: ExtensionManifest) -> NetworkAccessRequirement:
        raw = manifest.model_dump()
        gov_raw = raw.get("governance") or {}
        if isinstance(gov_raw, dict):
            net_raw = gov_raw.get("network") or {}
            if isinstance(net_raw, dict):
                return NetworkAccessRequirement(**net_raw)
        return NetworkAccessRequirement()

    def _default_role_permissions(self) -> Dict[str, Set[str]]:
        return {
            "user": {"read", "browser", "data:read"},
            "admin": {"*"},
            "system": {"*"},
            "guest": set(),
        }


__all__ = ["PermissionResolutionResult", "PluginPermissionResolver"]
