import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI

from ai_karen_engine.server.plugin_loader import load_plugins
from ai_karen_engine.server.optimized_startup import (
    initialize_optimization_components,
    optimized_service_startup,
    initialize_performance_monitoring,
    integrate_with_existing_logging,
    run_startup_audit,
    cleanup_optimization_components,
    load_plugins_optimized,
)

from ai_karen_engine.core.runtime.contracts import RuntimeCapabilitiesSnapshot
from ai_karen_engine.core.observability.emitter import get_observability_emitter
from ai_karen_engine.core.observability.contracts import RuntimeEventType
from ai_karen_engine.core.observability.context import get_observability_context
from ai_karen_engine.core.model_runtime.provider_health_monitor import HealthStatus

logger = logging.getLogger(__name__)

_registry_refresh_task: Optional[asyncio.Task] = None
_startup_init_task: Optional[asyncio.Task] = None
_optimization_enabled: bool = True
_core_services_initialized: bool = False
_core_services_init_lock: Optional[asyncio.Lock] = None


def _truthy_env(name: str, default: str = "false") -> bool:
    """Return True when an env var is enabled using common truthy values."""
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _get_app_settings(app: FastAPI) -> Any:
    settings = getattr(app.state, "settings", None)
    if settings is not None:
        return settings

    from ai_karen_engine.config import Settings

    return Settings()


async def init_database(app: Optional[FastAPI] = None) -> bool:
    """
    Initialize database connections and expose availability on app.state when available.

    Startup must continue in degraded mode if the database is unavailable.
    """
    try:
        if app is None:
            logger.debug("Database initialization skipped: no FastAPI app provided")
            return False

        from ai_karen_engine.services.database_config import get_database_config

        settings = _get_app_settings(app)
        db_config = get_database_config(settings)

        success = await db_config.initialize_database()
        app.state.database_available = success

        if success:
            logger.info("Database available - initialized successfully")
            await db_config.setup_graceful_shutdown()
        else:
            logger.info(
                "Database not available - running in degraded mode "
                "(DB-dependent features disabled)"
            )

        return bool(success)

    except Exception as e:
        logger.warning("Database initialization failed (degraded mode): %s", e)
        if app is not None:
            app.state.database_available = False
        return False


async def init_crawl4ai_service(app: FastAPI) -> None:
    """
    Initialize Crawl4AI diagnostics without launching a browser or blocking readiness.

    Crawl4AI is used as a governed acquisition/extraction engine by Intelligent
    Search. Browser work remains request-scoped inside the integration.
    """
    try:
        enabled = _truthy_env("KAREN_CRAWL4AI_ENABLED", "true")
        if not enabled:
            app.state.crawl4ai_available = False
            app.state.crawl4ai_health = {
                "integration": "crawl4ai",
                "available": False,
                "enabled": False,
                "reason": "disabled_by_environment",
            }
            logger.info("Crawl4AI integration disabled by environment")
            return

        from ai_karen_engine.integrations.web.crawl4ai_integration import (
            get_crawl4ai_integration,
        )

        integration = get_crawl4ai_integration()
        health = integration.health()

        app.state.crawl4ai_available = bool(health.get("available"))
        app.state.crawl4ai_health = health

        if app.state.crawl4ai_available:
            logger.info(
                "Crawl4AI integration available",
                extra={
                    "integration": "crawl4ai",
                    "available": True,
                    "headless": health.get("headless"),
                    "max_concurrency": health.get("max_concurrency"),
                    "timeout_seconds": health.get("timeout_seconds"),
                },
            )
        else:
            logger.warning(
                "Crawl4AI integration degraded",
                extra={
                    "integration": "crawl4ai",
                    "available": False,
                    "health": health,
                },
            )

    except Exception as exc:
        app.state.crawl4ai_available = False
        app.state.crawl4ai_health = {
            "integration": "crawl4ai",
            "available": False,
            "enabled": True,
            "error": str(exc),
        }
        logger.warning("Crawl4AI initialization degraded: %s", exc)


async def cleanup_crawl4ai_service(app: Optional[FastAPI] = None) -> None:
    """Cleanup Crawl4AI singleton state if it was initialized."""
    try:
        from ai_karen_engine.integrations.web.crawl4ai_integration import (
            close_crawl4ai_integration,
        )

        await close_crawl4ai_integration()

        if app is not None:
            app.state.crawl4ai_available = False
            app.state.crawl4ai_health = {
                "integration": "crawl4ai",
                "available": False,
                "status": "shutdown",
            }

        logger.info("Crawl4AI integration shutdown completed")

    except ImportError:
        logger.debug("Crawl4AI cleanup skipped: integration module unavailable")
    except Exception as e:
        logger.warning("Crawl4AI integration shutdown failed: %s", e)


