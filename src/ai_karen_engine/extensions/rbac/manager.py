"""
Advanced RBAC system for extension permissions.

This module provides comprehensive role-based access control including:
- Role hierarchy and inheritance
- Dynamic role assignment with expiration
- Tenant-specific role policies
- Permission caching for performance
- Role delegation capabilities

Migrated from root server/extension_rbac.py as part of ROOT-CLEANUP-1A.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger(__name__)


class RoleAssignmentType(str, Enum):
    """Types of role assignments."""
    DIRECT = "direct"           # Directly assigned to user
    INHERITED = "inherited"     # Inherited from parent role
    TENANT = "tenant"           # Assigned via tenant membership
    GROUP = "group"             # Assigned via group membership
    TEMPORARY = "temporary"     # Temporary assignment with expiration


@dataclass
class RoleAssignment:
    """Represents a role assignment to a user."""
    user_id: str
    role: str  # Using string to avoid circular import with permissions module
    assignment_type: RoleAssignmentType
    tenant_id: Optional[str] = None
    assigned_by: Optional[str] = None
    assigned_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    conditions: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True


@dataclass
class TenantRolePolicy:
    """Defines role policies for a tenant."""
    tenant_id: str
    default_role: str
    allowed_roles: List[str]
    role_restrictions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    auto_assign_rules: List[Dict[str, Any]] = field(default_factory=list)


class ExtensionRBACManager:
    """Advanced RBAC manager for extension permissions."""

    def __init__(self):
        """Initialize the RBAC manager."""
        self.role_assignments: Dict[str, List[RoleAssignment]] = {}
        self.tenant_policies: Dict[str, TenantRolePolicy] = {}
        self.role_hierarchy: Dict[str, Set[str]] = {}
        self.permission_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = timedelta(minutes=15)
        self._initialize_role_hierarchy()

    def _initialize_role_hierarchy(self):
        """Initialize the role hierarchy for inheritance."""
        # Define role hierarchy (higher roles inherit from lower roles)
        self.role_hierarchy = {
            "admin": {"developer", "user", "viewer"},
            "developer": {"user", "viewer"},
            "user": {"viewer"},
            "system": {"admin", "developer", "user", "viewer"},
            "service": {"viewer"},
            "viewer": set()
        }

        logger.info("Extension role hierarchy initialized")

    def assign_role(
        self,
        user_id: str,
        role: str,
        tenant_id: Optional[str] = None,
        assigned_by: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        assignment_type: RoleAssignmentType = RoleAssignmentType.DIRECT,
        conditions: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Assign a role to a user."""
        try:
            # Validate role assignment against tenant policy
            if tenant_id and not self._validate_tenant_role_assignment(tenant_id, role):
                logger.warning(f"Role {role} not allowed for tenant {tenant_id}")
                return False

            assignment = RoleAssignment(
                user_id=user_id,
                role=role,
                assignment_type=assignment_type,
                tenant_id=tenant_id,
                assigned_by=assigned_by,
                expires_at=expires_at,
                conditions=conditions or {}
            )

            if user_id not in self.role_assignments:
                self.role_assignments[user_id] = []

            # Remove any existing assignment of the same role for the same tenant
            self.role_assignments[user_id] = [
                a for a in self.role_assignments[user_id]
                if not (a.role == role and a.tenant_id == tenant_id and a.is_active)
            ]

            # Add new assignment
            self.role_assignments[user_id].append(assignment)

            # Clear permission cache for user
            self._clear_user_cache(user_id)

            logger.info(f"Assigned role {role} to user {user_id} in tenant {tenant_id}")
            return True

        except Exception as e:
            logger.error(f"Error assigning role {role} to user {user_id}: {e}")
            return False

    def revoke_role(
        self,
        user_id: str,
        role: str,
        tenant_id: Optional[str] = None
    ) -> bool:
        """Revoke a role from a user."""
        try:
            if user_id not in self.role_assignments:
                return True  # Nothing to revoke

            # Mark matching assignments as inactive
            revoked_count = 0
            for assignment in self.role_assignments[user_id]:
                if (assignment.role == role and
                    assignment.tenant_id == tenant_id and
                    assignment.is_active):
                    assignment.is_active = False
                    revoked_count += 1

            # Clear permission cache for user
            self._clear_user_cache(user_id)

            if revoked_count > 0:
                logger.info(f"Revoked role {role} from user {user_id} in tenant {tenant_id}")

            return True

        except Exception as e:
            logger.error(f"Error revoking role {role} from user {user_id}: {e}")
            return False

    def get_user_roles(
        self,
        user_id: str,
        tenant_id: Optional[str] = None,
        include_inherited: bool = True
    ) -> List[str]:
        """Get all roles for a user, optionally including inherited roles."""
        try:
            roles = set()

            if user_id not in self.role_assignments:
                # Check for default tenant role
                if tenant_id and tenant_id in self.tenant_policies:
                    roles.add(self.tenant_policies[tenant_id].default_role)
                return list(roles)

            current_time = datetime.utcnow()

            # Get directly assigned roles
            for assignment in self.role_assignments[user_id]:
                if (assignment.is_active and
                    (assignment.tenant_id is None or assignment.tenant_id == tenant_id) and
                    (assignment.expires_at is None or assignment.expires_at > current_time)):
                    roles.add(assignment.role)

            # Add inherited roles if requested
            if include_inherited:
                inherited_roles = set()
                for role in roles:
                    inherited_roles.update(self.role_hierarchy.get(role, set()))
                roles.update(inherited_roles)

            # Add default tenant role if no roles assigned
            if not roles and tenant_id and tenant_id in self.tenant_policies:
                roles.add(self.tenant_policies[tenant_id].default_role)

            return list(roles)

        except Exception as e:
            logger.error(f"Error getting roles for user {user_id}: {e}")
            return []

    def check_role_permission(
        self,
        user_context: Dict[str, Any],
        permission: str,
        extension_name: Optional[str] = None,
        category: Optional[str] = None
    ) -> bool:
        """Check if user has permission through their roles."""
        try:
            user_id = user_context.get('user_id')
            tenant_id = user_context.get('tenant_id')

            # Check cache first
            cache_key = f"{user_id}:{tenant_id}:{permission}:{extension_name}:{category}"
            if cache_key in self.permission_cache:
                cache_entry = self.permission_cache[cache_key]
                if datetime.utcnow() - cache_entry['timestamp'] < self.cache_ttl:
                    return cache_entry['result']

            # Get user roles
            user_roles = self.get_user_roles(user_id, tenant_id, include_inherited=True)

            # Import permission manager to check role permissions
            # This avoids circular import
            try:
                from ai_karen_engine.extensions.rbac.permissions import get_extension_permission_manager
                permission_manager = get_extension_permission_manager()
            except ImportError:
                logger.warning("Permission manager not available, using basic role check")
                return permission in user_context.get('permissions', [])

            # Check each role for the permission
            for role in user_roles:
                if permission_manager._role_has_permission(role, permission, extension_name, category):
                    # Cache positive result
                    self.permission_cache[cache_key] = {
                        'result': True,
                        'timestamp': datetime.utcnow()
                    }
                    return True

            # Cache negative result
            self.permission_cache[cache_key] = {
                'result': False,
                'timestamp': datetime.utcnow()
            }
            return False

        except Exception as e:
            logger.error(f"Error checking role permission: {e}")
            return False

    def set_tenant_policy(
        self,
        tenant_id: str,
        default_role: str,
        allowed_roles: List[str],
        role_restrictions: Optional[Dict[str, Dict[str, Any]]] = None,
        auto_assign_rules: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """Set role policy for a tenant."""
        try:
            policy = TenantRolePolicy(
                tenant_id=tenant_id,
                default_role=default_role,
                allowed_roles=allowed_roles,
                role_restrictions=role_restrictions or {},
                auto_assign_rules=auto_assign_rules or []
            )

            self.tenant_policies[tenant_id] = policy

            # Clear cache for all users in this tenant
            self._clear_tenant_cache(tenant_id)

            logger.info(f"Set tenant policy for {tenant_id}: default_role={default_role}")
            return True

        except Exception as e:
            logger.error(f"Error setting tenant policy for {tenant_id}: {e}")
            return False

    def auto_assign_roles(self, user_context: Dict[str, Any]) -> List[str]:
        """Automatically assign roles based on tenant policies and user attributes."""
        try:
            user_id = user_context.get('user_id')
            tenant_id = user_context.get('tenant_id')

            if not tenant_id or tenant_id not in self.tenant_policies:
                return []

            policy = self.tenant_policies[tenant_id]
            assigned_roles = []

            # Process auto-assignment rules
            for rule in policy.auto_assign_rules:
                if self._evaluate_auto_assign_rule(rule, user_context):
                    role = rule['role']
                    if self.assign_role(
                        user_id=user_id,
                        role=role,
                        tenant_id=tenant_id,
                        assignment_type=RoleAssignmentType.TENANT,
                        conditions={'auto_assigned': True, 'rule': rule}
                    ):
                        assigned_roles.append(role)

            return assigned_roles

        except Exception as e:
            logger.error(f"Error auto-assigning roles: {e}")
            return []

    def _evaluate_auto_assign_rule(self, rule: Dict[str, Any], user_context: Dict[str, Any]) -> bool:
        """Evaluate if an auto-assignment rule matches the user context."""
        try:
            conditions = rule.get('conditions', {})

            # Check user attributes
            if 'user_attributes' in conditions:
                for attr, expected_value in conditions['user_attributes'].items():
                    if user_context.get(attr) != expected_value:
                        return False

            # Check role requirements
            if 'required_roles' in conditions:
                user_roles = set(user_context.get('roles', []))
                required_roles = set(conditions['required_roles'])
                if not user_roles.intersection(required_roles):
                    return False

            # Check permission requirements
            if 'required_permissions' in conditions:
                user_permissions = set(user_context.get('permissions', []))
                required_permissions = set(conditions['required_permissions'])
                if not user_permissions.intersection(required_permissions):
                    return False

            return True

        except Exception as e:
            logger.error(f"Error evaluating auto-assign rule: {e}")
            return False

    def _validate_tenant_role_assignment(self, tenant_id: str, role: str) -> bool:
        """Validate if a role can be assigned in a tenant."""
        if tenant_id not in self.tenant_policies:
            return True  # No policy restrictions

        policy = self.tenant_policies[tenant_id]
        return role in policy.allowed_roles

    def get_effective_permissions(
        self,
        user_context: Dict[str, Any],
        extension_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get all effective permissions for a user considering roles and inheritance."""
        try:
            user_id = user_context.get('user_id')
            tenant_id = user_context.get('tenant_id')

            # Get user roles
            user_roles = self.get_user_roles(user_id, tenant_id, include_inherited=True)

            # Get role assignments with details
            assignments = []
            if user_id in self.role_assignments:
                current_time = datetime.utcnow()
                for assignment in self.role_assignments[user_id]:
                    if (assignment.is_active and
                        (assignment.tenant_id is None or assignment.tenant_id == tenant_id) and
                        (assignment.expires_at is None or assignment.expires_at > current_time)):
                        assignments.append({
                            'role': assignment.role,
                            'assignment_type': assignment.assignment_type.value,
                            'assigned_by': assignment.assigned_by,
                            'assigned_at': assignment.assigned_at.isoformat(),
                            'expires_at': assignment.expires_at.isoformat() if assignment.expires_at else None
                        })

            # Try to get permission types from permission manager
            permissions = {}
            try:
                from ai_karen_engine.extensions.rbac.permissions import ExtensionPermission
                from ai_karen_engine.extensions.rbac.permissions import get_extension_permission_manager

                permission_manager = get_extension_permission_manager()

                for permission in ExtensionPermission:
                    has_perm = self.check_role_permission(
                        user_context, permission.value, extension_name
                    )
                    permissions[permission.value] = has_perm
            except ImportError:
                # Fallback to basic permissions from context
                permissions = {perm: True for perm in user_context.get('permissions', [])}

            return {
                'user_id': user_id,
                'tenant_id': tenant_id,
                'roles': user_roles,
                'role_assignments': assignments,
                'permissions': permissions,
                'extension_name': extension_name,
                'tenant_policy': self.tenant_policies.get(tenant_id, {}).__dict__ if tenant_id in self.tenant_policies else {}
            }

        except Exception as e:
            logger.error(f"Error getting effective permissions: {e}")
            return {'error': str(e)}

    def delegate_role(
        self,
        delegator_context: Dict[str, Any],
        delegatee_user_id: str,
        role: str,
        tenant_id: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """Delegate a role from one user to another."""
        try:
            delegator_id = delegator_context.get('user_id')
            delegator_roles = self.get_user_roles(delegator_id, tenant_id)

            # Check if delegator has the role to delegate
            if role not in delegator_roles:
                logger.warning(f"User {delegator_id} cannot delegate role {role} they don't have")
                return False

            # Check if delegator has delegation rights (admin role required)
            if "admin" not in delegator_roles:
                logger.warning(f"User {delegator_id} lacks delegation rights")
                return False

            # Assign role to delegatee
            return self.assign_role(
                user_id=delegatee_user_id,
                role=role,
                tenant_id=tenant_id,
                assigned_by=delegator_id,
                expires_at=expires_at,
                assignment_type=RoleAssignmentType.TEMPORARY,
                conditions={'delegated': True, 'delegator': delegator_id}
            )

        except Exception as e:
            logger.error(f"Error delegating role: {e}")
            return False

    def cleanup_expired_assignments(self) -> int:
        """Clean up expired role assignments."""
        try:
            removed_count = 0
            current_time = datetime.utcnow()

            for user_id in list(self.role_assignments.keys()):
                original_count = len(self.role_assignments[user_id])

                # Mark expired assignments as inactive
                for assignment in self.role_assignments[user_id]:
                    if (assignment.expires_at and
                        assignment.expires_at <= current_time and
                        assignment.is_active):
                        assignment.is_active = False
                        removed_count += 1

                # Remove inactive assignments older than 30 days
                cutoff_date = current_time - timedelta(days=30)
                self.role_assignments[user_id] = [
                    assignment for assignment in self.role_assignments[user_id]
                    if assignment.is_active or assignment.assigned_at > cutoff_date
                ]

                # Remove empty user entries
                if not self.role_assignments[user_id]:
                    del self.role_assignments[user_id]

            # Clear expired cache entries
            self._cleanup_permission_cache()

            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} expired role assignments")

            return removed_count

        except Exception as e:
            logger.error(f"Error cleaning up expired assignments: {e}")
            return 0

    def _clear_user_cache(self, user_id: str):
        """Clear permission cache for a specific user."""
        keys_to_remove = [key for key in self.permission_cache.keys() if key.startswith(f"{user_id}:")]
        for key in keys_to_remove:
            del self.permission_cache[key]

    def _clear_tenant_cache(self, tenant_id: str):
        """Clear permission cache for all users in a tenant."""
        keys_to_remove = [key for key in self.permission_cache.keys() if f":{tenant_id}:" in key]
        for key in keys_to_remove:
            del self.permission_cache[key]

    def _cleanup_permission_cache(self):
        """Clean up expired permission cache entries."""
        current_time = datetime.utcnow()
        keys_to_remove = []

        for key, entry in self.permission_cache.items():
            if current_time - entry['timestamp'] >= self.cache_ttl:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.permission_cache[key]


# Global RBAC manager instance
_rbac_manager: Optional[ExtensionRBACManager] = None


def get_extension_rbac_manager() -> ExtensionRBACManager:
    """Get or create the global extension RBAC manager."""
    global _rbac_manager
    if _rbac_manager is None:
        _rbac_manager = ExtensionRBACManager()
    return _rbac_manager


def check_extension_role_permission(
    user_context: Dict[str, Any],
    permission: str,
    extension_name: Optional[str] = None,
    category: Optional[str] = None
) -> bool:
    """Convenience function to check role-based extension permissions."""
    manager = get_extension_rbac_manager()
    return manager.check_role_permission(user_context, permission, extension_name, category)