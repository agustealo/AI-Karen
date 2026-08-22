"""
Dependency Injection Framework for AI Karen Engine.

This module provides a unified, production-grade dependency management system.
It supports multiple resolution strategies:
1. Dynamic Service Registry (Primary)
2. Optimized Lazy Loading (Secondary Fallback)
3. Direct Factory Injection (Final Resilience Fallback)
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional, Callable, Union, Literal, TYPE_CHECKING, cast

from fastapi import Depends, HTTPException, Request

from ai_karen_engine.config.config_manager import AIKarenConfig, get_config

# from ai_karen_engine.core.services.service_registry import get_service_registry  <- Moved to local scope
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.auth.auth_middleware import AuthenticationError

logger = logging.getLogger(__name__)


class _NoopConversationMemoryService:
    """Lightweight fallback used when the full memory stack is unavailable."""

    db_client = None

    async def initialize(self) -> None:
        return None

    async def query(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(hits=[])

    async def query_memories(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    async def commit(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(id=None, success=False)

    async def store_web_ui_memory(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def build_conversation_context(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "memories": [],
            "total_memories": 0,
            "memory_types_found": [],
            "conversation_context": None,
            "query_analysis": {},
            "context_metadata": {},
        }

# --- Authentication Dependencies ---


async def get_user_context(request: Request) -> UserData:
    """
    Unified user context provider.
    Handles both development bypass and real production authentication.
    """
    try:
        from ai_karen_engine.core.security.auth_config import auth_config

        # 1. Check for explicit Auth Bypass (Dev/Test mode)
        if auth_config.should_bypass_auth():
            logger.info("Auth Bypass Active: Providing elevated developer context")
            payload = auth_config.get_dev_user_context()
            return UserData.from_dict(payload)

        # 2. Production Path: Real Authentication via Auth Middleware
        #    Fail closed: production auth failure is 401, not anonymous.
        from ai_karen_engine.auth.auth_middleware import get_current_user as get_real_user
        
        try:
            user_dict = await get_real_user(request)
            return UserData.from_dict(user_dict)
        except Exception as auth_err:
            logger.warning("Production auth failed: %s", auth_err)
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
            )

        # 3. Fallback: Anonymous User — REMOVED per CHAT-LIVE fail-closed auth
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Context resolution failure: %s", e)
        raise HTTPException(
            status_code=401, detail="Authentication context unavailable"
        )


# Alias for backward compatibility while we migrate
bypass_user_context_func = get_user_context


async def get_current_user_id(
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
) -> str:
    return str(user_ctx.get("user_id", "anonymous"))


async def get_current_tenant_id(
    user_ctx: Dict[str, Any] = Depends(bypass_user_context_func),
) -> str:
    return str(user_ctx.get("tenant_id", "dev-tenant"))


# --- Core Service Resolution Helper ---


async def _resolve_service(
    service_name: str, factory_func: Optional[Callable] = None
) -> Any:
    """
    internal helper following the DRY principle for service discovery.
    Tries Registry -> Lazy Loading -> Factory.
    """
    # 1. Primary: Service Registry
    try:
        from ai_karen_engine.core.services.service_registry import get_service_registry
        registry = get_service_registry()
        service = await registry.get_service(service_name)
        if service:
            return service
    except Exception as e:
        logger.debug(f"Registry lookup for {service_name} missed: {e}")

    # 2. Secondary: Lazy Loading
    try:
        from ai_karen_engine.core.runtime.lazy_loading import lazy_registry, setup_lazy_services

        if not lazy_registry.list_services():
            await setup_lazy_services()

        service = await lazy_registry.get_service_instance(service_name)
        if service:
            return service
    except Exception as e:
        logger.debug(f"Lazy loading fallback for {service_name} missed: {e}")

    # 3. Final: Factory Fallback
    if factory_func:
        try:
            logger.info(
                f"🔄 Final resilience fallback: Executing factory for {service_name}"
            )
            service = await factory_func()
            if service:
                return service
        except Exception as e:
            logger.error(f"❌ Factory fallback for {service_name} failed: {e}")

    logger.error(f"❌ Critical Service Failure: {service_name} is unavailable.")
    raise HTTPException(
        status_code=503, detail=f"Service '{service_name}' is currently unavailable."
    )


# --- Public Service Dependencies ---


async def get_langgraph_orchestrator_service() -> Any:
    """Discovery for the LangGraph orchestrator service."""
    return await _resolve_service("langgraph_orchestrator")


async def get_memory_service() -> Any:
    """Discovery for Memory service."""
    return await _resolve_service("memory_service")


async def get_profile_service() -> Any:
    """Discovery for Profile service."""
    return await _resolve_service("profile_service")


async def get_persona_service() -> Any:
    """Discovery for Persona service."""

    async def factory():
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
    """Discovery for Conversation service with complex legacy mapping support."""

    async def factory():
        from ai_karen_engine.services.memory.conversation_service import ConversationService
        from ai_karen_engine.core.memory.memory_service import WebUIMemoryService
        from ai_karen_engine.database.conversation_manager import ConversationManager
        from ai_karen_engine.database.client import MultiTenantPostgresClient

        memory_service = None
        try:
            from ai_karen_engine.core.services.service_registry import (
                get_memory_service as resolve_memory_service,
            )

            memory_service = await resolve_memory_service()
        except Exception:
            try:
                from ai_karen_engine.core.runtime.lazy_loading import lazy_registry

                memory_service = await lazy_registry.get_service_instance(
                    "memory_service"
                )
            except Exception:
                memory_service = None

        if memory_service is None:
            try:
                memory_service = WebUIMemoryService()
            except Exception as exc:
                logger.warning(
                    "Falling back to no-op conversation memory service: %s", exc
                )
                memory_service = _NoopConversationMemoryService()

        base_manager = ConversationManager(db_client=MultiTenantPostgresClient())

        return ConversationService(
            base_conversation_manager=cast(Any, base_manager),
            memory_service=memory_service,
        )

    return await _resolve_service("conversation_service", factory)


async def get_plugin_service() -> Any:
    async def factory():
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
            service = await initialize_plugin_service(
                marketplace_path=expected_path,
                core_plugins_path=expected_path,
                auto_discover=True,
            )
        else:
            # Service initialized but maybe not discovered lately
            await service.discover_plugins()
            await service.validate_and_register_all_discovered()

        # Automatically trigger UI materialization to sync files to plugin_repo
        try:
            from ai_karen_engine.extensions.platform.core.registry.ui_materialization import (
                get_ui_pipeline,
            )

            pipeline = get_ui_pipeline()
            # This is an async call but we can run it in the background or await it
            await pipeline.materialize_all()
            logger.info(
                "UI materialization completed during plugin service acquisition"
            )
        except Exception as ui_err:
            logger.warning(f"Auto UI materialization failed: {ui_err}")

        return service

    return await _resolve_service("plugin_service", factory)


async def get_tool_service() -> Any:
    async def factory():
        from ai_karen_engine.services.tooling.tool_service import ToolService

        return ToolService()

    return await _resolve_service("tool_service", factory)


async def get_analytics_service() -> Any:
    return await _resolve_service("analytics_service")


async def get_current_config() -> AIKarenConfig:
    return get_config()


async def get_service_registry_instance() -> Any:
    return get_service_registry()


# --- Dependency Injection Aliases (The API Surface) ---

Config_Dep = Depends(get_current_config)
ServiceRegistry_Dep = Depends(get_service_registry_instance)

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