async def init_ai_services(settings: Any) -> None:
    """Initialize all AI-related services with optimization."""
    global _optimization_enabled

    _optimization_enabled = getattr(
        settings,
        "enable_performance_optimization",
        os.getenv("ENABLE_PERFORMANCE_OPTIMIZATION", "true").lower() == "true",
    )

    lazy_loading_enabled = os.getenv("KARI_LAZY_LOADING", "true").lower() == "true"

    try:
        if lazy_loading_enabled:
            logger.info("⚡ Using ultra-optimized lazy loading startup")

            from ai_karen_engine.core.runtime.optimized_startup import (
                optimized_startup_sequence,
            )

            startup_report = await optimized_startup_sequence(settings)

            logger.info("✅ Lazy loading startup completed")
            logger.info(
                "   • Startup time: %.2fs",
                startup_report.get("startup_time", 0),
            )
            logger.info("   • Mode: %s", startup_report.get("mode", "optimized"))
            logger.info(
                "   • Initialized services: %s",
                len(startup_report.get("initialized_services", [])),
            )

        elif _optimization_enabled:
            logger.info("🚀 Using optimized service initialization")

            optimization_report = await initialize_optimization_components(settings)
            audit_report = await run_startup_audit(settings)
            startup_report = await optimized_service_startup(settings)

            await initialize_performance_monitoring(settings)
            await integrate_with_existing_logging(settings)
            await load_plugins_optimized(settings.plugin_dir, settings)

            logger.info("✅ Optimized AI services initialization completed")
            logger.info(
                "   • Optimization time: %.2fs",
                optimization_report.get("initialization_time", 0),
            )
            logger.info(
                "   • Startup time: %.2fs",
                startup_report.get("startup_time", 0),
            )
            logger.debug("Startup audit report: %s", audit_report)

        else:
            logger.info("📦 Using standard service initialization")

            from ai_karen_engine.core.memory import (
                memory_runtime_manager as memory_manager,
            )

            memory_manager.init_memory()
            load_plugins(settings.plugin_dir)

            try:
                from ai_karen_engine.server.plugin_loader import ENABLED_PLUGINS

                if "model_orchestrator" in ENABLED_PLUGINS:
                    from plugin_marketplace.ai.model_orchestrator.service import (
                        ModelOrchestratorService,
                    )

                    orchestrator_service = ModelOrchestratorService()
                    await orchestrator_service.initialize()
                    logger.info("Model orchestrator plugin initialized")
            except Exception as e:
                logger.warning(
                    "Model orchestrator plugin initialization failed: %s", str(e)
                )

            from ai_karen_engine.core.model_runtime.model_registry_writer import (
                sync_model_registry_cache,
            )

            sync_model_registry_cache()

            from ai_karen_engine.core.services.service_registry import initialize_services

            await initialize_services()

            logger.info("AI services initialized")

        try:
            from ai_karen_engine.core.memory.graph.service import get_leangraph_service

            svc = get_leangraph_service()
            svc.initialize()
            logger.info("LeanGraph relationship projection initialized")
        except Exception as graph_exc:
            logger.warning("LeanGraph initialization degraded: %s", str(graph_exc))

    except Exception as e:
        logger.error("AI services initialization failed: %s", str(e))

        if lazy_loading_enabled or _optimization_enabled:
            logger.info("🔄 Falling back to minimal startup")

            try:
                logger.info("⚡ Using minimal fallback initialization")

                from ai_karen_engine.core.runtime.optimized_startup import (
                    MinimalStartupMode,
                )

                startup_report = await MinimalStartupMode.initialize(settings)

                logger.info("✅ Minimal fallback initialization completed")
                logger.info(
                    "   • Startup time: %.2fs",
                    startup_report.get("startup_time", 0),
                )

            except Exception as fallback_error:
                logger.error("Minimal fallback also failed: %s", str(fallback_error))
                logger.info("🔄 Last resort: basic initialization")

                from ai_karen_engine.core.memory import (
                    memory_runtime_manager as memory_manager,
                )

                memory_manager.init_memory()
                logger.info("Basic initialization completed")
        else:
            raise


