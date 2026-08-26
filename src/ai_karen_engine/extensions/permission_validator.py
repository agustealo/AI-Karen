"""
Plugin permission validation system.

Provides comprehensive permission checking, validation, and enforcement
for extension execution. Ensures security and compliance requirements.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from ai_karen_engine.extensions.contracts import (
    ExtensionManifest,
    ExtensionCapability,
    ExtensionExecutionContext,
    ExtensionPermissionGrant,
    TrustTier,
    RiskClass,
    DataClassification,
)

logger = logging.getLogger("kari.extensions.permissions")


class PermissionResult(str, Enum):
    """Permission check result types."""
    GRANTED = "granted"
    DENIED = "denied"
    CONDITIONAL = "conditional"
    NEEDS_APPROVAL = "needs_approval"


@dataclass
class PermissionCheck:
    """Result of a permission check."""
    
    result: PermissionResult
    granted: bool
    permission_id: str
    reason: str
    conditions: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "result": self.result.value,
            "granted": self.granted,
            "permission_id": self.permission_id,
            "reason": self.reason,
            "conditions": self.conditions,
            "required_approvals": self.required_approvals,
            "metadata": self.metadata,
        }


@dataclass
class PermissionPolicy:
    """Permission policy definition."""
    
    id: str
    name: str
    description: str
    required_permissions: List[str]
    denied_permissions: List[str]
    allowed_trust_tiers: List[TrustTier]
    allowed_risk_classes: List[RiskClass]
    allowed_data_classifications: List[DataClassification]
    conditional_permissions: Dict[str, List[str]] = field(default_factory=dict)
    approval_required: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PermissionValidator:
    """Validates extension permissions against policies and context."""
    
    def __init__(self):
        self.policies: Dict[str, PermissionPolicy] = {}
        self._register_default_policies()
    
    def _register_default_policies(self):
        """Register default permission policies."""
        
        # High-risk operations policy
        high_risk_policy = PermissionPolicy(
            id="high_risk_operations",
            name="High-Risk Operations",
            description="Controls access to high-risk operations",
            required_permissions=["system_admin"],
            denied_permissions=[],
            allowed_trust_tiers=[TrustTier.BUILTIN_TRUSTED, TrustTier.FIRST_PARTY],
            allowed_risk_classes=[RiskClass.LOW, RiskClass.SAFE],
            allowed_data_classifications=[DataClassification.PUBLIC],
            approval_required=["security_officer"],
            metadata={"priority": "high"}
        )
        
        # Data access policy
        data_access_policy = PermissionPolicy(
            id="data_access",
            name="Data Access Control",
            description="Controls access to sensitive data",
            required_permissions=["data_access"],
            denied_permissions=["system_admin"],  # System admins can't bypass data policies
            allowed_trust_tiers=[TrustTier.BUILTIN_TRUSTED, TrustTier.FIRST_PARTY],
            allowed_risk_classes=[RiskClass.SAFE, RiskClass.LOW],
            allowed_data_classifications=[DataClassification.PUBLIC, DataClassification.INTERNAL],
            conditional_permissions={
                "data_access": ["user_role:admin", "tenant_scope:global"]
            },
            metadata={"priority": "medium"}
        )
        
        # Network access policy
        network_policy = PermissionPolicy(
            id="network_access",
            name="Network Access Control",
            description="Controls network access",
            required_permissions=["network_access"],
            denied_permissions=[],
            allowed_trust_tiers=[TrustTier.BUILTIN_TRUSTED, TrustTier.FIRST_PARTY],
            allowed_risk_classes=[RiskClass.SAFE, RiskClass.LOW],
            allowed_data_classifications=[DataClassification.PUBLIC],
            metadata={"priority": "medium"}
        )
        
        # Filesystem access policy
        filesystem_policy = PermissionPolicy(
            id="filesystem_access",
            name="Filesystem Access Control",
            description="Controls filesystem access",
            required_permissions=["filesystem_access"],
            denied_permissions=[],
            allowed_trust_tiers=[TrustTier.BUILTIN_TRUSTED, TrustTier.FIRST_PARTY],
            allowed_risk_classes=[RiskClass.SAFE, RiskClass.LOW],
            allowed_data_classifications=[DataClassification.PUBLIC],
            metadata={"priority": "medium"}
        )
        
        # External API access policy
        external_api_policy = PermissionPolicy(
            id="external_api_access",
            name="External API Access Control",
            description="Controls external API access",
            required_permissions=["external_api_access"],
            denied_permissions=[],
            allowed_trust_tiers=[TrustTier.BUILTIN_TRUSTED, TrustTier.FIRST_PARTY, TrustTier.SIGNED_THIRD_PARTY],
            allowed_risk_classes=[RiskClass.LOW, RiskClass.MEDIUM],
            allowed_data_classifications=[DataClassification.PUBLIC, DataClassification.INTERNAL],
            approval_required=["api_manager"],
            metadata={"priority": "high"}
        )
        
        self.policies = {
            high_risk_policy.id: high_risk_policy,
            data_access_policy.id: data_access_policy,
            network_policy.id: network_policy,
            filesystem_policy.id: filesystem_policy,
            external_api_policy.id: external_api_policy,
        }
    
    def check_permissions(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext,
        authorized_plan: Optional[Dict[str, Any]] = None
    ) -> List[PermissionCheck]:
        """Check permissions for extension execution."""
        
        checks: List[PermissionCheck] = []
        
        # Get required permissions
        required_perms = self._get_required_permissions(manifest, capability)
        
        # Check each required permission
        for perm in required_perms:
            check = self._check_single_permission(perm, manifest, capability, context, authorized_plan)
            checks.append(check)
        
        # Check policy constraints
        policy_checks = self._check_policy_constraints(manifest, capability, context, authorized_plan)
        checks.extend(policy_checks)
        
        return checks
    
    def _get_required_permissions(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability]
    ) -> List[str]:
        """Get required permissions from manifest and capability."""
        if capability and capability.required_permissions:
            return capability.required_permissions
        return manifest.required_permissions
    
    def _check_single_permission(
        self,
        permission_id: str,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext,
        authorized_plan: Optional[Dict[str, Any]] = None
    ) -> PermissionCheck:
        """Check a single permission against context and policy."""
        
        # Check if permission is explicitly allowed
        allowed_capabilities = authorized_plan.get("allowed_capabilities", []) if authorized_plan else []
        if allowed_capabilities and permission_id not in allowed_capabilities:
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id=permission_id,
                reason=f"Permission '{permission_id}' not in allowed_capabilities",
                metadata={"source": "authorized_plan"}
            )
        
        # Check trust tier compatibility
        trust_tier_check = self._check_trust_tier(manifest, capability, context)
        if not trust_tier_check.granted:
            return trust_tier_check
        
        # Check risk class compatibility
        risk_check = self._check_risk_class(manifest, capability, context)
        if not risk_check.granted:
            return risk_check
        
        # Check data classification compatibility
        data_check = self._check_data_classification(manifest, capability, context)
        if not data_check.granted:
            return data_check
        
        # Check tenant scope
        tenant_check = self._check_tenant_scope(manifest, capability, context)
        if not tenant_check.granted:
            return tenant_check
        
        # Check user roles
        role_check = self._check_user_roles(manifest, capability, context)
        if not role_check.granted:
            return role_check
        
        return PermissionCheck(
            result=PermissionResult.GRANTED,
            granted=True,
            permission_id=permission_id,
            reason=f"Permission '{permission_id}' granted",
            metadata={"source": "validated"}
        )
    
    def _check_trust_tier(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext
    ) -> PermissionCheck:
        """Check trust tier compatibility."""
        
        # Get applicable trust tier requirement
        required_trust_tiers = getattr(capability, "required_trust_tiers", None) if capability else None
        if required_trust_tiers is None:
            required_trust_tiers = [manifest.trust_tier]
        
        # Check if manifest trust tier is allowed
        if manifest.trust_tier not in required_trust_tiers:
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id="trust_tier",
                reason=f"Trust tier {manifest.trust_tier} not in required {required_trust_tiers}",
                metadata={"manifest_trust_tier": manifest.trust_tier.value}
            )
        
        return PermissionCheck(
            result=PermissionResult.GRANTED,
            granted=True,
            permission_id="trust_tier",
            reason="Trust tier compatible",
            metadata={"manifest_trust_tier": manifest.trust_tier.value}
        )
    
    def _check_risk_class(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext
    ) -> PermissionCheck:
        """Check risk class compatibility."""
        
        # Get applicable risk class
        risk_class = getattr(capability, "risk_class", manifest.risk_class) if capability else manifest.risk_class
        
        # Check if risk class is acceptable for context
        if risk_class == RiskClass.CRITICAL:
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id="risk_class",
                reason=f"Critical risk class not allowed in context",
                metadata={"risk_class": risk_class.value}
            )
        
        return PermissionCheck(
            result=PermissionResult.GRANTED,
            granted=True,
            permission_id="risk_class",
            reason="Risk class acceptable",
            metadata={"risk_class": risk_class.value}
        )
    
    def _check_data_classification(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext
    ) -> PermissionCheck:
        """Check data classification compatibility."""
        
        # Get applicable data classification
        data_classification = getattr(capability, "data_classification", manifest.data_classification) if capability else manifest.data_classification
        
        # Check if data classification is acceptable for context
        if data_classification in [DataClassification.RESTRICTED, DataClassification.CONFIDENTIAL]:
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id="data_classification",
                reason=f"High data classification {data_classification.value} not allowed in context",
                metadata={"data_classification": data_classification.value}
            )
        
        return PermissionCheck(
            result=PermissionResult.GRANTED,
            granted=True,
            permission_id="data_classification",
            reason="Data classification acceptable",
            metadata={"data_classification": data_classification.value}
        )
    
    def _check_tenant_scope(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext
    ) -> PermissionCheck:
        """Check tenant scope compatibility."""
        
        if not context.get_tenant_scope(manifest):
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id="tenant_scope",
                reason=f"Tenant scope mismatch: {manifest.tenant_scope} vs {context.tenant_id}",
                metadata={"manifest_tenant_scope": manifest.tenant_scope.value, "context_tenant_id": context.tenant_id}
            )
        
        return PermissionCheck(
            result=PermissionResult.GRANTED,
            granted=True,
            permission_id="tenant_scope",
            reason="Tenant scope compatible",
            metadata={"manifest_tenant_scope": manifest.tenant_scope.value, "context_tenant_id": context.tenant_id}
        )
    
    def _check_user_roles(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext
    ) -> PermissionCheck:
        """Check user role compatibility."""
        
        # Get required roles
        required_roles = getattr(capability, "required_roles", manifest.required_roles) if capability else manifest.required_roles
        
        # Get user roles from context
        user_roles = context.audit_context.get("user_roles", [])
        
        # Check if user has required roles
        if required_roles and not set(required_roles) & set(user_roles):
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id="user_roles",
                reason=f"User roles {user_roles} do not meet required {required_roles}",
                metadata={"required_roles": required_roles, "user_roles": user_roles}
            )
        
        return PermissionCheck(
            result=PermissionResult.GRANTED,
            granted=True,
            permission_id="user_roles",
            reason="User roles compatible",
            metadata={"required_roles": required_roles, "user_roles": user_roles}
        )
    
    def _check_policy_constraints(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext,
        authorized_plan: Optional[Dict[str, Any]] = None
    ) -> List[PermissionCheck]:
        """Check policy constraints for the extension."""
        
        checks: List[PermissionCheck] = []
        
        # Check relevant policies
        for policy_id, policy in self.policies.items():
            policy_check = self._check_policy(policy, manifest, capability, context, authorized_plan)
            if policy_check:
                checks.append(policy_check)
        
        return checks
    
    def _check_policy(
        self,
        policy: PermissionPolicy,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext,
        authorized_plan: Optional[Dict[str, Any]] = None
    ) -> Optional[PermissionCheck]:
        """Check if extension meets policy requirements."""
        
        # Check if manifest requires any of the policy's required permissions
        required_perms = self._get_required_permissions(manifest, capability)
        if not set(required_perms) & set(policy.required_permissions):
            return None  # Policy not applicable
        
        # Check denied permissions
        if set(required_perms) & set(policy.denied_permissions):
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id=f"policy:{policy.id}",
                reason=f"Extension uses denied permission for policy {policy.id}",
                metadata={"policy_id": policy.id, "denied_permissions": policy.denied_permissions}
            )
        
        # Check trust tier compatibility
        if manifest.trust_tier not in policy.allowed_trust_tiers:
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id=f"policy:{policy.id}",
                reason=f"Trust tier {manifest.trust_tier} not allowed by policy {policy.id}",
                metadata={"policy_id": policy.id, "allowed_trust_tiers": [t.value for t in policy.allowed_trust_tiers]}
            )
        
        # Check risk class compatibility
        risk_class = getattr(capability, "risk_class", manifest.risk_class) if capability else manifest.risk_class
        if risk_class not in policy.allowed_risk_classes:
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id=f"policy:{policy.id}",
                reason=f"Risk class {risk_class.value} not allowed by policy {policy.id}",
                metadata={"policy_id": policy.id, "allowed_risk_classes": [r.value for r in policy.allowed_risk_classes]}
            )
        
        # Check data classification compatibility
        data_classification = getattr(capability, "data_classification", manifest.data_classification) if capability else manifest.data_classification
        if data_classification not in policy.allowed_data_classifications:
            return PermissionCheck(
                result=PermissionResult.DENIED,
                granted=False,
                permission_id=f"policy:{policy.id}",
                reason=f"Data classification {data_classification.value} not allowed by policy {policy.id}",
                metadata={"policy_id": policy.id, "allowed_data_classifications": [d.value for d in policy.allowed_data_classifications]}
            )
        
        # Check conditional permissions
        for perm, conditions in policy.conditional_permissions.items():
            if perm in required_perms:
                # Check if conditions are met
                conditions_met = self._check_conditions(conditions, context)
                if not conditions_met:
                    return PermissionCheck(
                        result=PermissionResult.CONDITIONAL,
                        granted=False,
                        permission_id=f"policy:{policy.id}",
                        reason=f"Conditions not met for permission {perm} in policy {policy.id}",
                        metadata={"policy_id": policy.id, "conditions": conditions, "conditions_met": conditions_met}
                    )
        
        # Check if approval is required
        if set(required_perms) & set(policy.approval_required):
            user_roles = context.audit_context.get("user_roles", [])
            if not set(policy.approval_required) & set(user_roles):
                return PermissionCheck(
                    result=PermissionResult.NEEDS_APPROVAL,
                    granted=False,
                    permission_id=f"policy:{policy.id}",
                    reason=f"Approval required from {policy.approval_required}",
                    metadata={"policy_id": policy.id, "required_approvals": policy.approval_required}
                )
        
        return PermissionCheck(
            result=PermissionResult.GRANTED,
            granted=True,
            permission_id=f"policy:{policy.id}",
            reason=f"Policy {policy.id} requirements met",
            metadata={"policy_id": policy.id}
        )
    
    def _check_conditions(self, conditions: List[str], context: ExtensionExecutionContext) -> bool:
        """Check if conditional requirements are met."""
        
        for condition in conditions:
            if condition.startswith("user_role:"):
                role = condition.split(":", 1)[1]
                user_roles = context.audit_context.get("user_roles", [])
                if role not in user_roles:
                    return False
            
            elif condition.startswith("tenant_scope:"):
                scope = condition.split(":", 1)[1]
                if scope == "global" and context.tenant_id:
                    return False
                elif scope == "single" and not context.tenant_id:
                    return False
                elif scope == "multi" and context.tenant_id not in context.resource_scope.get("allowed_tenants", []):
                    return False
            
            elif condition.startswith("budget:"):
                budget_type = condition.split(":", 1)[1]
                if budget_type == "available" and context.is_budget_exhausted:
                    return False
            
            elif condition.startswith("time:"):
                # Time-based conditions could be implemented here
                pass
        
        return True
    
    def validate_execution_plan(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext,
        authorized_plan: Dict[str, Any]
    ) -> bool:
        """Validate that execution plan is compatible with extension requirements."""
        
        # Check all permissions
        checks = self.check_permissions(manifest, capability, context, authorized_plan)
        
        # Check if all required permissions are granted
        for check in checks:
            if check.result == PermissionResult.DENIED:
                return False
            elif check.result == PermissionResult.NEEDS_APPROVAL:
                # For now, treat as denial - could be extended to handle approval workflow
                return False
        
        return True
    
    def get_permission_summary(
        self,
        manifest: ExtensionManifest,
        capability: Optional[ExtensionCapability],
        context: ExtensionExecutionContext,
        authorized_plan: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get a summary of permission checks."""
        
        checks = self.check_permissions(manifest, capability, context, authorized_plan)
        
        granted = sum(1 for check in checks if check.granted)
        denied = sum(1 for check in checks if check.result == PermissionResult.DENIED)
        conditional = sum(1 for check in checks if check.result == PermissionResult.CONDITIONAL)
        needs_approval = sum(1 for check in checks if check.result == PermissionResult.NEEDS_APPROVAL)
        
        return {
            "total_checks": len(checks),
            "granted": granted,
            "denied": denied,
            "conditional": conditional,
            "needs_approval": needs_approval,
            "checks": [check.to_dict() for check in checks],
            "valid": denied == 0 and needs_approval == 0,
        }


# Global validator instance
_permission_validator: Optional[PermissionValidator] = None


def get_permission_validator() -> PermissionValidator:
    """Get or create the global permission validator."""
    global _permission_validator
    if _permission_validator is None:
        _permission_validator = PermissionValidator()
    return _permission_validator


def validate_plugin_permissions(
    manifest: ExtensionManifest,
    capability: Optional[ExtensionCapability],
    context: ExtensionExecutionContext,
    authorized_plan: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Validate plugin permissions and return summary."""
    validator = get_permission_validator()
    return validator.get_permission_summary(manifest, capability, context, authorized_plan)