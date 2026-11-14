"""
Unified Extension Service

Provides high-level extension management services that coordinate all
the unified components (registry, loader, permissions, health, lifecycle, config).
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .extension_registry import ExtensionRegistry
from .extension_loader import ExtensionLoader, LEGACY_UNIFIED_EXECUTION_DISABLED
from .extension_permissions import ExtensionPermissions
from .extension_health_monitor import ExtensionHealthMonitor
from .extension_lifecycle_manager import ExtensionLifecycleManager
from .extension_config import ExtensionConfigManager
from ...platform.core.host.loader import ExtensionContext

logger = logging.getLogger(__name__)


@dataclass
class ExtensionServiceResult:
    """Result of extension service operations."""

    success: bool
    message: str
    data: Optional[Any] = None
    errors: List[str] = None


class ExtensionService:
    """Unified extension service that coordinates all components."""

    def __init__(self):
        self.registry = ExtensionRegistry()
        self.loader = ExtensionLoader(self.registry)
        self.permissions = ExtensionPermissions(self.registry)
        self.health_monitor = ExtensionHealthMonitor(self.registry)
        self.lifecycle_manager = ExtensionLifecycleManager(self.registry)
        self.config_manager = ExtensionConfigManager(self.registry)

        # Service state
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Do not start a second plugin registry, loader or health monitor."""
        raise PermissionError(LEGACY_UNIFIED_EXECUTION_DISABLED)

    async def install_extension(
        self,
        manifest_data: Dict[str, Any],
        extension_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionServiceResult:
        """Fail before legacy installation can write database or filesystem."""
        del manifest_data, extension_path, metadata
        return ExtensionServiceResult(
            success=False, message=LEGACY_UNIFIED_EXECUTION_DISABLED
        )

    async def enable_extension(self, extension_id: str) -> ExtensionServiceResult:
        """Never activate an extension through a shadow state machine."""
        del extension_id
        return ExtensionServiceResult(
            success=False, message=LEGACY_UNIFIED_EXECUTION_DISABLED
        )

    async def disable_extension(self, extension_id: str) -> ExtensionServiceResult:
        """Never write a shadow disabled status or invoke legacy hooks."""
        del extension_id
        return ExtensionServiceResult(
            success=False, message=LEGACY_UNIFIED_EXECUTION_DISABLED
        )

    async def uninstall_extension(self, extension_id: str) -> ExtensionServiceResult:
        """Never delete plugin data through an ungoverned legacy manager."""
        del extension_id
        return ExtensionServiceResult(
            success=False, message=LEGACY_UNIFIED_EXECUTION_DISABLED
        )

    async def reload_extension(self, extension_id: str) -> ExtensionServiceResult:
        """Retain the old result shape but never import or replace code."""
        del extension_id
        return ExtensionServiceResult(
            success=False, message=LEGACY_UNIFIED_EXECUTION_DISABLED
        )

    async def get_extension_info(self, extension_id: str) -> ExtensionServiceResult:
        """Get information about an extension."""
        try:
            extension = await self.registry.get_extension(extension_id)
            if not extension:
                return ExtensionServiceResult(
                    success=False, message="Extension not found"
                )

            # Get additional info
            health_status = await self.health_monitor.get_current_health_status(
                extension_id
            )
            lifecycle_state = await self.lifecycle_manager.get_extension_state(
                extension_id
            )
            config = await self.config_manager.get_all_config(extension_id)

            info = {
                "extension": extension.to_dict(),
                "health_status": health_status.value,
                "lifecycle_state": lifecycle_state.value,
                "config": config,
                "loaded": await self.loader.is_extension_loaded(extension_id),
            }

            return ExtensionServiceResult(
                success=True, message="Extension info retrieved", data=info
            )

        except Exception as e:
            logger.error(f"Error getting extension info: {e}")
            return ExtensionServiceResult(
                success=False, message=f"Get info failed: {str(e)}"
            )

    async def list_extensions(
        self, state: Optional[str] = None, author: Optional[str] = None
    ) -> ExtensionServiceResult:
        """List all extensions."""
        try:
            from ..database_models import ExtensionState

            # Convert state string to enum
            state_enum = None
            if state:
                try:
                    state_enum = ExtensionState(state)
                except ValueError:
                    return ExtensionServiceResult(
                        success=False, message=f"Invalid state: {state}"
                    )

            extensions = await self.registry.list_extensions(state_enum, author)

            # Add additional info to each extension
            extension_list = []
            for extension in extensions:
                health_status = await self.health_monitor.get_current_health_status(
                    extension.id
                )
                lifecycle_state = await self.lifecycle_manager.get_extension_state(
                    extension.id
                )

                extension_info = {
                    "extension": extension.to_dict(),
                    "health_status": health_status.value,
                    "lifecycle_state": lifecycle_state.value,
                    "loaded": await self.loader.is_extension_loaded(extension.id),
                }
                extension_list.append(extension_info)

            return ExtensionServiceResult(
                success=True,
                message=f"Found {len(extensions)} extensions",
                data=extension_list,
            )

        except Exception as e:
            logger.error(f"Error listing extensions: {e}")
            return ExtensionServiceResult(
                success=False, message=f"List failed: {str(e)}"
            )

    async def check_extension_permission(
        self,
        extension_id: str,
        permission_type: str,
        resource: str,
        action: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtensionServiceResult:
        """Check if an extension has a specific permission."""
        try:
            from .extension_permissions import ExtensionPermissionType

            # Convert permission type string to enum
            try:
                perm_type = ExtensionPermissionType(permission_type)
            except ValueError:
                return ExtensionServiceResult(
                    success=False, message=f"Invalid permission type: {permission_type}"
                )

            # Check permission
            result = await self.permissions.check_permission(
                extension_id, perm_type, resource, action, context
            )

            return ExtensionServiceResult(
                success=True,
                message="Permission check completed",
                data={
                    "granted": result.granted,
                    "reason": result.reason,
                    "conditions": result.conditions,
                },
            )

        except Exception as e:
            logger.error(f"Error checking permission: {e}")
            return ExtensionServiceResult(
                success=False, message=f"Permission check failed: {str(e)}"
            )

    async def get_extension_health(self, extension_id: str) -> ExtensionServiceResult:
        """Get health information for an extension."""
        try:
            health_data = await self.health_monitor.check_extension_health(extension_id)

            return ExtensionServiceResult(
                success=True, message="Health data retrieved", data=health_data
            )

        except Exception as e:
            logger.error(f"Error getting extension health: {e}")
            return ExtensionServiceResult(
                success=False, message=f"Health check failed: {str(e)}"
            )

    async def get_extension_config(
        self, extension_id: str, key: str, default: Any = None
    ) -> ExtensionServiceResult:
        """Get configuration value for an extension."""
        try:
            value = await self.config_manager.get_config(extension_id, key, default)

            return ExtensionServiceResult(
                success=True, message="Config value retrieved", data={"value": value}
            )

        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return ExtensionServiceResult(
                success=False, message=f"Get config failed: {str(e)}"
            )

    async def set_extension_config(
        self, extension_id: str, key: str, value: Any,
        description: Optional[str] = None,
    ) -> ExtensionServiceResult:
        """Prevent a duplicate configuration store from writing plugin state."""
        del extension_id, key, value, description
        return ExtensionServiceResult(
            success=False, message=LEGACY_UNIFIED_EXECUTION_DISABLED
        )

    async def _setup_interconnections(self) -> None:
        """Setup interconnections between components."""
        # Connect loader to lifecycle manager
        self.loader.registry = self.registry

        # Connect permissions to health monitor
        self.health_monitor.register_alert_handler(self._handle_health_alert)

        # Connect config manager to lifecycle manager
        self.lifecycle_manager.register_event_handler(
            "state_transition", self._handle_state_change
        )

    async def _check_dependencies(self, extension_id: str) -> bool:
        """Check if extension dependencies are satisfied."""
        dependencies = await self.registry.get_extension_dependencies(extension_id)

        for dep in dependencies:
            dep_state = await self.lifecycle_manager.get_extension_state(dep.id)
            if dep_state.value != "enabled":
                return False

        return True

    async def _handle_health_alert(self, alert) -> None:
        """Handle health alerts."""
        logger.warning(f"Health alert: {alert.message}")

        # Could trigger extension state changes based on alert severity
        if alert.severity.value == "critical":
            # Could disable extension or take other action
            pass

    async def _handle_state_change(self, event) -> None:
        """Handle extension state changes."""
        logger.info(
            f"Extension state change: {event.extension_id} {event.from_state} -> {event.to_state}"
        )

        # Update health status based on state
        if event.to_state.value == "enabled":
            # Extension is enabled, check health
            await self.health_monitor.check_extension_health(event.extension_id)
        elif event.to_state.value == "disabled":
            # Extension is disabled, could stop health monitoring
            pass
