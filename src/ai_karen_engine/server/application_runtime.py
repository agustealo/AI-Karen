from __future__ import annotations

"""Application lifecycle ownership for the canonical Runtime services.

The FastAPI lifespan is the process lifecycle boundary. Runtime composition,
ChatRuntime, ChatRuntimeControlPlane, and long-lived model-download worker are
attached to ``app.state`` here so startup owns the live service graph and
shutdown drains workers before database teardown.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

_RUNTIME_ATTACHED_STATE_KEY = "_canonical_runtime_attached"
_RUNTIME_SHUTDOWN_STATE_KEY = "_canonical_runtime_shutdown"


async def initialize_application_channel_host(app: FastAPI) -> None:
    """Attach explicitly opted-in channel transport dependencies, never activate tenants."""
    from ai_karen_engine.config.channels import load_channel_host_settings

    settings = load_channel_host_settings()
    # Keep the public provider webhook entirely unavailable by default.
    app.state.channel_ingress_service = None
    app.state.channel_host_services = None
    if not settings.enabled:
        return

    import httpx

    from ai_karen_engine.extensions.plugin_kernel import PluginKernel
    from ai_karen_engine.persistence.repositories.channel_repository import (
        SqlChannelRepository,
    )
    from ai_karen_engine.services.channels.host import ChannelHostServices
    from ai_karen_engine.services.identity_vault.credential_vault_service import (
        CredentialVaultService,
    )

    existing_kernel = getattr(app.state, "plugin_kernel", None)
    existing_vault = getattr(app.state, "credential_vault_service", None)
    if existing_kernel is not None and not isinstance(existing_kernel, PluginKernel):
        raise RuntimeError("Canonical PluginKernel ownership is invalid")
    if existing_vault is not None and not isinstance(
        existing_vault, CredentialVaultService
    ):
        raise RuntimeError("Canonical Identity Vault ownership is invalid")
    kernel = existing_kernel or PluginKernel(PluginKernel.canonical_extensions_root())
    vault = existing_vault or CredentialVaultService()
    client = httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        trust_env=False,
        follow_redirects=False,
    )
    host = ChannelHostServices(
        settings=settings, kernel=kernel, vault=vault,
        repository=SqlChannelRepository(), http_client=client,
        owns_kernel=existing_kernel is None,
        owns_vault=existing_vault is None,
    )
    await host.initialize()
    if host.ingress is None or host.activation is None:
        await host.shutdown()
        raise RuntimeError("Configured channel host did not attach its services")

    # Mount only after every configured adapter is verified and bound. HTTP
    # requests never select a plugin, vault actor, model, or generic executor.
    app.state.plugin_kernel = kernel
    app.state.credential_vault_service = vault
    app.state.channel_host_services = host
    app.state.channel_ingress_service = host.ingress
    logger.info(
        "Canonical channel host attached",
        extra={"installed_transports": len(settings.installations),
               "tenant_connections_auto_started": 0},
    )


async def initialize_application_runtime(app: FastAPI) -> None:
    """Attach canonical Runtime services to the application lifecycle."""
    if getattr(app.state, _RUNTIME_ATTACHED_STATE_KEY, False) and not getattr(
        app.state, _RUNTIME_SHUTDOWN_STATE_KEY, False
    ):
        return

    from ai_karen_engine.config.model_download import load_model_download_worker_settings
    from ai_karen_engine.core.langgraph_orchestrator import (
        create_orchestrator,
        set_default_orchestrator,
    )
    from ai_karen_engine.core.model_runtime.model_download_control_service import (
        get_model_download_control_service,
    )
    from ai_karen_engine.core.model_runtime.model_download_worker import ModelDownloadWorker
    from ai_karen_engine.core.runtime.chat_runtime import get_chat_runtime
    from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
        get_chat_runtime_control_plane,
    )
    from ai_karen_engine.core.runtime.composition import get_runtime_composition
    from ai_karen_engine.integrations.memory.profile_service import get_profile_service

    composition = get_runtime_composition()
    workflow_orchestrator = create_orchestrator(profile_service=get_profile_service())
    set_default_orchestrator(workflow_orchestrator)
    control_plane = await get_chat_runtime_control_plane()
    if not getattr(control_plane, "_initialized", False):
        await control_plane.initialize()
    chat_runtime = get_chat_runtime()

    model_download_service = get_model_download_control_service()
    await model_download_service.initialize()
    model_download_worker = ModelDownloadWorker(
        model_download_service,
        load_model_download_worker_settings(),
    )
    await model_download_worker.start()

    app.state.runtime_composition = composition
    app.state.workflow_orchestrator = workflow_orchestrator
    app.state.chat_runtime = chat_runtime
    app.state.chat_runtime_control_plane = control_plane
    app.state.model_download_control_service = model_download_service
    app.state.model_download_worker = model_download_worker
    setattr(app.state, _RUNTIME_SHUTDOWN_STATE_KEY, False)
    try:
        await initialize_application_channel_host(app)
    except BaseException:
        # Startup failure must not leak the already-started model download worker.
        await shutdown_application_runtime(app)
        raise
    setattr(app.state, _RUNTIME_ATTACHED_STATE_KEY, True)

    logger.info("Canonical application Runtime services attached")


async def shutdown_application_runtime(app: FastAPI) -> None:
    """Stop application-owned Runtime and database resources exactly once."""
    if getattr(app.state, _RUNTIME_SHUTDOWN_STATE_KEY, False):
        return

    # Revoke ingress synchronously before any transport or database teardown.
    # Old public routes then return 503 even during shutdown/draining.
    app.state.channel_ingress_service = None
    host = getattr(app.state, "channel_host_services", None)
    app.state.channel_host_services = None
    if host is not None:
        try:
            await host.shutdown()
        except Exception as exc:
            logger.warning(
                "Channel host shutdown degraded",
                extra={"error_type": type(exc).__name__},
            )

    model_download_worker = getattr(app.state, "model_download_worker", None)
    if model_download_worker is not None:
        try:
            await model_download_worker.stop()
        except Exception as exc:
            logger.warning("Model download worker shutdown degraded: %s", exc)

    control_plane = getattr(app.state, "chat_runtime_control_plane", None)
    if control_plane is not None:
        try:
            await control_plane.shutdown()
        except Exception as exc:
            logger.warning("Runtime ControlPlane shutdown degraded: %s", exc)

    try:
        from ai_karen_engine.services.database.database_config import get_database_config

        settings = getattr(app.state, "settings", None)
        database_config = get_database_config(settings)
        await database_config.cleanup()
    except Exception as exc:
        logger.warning("Database cleanup degraded during application shutdown: %s", exc)

    setattr(app.state, _RUNTIME_SHUTDOWN_STATE_KEY, True)
    logger.info("Canonical application Runtime services shut down")


def create_application_lifespan(settings: Any):
    """Create the canonical app lifespan around existing service startup."""
    from ai_karen_engine.server.startup import on_shutdown, on_startup

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await on_startup(settings, app)
        await initialize_application_runtime(app)
        try:
            yield
        finally:
            await shutdown_application_runtime(app)
            await on_shutdown(app)

    return lifespan


__all__ = [
    "create_application_lifespan",
    "initialize_application_channel_host",
    "initialize_application_runtime",
    "shutdown_application_runtime",
]
