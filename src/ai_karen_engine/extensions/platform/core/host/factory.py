"""Compatibility factory for extension platform services.

Historically this factory built a second runtime registry, plugin router,
validator/dependency stack and host manager. Runtime execution authority now
belongs exclusively to ``PluginService`` / ``PluginKernel``. The factory is
retained for callers that need platform/catalog support services, but it may
only return adapters or ancillary services that do not execute plugin code.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ai_karen_engine.services.plugin_service import get_plugin_service

logger = logging.getLogger(__name__)


class ExtensionServiceConfig:
    """Configuration retained for extension-platform compatibility."""

    def __init__(
        self,
        extension_root: Optional[Path] = None,
        enable_marketplace: bool = True,
        enable_resource_monitoring: bool = True,
        enable_health_checks: bool = True,
        enable_dependency_resolution: bool = True,
        enable_workflow_engine: bool = True,
        enable_metrics_dashboard: bool = False,
        require_signature_verification: bool = False,
        allow_unsigned_extensions: bool = True,
        sandbox_extensions: bool = False,
        max_memory_per_extension_mb: int = 512,
        max_cpu_percent_per_extension: int = 25,
        max_extensions: int = 100,
        auto_discover_on_init: bool = True,
        auto_load_extensions: bool = False,
    ) -> None:
        self.extension_root = extension_root or (
            Path(__file__).parent.parent.parent.parent / "plugins"
        )
        self.enable_marketplace = enable_marketplace
        self.enable_resource_monitoring = enable_resource_monitoring
        self.enable_health_checks = enable_health_checks
        self.enable_dependency_resolution = enable_dependency_resolution
        self.enable_workflow_engine = enable_workflow_engine
        self.enable_metrics_dashboard = enable_metrics_dashboard
        self.require_signature_verification = require_signature_verification
        self.allow_unsigned_extensions = allow_unsigned_extensions
        self.sandbox_extensions = sandbox_extensions
        self.max_memory_per_extension_mb = max_memory_per_extension_mb
        self.max_cpu_percent_per_extension = max_cpu_percent_per_extension
        self.max_extensions = max_extensions
        self.auto_discover_on_init = auto_discover_on_init
        self.auto_load_extensions = auto_load_extensions


class CanonicalCatalogRegistryView:
    """Non-owning compatibility view of the kernel's catalog registry."""

    @property
    def _service(self):
        return get_plugin_service()

    @property
    def _kernel(self):
        service = self._service
        if not service.initialized or service.kernel is None:
            raise RuntimeError("Canonical plugin service is not initialized")
        return service.kernel

    async def initialize(self) -> None:
        service = self._service
        if not service.initialized:
            await service.initialize(auto_discover=True)

    async def refresh(self) -> int:
        service = self._service
        if not service.initialized:
            await service.initialize(auto_discover=True)
            return len(service.kernel.list_records()) if service.kernel else 0
        return await service.refresh_plugins()

    def list_discovered(self) -> list[str]:
        return [
            str(getattr(record.get("manifest"), "name", ""))
            for record in self._kernel.list_records()
            if getattr(record.get("manifest"), "name", None)
        ]

    def get_metadata(self, extension_id: str) -> Any:
        return self._kernel.catalog_registry.get_metadata(extension_id)

    def get_extension(self, extension_id: str) -> Any:
        return self._service.get_plugin(extension_id)

    def list_extensions(self) -> list[Dict[str, Any]]:
        return list(self._kernel.list_records())

    def get_extension_count(self) -> int:
        return len(self._kernel.list_records())