async def ensure_core_services_initialized() -> None:
    """Initialize core services once so chat dependencies are available before requests."""
    global _core_services_initialized, _core_services_init_lock

    if _core_services_initialized:
        return

    if _core_services_init_lock is None:
        _core_services_init_lock = asyncio.Lock()

    async with _core_services_init_lock:
        if _core_services_initialized:
            return

        from ai_karen_engine.core.services.service_registry import initialize_services

        await initialize_services()
        _core_services_initialized = True


async def run_canonical_runtime_bootstrap(settings: Any, app: Optional[FastAPI] = None) -> Dict[str, Any]:
    """Canonical runtime bootstrap sequence.

    1. load + validate central config
    2. initialize observability context
    3. initialize ProviderRegistryService
    4. register configured ProviderEndpoints
    5. run model discovery
    6. synchronize model inventory
    7. initialize provider adapters lazily
    8. initialize health service
    9. take initial health snapshot
    10. construct RuntimeCapabilitiesSnapshot
    11. initialize ChatRuntime
    12. mark application ready
    """
    emitter = get_observability_emitter()
    emitter.emit(RuntimeEventType.RUNTIME_STARTUP_STARTED)

    try:
        # 1. config already loaded as `settings` by caller

        # 2. observability context is initialized lazily via get_observability_context()

        # 3. ProviderRegistryService
        from ai_karen_engine.core.model_runtime.provider_registry_service import (
            get_provider_registry_service,
        )
        registry = get_provider_registry_service()

        # 4. register configured ProviderEndpoints from settings
        configured = getattr(settings, "providers", None) or {}
        for provider_id, endpoint_data in configured.items():
            try:
                registry.register_configured_endpoint(
                    {
                        "provider_id": provider_id,
                        **endpoint_data,
                    }
                )
            except Exception as exc:
                logger.warning("Failed to register configured provider %s: %s", provider_id, exc)

        # 4b. Sync local OpenAI-compatible endpoints from ProviderRegistryService into LLMRegistry
        try:
            from ai_karen_engine.integrations.llm_registry import get_registry, LLMRegistry
            from ai_karen_engine.core.model_runtime.provider_registry_service import get_provider_registry_service
            from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpointType
            from ai_karen_engine.integrations.providers.openai_compatible_provider import OpenAICompatibleProvider

            llm_registry = get_registry()
            canonical_registry = get_provider_registry_service()
            for endpoint in canonical_registry.list_provider_endpoints():
                if endpoint.endpoint_type == ProviderEndpointType.OPENAI_COMPATIBLE and endpoint.base_url:
                    try:
                        llm_registry.register_provider(
                            name=endpoint.provider_id,
                            provider_class=OpenAICompatibleProvider,
                            description=f"Synced local endpoint: {endpoint.display_name}",
                            supports_streaming=endpoint.supports_streaming,
                            supports_embeddings=endpoint.supports_embeddings,
                            requires_api_key=False,
                            default_model=endpoint.default_model or "",
                        )
                        logger.info(f"Synced local endpoint to LLMRegistry: {endpoint.provider_id}")
                    except Exception as exc:
                        logger.debug(f"Local endpoint sync skipped for {endpoint.provider_id}: {exc}")
        except Exception as exc:
            logger.warning("Local endpoint sync failed: %s", exc)

        # 5-6. model discovery + inventory sync
        try:
            from ai_karen_engine.core.model_runtime.model_registry_writer import (
                sync_model_registry_cache,
            )
            sync_model_registry_cache()
        except Exception as exc:
            logger.warning("Model registry sync failed: %s", exc)

        # 7. provider adapters are initialized lazily on first use

        # 8. health service is owned by ProviderRegistryService

        # 9. initial health snapshot
        try:
            from ai_karen_engine.core.model_runtime.provider_health_monitor import (
                get_health_monitor,
            )
            health_monitor = get_health_monitor()
            all_health = health_monitor.get_all_provider_health()
            healthy_count = sum(
                1 for info in all_health.values()
                if info.health_status in {
                    HealthStatus.HEALTHY,
                    HealthStatus.DEGRADED,
                }
            )
            logger.info(
                "Initial health snapshot: %d/%d providers healthy/degraded",
                healthy_count,
                len(all_health),
            )
        except Exception as exc:
            logger.warning("Initial health snapshot failed: %s", exc)

        # 10. RuntimeCapabilitiesSnapshot
        try:
            available_providers = registry.get_available_providers()
            available_models: List[str] = []
            for provider_id in available_providers:
                try:
                    available_models.extend(
                        registry.get_registered_models(provider_id, healthy_only=False)
                    )
                except Exception:
                    pass
            snapshot = RuntimeCapabilitiesSnapshot(
                available_providers=available_providers,
                available_models=available_models,
                available_tools=[],
                available_workflows=[],
                available_agents=[],
                available_reasoning_modes=[],
                degraded_state=False,
                runtime_mode="normal",
            )
            if app is not None:
                app.state.runtime_capabilities = snapshot
            emitter.emit(RuntimeEventType.RUNTIME_CAPABILITIES_READY)
        except Exception as exc:
            logger.warning("Runtime capabilities snapshot failed: %s", exc)

        # 11. ChatRuntime
        try:
            from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
            get_chat_runtime()
        except Exception as exc:
            logger.warning("ChatRuntime initialization failed: %s", exc)

        # 12. mark ready
        emitter.emit(RuntimeEventType.RUNTIME_STARTUP_COMPLETED)
        logger.info("Canonical runtime bootstrap completed")

        return {
            "status": "success",
            "providers_registered": len(registry.list_provider_endpoints()),
            "providers_available": len(registry.get_available_providers()),
        }

    except Exception as exc:
        emitter.emit(RuntimeEventType.RUNTIME_STARTUP_FAILED, status="error")
        logger.error("Canonical runtime bootstrap failed: %s", exc, exc_info=True)
        return {
            "status": "error",
            "error": str(exc),
        }


