"""
Plugin Lifecycle Manager - Production-ready plugin management system.

Handles complete plugin lifecycle including:
- Installation from various sources (local, remote, marketplace)
- Uninstallation with proper cleanup
- Enable/disable operations
- UI component registration/deregistration
- Dependency management
- Version control and rollback
- Backup and restore functionality
"""

import asyncio
import logging
import shutil
import tempfile
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, func

from ai_karen_engine.extensions.platform.core.registry.plugin_registry import PluginRegistry
from ai_karen_engine.extensions.platform.core.registry.database_models import (
    ExtensionDBModel,
    ExtensionInstallationHistory,
)

logger = logging.getLogger("kari.plugin_lifecycle")


class PluginLifecycleState(Enum):
    """Plugin lifecycle states."""

    AVAILABLE = "available"  # Plugin available for installation
    INSTALLING = "installing"  # Installation in progress
    INSTALLED = "installed"  # Successfully installed
    ENABLING = "enabling"  # Enable operation in progress
    ENABLED = "enabled"  # Plugin is active and enabled
    DISABLING = "disabling"  # Disable operation in progress
    DISABLED = "disabled"  # Plugin disabled but installed
    UNINSTALLING = "uninstalling"  # Uninstallation in progress
    UNINSTALLED = "uninstalled"  # Plugin removed
    ERROR = "error"  # Error state
    ROLLING_BACK = "rolling_back"  # Rollback in progress


LIFECYCLE_TRANSITIONS = {
    PluginLifecycleState.AVAILABLE: {PluginLifecycleState.INSTALLING},
    PluginLifecycleState.INSTALLING: {PluginLifecycleState.INSTALLED, PluginLifecycleState.ERROR},
    PluginLifecycleState.INSTALLED: {PluginLifecycleState.ENABLING, PluginLifecycleState.UNINSTALLING},
    PluginLifecycleState.ENABLING: {PluginLifecycleState.ENABLED, PluginLifecycleState.ERROR},
    PluginLifecycleState.ENABLED: {PluginLifecycleState.DISABLING},
    PluginLifecycleState.DISABLING: {PluginLifecycleState.DISABLED, PluginLifecycleState.ERROR},
    PluginLifecycleState.DISABLED: {PluginLifecycleState.ENABLING, PluginLifecycleState.UNINSTALLING},
    PluginLifecycleState.UNINSTALLING: {PluginLifecycleState.UNINSTALLED, PluginLifecycleState.ERROR},
    PluginLifecycleState.UNINSTALLED: {PluginLifecycleState.AVAILABLE},
    PluginLifecycleState.ERROR: {PluginLifecycleState.AVAILABLE, PluginLifecycleState.INSTALLING},
    PluginLifecycleState.ROLLING_BACK: {PluginLifecycleState.INSTALLED, PluginLifecycleState.ERROR},
}


class PluginOperation(Enum):
    """Plugin operations."""

    INSTALL = "install"
    UNINSTALL = "uninstall"
    ENABLE = "enable"
    DISABLE = "disable"
    UPDATE = "update"
    ROLLBACK = "rollback"
    BACKUP = "backup"
    RESTORE = "restore"


@dataclass
class PluginOperationResult:
    """Result of a plugin operation."""

    success: bool
    plugin_id: str
    operation: PluginOperation
    new_state: PluginLifecycleState
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    duration_ms: int


@dataclass
class PluginBackup:
    """Plugin backup information."""

    plugin_id: str
    version: str
    backup_path: Path
    created_at: datetime
    checksum: str
    size_bytes: int


