import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("kari.plugin_manager")


@dataclass
class ExtensionExecutionResult:
    extension_id: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


class PluginManager:
    """
    Unified Application Integration Layer for Karen AI Extensions.
    Coordinated by:
    - ExtensionLifecycleManager: State and Discovery
    - PermissionsManager: RBAC and Security
    - PluginRouter: AI Orchestration and Dispatch
    """

    def __init__(self, extensions_dir: str = "src/ai_karen_engine/extensions/plugins"):
        from .permissions_manager import PermissionsManager
        from .sandbox_manager import SandboxManager
        from ..host.router import get_plugin_router
        from ..registry.plugin_registry import get_registry

        self.extensions_dir = extensions_dir
        self.registry = get_registry()
        self.router = get_plugin_router()
        self.permissions = PermissionsManager()
        self.sandbox = SandboxManager()
        self.lifecycle = None

    def _ensure_lifecycle_manager(self):
        if self.lifecycle is None:
            from .lifecycle_manager import ExtensionLifecycleManager

            self.lifecycle = ExtensionLifecycleManager(
                extensions_dir=self.extensions_dir,
                app_instance=None,  # Wired during app startup
            )
        return self.lifecycle

    async def initialize(self):
        """Perform full system initialization."""
        logger.info("Initializing Modular Extension Backbone...")
        lifecycle = self._ensure_lifecycle_manager()
        await lifecycle.initialize()
        await self.router.reload()
        logger.info("Modular Extension Backbone Ready.")

    async def run_plugin(
        self, name: str, params: Dict[str, Any], user_ctx: Dict[str, Any]
    ) -> Any:
        """
        Main execution entry point from the Engine.
        Enforces permissions and delegates to Router for dispatch.
        """
        # 1. Permission Check
        roles = user_ctx.get("roles", [])
        if not await self.permissions.check_permission(name, roles):
            raise PermissionError(
                f"User roles {roles} not permitted for extension {name}"
            )

        # 2. Dispatch
        return await self.router.dispatch(name, params, roles=roles)

    async def dispatch_agent_action(self, agent_action: Any, context: Any):
        """
        Dispatch an agent action to the appropriate extension.

        This method takes a standardized AgentAction and routes it to the
        appropriate extension based on intent or explicit extension_id,
        enforcing RBAC/permissions before execution.

        Args:
            agent_action: AgentAction instance with type, tool, extension_id, params
            context: ProcessingContext with user information and metadata

        Returns:
            ExtensionExecutionResult with success status and data
        """
        import time

        start_time = time.time()
        extension_id = agent_action.extension_id or agent_action.tool

        if not extension_id:
            return ExtensionExecutionResult(
                extension_id="unknown",
                success=False,
                error="No extension_id or tool specified in agent action",
                execution_time_ms=0,
            )

        user_ctx = {
            "roles": getattr(context, "user_roles", []),
            "user_id": context.user_id,
            "tenant_id": getattr(context, "tenant_id", "default"),
            "correlation_id": context.correlation_id,
        }

        try:
            result = await self.run_plugin(
                name=extension_id, params=agent_action.params, user_ctx=user_ctx
            )

            execution_time = int((time.time() - start_time) * 1000)

            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=True,
                data={"result": result} if not isinstance(result, dict) else result,
                execution_time_ms=execution_time,
            )

        except PermissionError as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.warning(f"Permission denied for extension {extension_id}: {e}")
            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=False,
                error=f"Permission denied: {str(e)}",
                execution_time_ms=execution_time,
            )

        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            logger.error(
                f"Extension execution failed for {extension_id}: {e}", exc_info=True
            )
            return ExtensionExecutionResult(
                extension_id=extension_id,
                success=False,
                error=str(e),
                execution_time_ms=execution_time,
            )

    def get_health_summary(self) -> Dict[str, Any]:
        """Summarize health across all extensions via LifecycleManager."""
        lifecycle = self.lifecycle
        active = lifecycle.get_active_extensions() if lifecycle else []
        total = len(self.registry.list_discovered())
        return {
            "status": "healthy" if len(active) > 0 or total == 0 else "degraded",
            "active_count": len(active),
            "discovered_count": total,
            "lifecycle_states": {
                name: state.value for name, state in lifecycle.extension_states.items()
            }
            if lifecycle
            else {},
        }


# Singleton accessor
_manager_instance: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PluginManager()
    return _manager_instance