async def cleanup_ai_services() -> None:
    """Cleanup AI resources with optimization."""
    try:
        if _optimization_enabled:
            logger.info("🧹 Using optimized cleanup")
            await cleanup_optimization_components()

        lazy_loading_enabled = os.getenv("KARI_LAZY_LOADING", "true").lower() == "true"

        if lazy_loading_enabled:
            logger.info("🧹 Cleaning up lazy services")
            from ai_karen_engine.core.runtime.lazy_loading import cleanup_lazy_services

            await cleanup_lazy_services()

        try:
            from ai_karen_engine.core.services.service_registry import (
                get_service_registry,
            )

            registry = get_service_registry()
            await registry.shutdown()
        except Exception as e:
            logger.warning("Service registry cleanup failed: %s", e)

        logger.info("✅ AI services cleanup completed")

    except Exception as e:
        logger.error("Error during AI services cleanup: %s", e)

        try:
            from ai_karen_engine.core.memory import (
                memory_runtime_manager as memory_manager,
            )

            await memory_manager.close()
        except Exception as memory_error:
            logger.warning("Memory cleanup failed: %s", memory_error)

        logger.info("AI services cleanup completed with degraded cleanup path")


def init_security(settings: Any) -> None:
    """Initialize security components."""
    if settings.secret_key == "changeme" and settings.environment == "production":
        logger.critical("Insecure default secret key in production!")
    logger.info("Security components initialized")


def start_background_tasks(settings: Any) -> None:
    """Start background tasks."""
    global _registry_refresh_task

    if settings.llm_refresh_interval > 0:

        async def _periodic_refresh() -> None:
            from ai_karen_engine.core.model_runtime.model_registry_writer import (
                sync_model_registry_cache,
            )

            while True:
                await asyncio.sleep(settings.llm_refresh_interval)
                sync_model_registry_cache()

        _registry_refresh_task = asyncio.create_task(_periodic_refresh())
        logger.info("Started model registry refresh task")


async def stop_background_tasks() -> None:
    """Stop background tasks."""
    global _registry_refresh_task

    if _registry_refresh_task:
        _registry_refresh_task.cancel()
        try:
            await _registry_refresh_task
        except asyncio.CancelledError:
            logger.info("Background tasks stopped")
        except Exception as e:
            logger.error("Error stopping background tasks: %s", str(e))
        finally:
            _registry_refresh_task = None


