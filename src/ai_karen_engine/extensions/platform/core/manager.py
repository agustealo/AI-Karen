"""Compatibility facade over the canonical plugin service.

Catalog discovery remains owned by the platform registry used by ``PluginKernel``.
This module no longer owns loading, execution, routing, or a second runtime
registry. Existing callers may continue to use the historical manager surface,
but all state changes are delegated to the one canonical ``PluginService``.

The PluginService accessors are intentionally imported lazily. ``PluginKernel``
loads platform catalog modules while PluginService itself imports PluginKernel,
so an import-time dependency in this facade would create a package cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from ai_karen_engine.services.plugin_service import PluginService
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.plugin_lifecycle_approval import PluginLifecycleApprovalScope

logger = logging.getLogger(__name__)


def get_plugin_service() -> "PluginService":
    """Resolve the canonical service lazily to keep platform imports acyclic."""
    from ai_karen_engine.services.plugin_service import get_plugin_service as _get

    return _get()


async def initialize_plugin_service(**kwargs: Any) -> "PluginService":
    """Initialize the canonical service without an import-time kernel back-edge."""
    from ai_karen_engine.services.plugin_service import (
        initialize_plugin_service as _initialize,
    )

    return await _initialize(**kwargs)


@dataclass
class ExtensionCoreManager:
    """Read/catalog facade backed by the canonical plugin runtime."""

    extensions_dir: Optional[str] = None

    def __post_init__(self) -> None:
        from ai_karen_engine.services.plugin_service import _CANONICAL_PLUGIN_ROOT

        self._root = Path(self.extensions_dir) if self.extensions_dir else _CANONICAL_PLUGIN_ROOT

    def _service(self) -> "PluginService":
        from ai_karen_engine.services.plugin_service import _CANONICAL_PLUGIN_ROOT

        service = get_plugin_service()
        if service.initialized:
            active_root = Path(
                service.core_plugins_path
                or service.marketplace_path
                or _CANONICAL_PLUGIN_ROOT
            )
            if active_root.resolve() != self._root.resolve():
                raise RuntimeError(
                    "ExtensionCoreManager root does not match the initialized PluginService"
                )
        return service

    async def _ensure_service(self) -> "PluginService":
        service = self._service()
        if service.initialized:
            return service
        return await initialize_plugin_service(
            marketplace_path=self._root,
            core_plugins_path=self._root,
            auto_discover=True,
        )

    @staticmethod
    def _extension_capabilities(manifest: Any) -> Dict[str, Any]:
        """Project reviewed declarations without implying runtime readiness.

        The host's modality UI is independent of plugin-supplied frontend
        bundles. This catalog declares *what a plugin supports*, never that a
        model has been installed, licensed or authorized for this consumer.
        Actual availability comes only from VoiceRuntime.engine_catalog().
        """
        capabilities = getattr(manifest, "capabilities", manifest)
        projection: Dict[str, Any] = {
            "provides_ui": bool(getattr(capabilities, "provides_ui", False)),
            "provides_api": bool(getattr(capabilities, "provides_api", False)),
            "provides_background_tasks": bool(
                getattr(capabilities, "provides_background_tasks", False)
            ),
            "provides_webhooks": bool(
                getattr(capabilities, "provides_webhooks", False)
            ),
            "communication_channel": (
                getattr(capabilities, "communication_channel", None) is not None
            ),
        }
        voice = getattr(capabilities, "voice_modality", None)
        if voice is not None:
            # ExtensionManifest already validates the version and the allowed
            # modality vocabulary. Project only navigation-relevant fields;
            # runtime health, model inventory and permissions are not leaked.
            projection["voice_modality"] = {
                "version": str(voice.version),
                "modalities": list(voice.modalities),
            }
        generative = getattr(capabilities, "generative_presentations", None)
        if generative is not None:
            # Registry metadata, NOT authorization, installed renderer health,
            # live source evidence, or permission to execute an interaction.
            projection["generative_presentations"] = {
                "version": str(generative.version),
                "component_types": list(generative.component_types),
                "surfaces": list(generative.surfaces),
                "interaction_mode": "read_only",
                "status": "declaration_only",
            }
        return projection

    @classmethod
    def _status_from_record(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        manifest = record.get("manifest")
        if manifest is None:
            raise ValueError("Plugin catalog record is missing its manifest")
        return {
            "id": manifest.name,
            "name": manifest.name,
            "display_name": getattr(manifest, "display_name", None) or manifest.name,
            "description": getattr(manifest, "description", None)
            or "No description available",
            "version": manifest.version,
            "status": str(record.get("status") or "unknown"),
            "loaded_at": None,
            "error_message": record.get("error_message"),
            "capabilities": cls._extension_capabilities(manifest),
            "menu_contributions": list(
                getattr(getattr(manifest, "ui", None), "menu_contributions", []) or []
            ),
            "rbac": {
                "allowed_roles": [
                    getattr(role, "value", str(role))
                    for role in (getattr(getattr(manifest, "rbac", None), "allowed_roles", []) or [])
                ],
                "default_enabled": bool(
                    getattr(getattr(manifest, "rbac", None), "default_enabled", False)
                ),
            },
        }

    async def refresh_registry(self) -> Dict[str, Any]:
        """Refuse unapproved registry rebuilds that can change runtime state."""
        raise PermissionError(
            "Plugin registry refresh needs governed lifecycle admission"
        )

    def list_extension_statuses(self) -> List[Dict[str, Any]]:
        service = self._service()
        if not service.initialized or service.kernel is None:
            return []
        return [
            self._status_from_record(record)
            for record in service.kernel.list_records()
        ]

    def get_extension_status(self, extension_name: str) -> Optional[Dict[str, Any]]:
        service = self._service()
        record = service.get_plugin(extension_name)
        return self._status_from_record(record) if record is not None else None

    async def reload_runtime(self) -> Dict[str, Any]:
        """Legacy reload is not an approved multi-plugin state transition."""
        raise PermissionError(
            "Plugin runtime reload needs governed lifecycle admission"
        )

    async def initialize(self) -> Dict[str, Any]:
        """Initialize the canonical service without importing plugin code."""
        await self._ensure_service()
        logger.info("Canonical plugin service initialized through platform facade")
        return self.health_summary()

    async def load_extension(
        self,
        extension_name: str,
        *,
        context: Optional["ChatExecutionContext"] = None,
        scope: Optional["PluginLifecycleApprovalScope"] = None,
        approval_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Compatibility name for one approved general-plugin enable.

        Historical callers may not use the raw PluginService enable method.
        The governed service verifies the current principal, human approval,
        global revision and actual kernel transition before reporting success.
        """
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )

        if (
            context is None
            or not isinstance(scope, PluginLifecycleApprovalScope)
            or not approval_id
        ):
            raise PermissionError("Approved lifecycle execution context required")
        if scope.installation_id != extension_name or scope.action != "enable":
            raise ValueError("Approved lifecycle action differs from requested extension")
        service = await self._ensure_service()
        receipt = await service.execute_approved_lifecycle(
            context=context, scope=scope, approval_id=approval_id,
        )
        if receipt.get("status") != "verified_committed":
            raise RuntimeError("Extension enable did not commit a verified lifecycle receipt")
        record = await service.get_plugin_info(extension_name)
        return self._status_from_record(record) if record is not None else None

    async def unload_extension(
        self,
        extension_name: str,
        *,
        context: Optional["ChatExecutionContext"] = None,
        scope: Optional["PluginLifecycleApprovalScope"] = None,
        approval_id: Optional[str] = None,
    ) -> bool:
        """Compatibility name for one approved general-plugin disable."""
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )

        if (
            context is None
            or not isinstance(scope, PluginLifecycleApprovalScope)
            or not approval_id
        ):
            raise PermissionError("Approved lifecycle execution context required")
        if scope.installation_id != extension_name or scope.action != "disable":
            raise ValueError("Approved lifecycle action differs from requested extension")
        service = await self._ensure_service()
        receipt = await service.execute_approved_lifecycle(
            context=context, scope=scope, approval_id=approval_id,
        )
        return receipt.get("status") == "verified_committed"

    async def reload_extension(self, extension_name: str) -> Optional[Dict[str, Any]]:
        """Never silently turn one reload into an unapproved enable.

        A real physical disable/re-enable requires two separate, current
        revision-bound human approvals and verified terminal receipts.
        """
        raise PermissionError(
            "Extension reload requires separately approved disable and enable transitions"
        )

    async def discover_extensions(self) -> List[Dict[str, Any]]:
        service = await self._ensure_service()
        return [
            self._status_from_record(record)
            for record in await service.list_plugins()
        ]

    @staticmethod
    def _catalog_record_visible(
        record: Dict[str, Any], user_context: Dict[str, Any]
    ) -> bool:
        from ai_karen_engine.extensions.platform.core.governance.permission_resolver import (
            PluginPermissionResolver,
        )

        manifest = record.get("manifest")
        if manifest is None:
            return False
        resolver = PluginPermissionResolver()
        result = resolver.can_view_catalog(
            manifest,
            tenant_id=user_context.get("tenant_id"),
            user_id=user_context.get("user_id"),
            user_roles=list(user_context.get("roles") or []),
        )
        return result.allowed

    async def refresh_extensions(
        self, *, user_context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        # GET/catalog projection must not silently perform a runtime rebuild.
        # Initialization already establishes the current read-only snapshot.
        service = await self._ensure_service()
        records = await service.list_plugins()
        if user_context is not None:
            records = [
                record
                for record in records
                if self._catalog_record_visible(record, user_context)
            ]
        return [self._status_from_record(record) for record in records]

    def health_summary(self) -> Dict[str, Any]:
        service = self._service()
        stats = service.get_service_stats()
        if not stats.get("initialized"):
            return {
                "registry": {"discovered_count": 0, "loaded_count": 0},
                "integration": {
                    "status": "initializing",
                    "authority": "PluginService",
                },
            }
        registry = stats.get("registry_stats", {})
        by_status = registry.get("by_status", {})
        enabled_count = sum(
            int(by_status.get(state, 0) or 0)
            for state in ("registered", "enabled", "loaded", "active")
        )
        return {
            "registry": {
                "discovered_count": int(registry.get("total_plugins", 0) or 0),
                "loaded_count": enabled_count,
            },
            "integration": {
                "status": "healthy",
                "authority": "PluginService",
            },
        }


_core_manager: ExtensionCoreManager | None = None


def get_extension_core_manager() -> ExtensionCoreManager:
    global _core_manager
    if _core_manager is None:
        _core_manager = ExtensionCoreManager()
    return _core_manager


PluginManager = ExtensionCoreManager
