"""Dependency injection helpers for Core-facing application services.

Runtime lazy loading is the single Core service-resolution authority. This
module adapts that authority to FastAPI dependencies and explicit application
service factories. It must not maintain a second service registry or fabricate
successful fallback services when a required dependency is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, cast

from fastapi import Depends, HTTPException, Request

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.config.config_manager import AIKarenConfig, get_config

logger = logging.getLogger(__name__)


async def get_user_context(request: Request) -> UserData:
    try:
        from ai_karen_engine.core.security.auth_config import auth_config

        if auth_config.should_bypass_auth():
            logger.info("Auth bypass active: providing configured developer context")
            return UserData.from_dict(auth_config.get_dev_user_context())

        from ai_karen_engine.auth.auth_middleware import get_current_user as get_real_user

        try:
            user_dict = await get_real_user(request)
            return UserData.from_dict(user_dict)
        except Exception as auth_err:
            logger.warning("Production auth failed: %s", auth_err)
            raise HTTPException(status_code=401, detail="Authentication required")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Context resolution failure: %s", exc)
        raise HTTPException(status_code=401, detail="Authentication context unavailable")


bypass_user_context_func = get_user_context


async def get_current_user_id(
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
) -> str:
    if isinstance(user_ctx, dict):
        return str(user_ctx.get("user_id", "anonymous"))
    return str(getattr(user_ctx, "user_id", "anonymous"))


async def get_current_tenant_id(
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
) -> str:
    if isinstance(user_ctx, dict):
        return str(user_ctx.get("tenant_id", "dev-tenant"))
    return str(getattr(user_ctx, "tenant_id", "dev-tenant"))


async def _get_runtime_service(service_name: str) -> Any | None:
    """Resolve one service through the canonical Runtime lazy-loading registry."""
    try:
        from ai_karen_engine.core.runtime.lazy_loading import lazy_registry, setup_lazy_services

        if not lazy_registry.list_services():
            await setup_lazy_services()
        return await lazy_registry.get_service_instance(service_name)
    except Exception as exc:
        logger.debug("Runtime service lookup for %s missed: %s", service_name, exc)
        return None


async def _resolve_service(
    service_name: str,
    factory_func: Optional[Callable[..., Any]] = None,
) -> Any:
    service = await _get_runtime_service(service_name)
    if service is not None:
        return service

    if factory_func is not None:
        try:
            service = await factory_func()
            if service is not None:
                return service
        except Exception as exc:
            logger.error("Factory resolution for %s failed: %s", service_name, exc)

    logger.error("Critical service unavailable: %s", service_name)
    raise HTTPException(
        status_code=503,
        detail=f"Service '{service_name}' is currently unavailable.",
    )


async def get_langgraph_orchestrator_service() -> Any:
    return await _resolve_service("langgraph_orchestrator")


async def get_memory_service() -> Any:
    return await _resolve_service("memory_service")


async def get_profile_service() -> Any:
    return await _resolve_service("profile_service")


async def get_persona_service() -> Any:
    async def factory() -> Any:
        from ai_karen_engine.services.persona.persona_service import (
            get_persona_service as get_persona_service_impl,
            initialize_persona_service,
        )

        service = get_persona_service_impl()
        if getattr(service, "db_client", None) is None:
            service = initialize_persona_service()
        return service

    return await _resolve_service("persona_service", factory)


async def get_conversation_service() -> Any:
    async def factory() -> Any:
        from ai_karen_engine.core.memory.service_factory import (
            create_unified_memory_service,
        )
        from ai_karen_engine.database.client import MultiTenantPostgresClient
        from ai_karen_engine.database.conversation_manager import ConversationManager
        from ai_karen_engine.services.memory.conversation_service import ConversationService

        memory_service = await _get_runtime_service("memory_service")
        if memory_service is None:
            try:
                memory_service = create_unified_memory_service()
            except Exception as exc:
                logger.error("Memory service unavailable for conversation service: %s", exc)
                raise RuntimeError("memory_service unavailable") from exc

        base_manager = ConversationManager(db_client=MultiTenantPostgresClient())
        return ConversationService(
            base_conversation_manager=cast(Any, base_manager),
            memory_service=memory_service,
        )

    return await _resolve_service("conversation_service", factory)


async def get_plugin_service() -> Any:
    """Resolve plugin capability without triggering UI materialization."""

    async def factory() -> Any:
        from pathlib import Path

        from ai_karen_engine.services.plugin_service import (
            get_plugin_service as get_plugin_service_impl,
            initialize_plugin_service,
        )

        expected_path = Path("src/ai_karen_engine/extensions/plugins")
        service = get_plugin_service_impl()
        if (
            not getattr(service, "initialized", False)
            or getattr(service, "marketplace_path", None) != expected_path
            or getattr(service, "core_plugins_path", None) != expected_path
        ):
            return await initialize_plugin_service(
                marketplace_path=expected_path,
                core_plugins_path=expected_path,
                auto_discover=True,
            )
        await service.discover_plugins()
        await service.validate_and_register_all_discovered()
        return service

    return await _resolve_service("plugin_service", factory)


async def get_tool_service() -> Any:
    async def factory() -> Any:
        from ai_karen_engine.services.tooling.tool_service import ToolService

        return ToolService()

    return await _resolve_service("tool_service", factory)


async def get_analytics_service() -> Any:
    return await _resolve_service("analytics_service")


async def get_current_config() -> AIKarenConfig:
    return get_config()


Config_Dep = Depends(get_current_config)
LangGraphOrchestrator_Dep = Depends(get_langgraph_orchestrator_service)
MemoryService_Dep = Depends(get_memory_service)
ProfileService_Dep = Depends(get_profile_service)
ConversationService_Dep = Depends(get_conversation_service)
PluginService_Dep = Depends(get_plugin_service)
ToolService_Dep = Depends(get_tool_service)
AnalyticsService_Dep = Depends(get_analytics_service)
UserContext_Dep = Depends(bypass_user_context_func)
UserId_Dep = Depends(get_current_user_id)
TenantId_Dep = Depends(get_current_tenant_id)