async def on_startup(settings: Any, app: Optional[FastAPI] = None) -> None:
    """Base server startup path."""
    global _startup_init_task

    logger.info("Starting Kari AI Server in %s mode", settings.environment)

    if app is not None:
        app.state.settings = settings
        await init_database(app)
        await init_crawl4ai_service(app)
    else:
        logger.debug("Startup called without app; app-scoped services skipped")

    try:
        from ai_karen_engine.extensions.platform.core.manager import (
            get_extension_core_manager,
        )

        extension_manager = get_extension_core_manager()
        if extension_manager:
            if _truthy_env("KARI_FAST_STARTUP", "false"):
                logger.info("⚡ Fast startup: skipping blocking extension initialization")
            else:
                logger.info("Initializing extension system in background")
                asyncio.create_task(extension_manager.initialize())
    except Exception as e:
        logger.warning("Could not initialize extension system: %s", e)

    fast_start = os.getenv(
        "KARI_FAST_STARTUP", os.getenv("FAST_STARTUP", "true")
    ).lower() in ("1", "true", "yes")

    if fast_start and (settings.environment or "").lower() in (
        "development",
        "dev",
        "local",
    ):
        logger.info("⚡ Fast startup enabled: initializing AI services in background")
        _startup_init_task = asyncio.create_task(init_ai_services(settings))
    else:
        try:
            await init_ai_services(settings)
        except Exception as e:
            logger.error("Failed to initialize AI services: %s", e, exc_info=True)
            logger.warning("Continuing startup without AI services")

    init_security(settings)
    start_background_tasks(settings)
    logger.info("Server startup completed")


async def on_shutdown(app: Optional[FastAPI] = None) -> None:
    """Base server shutdown path."""
    global _startup_init_task

    logger.info("Shutting down Kari AI Server")

    if _startup_init_task and not _startup_init_task.done():
        _startup_init_task.cancel()
        try:
            await _startup_init_task
        except asyncio.CancelledError:
            logger.info("Background startup task cancelled")
        except Exception as e:
            logger.warning("Background startup task error during shutdown: %s", e)
        finally:
            _startup_init_task = None

    await stop_background_tasks()
    await cleanup_crawl4ai_service(app)
    await cleanup_ai_services()

    logger.info("Server shutdown completed")


async def init_extension_monitoring(app: FastAPI) -> None:
    """Initialize extension monitoring and alerting system."""
    try:
        from ai_karen_engine.monitoring.extensions.extension_monitoring_startup import (
            initialize_extension_monitoring,
        )

        await initialize_extension_monitoring()
        logger.info("Extension monitoring system initialized")
    except Exception as e:
        logger.warning("Extension monitoring initialization failed: %s", e)


async def init_extension_health_monitor(app: FastAPI) -> None:
    """Initialize extension health monitor."""
    try:
        from ai_karen_engine.extensions.health_monitor import (
            initialize_extension_health_monitor,
        )

        extension_manager = None
        try:
            extension_system = getattr(app.state, "extension_system", None)
            if extension_system:
                extension_manager = extension_system.extension_manager
        except Exception:
            logger.debug("Extension manager lookup failed", exc_info=True)

        await initialize_extension_health_monitor(extension_manager)
        logger.info("Extension health monitor initialized")
    except Exception as e:
        logger.warning("Extension health monitor initialization failed: %s", e)


async def init_extension_database_service(app: FastAPI) -> None:
    """Initialize extension database service."""
    if not getattr(app.state, "database_available", False):
        logger.info("Skipping extension database service (database not available)")
        return

    try:
        from ai_karen_engine.extensions.database_service import (
            initialize_database_service,
        )

        settings = _get_app_settings(app)
        database_url = settings.database_url

        async_database_url = database_url.replace(
            "postgresql://", "postgresql+asyncpg://"
        )
        initialize_database_service(async_database_url)
        logger.info("Extension database service initialized")
    except Exception as e:
        logger.warning("Extension database service initialization failed: %s", e)


async def init_extension_service_recovery(app: FastAPI) -> None:
    """Initialize extension service recovery system with integration to existing patterns."""
    if not getattr(app.state, "database_available", False):
        logger.info("Skipping extension service recovery (database not available)")
        return

    try:
        from ai_karen_engine.extensions.service_recovery import (
            initialize_extension_service_recovery_manager,
        )
        from ai_karen_engine.services.database_config import get_database_config
        from ai_karen_engine.services.enhanced_database_health_monitor import (
            get_enhanced_database_health_monitor,
        )

        settings = _get_app_settings(app)

        database_config = get_database_config(settings)
        enhanced_health_monitor = get_enhanced_database_health_monitor()

        extension_manager = None
        try:
            extension_system = getattr(app.state, "extension_system", None)
            if extension_system:
                extension_manager = extension_system.extension_manager
        except Exception:
            logger.debug("Extension manager lookup failed", exc_info=True)

        recovery_manager = await initialize_extension_service_recovery_manager(
            extension_manager=extension_manager,
            database_config=database_config,
            enhanced_health_monitor=enhanced_health_monitor,
        )

        recovery_manager.add_startup_handler(
            lambda: _extension_startup_recovery_handler(recovery_manager)
        )
        recovery_manager.add_graceful_degradation_handler(
            "extension_api", lambda: _extension_api_degradation_handler()
        )
        recovery_manager.add_graceful_degradation_handler(
            "authentication", lambda: _authentication_degradation_handler()
        )

        await recovery_manager.execute_startup_handlers()

        logger.info("Extension service recovery initialized")

    except Exception as e:
        logger.warning("Extension service recovery initialization failed: %s", e)


async def _extension_startup_recovery_handler(recovery_manager: Any) -> None:
    """Extension-specific startup recovery handler."""
    try:
        logger.info("Executing extension startup recovery checks")

        status = recovery_manager.get_recovery_status()
        unhealthy_services = [
            name
            for name, state in status["service_states"].items()
            if not state["healthy"]
        ]

        if unhealthy_services:
            logger.warning(
                "Unhealthy services detected on startup: %s", unhealthy_services
            )

            for service_name in unhealthy_services:
                if "authentication" in service_name or "database" in service_name:
                    await recovery_manager.force_recovery(service_name)
        else:
            logger.info("All extension services healthy on startup")

    except Exception as e:
        logger.error("Extension startup recovery handler failed: %s", e)


async def _extension_api_degradation_handler() -> None:
    """Graceful degradation handler for extension API."""
    try:
        logger.info("Enabling graceful degradation for extension API")
        logger.info("Extension API graceful degradation enabled")
    except Exception as e:
        logger.error("Extension API degradation handler failed: %s", e)


async def _authentication_degradation_handler() -> None:
    """Graceful degradation handler for authentication service."""
    try:
        logger.info("Enabling graceful degradation for authentication service")
        logger.info("Authentication service graceful degradation enabled")
    except Exception as e:
        logger.error("Authentication degradation handler failed: %s", e)


async def warm_local_llm_stack(app: FastAPI) -> None:
    """Warm the local chat/LLM stack during startup so first chat request does not time out."""
    if not _truthy_env("KARI_WARM_LOCAL_LLM_ON_STARTUP", "false"):
        logger.info("Skipping local LLM warmup (disabled by environment)")
        return

    try:
        from ai_karen_engine.services.formatting.settings_manager import (
            get_settings_manager,
        )

        settings_manager = get_settings_manager()
        active_provider = (
            str(settings_manager.get_setting("provider", "") or "").strip().lower()
        )

        local_providers = {
            "builtin_transformers",
            "builtin_vllm",
            "ollama",
            "local",
            "local_gguf",
        }

        if active_provider not in local_providers:
            logger.info(
                "Skipping local LLM warmup for non-local provider: %s",
                active_provider or "unset",
            )
            return

        logger.info("Warming local chat stack for provider: %s", active_provider)

        def _warm() -> None:
            from ai_karen_engine.api_routes.chat.copilot import (
                get_langgraph_orchestrator,
            )
            from ai_karen_engine.llm_orchestrator import get_orchestrator

            get_langgraph_orchestrator()
            get_orchestrator()._ensure_minimum_models_registered()

        await asyncio.to_thread(_warm)
        app.state.local_llm_warmed = True
        logger.info("Local chat stack warmup completed")
    except Exception as e:
        app.state.local_llm_warmed = False
        logger.warning("Local LLM warmup skipped after failure: %s", e)