class PluginLifecycleManager:
    """
    Production-ready plugin lifecycle manager.

    Handles complete plugin lifecycle with proper error handling,
    rollback capabilities, and comprehensive state management.
    """

    def __init__(
        self,
        registry: PluginRegistry,
        db_session: AsyncSession,
        plugins_dir: Path = Path("src/ai_karen_engine/extensions/plugins"),
        backups_dir: Path = Path("data/plugin_backups"),
        ui_materialization_dir: Path = Path(
            "src/ui_launchers/Karen-AI-Theme/src/plugin_repo"
        ),
    ):
        self.registry = registry
        self.db_session = db_session
        self.plugins_dir = plugins_dir
        self.backups_dir = backups_dir
        self.ui_materialization_dir = ui_materialization_dir

        # Ensure directories exist
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self.ui_materialization_dir.mkdir(parents=True, exist_ok=True)

        # Operation tracking
        self._active_operations: Dict[str, PluginOperationResult] = {}
        self._operation_lock = asyncio.Lock()

    async def install_plugin(
        self,
        plugin_id: str,
        source_url: Optional[str] = None,
        version: Optional[str] = None,
        force: bool = False,
    ) -> PluginOperationResult:
        """
        Install a plugin from source.

        Args:
            plugin_id: Plugin identifier
            source_url: URL to download plugin from (None for local installation)
            version: Specific version to install
            force: Force installation even if plugin exists

        Returns:
            Operation result
        """
        start_time = datetime.now()

        async with self._operation_lock:
            # Check if plugin is already installed
            if not force:
                existing = await self._get_plugin_state(plugin_id)
                if existing and existing in [
                    PluginLifecycleState.INSTALLED,
                    PluginLifecycleState.ENABLED,
                ]:
                    return PluginOperationResult(
                        success=False,
                        plugin_id=plugin_id,
                        operation=PluginOperation.INSTALL,
                        new_state=existing,
                        message=f"Plugin {plugin_id} is already installed",
                        details={"existing_state": existing.value},
                        timestamp=start_time,
                        duration_ms=int(
                            (datetime.now() - start_time).total_seconds() * 1000
                        ),
                    )

            try:
                # Set installing state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.INSTALLING)

                # Create backup if plugin exists
                backup_path = None
                if await self._plugin_directory_exists(plugin_id):
                    backup_path = await self._create_backup(plugin_id)

                # Download/install plugin
                if source_url:
                    plugin_path = await self._download_plugin(
                        plugin_id, source_url, version
                    )
                else:
                    plugin_path = await self._install_local_plugin(plugin_id, version)

                # Validate plugin
                manifest = await self._validate_plugin(plugin_path)

                # Check dependencies
                await self._check_dependencies(manifest)

                # Register plugin in database
                await self._register_plugin_installation(
                    plugin_id, manifest, plugin_path
                )

                # Materialize UI components if needed
                if manifest.get("capabilities", {}).get("provides_ui"):
                    await self._materialize_ui_components(plugin_id, manifest)

                # Set installed state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.INSTALLED)

                # Log installation
                await self._log_operation(
                    plugin_id,
                    PluginOperation.INSTALL,
                    True,
                    f"Plugin {plugin_id} installed successfully",
                    {
                        "version": manifest.get("version"),
                        "backup_path": str(backup_path) if backup_path else None,
                    },
                )

                return PluginOperationResult(
                    success=True,
                    plugin_id=plugin_id,
                    operation=PluginOperation.INSTALL,
                    new_state=PluginLifecycleState.INSTALLED,
                    message=f"Plugin {plugin_id} installed successfully",
                    details={
                        "version": manifest.get("version"),
                        "path": str(plugin_path),
                        "backup_created": backup_path is not None,
                    },
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            except Exception as e:
                logger.error(
                    f"Failed to install plugin {plugin_id}: {e}", exc_info=True
                )

                # Attempt rollback
                try:
                    await self._rollback_installation(plugin_id, backup_path)
                except Exception as rollback_error:
                    logger.error(
                        f"Failed to rollback installation of {plugin_id}: {rollback_error}"
                    )

                # Set error state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.ERROR)

                # Log failure
                await self._log_operation(
                    plugin_id,
                    PluginOperation.INSTALL,
                    False,
                    f"Plugin {plugin_id} installation failed: {str(e)}",
                    {
                        "error": str(e),
                        "backup_path": str(backup_path) if backup_path else None,
                    },
                )

                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.INSTALL,
                    new_state=PluginLifecycleState.ERROR,
                    message=f"Installation failed: {str(e)}",
                    details={"error": str(e)},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

    async def uninstall_plugin(
        self, plugin_id: str, keep_backup: bool = True
    ) -> PluginOperationResult:
        """
        Uninstall a plugin completely.

        Args:
            plugin_id: Plugin identifier
            keep_backup: Whether to keep backup after uninstallation

        Returns:
            Operation result
        """
        start_time = datetime.now()

        async with self._operation_lock:
            # Check current state
            current_state = await self._get_plugin_state(plugin_id)
            if current_state in [
                PluginLifecycleState.UNINSTALLED,
                PluginLifecycleState.AVAILABLE,
            ]:
                # Treat uninstall as idempotent cleanup for stale records so the
                # UI can remove dead plugins even when their files are already gone.
                self.registry.unload_extension(plugin_id)
                await self._remove_ui_components(plugin_id)

                try:
                    await self._unregister_plugin_installation(plugin_id)
                except Exception as db_error:
                    logger.warning(
                        "Failed to delete database record for %s during cleanup: %s",
                        plugin_id,
                        db_error,
                    )

                self._set_lifecycle_state(plugin_id, "uninstalled")

                return PluginOperationResult(
                    success=True,
                    plugin_id=plugin_id,
                    operation=PluginOperation.UNINSTALL,
                    new_state=PluginLifecycleState.UNINSTALLED,
                    message=(
                        f"Plugin {plugin_id} was already absent; stale records were cleaned up"
                    ),
                    details={"backup_created": False},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            # Disable first if enabled
            if current_state == PluginLifecycleState.ENABLED:
                disable_result = await self.disable_plugin(plugin_id)
                if not disable_result.success:
                    return PluginOperationResult(
                        success=False,
                        plugin_id=plugin_id,
                        operation=PluginOperation.UNINSTALL,
                        new_state=current_state,
                        message=f"Failed to disable plugin before uninstall: {disable_result.message}",
                        details={"disable_error": disable_result.message},
                        timestamp=start_time,
                        duration_ms=int(
                            (datetime.now() - start_time).total_seconds() * 1000
                        ),
                    )

            try:
                # Set uninstalling state
                await self._set_plugin_state(
                    plugin_id, PluginLifecycleState.UNINSTALLING
                )

                # Create backup if requested
                backup_path = None
                if keep_backup:
                    backup_path = await self._create_backup(plugin_id)

                # Remove UI components
                await self._remove_ui_components(plugin_id)

                # Unload from registry
                self.registry.unload_extension(plugin_id)

                # Remove plugin directory
                plugin_path = self.plugins_dir / plugin_id
                if plugin_path.exists():
                    shutil.rmtree(plugin_path)

                # Remove from database
                await self._unregister_plugin_installation(plugin_id)

                # Set uninstalled state
                await self._set_plugin_state(
                    plugin_id, PluginLifecycleState.UNINSTALLED
                )

                # Clean up backup if not keeping
                if not keep_backup and backup_path:
                    shutil.rmtree(backup_path)

                # Log uninstallation
                await self._log_operation(
                    plugin_id,
                    PluginOperation.UNINSTALL,
                    True,
                    f"Plugin {plugin_id} uninstalled successfully",
                    {"backup_path": str(backup_path) if backup_path else None},
                )

                return PluginOperationResult(
                    success=True,
                    plugin_id=plugin_id,
                    operation=PluginOperation.UNINSTALL,
                    new_state=PluginLifecycleState.UNINSTALLED,
                    message=f"Plugin {plugin_id} uninstalled successfully",
                    details={"backup_created": backup_path is not None},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            except Exception as e:
                logger.error(
                    f"Failed to uninstall plugin {plugin_id}: {e}", exc_info=True
                )

                # Set error state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.ERROR)

                # Log failure
                await self._log_operation(
                    plugin_id,
                    PluginOperation.UNINSTALL,
                    False,
                    f"Plugin {plugin_id} uninstallation failed: {str(e)}",
                    {"error": str(e)},
                )

                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.UNINSTALL,
                    new_state=PluginLifecycleState.ERROR,
                    message=f"Uninstallation failed: {str(e)}",
                    details={"error": str(e)},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

    async def enable_plugin(self, plugin_id: str) -> PluginOperationResult:
        """
        Enable a plugin (make it active).

        Args:
            plugin_id: Plugin identifier

        Returns:
            Operation result
        """
        start_time = datetime.now()

        async with self._operation_lock:
            # Check current state
            current_state = await self._get_plugin_state(plugin_id)
            if current_state == PluginLifecycleState.ENABLED:
                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.ENABLE,
                    new_state=current_state,
                    message=f"Plugin {plugin_id} is already enabled",
                    details={},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            if current_state != PluginLifecycleState.INSTALLED:
                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.ENABLE,
                    new_state=current_state,
                    message=f"Plugin {plugin_id} must be installed before enabling",
                    details={"current_state": current_state.value},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            try:
                # Set enabling state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.ENABLING)

                # Load plugin into registry
                record = await self.registry.load_extension(plugin_id)

                # Register UI components
                await self._register_ui_components(plugin_id)

                # Set enabled state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.ENABLED)

                # Update database
                await self._update_plugin_enabled_status(plugin_id, True)

                # Log operation
                await self._log_operation(
                    plugin_id,
                    PluginOperation.ENABLE,
                    True,
                    f"Plugin {plugin_id} enabled successfully",
                    {"record_status": record.status.value if record else "unknown"},
                )

                return PluginOperationResult(
                    success=True,
                    plugin_id=plugin_id,
                    operation=PluginOperation.ENABLE,
                    new_state=PluginLifecycleState.ENABLED,
                    message=f"Plugin {plugin_id} enabled successfully",
                    details={},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            except Exception as e:
                logger.error(f"Failed to enable plugin {plugin_id}: {e}", exc_info=True)

                # Set error state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.ERROR)

                # Log failure
                await self._log_operation(
                    plugin_id,
                    PluginOperation.ENABLE,
                    False,
                    f"Plugin {plugin_id} enable failed: {str(e)}",
                    {"error": str(e)},
                )

                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.ENABLE,
                    new_state=PluginLifecycleState.ERROR,
                    message=f"Enable failed: {str(e)}",
                    details={"error": str(e)},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

    async def disable_plugin(self, plugin_id: str) -> PluginOperationResult:
        """
        Disable a plugin (make it inactive).

        Args:
            plugin_id: Plugin identifier

        Returns:
            Operation result
        """
        start_time = datetime.now()

        async with self._operation_lock:
            # Check current state
            current_state = await self._get_plugin_state(plugin_id)
            if current_state == PluginLifecycleState.DISABLED:
                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.DISABLE,
                    new_state=current_state,
                    message=f"Plugin {plugin_id} is already disabled",
                    details={},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            if current_state != PluginLifecycleState.ENABLED:
                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.DISABLE,
                    new_state=current_state,
                    message=f"Plugin {plugin_id} is not enabled",
                    details={"current_state": current_state.value},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            try:
                # Set disabling state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.DISABLING)

                # Unregister UI components
                await self._unregister_ui_components(plugin_id)

                # Unload from registry
                await self.registry.unload_extension(plugin_id)

                # Set disabled state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.DISABLED)

                # Update database
                await self._update_plugin_enabled_status(plugin_id, False)

                # Log operation
                await self._log_operation(
                    plugin_id,
                    PluginOperation.DISABLE,
                    True,
                    f"Plugin {plugin_id} disabled successfully",
                    {},
                )

                return PluginOperationResult(
                    success=True,
                    plugin_id=plugin_id,
                    operation=PluginOperation.DISABLE,
                    new_state=PluginLifecycleState.DISABLED,
                    message=f"Plugin {plugin_id} disabled successfully",
                    details={},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

            except Exception as e:
                logger.error(
                    f"Failed to disable plugin {plugin_id}: {e}", exc_info=True
                )

                # Set error state
                await self._set_plugin_state(plugin_id, PluginLifecycleState.ERROR)

                # Log failure
                await self._log_operation(
                    plugin_id,
                    PluginOperation.DISABLE,
                    False,
                    f"Plugin {plugin_id} disable failed: {str(e)}",
                    {"error": str(e)},
                )

                return PluginOperationResult(
                    success=False,
                    plugin_id=plugin_id,
                    operation=PluginOperation.DISABLE,
                    new_state=PluginLifecycleState.ERROR,
                    message=f"Disable failed: {str(e)}",
                    details={"error": str(e)},
                    timestamp=start_time,
                    duration_ms=int(
                        (datetime.now() - start_time).total_seconds() * 1000
                    ),
                )

    async def get_plugin_state(self, plugin_id: str) -> PluginLifecycleState:
        """Get current lifecycle state of a plugin."""
        return await self._get_plugin_state(plugin_id)

    def validate_transition(
        self, plugin_id: str, from_state: PluginLifecycleState, to_state: PluginLifecycleState
    ) -> bool:
        """Validate that a lifecycle transition is allowed."""
        valid_transitions = LIFECYCLE_TRANSITIONS.get(from_state, set())
        if to_state not in valid_transitions:
            raise ValueError(
                f"Invalid transition for {plugin_id}: {from_state.value} -> {to_state.value}. "
                f"Valid transitions: {sorted(s.value for s in valid_transitions)}"
            )
        return True

    async def list_plugins(
        self, include_available: bool = True, include_installed: bool = True
    ) -> List[Dict[str, Any]]:
        """
        List plugins with their states.

        Args:
            include_available: Include available (not installed) plugins
            include_installed: Include installed plugins

        Returns:
            List of plugin information
        """
        plugins = []

        # Get installed plugins from database
        if include_installed:
            stmt = select(ExtensionDBModel)
            result = await self.db_session.execute(stmt)
            installed_plugins = result.scalars().all()

            for plugin in installed_plugins:
                plugins.append(
                    {
                        "id": plugin.name,
                        "name": plugin.name,
                        "display_name": plugin.display_name,
                        "description": plugin.description,
                        "version": plugin.version,
                        "state": PluginLifecycleState(plugin.lifecycle_state),
                        "installed_at": plugin.installed_at,
                        "enabled": plugin.enabled,
                        "category": plugin.category,
                        "capabilities": plugin.capabilities or {},
                    }
                )

        # Get available plugins from registry discovery
        if include_available:
            try:
                discovered = await self.registry.discovery.discover_all()
                for metadata in discovered:
                    # Skip if already in installed list
                    if any(p["id"] == metadata.name for p in plugins):
                        continue

                    plugins.append(
                        {
                            "id": metadata.name,
                            "name": metadata.name,
                            "display_name": metadata.display_name,
                            "description": metadata.description,
                            "version": metadata.version,
                            "state": PluginLifecycleState.AVAILABLE,
                            "installed_at": None,
                            "enabled": False,
                            "category": metadata.category,
                            "capabilities": metadata.capabilities or {},
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to discover available plugins: {e}")

        return plugins

    async def create_backup(self, plugin_id: str) -> Optional[PluginBackup]:
        """Create a backup of an installed plugin."""
        return await self._create_backup(plugin_id)

    async def restore_backup(
        self, plugin_id: str, backup_path: Path
    ) -> PluginOperationResult:
        """Restore a plugin from backup."""
        start_time = datetime.now()

        try:
            # Validate backup
            if not backup_path.exists():
                raise ValueError(f"Backup path does not exist: {backup_path}")

            # Load backup manifest
            manifest_path = backup_path / "manifest.json"
            if not manifest_path.exists():
                raise ValueError(f"Backup manifest not found: {manifest_path}")

            with open(manifest_path, "r") as f:
                manifest = json.load(f)

            # Verify plugin ID matches
            if manifest.get("id") != plugin_id:
                raise ValueError(
                    f"Backup plugin ID mismatch: expected {plugin_id}, got {manifest.get('id')}"
                )

            # Set restoring state
            await self._set_plugin_state(plugin_id, PluginLifecycleState.ROLLING_BACK)

            # Restore plugin directory
            plugin_path = self.plugins_dir / plugin_id
            if plugin_path.exists():
                shutil.rmtree(plugin_path)

            # Copy backup to plugin directory
            shutil.copytree(backup_path, plugin_path)

            # Re-register in database
            await self._register_plugin_installation(plugin_id, manifest, plugin_path)

            # Restore UI components
            if manifest.get("capabilities", {}).get("provides_ui"):
                await self._materialize_ui_components(plugin_id, manifest)

            # Set appropriate state
            final_state = PluginLifecycleState.INSTALLED
            await self._set_plugin_state(plugin_id, final_state)

            # Log operation
            await self._log_operation(
                plugin_id,
                PluginOperation.RESTORE,
                True,
                f"Plugin {plugin_id} restored from backup",
                {"backup_path": str(backup_path), "version": manifest.get("version")},
            )

            return PluginOperationResult(
                success=True,
                plugin_id=plugin_id,
                operation=PluginOperation.RESTORE,
                new_state=final_state,
                message=f"Plugin {plugin_id} restored successfully",
                details={
                    "backup_path": str(backup_path),
                    "version": manifest.get("version"),
                },
                timestamp=start_time,
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
            )

        except Exception as e:
            logger.error(f"Failed to restore plugin {plugin_id}: {e}", exc_info=True)

            await self._set_plugin_state(plugin_id, PluginLifecycleState.ERROR)

            await self._log_operation(
                plugin_id,
                PluginOperation.RESTORE,
                False,
                f"Plugin {plugin_id} restore failed: {str(e)}",
                {"error": str(e), "backup_path": str(backup_path)},
            )

            return PluginOperationResult(
                success=False,
                plugin_id=plugin_id,
                operation=PluginOperation.RESTORE,
                new_state=PluginLifecycleState.ERROR,
                message=f"Restore failed: {str(e)}",
                details={"error": str(e), "backup_path": str(backup_path)},
                timestamp=start_time,
                duration_ms=int((datetime.now() - start_time).total_seconds() * 1000),
            )

    # Private helper methods

    async def _get_plugin_state(self, plugin_id: str) -> PluginLifecycleState:
        """Get current lifecycle state from database."""
        stmt = select(ExtensionDBModel.lifecycle_state).where(
            ExtensionDBModel.name == plugin_id
        )
        result = await self.db_session.execute(stmt)
        state_str = result.scalar_one_or_none()

        if state_str:
            try:
                return PluginLifecycleState(state_str)
            except ValueError:
                logger.warning(f"Invalid lifecycle state for {plugin_id}: {state_str}")
                return PluginLifecycleState.ERROR
        else:
            # Check if plugin directory exists (legacy detection)
            if await self._plugin_directory_exists(plugin_id):
                return PluginLifecycleState.INSTALLED
            else:
                return PluginLifecycleState.AVAILABLE

    async def _set_plugin_state(
        self, plugin_id: str, state: PluginLifecycleState
    ) -> None:
        """Set plugin lifecycle state in database."""
        stmt = (
            update(ExtensionDBModel)
            .where(ExtensionDBModel.name == plugin_id)
            .values(lifecycle_state=state.value, updated_at=datetime.now())
        )
        await self.db_session.execute(stmt)
        await self.db_session.commit()

    async def _plugin_directory_exists(self, plugin_id: str) -> bool:
        """Check if plugin directory exists."""
        plugin_path = self.plugins_dir / plugin_id
        manifest_path = plugin_path / "manifest.json"
        return plugin_path.exists() and manifest_path.exists()

    async def _download_plugin(
        self, plugin_id: str, source_url: str, version: Optional[str] = None
    ) -> Path:
        """Download plugin from remote source."""
        # Implementation for downloading from URL
        # This would handle marketplace downloads, git clones, etc.
        raise NotImplementedError("Remote plugin installation not yet implemented")

    async def _install_local_plugin(
        self, plugin_id: str, version: Optional[str] = None
    ) -> Path:
        """Install plugin from local discovery."""
        # For now, assume plugin is already in the plugins directory
        plugin_path = self.plugins_dir / plugin_id
        if not plugin_path.exists():
            raise ValueError(f"Plugin {plugin_id} not found in local plugins directory")

        return plugin_path

    async def _validate_plugin(self, plugin_path: Path) -> Dict[str, Any]:
        """Validate plugin structure and manifest."""
        manifest_path = plugin_path / "manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"Plugin manifest not found: {manifest_path}")

        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        # Basic validation
        required_fields = ["id", "version", "display_name"]
        for field in required_fields:
            if field not in manifest:
                raise ValueError(f"Missing required field in manifest: {field}")

        if manifest["id"] != plugin_path.name:
            raise ValueError(
                f"Plugin ID mismatch: manifest says {manifest['id']}, directory is {plugin_path.name}"
            )

        return manifest

    async def _check_dependencies(self, manifest: Dict[str, Any]) -> None:
        """Check plugin dependencies."""
        dependencies = manifest.get("dependencies", [])
        if not dependencies:
            return

        # Check each dependency
        for dep in dependencies:
            dep_name = dep.get("name")
            if not dep_name:
                continue

            # Check if dependency is installed
            stmt = select(ExtensionDBModel).where(
                and_(
                    ExtensionDBModel.name == dep_name,
                    ExtensionDBModel.lifecycle_state.in_(
                        [
                            PluginLifecycleState.INSTALLED.value,
                            PluginLifecycleState.ENABLED.value,
                        ]
                    ),
                )
            )
            result = await self.db_session.execute(stmt)
            installed_dep = result.scalar_one_or_none()

            if not installed_dep:
                raise ValueError(f"Missing dependency: {dep_name}")

    async def _register_plugin_installation(
        self, plugin_id: str, manifest: Dict[str, Any], plugin_path: Path
    ) -> None:
        """Register plugin installation in database."""
        # Check if already exists
        stmt = select(ExtensionDBModel).where(ExtensionDBModel.name == plugin_id)
        result = await self.db_session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            existing.version = manifest.get("version")
            existing.display_name = manifest.get("display_name")
            existing.description = manifest.get("description")
            existing.lifecycle_state = PluginLifecycleState.INSTALLED.value
            existing.installed_at = datetime.now()
            existing.enabled = False
            existing.capabilities = manifest.get("capabilities", {})
            existing.category = manifest.get("category", "plugins")
            existing.updated_at = datetime.now()
        else:
            # Create new
            plugin_record = ExtensionDBModel(
                name=plugin_id,
                version=manifest.get("version"),
                display_name=manifest.get("display_name"),
                description=manifest.get("description"),
                lifecycle_state=PluginLifecycleState.INSTALLED.value,
                installed_at=datetime.now(),
                enabled=False,
                capabilities=manifest.get("capabilities", {}),
                category=manifest.get("category", "plugins"),
                install_path=str(plugin_path),
            )
            self.db_session.add(plugin_record)

        await self.db_session.commit()

    async def _unregister_plugin_installation(self, plugin_id: str) -> None:
        """Remove plugin from database."""
        stmt = delete(ExtensionDBModel).where(ExtensionDBModel.name == plugin_id)
        await self.db_session.execute(stmt)
        await self.db_session.commit()

    async def _update_plugin_enabled_status(
        self, plugin_id: str, enabled: bool
    ) -> None:
        """Update plugin enabled status."""
        stmt = (
            update(ExtensionDBModel)
            .where(ExtensionDBModel.name == plugin_id)
            .values(enabled=enabled, updated_at=datetime.now())
        )
        await self.db_session.execute(stmt)
        await self.db_session.commit()

    async def _materialize_ui_components(
        self, plugin_id: str, manifest: Dict[str, Any]
    ) -> None:
        """Materialize UI components for plugin."""
        # This would call the UI materialization pipeline
        # For now, just ensure the directory structure exists
        ui_path = self.ui_materialization_dir / plugin_id
        ui_path.mkdir(parents=True, exist_ok=True)

        # Copy UI source files if they exist
        plugin_path = self.plugins_dir / plugin_id
        ui_source = plugin_path / "ui"
        if ui_source.exists():
            shutil.copytree(ui_source, ui_path, dirs_exist_ok=True)

    async def _remove_ui_components(self, plugin_id: str) -> None:
        """Remove UI components for plugin."""
        ui_path = self.ui_materialization_dir / plugin_id
        if ui_path.exists():
            shutil.rmtree(ui_path)

    async def _register_ui_components(self, plugin_id: str) -> None:
        """Register UI components with the frontend loader."""
        # This would update the import map and notify frontend
        # For now, this is handled by the UI materialization pipeline
        pass

    async def _unregister_ui_components(self, plugin_id: str) -> None:
        """Unregister UI components from frontend loader."""
        # This would remove from import map and notify frontend
        pass

    async def _create_backup(self, plugin_id: str) -> Optional[Path]:
        """Create backup of plugin."""
        plugin_path = self.plugins_dir / plugin_id
        if not plugin_path.exists():
            return None

        # Create backup directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backups_dir / f"{plugin_id}_{timestamp}"
        backup_path.mkdir(parents=True, exist_ok=True)

        # Copy plugin files
        for item in plugin_path.iterdir():
            if item.is_file():
                shutil.copy2(item, backup_path / item.name)
            elif item.is_dir():
                shutil.copytree(item, backup_path / item.name, dirs_exist_ok=True)

        # Create backup manifest
        manifest = {
            "plugin_id": plugin_id,
            "backup_created": datetime.now().isoformat(),
            "original_path": str(plugin_path),
            "backup_path": str(backup_path),
        }

        # Try to read original manifest
        manifest_path = plugin_path / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r") as f:
                original_manifest = json.load(f)
                manifest.update(original_manifest)

        with open(backup_path / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        # Calculate checksum
        checksum = await self._calculate_directory_checksum(backup_path)
        manifest["checksum"] = checksum

        # Update manifest with checksum
        with open(backup_path / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"Created backup for plugin {plugin_id}: {backup_path}")
        return backup_path

    async def _calculate_directory_checksum(self, path: Path) -> str:
        """Calculate SHA256 checksum of directory contents."""
        hash_obj = hashlib.sha256()

        for file_path in sorted(path.rglob("*")):
            if file_path.is_file() and file_path.name != "manifest.json":
                with open(file_path, "rb") as f:
                    while chunk := f.read(8192):
                        hash_obj.update(chunk)

        return hash_obj.hexdigest()

    async def _rollback_installation(
        self, plugin_id: str, backup_path: Optional[Path]
    ) -> None:
        """Rollback failed installation."""
        plugin_path = self.plugins_dir / plugin_id

        # Remove partially installed plugin
        if plugin_path.exists():
            shutil.rmtree(plugin_path)

        # Restore from backup if available
        if backup_path and backup_path.exists():
            shutil.copytree(backup_path, plugin_path, dirs_exist_ok=True)
            logger.info(f"Rolled back plugin {plugin_id} from backup")

    async def _log_operation(
        self,
        plugin_id: str,
        operation: PluginOperation,
        success: bool,
        message: str,
        details: Dict[str, Any],
    ) -> None:
        """Log plugin operation to database."""
        history_entry = ExtensionInstallationHistory(
            extension_name=plugin_id,
            operation=operation.value,
            success=success,
            message=message,
            details=json.dumps(details),
            timestamp=datetime.now(),
        )

        self.db_session.add(history_entry)
        await self.db_session.commit()
