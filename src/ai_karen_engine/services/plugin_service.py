"""
Comprehensive Plugin Service.

This service provides a unified interface for plugin management, combining
registry, discovery, validation, and execution capabilities.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.plugin_discovery import (
    PluginRegistry,
    get_plugin_registry,
    initialize_plugin_registry,
)
from ai_karen_engine.services.plugin_execution import (
    PluginExecutionEngine,
    ExecutionRequest,
    ExecutionResult,
    ExecutionMode,
    ResourceLimits,
    SecurityPolicy,
    get_plugin_execution_engine,
    initialize_plugin_execution_engine,
)

logger = logging.getLogger(__name__)


class PluginService:
    """
    Comprehensive plugin service providing unified plugin management.
    """

    def __init__(
        self,
        marketplace_path: Optional[Path] = None,
        core_plugins_path: Optional[Path] = None,
    ):
        """Initialize plugin service."""
        self.registry: Optional[PluginRegistry] = None
        self.execution_engine: Optional[PluginExecutionEngine] = None
        self.marketplace_path = marketplace_path
        self.core_plugins_path = core_plugins_path
        self.initialized = False

    async def initialize(self, auto_discover: bool = True) -> None:
        """
        Initialize the plugin service.

        Args:
            auto_discover: Whether to automatically discover plugins
        """
        if self.initialized:
            return

        logger.info("Initializing plugin service...")

        # Initialize registry
        self.registry = await initialize_plugin_registry(
            marketplace_path=self.marketplace_path,
            core_plugins_path=self.core_plugins_path,
            auto_discover=auto_discover,
        )

        # Initialize execution engine
        self.execution_engine = await initialize_plugin_execution_engine(
            registry=self.registry
        )

        self.initialized = True
        logger.info("Plugin service initialized successfully")

    async def discover_plugins(
        self, force_refresh: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        """
        Discover available plugins.

        Args:
            force_refresh: Force rediscovery of all plugins

        Returns:
            Dictionary of discovered plugin metadata
        """
        await self._ensure_initialized()
        return await self._get_registry().discover_plugins(force_refresh)

    async def validate_plugin(self, plugin_name: str) -> bool:
        """
        Validate a discovered plugin.

        Args:
            plugin_name: Name of the plugin to validate

        Returns:
            True if validation successful, False otherwise
        """
        await self._ensure_initialized()
        return await self._get_registry().validate_plugin(plugin_name)

    async def register_plugin(self, plugin_name: str) -> bool:
        """
        Register a validated plugin.

        Args:
            plugin_name: Name of the plugin to register

        Returns:
            True if registration successful, False otherwise
        """
        await self._ensure_initialized()
        return await self._get_registry().register_plugin(plugin_name)

    async def validate_and_register_plugin(self, plugin_name: str) -> bool:
        """
        Validate and register a plugin in one step.

        Args:
            plugin_name: Name of the plugin to validate and register

        Returns:
            True if both validation and registration successful, False otherwise
        """
        await self._ensure_initialized()

        registry = self._get_registry()
        if await registry.validate_plugin(plugin_name):
            return await registry.register_plugin(plugin_name)
        return False

    async def validate_and_register_all_discovered(self) -> Dict[str, bool]:
        """
        Validate and register all discovered plugins.

        Returns:
            Dictionary mapping plugin names to success status
        """
        await self._ensure_initialized()

        registry = self._get_registry()
        results = {}
        discovered_plugins = registry.get_plugins_by_status("discovered")

        for plugin_name, plugin_metadata in discovered_plugins.items():
            try:
                success = await self.validate_and_register_plugin(plugin_name)
                results[plugin_name] = success
                if success:
                    logger.info(f"Successfully registered plugin: {plugin_name}")
                else:
                    logger.warning(f"Failed to register plugin: {plugin_name}")
            except Exception as e:
                logger.error(f"Error registering plugin {plugin_name}: {e}")
                results[plugin_name] = False

        return results

    async def execute_plugin(
        self,
        plugin_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        execution_mode: ExecutionMode = ExecutionMode.SANDBOX,
        timeout_seconds: int = 30,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ExecutionResult:
        """
        Execute a plugin with the specified parameters.

        Args:
            plugin_name: Name of the plugin to execute
            parameters: Plugin parameters
            execution_mode: Execution mode (direct, thread, process, sandbox)
            timeout_seconds: Execution timeout
            user_id: User ID for tracking
            session_id: Session ID for tracking

        Returns:
            Execution result
        """
        await self._ensure_initialized()

        request = ExecutionRequest(
            plugin_name=plugin_name,
            parameters=parameters or {},
            execution_mode=execution_mode,
            timeout_seconds=timeout_seconds,
            user_id=user_id,
            session_id=session_id,
        )

        return await self._get_execution_engine().execute_plugin(request)

    async def cancel_execution(self, request_id: str) -> bool:
        """
        Cancel an active plugin execution.

        Args:
            request_id: Request ID to cancel

        Returns:
            True if cancellation successful, False otherwise
        """
        await self._ensure_initialized()
        return await self._get_execution_engine().cancel_execution(request_id)

    def get_plugin(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get plugin metadata by name."""
        if not self.initialized or not self.registry:
            return None
        return self.registry.get_plugin(plugin_name)

    async def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get plugin information by name (async version for API compatibility)."""
        await self._ensure_initialized()
        return self.get_plugin(plugin_name)

    async def list_plugins(
        self, category: Optional[str] = None, enabled_only: bool = False
    ) -> List[Dict[str, Any]]:
        """List plugins with optional filtering."""
        await self._ensure_initialized()

        if category:
            plugins = self.get_plugins_by_category(category)
        else:
            plugins = self.get_available_plugins()

        if enabled_only:
            plugins = [p for p in plugins if p.get("status") == "registered"]

        return plugins

    def get_plugins_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get plugins by category."""
        if not self.initialized or not self.registry:
            return []
        return self.registry.get_plugins_by_category(category)

    def get_plugins_by_type(self, plugin_type: str) -> List[Dict[str, Any]]:
        """Get plugins by type."""
        if not self.initialized or not self.registry:
            return []
        return self.registry.get_plugins_by_type(plugin_type)

    def get_plugins_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get plugins by status."""
        if not self.initialized or not self.registry:
            return []
        return self.registry.get_plugins_by_status(status)

    def get_available_plugins(self) -> List[Dict[str, Any]]:
        """Get all available (registered) plugins."""
        return self.get_plugins_by_status("registered")

    def get_active_executions(self) -> List[ExecutionResult]:
        """Get list of active executions."""
        if not self.initialized or not self.execution_engine:
            return []
        return self.execution_engine.get_active_executions()

    def get_execution_history(self, limit: int = 100) -> List[ExecutionResult]:
        """Get execution history."""
        if not self.initialized or not self.execution_engine:
            return []
        return self.execution_engine.get_execution_history(limit)

    def get_service_stats(self) -> Dict[str, Any]:
        """Get comprehensive service statistics."""
        if not self.initialized:
            return {"error": "Service not initialized"}

        stats = {
            "initialized": self.initialized,
            "registry_stats": self.registry.get_registry_stats()
            if self.registry
            else {},
            "execution_metrics": self.execution_engine.get_execution_metrics()
            if self.execution_engine
            else {},
            "active_executions": len(self.get_active_executions()),
            "timestamp": datetime.utcnow().isoformat(),
        }

        return stats

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the plugin service."""
        health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {},
        }

        try:
            # Check initialization
            if not self.initialized:
                health["status"] = "unhealthy"
                health["components"]["initialization"] = {
                    "status": "failed",
                    "error": "Service not initialized",
                }
                return health

            # Check registry
            if self.registry:
                registry_stats = self.registry.get_registry_stats()
                health["components"]["registry"] = {
                    "status": "healthy",
                    "total_plugins": registry_stats["total_plugins"],
                    "registered_plugins": registry_stats["by_status"].get(
                        "registered", 0
                    ),
                }
            else:
                health["status"] = "degraded"
                health["components"]["registry"] = {"status": "missing"}

            # Check execution engine
            if self.execution_engine:
                execution_metrics = self.execution_engine.get_execution_metrics()
                active_executions = len(self.execution_engine.get_active_executions())
                health["components"]["execution_engine"] = {
                    "status": "healthy",
                    "active_executions": active_executions,
                    "total_executions": execution_metrics["executions_total"],
                    "success_rate": (
                        execution_metrics["executions_successful"]
                        / max(execution_metrics["executions_total"], 1)
                    ),
                }
            else:
                health["status"] = "degraded"
                health["components"]["execution_engine"] = {"status": "missing"}

        except Exception as e:
            health["status"] = "unhealthy"
            health["error"] = str(e)
            logger.error(f"Health check failed: {e}")

        return health

    async def cleanup(self):
        """Clean up service resources."""
        if self.execution_engine:
            await self.execution_engine.cleanup()

        self.initialized = False
        logger.info("Plugin service cleaned up")

    async def disable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        plugin = self.get_plugin(plugin_name)
        if not plugin:
            return False
        plugin["status"] = "disabled"
        logger.info(f"Plugin {plugin_name} disabled")
        return True

    async def enable_plugin(self, plugin_name: str) -> bool:
        await self._ensure_initialized()
        plugin = self.get_plugin(plugin_name)
        if not plugin:
            return False
        plugin["status"] = "registered"
        logger.info(f"Plugin {plugin_name} enabled")
        return True

    async def _ensure_initialized(self):
        """Ensure the service is initialized."""
        if not self.initialized:
            await self.initialize()

    def _get_registry(self) -> PluginRegistry:
        """Get the initialized plugin registry."""
        if self.registry is None:
            raise RuntimeError("Plugin registry is not initialized")
        return self.registry

    def _get_execution_engine(self) -> PluginExecutionEngine:
        """Get the initialized plugin execution engine."""
        if self.execution_engine is None:
            raise RuntimeError("Plugin execution engine is not initialized")
        return self.execution_engine


# Global plugin service instance
_plugin_service: Optional[PluginService] = None


def get_plugin_service() -> PluginService:
    """Get global plugin service instance."""
    global _plugin_service
    if _plugin_service is None:
        # Auto-initialize with default paths if not already done
        path = Path("src/ai_karen_engine/extensions/plugins")
        _plugin_service = PluginService(marketplace_path=path, core_plugins_path=path)
    return _plugin_service


async def initialize_plugin_service(
    marketplace_path: Optional[Path] = None,
    core_plugins_path: Optional[Path] = None,
    auto_discover: bool = True,
) -> PluginService:
    """
    Initialize the global plugin service.

    Args:
        marketplace_path: Path to plugin marketplace
        core_plugins_path: Path to core plugins
        auto_discover: Whether to automatically discover plugins

    Returns:
        Initialized plugin service
    """
    global _plugin_service

    # Use canonical paths if not provided
    if marketplace_path is None:
        marketplace_path = Path("src/ai_karen_engine/extensions/plugins")
    if core_plugins_path is None:
        core_plugins_path = Path("src/ai_karen_engine/extensions/plugins")

    _plugin_service = PluginService(marketplace_path, core_plugins_path)
    await _plugin_service.initialize(auto_discover)

    if auto_discover:
        logger.info("Auto-registering all discovered plugins...")
        await _plugin_service.validate_and_register_all_discovered()

    return _plugin_service