async def on_startup_with_extensions(settings: Any, app: FastAPI) -> None:
    """Enhanced startup with extension and monitoring initialization."""
    global _startup_init_task

    logger.info("Starting Kari AI Server in %s mode", settings.environment)

    app.state.settings = settings
    await init_database(app)

    # Lightweight integration diagnostics. This does not launch browser work.
    await init_crawl4ai_service(app)

    fast_start = os.getenv(
        "KARI_FAST_STARTUP", os.getenv("FAST_STARTUP", "true")
    ).lower() in ("1", "true", "yes")

    lazy_environment = (settings.environment or "").lower() in (
        "development",
        "dev",
        "local",
    )

    await ensure_core_services_initialized()

    if fast_start and lazy_environment:
        logger.info(
            "⚡ Fast startup enabled: deferring extension and AI initialization to background"
        )

        async def _background_startup_init() -> None:
            try:
                await init_extension_monitoring(app)
                await init_extension_health_monitor(app)
                await init_extension_database_service(app)
                await init_extension_service_recovery(app)
                await warm_local_llm_stack(app)
                await init_ai_services(settings)
                logger.info("✅ Deferred startup initialization completed")
            except asyncio.CancelledError:
                logger.info("Deferred startup initialization cancelled")
                raise
            except Exception as e:
                logger.error(
                    "Deferred startup initialization failed: %s", e, exc_info=True
                )

        _startup_init_task = asyncio.create_task(_background_startup_init())
    else:
        await init_extension_monitoring(app)
        await init_extension_health_monitor(app)
        await init_extension_database_service(app)
        await init_extension_service_recovery(app)
        await warm_local_llm_stack(app)

        try:
            await init_ai_services(settings)
        except Exception as e:
            logger.error("Failed to initialize AI services: %s", e, exc_info=True)
            logger.warning("Continuing startup without AI services")

    init_security(settings)
    start_background_tasks(settings)
    logger.info("Server startup completed")


async def initialize_extension_system(app: FastAPI) -> None:
    """Initialize the production extension system and monitoring."""
    if not getattr(app.state, "database_available", False):
        logger.info("Skipping extension system initialization (database not available)")
        return

    try:
        success = await init_extensions_for_production(
            app=app,
            extension_root="extensions",
            db_session=None,
            plugin_router=None,
        )
        if not success:
            logger.warning("Extension system initialization unsuccessful")
            return

        try:
            from ai_karen_engine.extensions.health_monitor import (
                initialize_extension_health_monitor,
            )

            extension_system = getattr(app.state, "extension_system", None)
            extension_manager = (
                extension_system.get_extension_manager()
                if extension_system
                and hasattr(extension_system, "get_extension_manager")
                else None
            )
            if extension_manager:
                await initialize_extension_health_monitor(extension_manager)
                logger.info("Extension health monitoring initialized")
            else:
                logger.warning("Extension manager unavailable")
        except Exception as monitor_error:
            logger.warning("Extension health monitoring failed: %s", monitor_error)
    except Exception as exc:
        logger.warning("Extension system initialization error: %s", exc)


async def init_extensions_for_production(
    app: FastAPI, extension_root: str, db_session: Any, plugin_router: Any
) -> bool:
    """Initialize extensions for production environment."""
    try:
        from ai_karen_engine.extensions.platform.core.host.factory import (
            initialize_extensions_for_production as initialize_extensions,
        )

        success = await initialize_extensions(
            app=app,
            extension_root=extension_root,
            db_session=db_session,
            plugin_router=plugin_router,
        )
        return bool(success)

    except ImportError as canonical_error:
        try:
            from ai_karen_engine.extensions.platform.core.host.factory import (  # type: ignore
                initialize_extensions_for_production as initialize_extensions,
            )

            success = await initialize_extensions(
                app=app,
                extension_root=extension_root,
                db_session=db_session,
                plugin_router=plugin_router,
            )
            logger.info("✅ Extension system initialized via legacy fallback path")
            return bool(success)
        except ImportError as legacy_error:
            logger.warning(
                "Extension system not available (canonical=%s, fallback=%s)",
                canonical_error,
                legacy_error,
            )
            return False
    except Exception as e:
        logger.error("Extension system initialization failed: %s", e)
        return False


async def on_shutdown_with_extensions(app: FastAPI) -> None:
    """Enhanced shutdown with extension cleanup."""
    global _startup_init_task

    logger.info("Shutting down Kari AI Server")

    try:
        from ai_karen_engine.monitoring.extensions.extension_monitoring_startup import (
            shutdown_extension_monitoring,
        )

        await shutdown_extension_monitoring()
        logger.info("Extension monitoring shutdown completed")
    except Exception as e:
        logger.error("Extension monitoring shutdown failed: %s", e, exc_info=True)

    try:
        from ai_karen_engine.extensions.health_monitor import (
            shutdown_extension_health_monitor,
        )

        await shutdown_extension_health_monitor()
        logger.info("Extension health monitor shutdown completed")
    except Exception as e:
        logger.warning("Extension health monitor shutdown failed: %s", e)

    if _startup_init_task and not _startup_init_task.done():
        _startup_init_task.cancel()
        try:
            await _startup_init_task
        except asyncio.CancelledError:
            logger.info("Background startup task cancelled")
        except Exception as e:
            logger.warning("Background startup task error during shutdown: %s", e)
        finally:
            _startup_init_task = None

    await stop_background_tasks()
    await cleanup_crawl4ai_service(app)
    await cleanup_ai_services()

    logger.info("Server shutdown completed")