class ExtensionServiceFactory:
    """Factory for catalog/support services without runtime duplication."""

    def __init__(self, config: Optional[ExtensionServiceConfig] = None):
        self.config = config or ExtensionServiceConfig()
        self._services: Dict[str, Any] = {}
        logger.info("Canonical extension support factory initialized")

    def create_extension_registry(self) -> CanonicalCatalogRegistryView:
        registry = CanonicalCatalogRegistryView()
        self._services["extension_registry"] = registry
        return registry

    def create_extension_validator(self) -> None:
        logger.info(
            "Standalone extension validator retired; catalog validation is owned by PluginKernel"
        )
        return None

    def create_dependency_resolver(self) -> None:
        logger.info(
            "Standalone dependency resolver retired; dependency validation is owned by PluginKernel"
        )
        return None

    def create_resource_monitor(self):
        if not self.config.enable_resource_monitoring:
            return None
        try:
            from ai_karen_engine.extensions.resource_monitor import ResourceMonitor

            monitor = ResourceMonitor(
                max_memory_mb=self.config.max_memory_per_extension_mb,
                max_cpu_percent=self.config.max_cpu_percent_per_extension,
            )
            self._services["resource_monitor"] = monitor
            return monitor
        except Exception as exc:
            logger.warning("Extension resource monitor unavailable: %s", exc)
            return None

    def create_health_checker(self):
        if not self.config.enable_health_checks:
            return None
        try:
            from ai_karen_engine.extensions.resource_monitor import ExtensionHealthChecker

            monitor = self.get_service("resource_monitor") or self.create_resource_monitor()
            if monitor is None:
                return None
            checker = ExtensionHealthChecker(monitor)
            self._services["health_checker"] = checker
            return checker
        except Exception as exc:
            logger.warning("Extension health checker unavailable: %s", exc)
            return None

    def create_marketplace_client(self):
        if not self.config.enable_marketplace:
            return None
        try:
            from ai_karen_engine.extensions.marketplace_client import MarketplaceClient

            client = MarketplaceClient()
            self._services["marketplace_client"] = client
            return client
        except Exception as exc:
            logger.warning("Extension marketplace client unavailable: %s", exc)
            return None

    def create_workflow_engine(self):
        logger.info(
            "Standalone extension workflow engine retired; use governed runtime workflows"
        )
        return None

    def create_plugin_orchestrator(self):
        from ai_karen_engine.extensions.platform.core.integration.orchestrator import (
            get_plugin_orchestrator,
        )

        orchestrator = get_plugin_orchestrator()
        self._services["plugin_orchestrator"] = orchestrator
        return orchestrator

    def create_metrics_dashboard(self):
        if not self.config.enable_metrics_dashboard:
            return None
        try:
            from ai_karen_engine.extensions.metrics_dashboard import MetricsDashboard

            dashboard = MetricsDashboard()
            self._services["metrics_dashboard"] = dashboard
            return dashboard
        except Exception as exc:
            logger.warning("Extension metrics dashboard unavailable: %s", exc)
            return None

    def create_extension_data_manager(self):
        try:
            from ai_karen_engine.extensions.data_manager import ExtensionDataManager

            manager = ExtensionDataManager()
            self._services["extension_data_manager"] = manager
            return manager
        except Exception as exc:
            logger.warning("Extension data manager unavailable: %s", exc)
            return None

    def create_extension_manager(self):
        from ai_karen_engine.extensions.platform.core.manager import (
            get_extension_core_manager,
        )

        manager = get_extension_core_manager()
        self._services["extension_manager"] = manager
        return manager

    def create_all_services(self) -> Dict[str, Any]:
        """Create only catalog/support services; never a second runtime stack."""
        self.create_extension_registry()
        self.create_resource_monitor()
        self.create_health_checker()
        self.create_marketplace_client()
        self.create_plugin_orchestrator()
        self.create_extension_data_manager()
        self.create_metrics_dashboard()
        self.create_extension_manager()
        return dict(self._services)

    def get_service(self, service_name: str):
        return self._services.get(service_name)

    def get_all_services(self) -> Dict[str, Any]:
        return dict(self._services)

    def health_check(self) -> Dict[str, Any]:
        service = get_plugin_service()
        stats = service.get_service_stats()
        return {
            "plugin_runtime": {
                "healthy": bool(stats.get("initialized")),
                "authority": "PluginKernel",
                "stats": stats,
            },
            "support_services": sorted(self._services),
        }


_global_factory: Optional[ExtensionServiceFactory] = None


def get_extension_service_factory(
    config: Optional[ExtensionServiceConfig] = None,
) -> ExtensionServiceFactory:
    global _global_factory
    if _global_factory is None:
        _global_factory = ExtensionServiceFactory(config)
    return _global_factory


def get_extension_manager():
    factory = get_extension_service_factory()
    return factory.get_service("extension_manager") or factory.create_extension_manager()


def get_extension_registry():
    factory = get_extension_service_factory()
    return factory.get_service("extension_registry") or factory.create_extension_registry()


def get_marketplace_client():
    factory = get_extension_service_factory()
    return factory.get_service("marketplace_client") or factory.create_marketplace_client()


def initialize_extensions_for_production(
    config: Optional[ExtensionServiceConfig] = None,
):
    """Return the canonical platform facade; caller may await ``initialize()``."""
    factory = get_extension_service_factory(config)
    factory.create_all_services()
    return factory.get_service("extension_manager")


__all__ = [
    "CanonicalCatalogRegistryView",
    "ExtensionServiceConfig",
    "ExtensionServiceFactory",
    "get_extension_service_factory",
    "get_extension_manager",
    "get_extension_registry",
    "get_marketplace_client",
    "initialize_extensions_for_production",
]
