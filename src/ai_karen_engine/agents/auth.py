"""
Authentication and Authorization for Agent Integration System

This module provides authentication and authorization utilities for the Agent Integration system,
including permission checking, role-based access control, and security policies.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

from .models import (
    AgentExecutionMode,
    AgentCapability,
    AgentInfo,
    AgentRequest
)

logger = logging.getLogger(__name__)


class AgentPermission:
    """Agent system permissions."""
    
    # Agent management permissions. The legacy registry is installation-wide,
    # so catalog/management permissions are control-plane permissions and are
    # granted only to the admin role below.
    CREATE_AGENT = "create_agent"
    DELETE_AGENT = "delete_agent"
    TERMINATE_AGENT = "terminate_agent"
    VIEW_AGENT = "view_agent"
    MODIFY_AGENT = "modify_agent"
    
    # Execution permissions
    EXECUTE_AGENT = "execute_agent"
    EXECUTE_STREAM = "execute_stream"
    CANCEL_REQUEST = "cancel_request"
    
    # Monitoring permissions. Legacy agent metrics/lifecycle state are also
    # installation-wide control-plane data.
    VIEW_METRICS = "view_metrics"
    VIEW_SYSTEM_METRICS = "view_system_metrics"
    VIEW_LIFECYCLE_EVENTS = "view_lifecycle_events"
    
    # Routing permissions
    VIEW_ROUTING_RECOMMENDATIONS = "view_routing_recommendations"
    CONFIGURE_ROUTING = "configure_routing"


class AgentRole:
    """Agent system roles with associated permissions."""
    
    # Predefined roles with their permissions. Non-admin roles may execute
    # agents according to execution/capability policy, but they do not receive
    # installation-wide catalog, configuration, metrics, or mutation access.
    ROLES = {
        "viewer": {
            AgentPermission.EXECUTE_AGENT,
            AgentPermission.VIEW_ROUTING_RECOMMENDATIONS
        },
        "user": {
            AgentPermission.EXECUTE_AGENT,
            AgentPermission.EXECUTE_STREAM,
            AgentPermission.CANCEL_REQUEST,
            AgentPermission.VIEW_ROUTING_RECOMMENDATIONS
        },
        "developer": {
            AgentPermission.EXECUTE_AGENT,
            AgentPermission.EXECUTE_STREAM,
            AgentPermission.CANCEL_REQUEST,
            AgentPermission.VIEW_ROUTING_RECOMMENDATIONS
        },
        "admin": {
            # All permissions
            AgentPermission.CREATE_AGENT,
            AgentPermission.DELETE_AGENT,
            AgentPermission.TERMINATE_AGENT,
            AgentPermission.VIEW_AGENT,
            AgentPermission.MODIFY_AGENT,
            AgentPermission.EXECUTE_AGENT,
            AgentPermission.EXECUTE_STREAM,
            AgentPermission.CANCEL_REQUEST,
            AgentPermission.VIEW_METRICS,
            AgentPermission.VIEW_SYSTEM_METRICS,
            AgentPermission.VIEW_LIFECYCLE_EVENTS,
            AgentPermission.VIEW_ROUTING_RECOMMENDATIONS,
            AgentPermission.CONFIGURE_ROUTING
        }
    }


class AgentAuthManager:
    """Authentication and authorization manager for agent system."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.AgentAuthManager")
        self._execution_mode_restrictions: Dict[str, Set[str]] = {
            AgentExecutionMode.NATIVE.value: {"viewer", "user", "developer", "admin"},
            AgentExecutionMode.LANGGRAPH.value: {"user", "developer", "admin"},
            AgentExecutionMode.DEEP_AGENTS.value: {"developer", "admin"}
        }
        self._capability_restrictions: Dict[str, Set[str]] = {
            AgentCapability.TEXT_GENERATION.value: {"viewer", "user", "developer", "admin"},
            AgentCapability.CODE_GENERATION.value: {"user", "developer", "admin"},
            AgentCapability.ANALYSIS.value: {"viewer", "user", "developer", "admin"},
            AgentCapability.REASONING.value: {"user", "developer", "admin"},
            AgentCapability.MEMORY_ACCESS.value: {"user", "developer", "admin"},
            AgentCapability.TOOL_USE.value: {"developer", "admin"},
            AgentCapability.MULTIMODAL.value: {"developer", "admin"},
            AgentCapability.STREAMING.value: {"user", "developer", "admin"}
        }
    
    def get_user_permissions(self, user: Dict[str, Any]) -> Set[str]:
        """
        Get permissions for a user based on their roles.
        
        Args:
            user: User information dictionary
            
        Returns:
            Set of permission strings
        """
        # Get user roles
        user_roles = user.get("roles", [])
        if not user_roles:
            # Default to viewer role if no roles specified
            user_roles = ["viewer"]
        
        # Collect permissions from all roles
        permissions = set()
        for role in user_roles:
            role_permissions = AgentRole.ROLES.get(role, set())
            permissions.update(role_permissions)
        
        # Add any additional permissions directly assigned to user
        additional_permissions = user.get("permissions", [])
        if additional_permissions:
            permissions.update(additional_permissions)
        
        self.logger.info(f"User {user.get('user_id') or user.get('id')} has permissions: {permissions}")
        return permissions
    
    def has_permission(self, user: Dict[str, Any], permission: str) -> bool:
        """
        Check if a user has a specific permission.
        
        Args:
            user: User information dictionary
            permission: Permission to check
            
        Returns:
            True if user has permission, False otherwise
        """
        user_permissions = self.get_user_permissions(user)
        
        # Exact match
        if permission in user_permissions:
            return True
            
        # Wildcard match (e.g., "admin:*" matches "admin:view")
        for p in user_permissions:
            if "*" in p:
                pattern = re.escape(p.replace("*", "")).replace("\\", "") + ".*"
                if re.match(pattern, permission):
                    return True
                # Simple prefix match for common cases like "agent:*"
                prefix = p.split(":")[0] if ":" in p else p.replace("*", "")
                if permission.startswith(prefix):
                    return True
                    
        return False
    
    def can_execute_agent(self, user: Dict[str, Any], execution_mode: AgentExecutionMode) -> bool:
        """
        Check if a user can execute agents with a specific execution mode.
        
        Args:
            user: User information dictionary
            execution_mode: Execution mode to check
            
        Returns:
            True if user can execute, False otherwise
        """
        user_roles = set(user.get("roles", ["viewer"]))
        allowed_roles = self._execution_mode_restrictions.get(execution_mode.value, set())
        
        return bool(user_roles.intersection(allowed_roles))
    
    def can_use_capability(self, user: Dict[str, Any], capability: AgentCapability) -> bool:
        """
        Check if a user can use a specific capability.
        
        Args:
            user: User information dictionary
            capability: Capability to check
            
        Returns:
            True if user can use capability, False otherwise
        """
        user_roles = set(user.get("roles", ["viewer"]))
        allowed_roles = self._capability_restrictions.get(capability.value, set())
        
        return bool(user_roles.intersection(allowed_roles))
    
    def can_access_agent(self, user: Dict[str, Any], agent: AgentInfo) -> bool:
        """
        Check if a user can access a specific agent.
        
        Args:
            user: User information dictionary
            agent: Agent information
            
        Returns:
            True if user can access agent, False otherwise
        """
        # Check execution mode access
        if not self.can_execute_agent(user, agent.execution_mode):
            return False
        
        # Check capability access
        for capability in agent.capabilities:
            if not self.can_use_capability(user, capability):
                return False
        
        return True
    
    def can_execute_request(self, user: Dict[str, Any], request: AgentRequest) -> bool:
        """
        Check if a user can execute a specific request.
        
        Args:
            user: User information dictionary
            request: Agent request
            
        Returns:
            True if user can execute request, False otherwise
        """
        # Check execution mode access
        if not self.can_execute_agent(user, request.execution_mode):
            return False
        
        # Check capability access
        for capability in request.capabilities_required:
            if not self.can_use_capability(user, capability):
                return False
        
        # Check streaming permission
        if request.enable_streaming and not self.has_permission(user, AgentPermission.EXECUTE_STREAM):
            return False
        
        return True
    
    def filter_agents_by_permissions(self, user: Dict[str, Any], agents: List[AgentInfo]) -> List[AgentInfo]:
        """
        Filter agents based on user permissions.
        
        Args:
            user: User information dictionary
            agents: List of agents to filter
            
        Returns:
            Filtered list of agents
        """
        return [agent for agent in agents if self.can_access_agent(user, agent)]
    
    def get_execution_modes_for_user(self, user: Dict[str, Any]) -> List[AgentExecutionMode]:
        """
        Get execution modes available to a user.
        
        Args:
            user: User information dictionary
            
        Returns:
            List of available execution modes
        """
        user_roles = set(user.get("roles", ["viewer"]))
        available_modes = []
        
        for mode in AgentExecutionMode:
            allowed_roles = self._execution_mode_restrictions.get(mode.value, set())
            if user_roles.intersection(allowed_roles):
                available_modes.append(mode)
        
        return available_modes
    
    def get_capabilities_for_user(self, user: Dict[str, Any]) -> List[AgentCapability]:
        """
        Get capabilities available to a user.
        
        Args:
            user: User information dictionary
            
        Returns:
            List of available capabilities
        """
        user_roles = set(user.get("roles", ["viewer"]))
        available_capabilities = []
        
        for capability in AgentCapability:
            allowed_roles = self._capability_restrictions.get(capability.value, set())
            if user_roles.intersection(allowed_roles):
                available_capabilities.append(capability)
        
        return available_capabilities
    
    def validate_agent_config(self, user: Dict[str, Any], config: Dict[str, Any]) -> List[str]:
        """
        Validate agent configuration based on user permissions.
        
        Args:
            user: User information dictionary
            config: Agent configuration
            
        Returns:
            List of validation errors
        """
        errors = []
        
        # Check execution mode
        execution_mode = config.get("execution_mode")
        if execution_mode:
            try:
                mode = AgentExecutionMode(execution_mode)
                if not self.can_execute_agent(user, mode):
                    errors.append(f"User does not have permission to use execution mode: {execution_mode}")
            except ValueError:
                errors.append(f"Invalid execution mode: {execution_mode}")
        
        # Check capabilities
        capabilities = config.get("capabilities", [])
        for cap_str in capabilities:
            try:
                capability = AgentCapability(cap_str)
                if not self.can_use_capability(user, capability):
                    errors.append(f"User does not have permission to use capability: {cap_str}")
            except ValueError:
                errors.append(f"Invalid capability: {cap_str}")
        
        return errors
    
    def check_rate_limits(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check rate limits for a user.
        
        Args:
            user: User information dictionary
            
        Returns:
            Rate limit information
        """
        # This would typically integrate with a rate limiting service
        # For now, we'll return basic role-based limits
        user_roles = user.get("roles", ["viewer"])
        
        # Define rate limits by role
        rate_limits = {
            "viewer": {"requests_per_minute": 10, "requests_per_hour": 100},
            "user": {"requests_per_minute": 30, "requests_per_hour": 500},
            "developer": {"requests_per_minute": 60, "requests_per_hour": 1000},
            "admin": {"requests_per_minute": 120, "requests_per_hour": 2000}
        }
        
        # Get the most permissive limit based on user's roles
        max_per_minute = 0
        max_per_hour = 0
        
        for role in user_roles:
            limits = rate_limits.get(role, {"requests_per_minute": 0, "requests_per_hour": 0})
            max_per_minute = max(max_per_minute, limits["requests_per_minute"])
            max_per_hour = max(max_per_hour, limits["requests_per_hour"])
        
        return {
            "requests_per_minute": max_per_minute,
            "requests_per_hour": max_per_hour,
            "current_usage": self._get_current_usage(user.get("id"))
        }
    
    def _get_current_usage(self, user_id: Optional[str]) -> Dict[str, int]:
        """
        Get current usage statistics for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            Current usage statistics
        """
        # This would typically query a metrics or usage tracking service
        # For now, we'll return placeholder values
        return {
            "requests_this_minute": 0,
            "requests_this_hour": 0
        }
    
    def audit_access(self, user: Dict[str, Any], action: str, resource: str, result: bool):
        """
        Audit access attempt.
        
        Args:
            user: User information dictionary
            action: Action attempted
            resource: Resource accessed
            result: Whether the access was successful
        """
        self.logger.info(
            f"Access audit: user={user.get('id')}, action={action}, "
            f"resource={resource}, result={result}"
        )
        
        # In a real implementation, this would log to an audit system
        # and potentially trigger alerts for suspicious activity


# Global auth manager instance
_auth_manager: Optional[AgentAuthManager] = None


def get_auth_manager() -> AgentAuthManager:
    """Get the global auth manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AgentAuthManager()
    return _auth_manager


# Decorators for authorization
def require_permission(permission: str):
    """Decorator to require a specific permission."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract user from kwargs (typically passed by FastAPI dependency)
            user = kwargs.get("current_user")
            if not user:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")
            
            auth_manager = get_auth_manager()
            if not auth_manager.has_permission(user, permission):
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_execution_mode(execution_mode: AgentExecutionMode):
    """Decorator to require access to a specific execution mode."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract user from kwargs
            user = kwargs.get("current_user")
            if not user:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")
            
            auth_manager = get_auth_manager()
            if not auth_manager.can_execute_agent(user, execution_mode):
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=403,
                    detail=f"Access to execution mode {execution_mode.value} not permitted"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_capability(capability: AgentCapability):
    """Decorator to require access to a specific capability."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract user from kwargs
            user = kwargs.get("current_user")
            if not user:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="Authentication required")
            
            auth_manager = get_auth_manager()
            if not auth_manager.can_use_capability(user, capability):
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=403,
                    detail=f"Access to capability {capability.value} not permitted"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator