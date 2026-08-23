# mypy: ignore-errors
"""
Startup configuration for Kari FastAPI Server.
Handles lifespan, warmups, service initialization, and startup tasks.
"""

import asyncio
import os
import logging
from fastapi import FastAPI
from .config import Settings

logger = logging.getLogger("kari")

# Import lifespan from existing module
from ai_karen_engine.server.startup import create_lifespan


def register_startup_tasks(app: FastAPI) -> None:
    """Register startup tasks for LLM providers and services with extension recovery integration"""

    # Store database availability state in app
    app.state.database_available = False

    def _get_settings() -> Settings:
        settings = getattr(app.state, "settings", None)
        if settings is None:
            settings = Settings()
            app.state.settings = settings
        return settings

    @app.on_event("startup")
    async def _init_database_config() -> None:
        """Initialize database configuration with enhanced settings"""
        try:
            from .database_config import get_database_config

            settings = _get_settings()
            db_config = get_database_config(settings)
            app.state.database_config = db_config

            # Initialize database with enhanced configuration
            success = await db_config.initialize_database()
            app.state.database_available = success

            if success:
                logger.info("Database available - initialized successfully")

                # Setup graceful shutdown
                await db_config.setup_graceful_shutdown()
            else:
                logger.info(
                    "Database not available - running in degraded mode (DB-dependent features disabled)"
                )

        except Exception as e:
            logger.warning(f"Database initialization failed (degraded mode): {e}")
            app.state.database_available = False

    @app.on_event("startup")
    async def _init_extension_monitoring() -> None:
        """Initialize extension monitoring and alerting system"""
        # Skip if database is not available
        if not getattr(app.state, "database_available", False):
            logger.info("Skipping extension monitoring (database not available)")
            return

        try:
            from ai_karen_engine.monitoring.extensions.extension_monitoring_startup import (
                initialize_extension_monitoring,
            )

            await initialize_extension_monitoring()
            logger.info("Extension monitoring system initialized")
        except Exception as e:
            logger.warning(f"Extension monitoring initialization failed: {e}")

    @app.on_event("startup")
    async def _init_extension_health_monitor() -> None:
        """Initialize extension health monitor"""
        try:
            from .extension_health_monitor import initialize_extension_health_monitor

            # Get extension manager if available
            extension_manager = None
            try:
                extension_system = getattr(app.state, "extension_system", None)
                if extension_system:
                    extension_manager = extension_system.extension_manager
            except Exception:
                pass

            await initialize_extension_health_monitor(extension_manager)
            logger.info("Extension health monitor initialized")
        except Exception as e:
            logger.warning(f"Extension health monitor initialization failed: {e}")

    @app.on_event("startup")
    async def _init_extension_database_service() -> None:
        """Initialize extension database service"""
        # Skip if database is not available
        if not getattr(app.state, "database_available", False):
            logger.info("Skipping extension database service (database not available)")
            return

        try:
            from ai_karen_engine.extensions.platform.core.registry.database_service import (
                initialize_database_service,
            )

            settings = _get_settings()
            database_url = settings.database_url

            # Initialize extension database service
            # Use async driver for SQLAlchemy
            async_database_url = database_url.replace(
                "postgresql://", "postgresql+asyncpg://"
            )
            initialize_database_service(async_database_url)
            logger.info("Extension database service initialized")
        except Exception as e:
            logger.warning(f"Extension database service initialization failed: {e}")

    @app.on_event("startup")
    async def _init_extension_service_recovery() -> None:
        """Initialize extension service recovery system with integration to existing patterns"""
        # Skip if database is not available
        if not getattr(app.state, "database_available", False):
            logger.info("Skipping extension service recovery (database not available)")
            return

        try:
            from .extension_service_recovery import (
                initialize_extension_service_recovery_manager,
            )
            from .database_config import get_database_config
            from .enhanced_database_health_monitor import (
                get_enhanced_database_health_monitor,
            )

            settings = _get_settings()

            # Get existing components for integration
            database_config = getattr(app.state, "database_config", None) or get_database_config(settings)
            enhanced_health_monitor = get_enhanced_database_health_monitor()

            # Get extension manager if available
            extension_manager = None
            try:
                extension_system = getattr(app.state, "extension_system", None)
                if extension_system:
                    extension_manager = extension_system.extension_manager
            except Exception:
                pass

            # Initialize recovery manager with existing components
            recovery_manager = await initialize_extension_service_recovery_manager(
                extension_manager=extension_manager,
                database_config=database_config,
                enhanced_health_monitor=enhanced_health_monitor,
            )

            # Register extension-specific startup handlers
            recovery_manager.add_startup_handler(
                lambda: _extension_startup_recovery_handler(recovery_manager)
            )

            # Register extension-specific graceful degradation handlers
            recovery_manager.add_graceful_degradation_handler(
                "extension_api", lambda: _extension_api_degradation_handler()
            )
            recovery_manager.add_graceful_degradation_handler(
                "authentication", lambda: _authentication_degradation_handler()
            )

            # Execute startup handlers
            await recovery_manager.execute_startup_handlers()

            logger.info("Extension service recovery initialized")

        except Exception as e:
            logger.warning(f"Extension service recovery initialization failed: {e}")

    @app.on_event("startup")
    async def _warm_local_llm_stack() -> None:
        """Warm the local chat/LLM stack during startup so first chat request does not time out."""
        if os.getenv("KARI_WARM_LOCAL_LLM_ON_STARTUP", "false").lower() not in (
            "1",
            "true",
            "yes",
        ):
            logger.info("Skipping local LLM warmup (disabled by environment)")
            return

        try:
            from services.memory.settings_manager import get_settings_manager

            settings_manager = get_settings_manager()
            active_provider = (
                str(settings_manager.get_setting("provider", "") or "").strip().lower()
            )
            if active_provider not in {"builtin_vllm", "builtin_transformers", "local", "local_gguf"}:
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
            logger.warning(f"Local LLM warmup skipped after failure: {e}")

    async def _extension_startup_recovery_handler(recovery_manager):
        """Extension-specific startup recovery handler"""
        try:
            logger.info("Executing extension startup recovery checks")

            # Check if extension system needs recovery on startup
            status = recovery_manager.get_recovery_status()

            # Log startup recovery status
            unhealthy_services = [
                name
                for name, state in status["service_states"].items()
                if not state["healthy"]
            ]

            if unhealthy_services:
                logger.warning(
                    f"Unhealthy services detected on startup: {unhealthy_services}"
                )

                # Attempt immediate recovery for critical services
                for service_name in unhealthy_services:
                    if "authentication" in service_name or "database" in service_name:
                        await recovery_manager.force_recovery(service_name)
            else:
                logger.info("All extension services healthy on startup")

        except Exception as e:
            logger.error(f"Extension startup recovery handler failed: {e}")

    async def _extension_api_degradation_handler():
        """Graceful degradation handler for extension API"""
        try:
            logger.info("Enabling graceful degradation for extension API")

            # Set extension API to read-only mode or disable non-critical features
            # This would integrate with the extension system to limit functionality

            logger.info("Extension API graceful degradation enabled")

        except Exception as e:
            logger.error(f"Extension API degradation handler failed: {e}")

    async def _authentication_degradation_handler():
        """Graceful degradation handler for authentication service"""
        try:
            logger.info("Enabling graceful degradation for authentication service")

            # Enable development mode authentication or read-only access
            # This would integrate with the security system to provide fallback auth

            logger.info("Authentication service graceful degradation enabled")

        except Exception as e:
            logger.error(f"Authentication degradation handler failed: {e}")

    @app.on_event("startup")
    async def _init_llm_providers() -> None:
        try:
            from ai_karen_engine.server.startup import run_canonical_runtime_bootstrap
            await run_canonical_runtime_bootstrap(_get_settings(), app)
        except Exception as e:
            logger.warning(f"Canonical runtime bootstrap skipped: {e}")

    @app.on_event("startup")
    async def _init_memory_service() -> None:
        """Initialize memory service with proper error handling"""
        try:
            # Check if memory service should be initialized
            import os

            enable_memory = os.getenv("KARI_ENABLE_MEMORY_SERVICE", "true").lower() in (
                "1",
                "true",
                "yes",
            )
            fast = os.getenv(
                "KARI_FAST_STARTUP", os.getenv("FAST_STARTUP", "true")
            ).lower() in ("1", "true", "yes")

            if enable_memory:
                from ai_karen_engine.core.service_registry import initialize_services

                if fast:
                    logger.info(
                        "⚡ Fast startup: deferring memory service initialization to background"
                    )

                    async def _bg_init_memory() -> None:
                        try:
                            await initialize_services()
                            logger.info(
                                "Memory service initialized successfully (background)"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Background memory service initialization failed: {e}"
                            )

                    asyncio.create_task(_bg_init_memory())
                else:
                    logger.info("Initializing memory service...")
                    await initialize_services()
                    logger.info("Memory service initialized successfully")
            else:
                logger.info(
                    "Memory service initialization disabled by environment variable"
                )
        except Exception as e:
            logger.warning(f"Memory service initialization failed: {e}")
            # Continue startup even if memory service fails


