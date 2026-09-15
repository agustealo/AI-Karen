"""
Plugin Lifecycle Manager - Integrates version management with plugin system.

Provides:
- Plugin installation and uninstallation
- Version checking and updates
- Rollback capabilities
- Lifecycle state management
- Integration with DependencyResolver and VersionManager
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from ai_karen_engine.extensions.platform.core.host.loader import ExtensionLoader
from ai_karen_engine.extensions.platform.core.host.dependency_resolver import DependencyResolver
from ai_karen_engine.extensions.platform.core.integration.version_manager import (
    ExtensionVersionManager,
    VersionInfo,
    UpdateResult,
    UpdateStatus,
    UpdateChannel,
)
from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest, ExtensionStatus
from ai_karen_engine.extensions.platform.core.registry.plugin_registry import get_registry
from ai_karen_engine.extensions.platform.core.registry.package_manager import get_package_manager
from ai_karen_engine.extensions.platform.core.registry.database_service import get_database_service
from ai_karen_engine.extensions.platform.core.registry.state_machine import (
    get_state_machine,
    ExtensionState,
    TransitionEvent,
)


logger = logging.getLogger(__name__)


class PluginLifecycleManager:
    """
    Manages the full lifecycle of plugins from installation to removal.

    Integrates:
    - ExtensionLoader for plugin discovery and loading
    - DependencyResolver for dependency management
    - VersionManager for update and rollback
    - PluginRegistry for plugin tracking
    """

    def __init__(
        self,
        extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
        auto_update: bool = False,
        backup_before_update: bool = True,
    ):
        """
        Initialize the plugin lifecycle manager.

        Args:
            extensions_dir: Path to extensions directory
            auto_update: Enable automatic updates
            backup_before_update: Backup plugins before updating
        """
        self.extensions_dir = Path(extensions_dir)
        self.loader = ExtensionLoader(extensions_dir)
        self.registry = get_registry()
        self.dependency_resolver = DependencyResolver()
        self.version_manager = ExtensionVersionManager(
            auto_update=auto_update,
            backup_before_update=backup_before_update,
        )
        self.package_manager = get_package_manager(extensions_dir)
        self.database_service = get_database_service()
        self.state_machine = get_state_machine(database_service=self.database_service)
        self._lifecycle_state: Dict[str, str] = {}

        logger.info(f"PluginLifecycleManager initialized with dir={extensions_dir}")

    async def install_plugin(
        self,
        package_url: str,
        target_version: Optional[str] = None,
        channel: Optional[UpdateChannel] = None,
    ) -> Dict[str, Any]:
        """
        Install a plugin from a URL.

        Args:
            package_url: URL to plugin package
            target_version: Target version (latest if None)
            channel: Update channel to use

        Returns:
            Installation result dictionary
        """
        plugin_name = self._extract_plugin_name(package_url)
        logger.info(f"Installing plugin '{plugin_name}' from {package_url}")

        try:
            # Initialize plugin in state machine
            self.state_machine.initialize_plugin(plugin_name)

            # Transition to downloading state
            await self.state_machine.transition(
                plugin_name, TransitionEvent.DOWNLOAD_START
            )

            # Download plugin package
            package_file = await self.package_manager.download_plugin_package(
                package_url
            )

            # Transition to extracting state
            await self.state_machine.transition(
                plugin_name, TransitionEvent.EXTRACT_START
            )

            # Extract plugin package
            extracted_dir = await self.package_manager.extract_plugin_package(
                package_file
            )

            # Transition to extracting complete
            await self.state_machine.transition(
                plugin_name, TransitionEvent.EXTRACT_COMPLETE
            )

            # Validate plugin package
            (
                is_valid,
                validation_errors,
                manifest,
            ) = await self.package_manager.validate_plugin_package(extracted_dir)

            # Transition to validating
            await self.state_machine.transition(
                plugin_name, TransitionEvent.VALIDATE_START
            )

            if not is_valid:
                error_msg = f"Plugin validation failed: {', '.join(validation_errors)}"
                logger.error(error_msg)

                # Transition to error state
                await self.state_machine.transition(
                    plugin_name,
                    TransitionEvent.VALIDATE_FAILED,
                    error_message=error_msg,
                )

                self._set_lifecycle_state(plugin_name, "error")
                raise Exception(error_msg)

            if not manifest:
                error_msg = "Plugin manifest not found"
                logger.error(error_msg)

                # Transition to error state
                await self.state_machine.transition(
                    plugin_name,
                    TransitionEvent.VALIDATE_FAILED,
                    error_message=error_msg,
                )

                self._set_lifecycle_state(plugin_name, "error")
                raise Exception(error_msg)

            # Install plugin to filesystem
            installed_dir = await self.package_manager.install_plugin_to_filesystem(
                extracted_dir, manifest, self.extensions_dir
            )

            # Create database record
            try:
                db_extension = await self.database_service.create_extension(
                    manifest.to_dict(), str(installed_dir)
                )
                logger.info(
                    f"Extension database record created: {manifest.name} v{manifest.version}"
                )
            except Exception as e:
                logger.warning(f"Failed to create database record: {e}")
                # Continue even if database creation fails

            # Refresh registry to discover new plugin
            await self.registry.refresh()

            # Load the plugin
            try:
                instance = self.loader.load_extension(manifest.name)
                logger.info(f"Plugin '{plugin_name}' installed successfully")

                # Set lifecycle state
                self._set_lifecycle_state(plugin_name, "active")

                return {
                    "plugin_name": manifest.name,
                    "status": "installed",
                    "message": f"Plugin '{plugin_name}' installed successfully",
                    "version": manifest.version,
                    "directory": str(installed_dir),
                    "validation_passed": is_valid,
                    "validation_errors": validation_errors,
                }
            except Exception as e:
                logger.error(f"Failed to load plugin '{plugin_name}': {e}")
                # Clean up files if loading fails
                try:
                    await self.package_manager.remove_plugin_from_filesystem(
                        manifest.name, create_backup=False
                    )
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to cleanup failed installation: {cleanup_error}"
                    )
                self._set_lifecycle_state(plugin_name, "error")
                raise

        except Exception as e:
            logger.error(f"Failed to install plugin '{plugin_name}': {e}")
            self._set_lifecycle_state(plugin_name, "error")
            raise
        finally:
            # Clean up temporary files
            try:
                await self.package_manager.cleanup_temp_files()
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp files: {cleanup_error}")

    async def uninstall_plugin(
        self, plugin_name: str, backup: bool = True
    ) -> Dict[str, Any]:
        """
        Uninstall a plugin.

        Args:
            plugin_name: Name of plugin to uninstall
            backup: Create backup before uninstalling

        Returns:
            Uninstallation result dictionary
        """
        logger.info(f"Uninstalling plugin '{plugin_name}'")

        try:
            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "uninstalling")

            # Check if plugin is loaded
            loaded = self.loader.get_loaded_extensions()
            if plugin_name in loaded:
                # Shutdown the plugin
                instance = loaded[plugin_name]
                if hasattr(instance, "_shutdown"):
                    await instance._shutdown()

                # Remove from loaded extensions
                self.loader._loaded_extensions.pop(plugin_name, None)

            # Remove the runtime registry entry as well so the plugin overview
            # stops surfacing stale records after uninstall.
            self.registry.unload_extension(plugin_name)

            # Remove plugin from filesystem
            await self.package_manager.remove_plugin_from_filesystem(
                plugin_name, backup
            )

            # Update database
            try:
                extension = await self.registry.get_extension_by_name(plugin_name)
                if extension:
                    # The extension.id is already a UUID, so we can pass it directly
                    await self.database_service.delete_extension(extension.id)
                    logger.info(f"Extension database record deleted: {plugin_name}")
            except Exception as e:
                logger.warning(f"Failed to delete database record: {e}")

            # Update registry - loaded extensions are managed by the loader
            # The registry will be refreshed on next discovery cycle

            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "uninstalled")

            return {
                "plugin_name": plugin_name,
                "status": "uninstalled",
                "message": f"Plugin '{plugin_name}' uninstalled successfully",
                "backup_created": backup,
            }

        except Exception as e:
            logger.error(f"Failed to uninstall plugin '{plugin_name}': {e}")
            self._set_lifecycle_state(plugin_name, "error")
            raise

    async def enable_plugin(self, plugin_name: str) -> Dict[str, Any]:
        """
        Enable a plugin.

        Args:
            plugin_name: Name of plugin to enable

        Returns:
            Enable result dictionary
        """
        logger.info(f"Enabling plugin '{plugin_name}'")

        try:
            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "loading")

            # Load the plugin
            instance = self.loader.load_extension(plugin_name)

            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "active")

            return {
                "plugin_name": plugin_name,
                "status": "enabled",
                "message": f"Plugin '{plugin_name}' enabled successfully",
                "version": instance.manifest.version,
            }

        except Exception as e:
            logger.error(f"Failed to enable plugin '{plugin_name}': {e}")
            self._set_lifecycle_state(plugin_name, "error")
            raise

    async def disable_plugin(self, plugin_name: str) -> Dict[str, Any]:
        """
        Disable a plugin.

        Args:
            plugin_name: Name of plugin to disable

        Returns:
            Disable result dictionary
        """
        logger.info(f"Disabling plugin '{plugin_name}'")

        try:
            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "unloading")

            # Check if plugin is loaded
            loaded = self.loader.get_loaded_extensions()
            if plugin_name in loaded:
                # Shutdown the plugin
                instance = loaded[plugin_name]
                if hasattr(instance, "_shutdown"):
                    await instance._shutdown()

                # Remove from loaded extensions
                self.loader._loaded_extensions.pop(plugin_name, None)

                # Update registry status
                record = self.registry.get_extension(plugin_name)
                if record:
                    record.status = ExtensionStatus.INACTIVE

            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "inactive")

            return {
                "plugin_name": plugin_name,
                "status": "disabled",
                "message": f"Plugin '{plugin_name}' disabled successfully",
            }

        except Exception as e:
            logger.error(f"Failed to disable plugin '{plugin_name}': {e}")
            self._set_lifecycle_state(plugin_name, "error")
            raise

    async def update_plugin(
        self,
        plugin_name: str,
        target_version: Optional[str] = None,
        channel: Optional[UpdateChannel] = None,
        force: bool = False,
    ) -> UpdateResult:
        """
        Update a plugin to a new version.

        Args:
            plugin_name: Name of plugin to update
            target_version: Target version (latest if None)
            channel: Update channel to use
            force: Force update even if already up to date

        Returns:
            Update result
        """
        logger.info(f"Updating plugin '{plugin_name}' to {target_version or 'latest'}")

        try:
            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "updating")

            # Use version manager to perform update
            result = await self.version_manager.update_extension(
                plugin_name, target_version, channel, force
            )

            # Refresh registry if update succeeded
            if result.status in [UpdateStatus.INSTALLED, UpdateStatus.UP_TO_DATE]:
                await self.registry.refresh()

                # Set lifecycle state based on result
                if result.status == UpdateStatus.INSTALLED:
                    self._set_lifecycle_state(plugin_name, "active")
                elif result.status == UpdateStatus.UP_TO_DATE:
                    current_state = self._get_lifecycle_state(plugin_name)
                    if current_state not in ["inactive", "uninstalled"]:
                        self._set_lifecycle_state(plugin_name, "active")

            return result

        except Exception as e:
            logger.error(f"Failed to update plugin '{plugin_name}': {e}")
            self._set_lifecycle_state(plugin_name, "error")
            raise

    async def restore_plugin(
        self,
        plugin_name: str,
        backup_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Restore a plugin from a backup.

        Args:
            plugin_name: Name of plugin to restore
            backup_path: Path to backup (uses default if None)

        Returns:
            Restore result dictionary
        """
        logger.info(f"Restoring plugin '{plugin_name}' from backup")

        try:
            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "restoring")

            # Convert backup_path to Path if it's a string
            if backup_path is None:
                raise ValueError("backup_path is required for restore operation")

            backup_file_path = (
                Path(backup_path) if isinstance(backup_path, str) else backup_path
            )

            # Restore plugin from backup
            restored_dir = await self.package_manager.restore_plugin_from_backup(
                backup_file_path,
                target_plugin_name=plugin_name,
                target_extensions_dir=self.extensions_dir,
            )

            # Restore plugin from backup
            restored_dir = await self.package_manager.restore_plugin_from_backup(
                backup_file_path,
                target_plugin_name=plugin_name,
                target_extensions_dir=self.extensions_dir,
            )

            # Refresh registry to discover restored plugin
            await self.registry.refresh()

            # Reload the plugin
            instance = self.loader.load_extension(plugin_name)

            # Update database record
            try:
                extension = await self.registry.get_extension_by_name(plugin_name)
                if extension:
                    await self.database_service.update_extension(
                        extension.id,  # extension.id should be a UUID
                        {
                            "status": ExtensionStatus.ACTIVE,
                            "loaded_at": datetime.utcnow(),
                        },
                    )
            except Exception as e:
                logger.warning(f"Failed to update database record: {e}")

            # Set lifecycle state
            self._set_lifecycle_state(plugin_name, "active")

            return {
                "plugin_name": plugin_name,
                "status": "restored",
                "message": f"Plugin '{plugin_name}' restored successfully",
                "version": instance.manifest.version if instance else "unknown",
                "backup_path": str(backup_file_path),
                "restored_directory": str(restored_dir),
            }

        except Exception as e:
            logger.error(f"Failed to restore plugin '{plugin_name}': {e}")
            self._set_lifecycle_state(plugin_name, "error")
            raise

    async def check_updates(self, plugin_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Check for updates for plugins.

        Args:
            plugin_name: Specific plugin to check (None = check all)

        Returns:
            Dictionary of update information
        """
        logger.info(f"Checking updates for {plugin_name or 'all plugins'}")

        try:
            if plugin_name:
                # Check single plugin
                version_info = await self.version_manager.check_for_updates(plugin_name)
                return {
                    plugin_name: version_info.__dict__,
                }
            else:
                # Check all plugins
                plugins = self.loader.discover_extensions()
                updates = {}
                for name in plugins:
                    version_info = await self.version_manager.check_for_updates(name)
                    updates[name] = version_info.__dict__
                return updates

        except Exception as e:
            logger.error(f"Failed to check updates: {e}")
            raise

    def get_lifecycle_state(self, plugin_name: str) -> Optional[str]:
        """
        Get the lifecycle state of a plugin.

        Args:
            plugin_name: Name of plugin

        Returns:
            Lifecycle state or None if plugin not found
        """
        return self._lifecycle_state.get(plugin_name)

    def get_all_lifecycle_states(self) -> Dict[str, str]:
        """
        Get lifecycle states for all plugins.

        Returns:
            Dictionary of plugin_name -> lifecycle_state
        """
        return self._lifecycle_state.copy()

    def _set_lifecycle_state(self, plugin_name: str, state: str) -> None:
        """
        Set the lifecycle state of a plugin.

        Args:
            plugin_name: Name of plugin
            state: Lifecycle state
        """
        self._lifecycle_state[plugin_name] = state
        logger.debug(f"Plugin '{plugin_name}' state: {state}")

    def _get_lifecycle_state(self, plugin_name: str) -> Optional[str]:
        """Get the lifecycle state of a plugin."""
        return self._lifecycle_state.get(plugin_name)

    @staticmethod
    def _extract_plugin_name(package_url: str) -> str:
        """
        Extract plugin name from package URL.

        Args:
            package_url: URL or path to plugin package

        Returns:
            Plugin name
        """
        # Extract name from URL path
        parts = package_url.split("/")
        filename = parts[-1]

        # Remove extension
        if filename.endswith(".tar.gz") or filename.endswith(".zip"):
            filename = filename.rsplit(".", 2)[0]
        elif filename.endswith(".tgz"):
            filename = filename.rsplit(".", 1)[0]

        return filename

    async def get_plugin_dependencies(self, plugin_name: str) -> Dict[str, Any]:
        """
        Get dependency tree for a plugin.

        Args:
            plugin_name: Name of plugin

        Returns:
            Dependency tree information
        """
        try:
            # Load plugin manifest
            manifest = self.loader.load_manifest(plugin_name)

            # Build manifests dict
            manifests = {plugin_name: manifest}

            # Get dependency tree
            tree = self.dependency_resolver.get_dependency_tree(manifests)

            return tree[plugin_name]

        except Exception as e:
            logger.error(f"Failed to get dependencies for '{plugin_name}': {e}")
            raise


# Singleton instance
_lifecycle_manager_instance: Optional[PluginLifecycleManager] = None


def get_lifecycle_manager(
    extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
    auto_update: bool = False,
    backup_before_update: bool = True,
) -> PluginLifecycleManager:
    """Get the singleton plugin lifecycle manager instance."""
    global _lifecycle_manager_instance
    if _lifecycle_manager_instance is None:
        _lifecycle_manager_instance = PluginLifecycleManager(
            extensions_dir=extensions_dir,
            auto_update=auto_update,
            backup_before_update=backup_before_update,
        )
    return _lifecycle_manager_instance


__all__ = [
    "PluginLifecycleManager",
    "get_lifecycle_manager",
]