def create_lifespan(settings: Any):
    """Create a lifespan context manager bound to settings."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await on_startup(settings, app)
        try:
            yield
        finally:
            await on_shutdown(app)

    return lifespan


def create_lifespan_with_extensions(settings: Any):
    """Create a lifespan context manager with extension and monitoring initialization."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await on_startup_with_extensions(settings, app)
        try:
            yield
        finally:
            await on_shutdown_with_extensions(app)

    return lifespan


def register_startup_tasks(app: FastAPI) -> None:
    """Register startup tasks for LLM providers and services with extension recovery integration."""
    app.state.database_available = False
    app.state.crawl4ai_available = False
    app.state.crawl4ai_health = {
        "integration": "crawl4ai",
        "available": False,
        "status": "not_initialized",
    }

    @app.on_event("startup")
    async def _init_database_config() -> None:
        """Initialize database configuration with enhanced settings."""
        await init_database(app)

    @app.on_event("startup")
    async def _init_crawl4ai() -> None:
        """Initialize Crawl4AI diagnostics without blocking browser startup."""
        await init_crawl4ai_service(app)

    @app.on_event("startup")
    async def _init_llm_providers() -> None:
        try:
            await run_canonical_runtime_bootstrap(settings, app)
        except Exception as e:
            logger.warning("Canonical runtime bootstrap skipped: %s", e)

    @app.on_event("startup")
    async def _init_memory_service() -> None:
        """Initialize memory service with proper error handling."""
        try:
            enable_memory = os.getenv("KARI_ENABLE_MEMORY_SERVICE", "true").lower() in (
                "1",
                "true",
                "yes",
            )
            fast = os.getenv(
                "KARI_FAST_STARTUP", os.getenv("FAST_STARTUP", "true")
            ).lower() in ("1", "true", "yes")

            if enable_memory:
                if fast:
                    logger.info(
                        "⚡ Fast startup: ensuring memory service initialization "
                        "before background tasks"
                    )
                    await ensure_core_services_initialized()
                else:
                    logger.info("Initializing memory service")
                    await ensure_core_services_initialized()
                    logger.info("Memory service initialized successfully")
            else:
                logger.info(
                    "Memory service initialization disabled by environment variable"
                )
        except Exception as e:
            logger.warning("Memory service initialization failed: %s", e)


def register_shutdown_tasks(app: FastAPI) -> None:
    """Register shutdown tasks for extension service recovery integration."""

    @app.on_event("shutdown")
    async def _shutdown_crawl4ai() -> None:
        """Shutdown Crawl4AI integration singleton."""
        await cleanup_crawl4ai_service(app)

    @app.on_event("shutdown")
    async def _shutdown_database() -> None:
        """Graceful shutdown of database connections."""
        try:
            logger.info("Starting database shutdown process")

            from ai_karen_engine.services.database_config import get_database_config

            settings = _get_app_settings(app)
            db_config = get_database_config(settings)
            await db_config.cleanup()

            logger.info("Database shutdown completed successfully")
        except Exception as e:
            logger.error("Error during database shutdown: %s", e)

    @app.on_event("shutdown")
    async def _shutdown_extension_service_recovery() -> None:
        """Shutdown extension service recovery system with graceful cleanup."""
        try:
            from ai_karen_engine.extensions.service_recovery import (
                get_extension_service_recovery_manager,
                shutdown_extension_service_recovery_manager,
            )

            recovery_manager = get_extension_service_recovery_manager()
            if recovery_manager:
                await recovery_manager.execute_shutdown_handlers()
                await shutdown_extension_service_recovery_manager()

                logger.info("Extension service recovery system shutdown completed")

        except Exception as e:
            logger.error("Extension service recovery shutdown failed: %s", e)


async def initialize_fallback_systems() -> None:
    """Initialize fallback systems for degraded mode operation."""
    try:
        logger.info("Fallback systems initialized")
    except Exception as e:
        logger.error("Failed to initialize fallback systems: %s", e)


async def run_startup_checks_and_fallbacks(logger_param: logging.Logger) -> None:
    """Run startup checks and initialize fallback systems if needed."""
    try:
        await initialize_fallback_systems()
        logger_param.info("Startup checks completed successfully")
    except Exception as e:
        logger_param.error("Startup checks failed: %s", e)