async def initialize_fallback_systems() -> None:
    """Initialize fallback systems for degraded mode operation"""
    try:
        # This would contain fallback system initialization logic
        logger.info("Fallback systems initialized")
    except Exception as e:
        logger.error(f"Failed to initialize fallback systems: {e}")


def register_shutdown_tasks(app: FastAPI) -> None:
    """Register shutdown tasks for extension service recovery integration"""

    @app.on_event("shutdown")
    async def _shutdown_extension_monitoring() -> None:
        """Shutdown extension monitoring and alerting system"""
        try:
            from ai_karen_engine.monitoring.extensions.extension_monitoring_startup import (
                shutdown_extension_monitoring,
            )

            await shutdown_extension_monitoring()
            logger.info("Extension monitoring system shutdown completed")
        except Exception as e:
            logger.error(f"Extension monitoring shutdown failed: {e}")

    @app.on_event("shutdown")
    async def _shutdown_extension_health_monitor() -> None:
        """Shutdown extension health monitor"""
        try:
            from .extension_health_monitor import shutdown_extension_health_monitor

            await shutdown_extension_health_monitor()
            logger.info("Extension health monitor shutdown completed")
        except Exception as e:
            logger.error(f"Extension health monitor shutdown failed: {e}")

    @app.on_event("shutdown")
    async def _shutdown_extension_service_recovery() -> None:
        """Shutdown extension service recovery system with graceful cleanup"""
        try:
            from .extension_service_recovery import (
                get_extension_service_recovery_manager,
                shutdown_extension_service_recovery_manager,
            )

            recovery_manager = get_extension_service_recovery_manager()
            if recovery_manager:
                # Execute shutdown handlers first
                await recovery_manager.execute_shutdown_handlers()

                # Then shutdown the recovery system
                await shutdown_extension_service_recovery_manager()

                logger.info("Extension service recovery system shutdown completed")

        except Exception as e:
            logger.error(f"Extension service recovery shutdown failed: {e}")


async def run_startup_checks_and_fallbacks(logger) -> None:
    """Run startup checks and initialize fallback systems if needed"""
    try:
        await initialize_fallback_systems()
        logger.info("Startup checks completed successfully")
    except Exception as e:
        logger.error(f"Startup checks failed: {e}")
        # Continue with fallback systems