# Convenience functions for common operations
async def discover_and_register_all_plugins() -> Dict[str, bool]:
    """Discover and register all available plugins."""
    service = get_plugin_service()
    await service.discover_plugins(force_refresh=True)
    return await service.validate_and_register_all_discovered()


async def execute_plugin_simple(
    plugin_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 30,
) -> ExecutionResult:
    """Simple plugin execution with default settings."""
    service = get_plugin_service()
    return await service.execute_plugin(
        plugin_name=plugin_name,
        parameters=parameters or {},
        timeout_seconds=timeout_seconds,
    )


async def get_plugin_marketplace_info() -> Dict[str, Any]:
    """Get information about the plugin marketplace."""
    service = get_plugin_service()
    await service._ensure_initialized()

    stats = service.get_service_stats()
    registry_stats = stats.get("registry_stats", {})

    available_plugins = []
    for plugin in service.get_available_plugins():
        manifest = plugin.get("manifest")
        if manifest is None:
            continue
        available_plugins.append({
            "name": getattr(manifest, "name", ""),
            "version": getattr(manifest, "version", ""),
            "description": getattr(manifest, "description", ""),
            "category": getattr(manifest, "category", "general"),
            "type": getattr(manifest, "plugin_type", None) or getattr(manifest, "category", "custom"),
            "author": getattr(manifest, "author", ""),
        })

    return {
        "total_plugins": registry_stats.get("total_plugins", 0),
        "by_category": registry_stats.get("by_category", {}),
        "by_type": registry_stats.get("by_type", {}),
        "by_status": registry_stats.get("by_status", {}),
        "available_plugins": available_plugins,
    }
