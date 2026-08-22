"""
Frontend Integration Service - Bridges plugin lifecycle with frontend plugin host.

This service ensures that the frontend plugin host respects the canonical
plugin lifecycle and category rules established by backend services.

Authorization is owned by RuntimePolicy.
Lifecycle ownership is PluginLifecycleManager / PluginLifecycleState.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from ai_karen_engine.extensions.platform.core.category_validation import (
    CategoryValidationService,
    CategoryType,
    get_category_validation_service,
)
from ai_karen_engine.extensions.platform.core.plugin_lifecycle_manager import (
    PluginLifecycleManager,
    PluginLifecycleState,
)

logger = logging.getLogger("kari.frontend_integration")


class FrontendPermission(str, Enum):
    """Frontend-specific permissions."""

    VIEW_PLUGIN = "view_plugin"
    INTERACT_WITH_PLUGIN = "interact_with_plugin"
    CONFIGURE_PLUGIN_UI = "configure_plugin_ui"
    MOUNT_PLUGIN_COMPONENT = "mount_plugin_component"
    UNMOUNT_PLUGIN_COMPONENT = "unmount_plugin_component"
    REFRESH_PLUGIN_CATALOG = "refresh_plugin_catalog"


@dataclass
class FrontendPluginRecord:
    """Frontend representation of a plugin with lifecycle information."""

    plugin_id: str
    display_name: str
    description: str
    category: str
    lifecycle_state: PluginLifecycleState
    is_visible: bool = True
    is_mountable: bool = False
    is_configurable: bool = False
    required_permissions: Set[FrontendPermission] = field(default_factory=set)
    ui_components: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FrontendValidationResult:
    """Result of frontend validation."""

    is_valid: bool
    plugin_id: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    frontend_record: Optional[FrontendPluginRecord] = None


class FrontendIntegrationService:
    """
    Service that bridges backend plugin lifecycle with frontend plugin host.

    Responsibilities:
    - Filter plugins based on lifecycle state for frontend display
    - Enforce lifecycle rules in frontend operations
    - Provide canonical plugin catalog to frontend
    - Handle frontend plugin mounting/unmounting requests
    """

    def __init__(self, lifecycle_manager: PluginLifecycleManager):
        """Initialize frontend integration service."""
        self.lifecycle_manager = lifecycle_manager
        self.category_validation = get_category_validation_service()

        # Frontend plugin registry
        self.frontend_registry: Dict[str, FrontendPluginRecord] = {}

        # User permissions mapping (would come from authentication system)
        self.user_permissions: Dict[str, Set[FrontendPermission]] = {}

        logger.info("FrontendIntegrationService initialized")

    def register_user_permissions(
        self, user_id: str, permissions: Set[FrontendPermission]
    ):
        """Register frontend permissions for a user."""
        self.user_permissions[user_id] = permissions
        logger.debug(f"Registered permissions for user {user_id}")

    async def sync_frontend_registry(self) -> Dict[str, FrontendPluginRecord]:
        """
        Synchronize frontend registry with backend plugin lifecycle.

        Returns:
            Dictionary of frontend plugin records
        """
        logger.info("Synchronizing frontend registry with backend plugin lifecycle")

        # Clear existing registry
        self.frontend_registry.clear()

        plugins = await self.lifecycle_manager.list_plugins(
            include_available=True, include_installed=True
        )

        for plugin in plugins:
            plugin_id = plugin["id"]
            state = plugin.get("state", PluginLifecycleState.AVAILABLE)
            category = plugin.get("category", "plugins")

            frontend_record = self._create_frontend_record(plugin_id, plugin, state, category)
            if frontend_record:
                self.frontend_registry[plugin_id] = frontend_record

        logger.info(
            f"Synchronized {len(self.frontend_registry)} plugins to frontend registry"
        )
        return self.frontend_registry

    def _create_frontend_record(
        self,
        plugin_id: str,
        plugin: Dict[str, Any],
        state: PluginLifecycleState,
        category: str,
    ) -> Optional[FrontendPluginRecord]:
        """Create a frontend plugin record from lifecycle state."""
        try:
            category_info = self.category_validation.get_category_info(category)
            if not category_info:
                logger.warning(f"No category info for plugin: {plugin_id}")
                return None

            is_visible = self._is_frontend_visible(state)
            is_mountable = state in {
                PluginLifecycleState.ENABLED,
                PluginLifecycleState.DISABLED,
                PluginLifecycleState.INSTALLED,
            }
            is_configurable = state in {
                PluginLifecycleState.ENABLED,
                PluginLifecycleState.DISABLED,
            }

            required_permissions = self._calculate_required_permissions(state, category)

            return FrontendPluginRecord(
                plugin_id=plugin_id,
                display_name=plugin.get("display_name", plugin_id),
                description=plugin.get("description", ""),
                category=category_info["name"],
                lifecycle_state=state,
                is_visible=is_visible,
                is_mountable=is_mountable,
                is_configurable=is_configurable,
                required_permissions=required_permissions,
                ui_components=self._get_ui_components(plugin_id),
                last_updated=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(
                f"Failed to create frontend record for {plugin_id}: {str(e)}"
            )
            return None

    def _is_frontend_visible(self, state: PluginLifecycleState) -> bool:
        """Determine if a plugin should be visible in frontend based on lifecycle state."""
        return state in {
            PluginLifecycleState.AVAILABLE,
            PluginLifecycleState.INSTALLED,
            PluginLifecycleState.ENABLED,
            PluginLifecycleState.DISABLED,
        }

    def _calculate_required_permissions(
        self,
        lifecycle_state: PluginLifecycleState,
        category: str,
    ) -> Set[FrontendPermission]:
        """Calculate required frontend permissions for a plugin."""
        permissions = set()

        if lifecycle_state in {
            PluginLifecycleState.AVAILABLE,
            PluginLifecycleState.INSTALLED,
            PluginLifecycleState.ENABLED,
            PluginLifecycleState.DISABLED,
        }:
            permissions.add(FrontendPermission.VIEW_PLUGIN)

        if lifecycle_state in {
            PluginLifecycleState.ENABLED,
            PluginLifecycleState.DISABLED,
            PluginLifecycleState.INSTALLED,
        }:
            permissions.add(FrontendPermission.MOUNT_PLUGIN_COMPONENT)

        if lifecycle_state in {
            PluginLifecycleState.ENABLED,
            PluginLifecycleState.DISABLED,
        }:
            permissions.add(FrontendPermission.CONFIGURE_PLUGIN_UI)

        if category == CategoryType.PLUGINS.value:
            permissions.add(FrontendPermission.INTERACT_WITH_PLUGIN)

        return permissions

    def _get_ui_components(self, plugin_name: str) -> List[str]:
        """Get UI components for a plugin (placeholder implementation)."""
        return ["main_component", "settings_component"]

    def get_frontend_catalog(
        self, user_id: str, include_hidden: bool = False
    ) -> Dict[str, FrontendPluginRecord]:
        """
        Get frontend plugin catalog filtered by user permissions.

        Args:
            user_id: User ID to filter permissions for
            include_hidden: Whether to include plugins not normally visible

        Returns:
            Filtered catalog of plugins the user can access
        """
        user_permissions = self.user_permissions.get(user_id, set())
        catalog = {}

        for plugin_id, record in self.frontend_registry.items():
            if not record.is_visible and not include_hidden:
                continue

            if not user_permissions.issuperset(record.required_permissions):
                continue

            catalog[plugin_id] = record

        logger.debug(
            f"Frontend catalog generated for user {user_id}: {len(catalog)} plugins"
        )
        return catalog

    def validate_frontend_request(
        self,
        user_id: str,
        plugin_id: str,
        requested_action: str,
        action_params: Optional[Dict[str, Any]] = None,
    ) -> FrontendValidationResult:
        """
        Validate a frontend request against lifecycle rules.

        Authorization is owned by RuntimePolicy. This method validates
        frontend-specific constraints only.
        """
        result = FrontendValidationResult(is_valid=True, plugin_id=plugin_id)

        try:
            plugin_record = self.frontend_registry.get(plugin_id)
            if not plugin_record:
                result.is_valid = False
                result.errors.append(f"Plugin not found: {plugin_id}")
                return result

            user_permissions = self.user_permissions.get(user_id, set())

            required_permission = self._map_action_to_permission(requested_action)
            if required_permission and required_permission not in user_permissions:
                result.is_valid = False
                result.errors.append(
                    f"User {user_id} lacks permission: {required_permission.value}"
                )
                return result

            lifecycle_error = self._validate_lifecycle_action(
                plugin_record.lifecycle_state, requested_action
            )
            if lifecycle_error:
                result.is_valid = False
                result.errors.append(lifecycle_error)
                return result

            category_error = self._validate_category_action(
                plugin_record.category, requested_action, action_params
            )
            if category_error:
                result.is_valid = False
                result.errors.append(category_error)
                return result

            result.frontend_record = plugin_record

        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Unexpected error: {str(e)}")

        return result

    def _map_action_to_permission(self, action: str) -> Optional[FrontendPermission]:
        """Map a requested action to frontend permission."""
        action_mapping = {
            "view": FrontendPermission.VIEW_PLUGIN,
            "interact": FrontendPermission.INTERACT_WITH_PLUGIN,
            "configure": FrontendPermission.CONFIGURE_PLUGIN_UI,
            "mount": FrontendPermission.MOUNT_PLUGIN_COMPONENT,
            "unmount": FrontendPermission.UNMOUNT_PLUGIN_COMPONENT,
            "refresh": FrontendPermission.REFRESH_PLUGIN_CATALOG,
        }
        return action_mapping.get(action)

    def _validate_lifecycle_action(
        self, lifecycle_state: PluginLifecycleState, requested_action: str
    ) -> Optional[str]:
        """Validate that an action is compatible with the current lifecycle state."""

        if requested_action in ["mount", "interact", "configure"]:
            if lifecycle_state in {
                PluginLifecycleState.AVAILABLE,
                PluginLifecycleState.INSTALLING,
                PluginLifecycleState.UNINSTALLING,
                PluginLifecycleState.UNINSTALLED,
                PluginLifecycleState.ERROR,
            }:
                return (
                    f"Cannot {requested_action} plugin in {lifecycle_state.value} state"
                )

        if requested_action == "unmount":
            if lifecycle_state not in {
                PluginLifecycleState.ENABLED,
                PluginLifecycleState.DISABLED,
                PluginLifecycleState.INSTALLED,
            }:
                return f"Cannot unmount plugin in {lifecycle_state.value} state"

        return None

    def _validate_category_action(
        self,
        category: str,
        requested_action: str,
        action_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Validate category-specific action rules."""

        if category == CategoryType.SYS_EXTENSIONS.value:
            if requested_action in ["configure", "unmount"]:
                return f"Cannot {requested_action} system extensions"

        if category == CategoryType.CHANNELS.value:
            if requested_action == "configure" and action_params:
                if "protocol" not in action_params:
                    return "Channel configuration requires protocol specification"

        return None

    async def request_plugin_mount(
        self,
        user_id: str,
        plugin_id: str,
        component_id: str,
        mount_params: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, List[str]]:
        """
        Request to mount a plugin component.

        Returns:
            Tuple of (success, error_messages)
        """
        errors = []

        validation_result = self.validate_frontend_request(
            user_id,
            plugin_id,
            "mount",
            {"component_id": component_id, **(mount_params or {})},
        )

        if not validation_result.is_valid:
            return False, validation_result.errors

        plugin_record = validation_result.frontend_record
        if plugin_record.lifecycle_state == PluginLifecycleState.ENABLED:
            errors.append(f"Plugin {plugin_id} is already mounted and enabled")

        if plugin_record.lifecycle_state == PluginLifecycleState.INSTALLED:
            try:
                await self.lifecycle_manager.enable_plugin(plugin_id)
                return True, errors
            except Exception as e:
                errors.append(f"Failed to mount plugin: {str(e)}")
        elif plugin_record.lifecycle_state == PluginLifecycleState.DISABLED:
            try:
                await self.lifecycle_manager.enable_plugin(plugin_id)
                return True, errors
            except Exception as e:
                errors.append(f"Failed to mount plugin: {str(e)}")
        else:
            errors.append(
                f"Plugin {plugin_id} cannot be mounted from {plugin_record.lifecycle_state.value} state"
            )

        return False, errors

    async def request_plugin_unmount(
        self, user_id: str, plugin_id: str, component_id: str
    ) -> tuple[bool, List[str]]:
        """
        Request to unmount a plugin component.

        Returns:
            Tuple of (success, error_messages)
        """
        errors = []

        validation_result = self.validate_frontend_request(
            user_id, plugin_id, "unmount", {"component_id": component_id}
        )

        if not validation_result.is_valid:
            return False, validation_result.errors

        plugin_record = validation_result.frontend_record
        if plugin_record.lifecycle_state not in {
            PluginLifecycleState.ENABLED,
            PluginLifecycleState.DISABLED,
            PluginLifecycleState.INSTALLED,
        }:
            errors.append(
                f"Plugin {plugin_id} is not mounted (current state: {plugin_record.lifecycle_state.value})"
            )

        if plugin_record.lifecycle_state == PluginLifecycleState.ENABLED:
            try:
                await self.lifecycle_manager.disable_plugin(plugin_id)
                return True, errors
            except Exception as e:
                errors.append(f"Failed to unmount plugin: {str(e)}")
        elif plugin_record.lifecycle_state == PluginLifecycleState.DISABLED:
            try:
                await self.lifecycle_manager.uninstall_plugin(plugin_id)
                return True, errors
            except Exception as e:
                errors.append(f"Failed to unmount plugin: {str(e)}")
        else:
            errors.append(
                f"Plugin {plugin_id} cannot be unmounted from {plugin_record.lifecycle_state.value} state"
            )

        return False, errors

    def get_authority_boundary_status(self, user_id: str) -> Dict[str, Any]:
        """
        Get lifecycle boundary status for a user.

        This is descriptive UI metadata only. Runtime authorization is owned
        by RuntimePolicy.
        """
        user_permissions = self.user_permissions.get(user_id, set())

        category_counts = {}
        state_counts = {}

        for record in self.frontend_registry.values():
            if record.is_visible:
                category = record.category
                category_counts[category] = category_counts.get(category, 0) + 1

                state = record.lifecycle_state.value
                state_counts[state] = state_counts.get(state, 0) + 1

        return {
            "user_id": user_id,
            "user_permissions": [p.value for p in user_permissions],
            "total_visible_plugins": len(
                [r for r in self.frontend_registry.values() if r.is_visible]
            ),
            "category_distribution": category_counts,
            "state_distribution": state_counts,
            "boundary_health": "healthy"
            if len(user_permissions) > 0
            else "no_permissions",
        }


# Global singleton instance
_frontend_integration_service: Optional[FrontendIntegrationService] = None


def get_frontend_integration_service(
    lifecycle_manager: PluginLifecycleManager,
) -> FrontendIntegrationService:
    """Get the global frontend integration service instance."""
    global _frontend_integration_service
    if _frontend_integration_service is None:
        _frontend_integration_service = FrontendIntegrationService(
            lifecycle_manager
        )
    return _frontend_integration_service


__all__ = [
    "FrontendIntegrationService",
    "FrontendPermission",
    "FrontendPluginRecord",
    "FrontendValidationResult",
    "get_frontend_integration_service",
]
