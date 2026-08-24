"""
Comprehensive permission system for extension operations.

This module implements a sophisticated permission system including:
- Role-based permissions with inheritance
- Tenant-specific permission isolation
- Permission scopes (global, category, extension, tenant)
- Permission delegation and expiration
- Extension access restrictions

Migrated from root server/extension_permissions.py as part of ROOT-CLEANUP-1A.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Set, Union
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class ExtensionPermission(str, Enum):
    """Core extension permissions."""
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    BACKGROUND_TASKS = "background_tasks"
    CONFIGURE = "configure"
    INSTALL = "install"
    UNINSTALL = "uninstall"
    HEALTH = "health"
    LOGS = "logs"
    METRICS = "metrics"


class ExtensionRole(str, Enum):
    """Extension-specific roles."""
    VIEWER = "viewer"
    USER = "user"
    DEVELOPER = "developer"
    ADMIN = "admin"
    SYSTEM = "system"
    SERVICE = "service"


class PermissionScope(str, Enum):
    """Permission scope levels."""
    GLOBAL = "global"          # All extensions
    CATEGORY = "category"      # Extensions in specific category
    EXTENSION = "extension"    # Specific extension
    TENANT = "tenant"          # Tenant-specific
    USER = "user"              # User-specific


@dataclass
class ExtensionPermissionRule:
    """Represents a single permission rule."""
    permission: ExtensionPermission
    scope: PermissionScope
    target: str  # Extension name, category, or '*' for global
    tenant_id: Optional[str] = None
    granted: bool = True
    expires_at: Optional[datetime] = None
    granted_by: Optional[str] = None
    granted_at: datetime = field(default_factory=datetime.utcnow)
    conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtensionRoleDefinition:
    """Defines what permissions a role includes."""
    role: ExtensionRole
    permissions: List[ExtensionPermissionRule]
    inherits_from: List[ExtensionRole] = field(default_factory=list)
    description: str = ""
    is_system_role: bool = False


class ExtensionPermissionManager:
    """Manages extension permissions, roles, and access control."""

    def __init__(self):
        """Initialize the permission manager."""
        self.role_definitions: Dict[ExtensionRole, ExtensionRoleDefinition] = {}
        self.user_permissions: Dict[str, List[ExtensionPermissionRule]] = {}
        self.tenant_permissions: Dict[str, List[ExtensionPermissionRule]] = {}
        self.extension_restrictions: Dict[str, Dict[str, Any]] = {}
        self._initialize_default_roles()

    def _initialize_default_roles(self):
        """Initialize default extension roles and their permissions."""

        # Viewer role - read-only access
        viewer_permissions = [
            ExtensionPermissionRule(
                permission=ExtensionPermission.READ,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.HEALTH,
                scope=PermissionScope.GLOBAL,
                target="*"
            )
        ]

        self.role_definitions[ExtensionRole.VIEWER] = ExtensionRoleDefinition(
            role=ExtensionRole.VIEWER,
            permissions=viewer_permissions,
            description="Read-only access to extensions"
        )

        # User role - basic extension usage
        user_permissions = [
            ExtensionPermissionRule(
                permission=ExtensionPermission.READ,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.WRITE,
                scope=PermissionScope.CATEGORY,
                target="general"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.CONFIGURE,
                scope=PermissionScope.CATEGORY,
                target="general"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.HEALTH,
                scope=PermissionScope.GLOBAL,
                target="*"
            )
        ]

        self.role_definitions[ExtensionRole.USER] = ExtensionRoleDefinition(
            role=ExtensionRole.USER,
            permissions=user_permissions,
            inherits_from=[ExtensionRole.VIEWER],
            description="Standard user access to extensions"
        )

        # Developer role - development and testing
        developer_permissions = [
            ExtensionPermissionRule(
                permission=ExtensionPermission.READ,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.WRITE,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.CONFIGURE,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.BACKGROUND_TASKS,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.HEALTH,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.LOGS,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.METRICS,
                scope=PermissionScope.GLOBAL,
                target="*"
            )
        ]

        self.role_definitions[ExtensionRole.DEVELOPER] = ExtensionRoleDefinition(
            role=ExtensionRole.DEVELOPER,
            permissions=developer_permissions,
            inherits_from=[ExtensionRole.USER],
            description="Developer access for extension development and testing"
        )

        # Admin role - full extension management
        admin_permissions = [
            ExtensionPermissionRule(
                permission=ExtensionPermission.ADMIN,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.INSTALL,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.UNINSTALL,
                scope=PermissionScope.GLOBAL,
                target="*"
            )
        ]

        self.role_definitions[ExtensionRole.ADMIN] = ExtensionRoleDefinition(
            role=ExtensionRole.ADMIN,
            permissions=admin_permissions,
            inherits_from=[ExtensionRole.DEVELOPER],
            description="Full administrative access to extensions",
            is_system_role=True
        )

        # System role - internal system operations
        system_permissions = [
            ExtensionPermissionRule(
                permission=ExtensionPermission.ADMIN,
                scope=PermissionScope.GLOBAL,
                target="*"
            )
        ]

        self.role_definitions[ExtensionRole.SYSTEM] = ExtensionRoleDefinition(
            role=ExtensionRole.SYSTEM,
            permissions=system_permissions,
            description="System-level access for internal operations",
            is_system_role=True
        )

        # Service role - service-to-service operations
        service_permissions = [
            ExtensionPermissionRule(
                permission=ExtensionPermission.BACKGROUND_TASKS,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.HEALTH,
                scope=PermissionScope.GLOBAL,
                target="*"
            ),
            ExtensionPermissionRule(
                permission=ExtensionPermission.READ,
                scope=PermissionScope.GLOBAL,
                target="*"
            )
        ]

        self.role_definitions[ExtensionRole.SERVICE] = ExtensionRoleDefinition(
            role=ExtensionRole.SERVICE,
            permissions=service_permissions,
            description="Service-to-service access for background operations"
        )

        logger.info("Default extension roles initialized")

    def has_permission(
        self,
        user_context: Dict[str, Any],
        permission: Union[str, ExtensionPermission],
        extension_name: Optional[str] = None,
        category: Optional[str] = None
    ) -> bool:
        """
        Check if user has specific permission for extension operations.

        Args:
            user_context: User authentication context
            permission: Permission to check
            extension_name: Specific extension name (optional)
            category: Extension category (optional)

        Returns:
            bool: True if user has permission
        """
        try:
            # Convert string permission to enum
            if isinstance(permission, str):
                try:
                    permission = ExtensionPermission(permission)
                except ValueError:
                    logger.warning(f"Unknown permission: {permission}")
                    return False

            user_id = user_context.get('user_id')
            tenant_id = user_context.get('tenant_id')
            user_roles = user_context.get('roles', [])
            user_permissions = user_context.get('permissions', [])

            # Check for admin override
            if 'admin' in user_roles or 'extension:*' in user_permissions:
                return True

            # Check role-based permissions
            if self._check_role_permissions(user_roles, permission, extension_name, category):
                return True

            # Check explicit user permissions
            if self._check_user_permissions(user_id, permission, extension_name, category, tenant_id):
                return True

            # Check tenant-level permissions
            if self._check_tenant_permissions(tenant_id, permission, extension_name, category):
                return True

            # Check legacy permission format for backward compatibility
            if self._check_legacy_permissions(user_permissions, permission, extension_name):
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking permission {permission} for user {user_context.get('user_id')}: {e}")
            return False

    def _check_role_permissions(
        self,
        user_roles: List[str],
        permission: ExtensionPermission,
        extension_name: Optional[str],
        category: Optional[str]
    ) -> bool:
        """Check if user roles grant the required permission."""
        for role_name in user_roles:
            try:
                role = ExtensionRole(role_name)
                if self._role_has_permission(role, permission, extension_name, category):
                    return True
            except ValueError:
                # Not an extension role, skip
                continue

        return False

    def _role_has_permission(
        self,
        role: Union[ExtensionRole, str],  # Allow string for RBAC manager compatibility
        permission: ExtensionPermission,
        extension_name: Optional[str],
        category: Optional[str]
    ) -> bool:
        """Check if a specific role has the required permission."""
        # Convert string to enum if needed
        if isinstance(role, str):
            try:
                role = ExtensionRole(role)
            except ValueError:
                return False

        if role not in self.role_definitions:
            return False

        role_def = self.role_definitions[role]

        # Check inherited roles first
        for inherited_role in role_def.inherits_from:
            if self._role_has_permission(inherited_role, permission, extension_name, category):
                return True

        # Check role's own permissions
        for rule in role_def.permissions:
            if self._rule_matches(rule, permission, extension_name, category):
                return rule.granted and not self._is_rule_expired(rule)

        return False

    def _check_user_permissions(
        self,
        user_id: str,
        permission: ExtensionPermission,
        extension_name: Optional[str],
        category: Optional[str],
        tenant_id: Optional[str]
    ) -> bool:
        """Check user-specific permissions."""
        if user_id not in self.user_permissions:
            return False

        for rule in self.user_permissions[user_id]:
            if (self._rule_matches(rule, permission, extension_name, category) and
                (rule.tenant_id is None or rule.tenant_id == tenant_id)):
                return rule.granted and not self._is_rule_expired(rule)

        return False

    def _check_tenant_permissions(
        self,
        tenant_id: str,
        permission: ExtensionPermission,
        extension_name: Optional[str],
        category: Optional[str]
    ) -> bool:
        """Check tenant-level permissions."""
        if tenant_id not in self.tenant_permissions:
            return False

        for rule in self.tenant_permissions[tenant_id]:
            if self._rule_matches(rule, permission, extension_name, category):
                return rule.granted and not self._is_rule_expired(rule)

        return False

    def _check_legacy_permissions(
        self,
        user_permissions: List[str],
        permission: ExtensionPermission,
        extension_name: Optional[str]
    ) -> bool:
        """Check legacy permission format for backward compatibility."""
        # Check for exact permission match
        if f'extension:{permission.value}' in user_permissions:
            return True

        # Check for extension-specific permission
        if extension_name and f'extension:{extension_name}:{permission.value}' in user_permissions:
            return True

        # Check for wildcard permissions
        if 'extension:*' in user_permissions:
            return True

        return False

    def _rule_matches(
        self,
        rule: ExtensionPermissionRule,
        permission: ExtensionPermission,
        extension_name: Optional[str],
        category: Optional[str]
    ) -> bool:
        """Check if a permission rule matches the requested permission."""
        # Check permission match
        if rule.permission != permission:
            return False

        # Check scope and target
        if rule.scope == PermissionScope.GLOBAL:
            return rule.target == "*"
        elif rule.scope == PermissionScope.EXTENSION:
            return extension_name and rule.target == extension_name
        elif rule.scope == PermissionScope.CATEGORY:
            return category and rule.target == category

        return False

    def _is_rule_expired(self, rule: ExtensionPermissionRule) -> bool:
        """Check if a permission rule has expired."""
        if rule.expires_at is None:
            return False
        return datetime.utcnow() > rule.expires_at

    def grant_permission(
        self,
        user_id: str,
        permission: ExtensionPermission,
        scope: PermissionScope,
        target: str,
        tenant_id: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        granted_by: Optional[str] = None,
        conditions: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Grant a specific permission to a user."""
        try:
            rule = ExtensionPermissionRule(
                permission=permission,
                scope=scope,
                target=target,
                tenant_id=tenant_id,
                granted=True,
                expires_at=expires_at,
                granted_by=granted_by,
                conditions=conditions or {}
            )

            if user_id not in self.user_permissions:
                self.user_permissions[user_id] = []

            # Remove any existing conflicting rules
            self.user_permissions[user_id] = [
                r for r in self.user_permissions[user_id]
                if not (r.permission == permission and r.scope == scope and r.target == target)
            ]

            # Add new rule
            self.user_permissions[user_id].append(rule)

            logger.info(f"Granted permission {permission.value} to user {user_id} for {scope.value}:{target}")
            return True

        except Exception as e:
            logger.error(f"Error granting permission to user {user_id}: {e}")
            return False

    def revoke_permission(
        self,
        user_id: str,
        permission: ExtensionPermission,
        scope: PermissionScope,
        target: str,
        tenant_id: Optional[str] = None
    ) -> bool:
        """Revoke a specific permission from a user."""
        try:
            if user_id not in self.user_permissions:
                return True  # Nothing to revoke

            # Remove matching rules
            original_count = len(self.user_permissions[user_id])
            self.user_permissions[user_id] = [
                rule for rule in self.user_permissions[user_id]
                if not (
                    rule.permission == permission and
                    rule.scope == scope and
                    rule.target == target and
                    (tenant_id is None or rule.tenant_id == tenant_id)
                )
            ]

            revoked_count = original_count - len(self.user_permissions[user_id])

            if revoked_count > 0:
                logger.info(f"Revoked {revoked_count} permission(s) {permission.value} from user {user_id}")

            return True

        except Exception as e:
            logger.error(f"Error revoking permission from user {user_id}: {e}")
            return False

    def grant_tenant_permission(
        self,
        tenant_id: str,
        permission: ExtensionPermission,
        scope: PermissionScope,
        target: str,
        expires_at: Optional[datetime] = None,
        granted_by: Optional[str] = None
    ) -> bool:
        """Grant a permission to all users in a tenant."""
        try:
            rule = ExtensionPermissionRule(
                permission=permission,
                scope=scope,
                target=target,
                tenant_id=tenant_id,
                granted=True,
                expires_at=expires_at,
                granted_by=granted_by
            )

            if tenant_id not in self.tenant_permissions:
                self.tenant_permissions[tenant_id] = []

            # Remove any existing conflicting rules
            self.tenant_permissions[tenant_id] = [
                r for r in self.tenant_permissions[tenant_id]
                if not (r.permission == permission and r.scope == scope and r.target == target)
            ]

            # Add new rule
            self.tenant_permissions[tenant_id].append(rule)

            logger.info(f"Granted tenant permission {permission.value} to tenant {tenant_id} for {scope.value}:{target}")
            return True

        except Exception as e:
            logger.error(f"Error granting tenant permission to {tenant_id}: {e}")
            return False

    def set_extension_restrictions(
        self,
        extension_name: str,
        restrictions: Dict[str, Any]
    ) -> bool:
        """Set access restrictions for a specific extension."""
        try:
            self.extension_restrictions[extension_name] = restrictions
            logger.info(f"Set restrictions for extension {extension_name}: {restrictions}")
            return True

        except Exception as e:
            logger.error(f"Error setting restrictions for extension {extension_name}: {e}")
            return False

    def check_extension_access(
        self,
        user_context: Dict[str, Any],
        extension_name: str,
        operation: str = "access"
    ) -> bool:
        """Check if user can access a specific extension with restrictions."""
        try:
            # Check basic read permission first
            if not self.has_permission(user_context, ExtensionPermission.READ, extension_name):
                return False

            # Check extension-specific restrictions
            if extension_name in self.extension_restrictions:
                restrictions = self.extension_restrictions[extension_name]

                # Check tenant restrictions
                if 'allowed_tenants' in restrictions:
                    user_tenant = user_context.get('tenant_id')
                    if user_tenant not in restrictions['allowed_tenants']:
                        return False

                # Check role restrictions
                if 'required_roles' in restrictions:
                    user_roles = set(user_context.get('roles', []))
                    required_roles = set(restrictions['required_roles'])
                    if not user_roles.intersection(required_roles):
                        return False

                # Check time-based restrictions
                if 'access_hours' in restrictions:
                    current_hour = datetime.utcnow().hour
                    allowed_hours = restrictions['access_hours']
                    if current_hour not in allowed_hours:
                        return False

                # Check IP-based restrictions (if available in context)
                if 'allowed_ips' in restrictions and 'client_ip' in user_context:
                    client_ip = user_context['client_ip']
                    if client_ip not in restrictions['allowed_ips']:
                        return False

            return True

        except Exception as e:
            logger.error(f"Error checking extension access for {extension_name}: {e}")
            return False

    def get_user_permissions(
        self,
        user_context: Dict[str, Any],
        extension_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get all permissions for a user, optionally filtered by extension."""
        try:
            user_id = user_context.get('user_id')
            tenant_id = user_context.get('tenant_id')
            user_roles = user_context.get('roles', [])

            permissions = {
                'user_id': user_id,
                'tenant_id': tenant_id,
                'roles': user_roles,
                'permissions': {},
                'restrictions': {}
            }

            # Check each permission type
            for permission in ExtensionPermission:
                has_perm = self.has_permission(user_context, permission, extension_name)
                permissions['permissions'][permission.value] = has_perm

            # Include extension restrictions if specific extension requested
            if extension_name and extension_name in self.extension_restrictions:
                permissions['restrictions'][extension_name] = self.extension_restrictions[extension_name]

            return permissions

        except Exception as e:
            logger.error(f"Error getting user permissions: {e}")
            return {'error': str(e)}

    def delegate_permission(
        self,
        delegator_context: Dict[str, Any],
        delegatee_user_id: str,
        permission: ExtensionPermission,
        scope: PermissionScope,
        target: str,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """Delegate a permission from one user to another."""
        try:
            # Check if delegator has the permission to delegate
            if not self.has_permission(delegator_context, permission, target if scope == PermissionScope.EXTENSION else None):
                logger.warning(f"User {delegator_context.get('user_id')} cannot delegate permission they don't have")
                return False

            # Check if delegator has delegation rights
            if not self.has_permission(delegator_context, ExtensionPermission.ADMIN):
                logger.warning(f"User {delegator_context.get('user_id')} lacks delegation rights")
                return False

            # Grant permission to delegatee
            return self.grant_permission(
                user_id=delegatee_user_id,
                permission=permission,
                scope=scope,
                target=target,
                tenant_id=delegator_context.get('tenant_id'),
                expires_at=expires_at,
                granted_by=delegator_context.get('user_id'),
                conditions={'delegated': True, 'delegator': delegator_context.get('user_id')}
            )

        except Exception as e:
            logger.error(f"Error delegating permission: {e}")
            return False

    def cleanup_expired_permissions(self) -> int:
        """Clean up expired permissions and return count of removed permissions."""
        try:
            removed_count = 0
            current_time = datetime.utcnow()

            # Clean up user permissions
            for user_id in list(self.user_permissions.keys()):
                original_count = len(self.user_permissions[user_id])
                self.user_permissions[user_id] = [
                    rule for rule in self.user_permissions[user_id]
                    if rule.expires_at is None or rule.expires_at > current_time
                ]
                removed_count += original_count - len(self.user_permissions[user_id])

                # Remove empty user entries
                if not self.user_permissions[user_id]:
                    del self.user_permissions[user_id]

            # Clean up tenant permissions
            for tenant_id in list(self.tenant_permissions.keys()):
                original_count = len(self.tenant_permissions[tenant_id])
                self.tenant_permissions[tenant_id] = [
                    rule for rule in self.tenant_permissions[tenant_id]
                    if rule.expires_at is None or rule.expires_at > current_time
                ]
                removed_count += original_count - len(self.tenant_permissions[tenant_id])

                # Remove empty tenant entries
                if not self.tenant_permissions[tenant_id]:
                    del self.tenant_permissions[tenant_id]

            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} expired permissions")

            return removed_count

        except Exception as e:
            logger.error(f"Error cleaning up expired permissions: {e}")
            return 0


# Global permission manager instance
_permission_manager: Optional[ExtensionPermissionManager] = None


def get_extension_permission_manager() -> ExtensionPermissionManager:
    """Get or create the global extension permission manager."""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = ExtensionPermissionManager()
    return _permission_manager


def has_extension_permission(
    user_context: Dict[str, Any],
    permission: Union[str, ExtensionPermission],
    extension_name: Optional[str] = None,
    category: Optional[str] = None
) -> bool:
    """Convenience function to check extension permissions."""
    manager = get_extension_permission_manager()
    return manager.has_permission(user_context, permission, extension_name, category)


def require_extension_permission(permission: Union[str, ExtensionPermission], extension_name: Optional[str] = None):
    """FastAPI dependency to require specific extension permission."""
    from fastapi import HTTPException, Depends

    async def permission_checker(
        user_context: Dict[str, Any] = Depends(lambda: {})
    ) -> Dict[str, Any]:
        if not has_extension_permission(user_context, permission, extension_name):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {permission} for extension: {extension_name or 'any'}"
            )
        return user_context

    return permission_checker