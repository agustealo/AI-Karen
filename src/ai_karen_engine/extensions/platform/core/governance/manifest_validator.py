"""
Versioned manifest validator for governed plugins.

Validates that a plugin manifest satisfies the governance closure contract
before registration: identity, capabilities, permissions, prompt contracts,
tenant scope, network/filesystem/secret access, side-effects, audit requirements,
and deprecation metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, ValidationError

from ai_karen_engine.extensions.platform.core.manifest import (
    ExtensionManifest,
    ExtensionPermissions,
    ExtensionCapabilities,
    ExtensionRBAC,
    ExtensionResources,
    ExtensionDependencies,
    ExtensionPromptFiles,
)
from ai_karen_engine.extensions.platform.core.governance.manifest_schema import (
    PluginGovernanceManifest,
    SideEffectLevel,
    AuditRequirements,
    TenantIsolation,
    SecretAccessRequirement,
    NetworkAccessRequirement,
    DeprecationInfo,
)

logger = logging.getLogger("kari.plugin_governance.validator")


@dataclass
class GovernanceValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    plugin_id: Optional[str] = None
    plugin_version: Optional[str] = None
    validated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "validated_at": self.validated_at.isoformat(),
        }


class PluginManifestValidator:
    """Enforces the plugin governance manifest contract.

    A plugin must declare all governance fields before it can be registered.
    Validation failures block registration; warnings allow registration but
    are surfaced for operator review.
    """

    def __init__(
        self,
        *,
        require_prompt_contract: bool = False,
        require_tenant_isolation: bool = True,
        require_network_declaration: bool = True,
        require_secret_declaration: bool = True,
        require_audit_requirements: bool = True,
        max_side_effect_level: SideEffectLevel = SideEffectLevel.WRITE,
    ):
        self.require_prompt_contract = require_prompt_contract
        self.require_tenant_isolation = require_tenant_isolation
        self.require_network_declaration = require_network_declaration
        self.require_secret_declaration = require_secret_declaration
        self.require_audit_requirements = require_audit_requirements
        self.max_side_effect_level = max_side_effect_level
        self._level_order = {
            SideEffectLevel.NONE: 0,
            SideEffectLevel.READ: 1,
            SideEffectLevel.WRITE: 2,
            SideEffectLevel.EXTERNAL: 3,
        }

    def validate(self, manifest: ExtensionManifest) -> GovernanceValidationResult:
        result = GovernanceValidationResult(
            valid=True,
            plugin_id=manifest.name,
            plugin_version=manifest.version,
        )

        governance = self._coerce_governance(manifest)

        self._validate_identity(manifest, result)
        self._validate_capabilities(manifest, result)
        self._validate_permissions(manifest, result)
        self._validate_prompt_contract(manifest, governance, result)
        self._validate_tenant_isolation(manifest, governance, result)
        self._validate_network_access(manifest, governance, result)
        self._validate_secret_access(manifest, governance, result)
        self._validate_side_effects(manifest, governance, result)
        self._validate_audit_requirements(manifest, governance, result)
        self._validate_deprecation(manifest, governance, result)
        self._validate_rbac(manifest, result)
        self._validate_resources(manifest, result)

        if result.errors:
            result.valid = False

        return result

    def _coerce_governance(self, manifest: ExtensionManifest) -> PluginGovernanceManifest:
        raw = manifest.model_dump()
        gov_raw = raw.get("governance") or {}
        if isinstance(gov_raw, dict):
            return PluginGovernanceManifest(**gov_raw)
        return PluginGovernanceManifest()

    def _validate_identity(self, manifest: ExtensionManifest, result: GovernanceValidationResult) -> None:
        if not manifest.name:
            result.errors.append("Plugin manifest missing required field: name")
        if not manifest.version:
            result.errors.append("Plugin manifest missing required field: version")
        if not manifest.author:
            result.errors.append("Plugin manifest missing required field: author")
        if not manifest.license:
            result.errors.append("Plugin manifest missing required field: license")

    def _validate_capabilities(self, manifest: ExtensionManifest, result: GovernanceValidationResult) -> None:
        capabilities = manifest.capabilities
        if not isinstance(capabilities, ExtensionCapabilities):
            result.errors.append("Plugin manifest missing valid capabilities declaration")
            return

        if not any([
            capabilities.provides_ui,
            capabilities.provides_api,
            capabilities.provides_background_tasks,
            capabilities.provides_webhooks,
        ]):
            result.warnings.append(
                "Plugin does not declare any capabilities (UI, API, background tasks, webhooks)"
            )

    def _validate_permissions(self, manifest: ExtensionManifest, result: GovernanceValidationResult) -> None:
        permissions = manifest.permissions
        if not isinstance(permissions, ExtensionPermissions):
            result.errors.append("Plugin manifest missing valid permissions declaration")
            return

        dangerous_perms = []
        if permissions.memory_write:
            dangerous_perms.append("memory_write")
        if permissions.user_data_write:
            dangerous_perms.append("user_data_write")
        if permissions.system_config_write:
            dangerous_perms.append("system_config_write")
        if permissions.tools:
            dangerous_perms.extend(f"tool:{t}" for t in permissions.tools)

        if dangerous_perms:
            result.warnings.append(
                f"Plugin requests elevated permissions: {', '.join(dangerous_perms)}. "
                "These must be granted by policy, not inferred from plugin code."
            )

    def _validate_prompt_contract(self, manifest: ExtensionManifest, governance: PluginGovernanceManifest, result: GovernanceValidationResult) -> None:
        prompt_files = manifest.prompt_files
        if not isinstance(prompt_files, ExtensionPromptFiles):
            result.errors.append("Plugin manifest missing valid prompt_files declaration")
            return

        has_prompt = any([
            prompt_files.system,
            prompt_files.user,
            prompt_files.templates,
        ])
        has_contract = bool(governance.prompt_contract_id) or bool(prompt_files.contract_id)

        if has_prompt and not has_contract:
            if self.require_prompt_contract:
                result.errors.append(
                    "AI-capable plugin must reference a versioned prompt_contract_id"
                )
            else:
                result.warnings.append(
                    "AI-capable plugin declares prompts but has no prompt_contract_id"
                )

        if governance.prompt_version and not governance.prompt_contract_id:
            result.warnings.append(
                "prompt_version is set but prompt_contract_id is missing"
            )

        if governance.input_schema_version and not governance.prompt_contract_id:
            result.warnings.append(
                "input_schema_version is set but prompt_contract_id is missing"
            )

        if governance.output_schema_version and not governance.prompt_contract_id:
            result.warnings.append(
                "output_schema_version is set but prompt_contract_id is missing"
            )

    def _validate_tenant_isolation(self, manifest: ExtensionManifest, governance: PluginGovernanceManifest, result: GovernanceValidationResult) -> None:
        if self.require_tenant_isolation and governance.tenant.scope == TenantIsolation.TenantScope.GLOBAL:
            result.errors.append(
                "Plugin requests global tenant scope which is forbidden. "
                "Use single or multi with explicit tenant allowlist."
            )

        if governance.tenant.scope == TenantIsolation.TenantScope.MULTI and not governance.tenant.allowed_tenant_ids:
            result.warnings.append(
                "Multi-tenant plugin must declare allowed_tenant_ids"
            )

        if not governance.tenant.deny_cross_tenant:
            result.warnings.append(
                "Plugin has deny_cross_tenant=false; cross-tenant access must be explicitly authorized by policy"
            )

    def _validate_network_access(self, manifest: ExtensionManifest, governance: PluginGovernanceManifest, result: GovernanceValidationResult) -> None:
        permissions = manifest.permissions
        if not isinstance(permissions, ExtensionPermissions):
            return

        declares_network = bool(permissions.network_access)
        gov_network = governance.network

        if declares_network and not gov_network.allow_external and not gov_network.allowed_domains:
            result.warnings.append(
                "Plugin declares network_access in permissions but network.governance block does not declare allowed_domains"
            )

        if gov_network.allow_external and not gov_network.allowed_domains:
            result.errors.append(
                "Plugin requests external network access but does not declare allowed_domains"
            )

        if gov_network.allow_external and not gov_network.require_tls:
            result.warnings.append(
                "Plugin allows external network access without requiring TLS"
            )

    def _validate_secret_access(self, manifest: ExtensionManifest, governance: PluginGovernanceManifest, result: GovernanceValidationResult) -> None:
        if self.require_secret_declaration and not governance.secrets.required_secrets:
            if self._plugin_needs_secrets(manifest):
                result.warnings.append(
                    "Plugin likely needs secrets but does not declare required_secrets"
                )

        if governance.secrets.allow_runtime_resolution and not governance.secrets.required_secrets:
            result.warnings.append(
                "allow_runtime_resolution is true but required_secrets is empty"
            )

    def _validate_side_effects(self, manifest: ExtensionManifest, governance: PluginGovernanceManifest, result: GovernanceValidationResult) -> None:
        level = governance.side_effects.level
        declared = self._level_order.get(level, 0)
        max_allowed = self._level_order.get(self.max_side_effect_level, 2)

        if declared > max_allowed:
            result.errors.append(
                f"Plugin declares side-effect level '{level.value}' which exceeds maximum allowed '{self.max_side_effect_level.value}'"
            )

        if level == SideEffectLevel.WRITE and not governance.side_effects.reversible:
            result.warnings.append(
                "Plugin declares write side-effects but marks them as irreversible"
            )

    def _validate_audit_requirements(self, manifest: ExtensionManifest, governance: PluginGovernanceManifest, result: GovernanceValidationResult) -> None:
        if self.require_audit_requirements:
            req = governance.audit.requirement
            if req == AuditRequirements.NONE:
                result.warnings.append(
                    "Plugin disables audit requirements; this should be explicitly authorized by policy"
                )

            if not governance.audit.log_input and not governance.audit.log_output:
                result.warnings.append(
                    "Plugin disables both input and output audit logging"
                )

    def _validate_deprecation(self, manifest: ExtensionManifest, governance: PluginGovernanceManifest, result: GovernanceValidationResult) -> None:
        dep = governance.deprecation
        if dep.deprecated and not dep.removal_date:
            result.warnings.append(
                "Deprecated plugin has no removal_date specified"
            )

        if dep.deprecated and dep.removal_date and dep.removal_date < datetime.utcnow():
            result.errors.append(
                "Deprecated plugin removal_date is in the past; plugin must be removed"
            )

    def _validate_rbac(self, manifest: ExtensionManifest, result: GovernanceValidationResult) -> None:
        rbac = manifest.rbac
        if not isinstance(rbac, ExtensionRBAC):
            result.errors.append("Plugin manifest missing valid rbac declaration")
            return

        if not rbac.allowed_roles:
            result.warnings.append("Plugin does not declare allowed_roles; defaulting to guest-only access")

    def _validate_resources(self, manifest: ExtensionManifest, result: GovernanceValidationResult) -> None:
        resources = manifest.resources
        if not isinstance(resources, ExtensionResources):
            result.errors.append("Plugin manifest missing valid resources declaration")
            return

        if resources.max_memory_mb <= 0:
            result.errors.append("Plugin resources.max_memory_mb must be positive")

        if resources.max_cpu_percent <= 0 or resources.max_cpu_percent > 100:
            result.errors.append("Plugin resources.max_cpu_percent must be between 1 and 100")

    def _plugin_needs_secrets(self, manifest: ExtensionManifest) -> bool:
        permissions = manifest.permissions
        if not isinstance(permissions, ExtensionPermissions):
            return False

        sensitive_perms = [
            permissions.memory_read,
            permissions.memory_write,
            permissions.user_data_read,
            permissions.user_data_write,
            permissions.system_config_read,
            permissions.system_config_write,
            bool(permissions.tools),
            bool(permissions.data_access),
            bool(permissions.system_access),
        ]
        return any(sensitive_perms)


__all__ = ["GovernanceValidationResult", "PluginManifestValidator"]
