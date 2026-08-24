"""
Role-Based Access Control (RBAC) system for extensions.

This package provides comprehensive permission and role management:
- Advanced permissions with scopes and inheritance
- Role hierarchy and delegation
- Tenant-specific access control
- Permission caching and expiration

Migrated from root server/ extension_* files as part of ROOT-CLEANUP-1A.
"""

from .permissions import (
    ExtensionPermission,
    ExtensionRole,
    PermissionScope,
    ExtensionPermissionRule,
    ExtensionRoleDefinition,
    ExtensionPermissionManager,
    get_extension_permission_manager,
    has_extension_permission,
    require_extension_permission,
)

from .manager import (
    RoleAssignmentType,
    RoleAssignment,
    TenantRolePolicy,
    ExtensionRBACManager,
    get_extension_rbac_manager,
    check_extension_role_permission,
)

__all__ = [
    # Permission system
    "ExtensionPermission",
    "ExtensionRole",
    "PermissionScope",
    "ExtensionPermissionRule",
    "ExtensionRoleDefinition",
    "ExtensionPermissionManager",
    "get_extension_permission_manager",
    "has_extension_permission",
    "require_extension_permission",
    
    # RBAC system
    "RoleAssignmentType",
    "RoleAssignment",
    "TenantRolePolicy",
    "ExtensionRBACManager",
    "get_extension_rbac_manager",
    "check_extension_role_permission",
]