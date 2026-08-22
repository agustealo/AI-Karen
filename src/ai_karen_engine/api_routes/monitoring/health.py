from __future__ import annotations

"""Health monitoring API routes.

Expose structured service health information with Prometheus metrics,
correlation-aware logging, and circuit breaker support.
"""

import time
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from ai_karen_engine.utils.dependency_checks import import_fastapi
from ai_karen_engine.core.runtime.resilience.connection_health_manager import (
    ConnectionHealthManager,
    get_connection_health_manager,
)
from ai_karen_engine.monitoring.correlation_service import get_request_id
from ai_karen_engine.core.logging import (
    get_logger,
    get_structured_logging_service,
)

logger = get_logger(__name__)

APIRouter, Request = import_fastapi("APIRouter", "Request")

# ---------------------------------------------------------------------------
# Prometheus metrics with safe fallbacks
# ---------------------------------------------------------------------------
try:  # pragma: no cover - optional dependency
    from prometheus_client import Counter, Histogram

    _REQ_COUNTER = Counter(
        "health_endpoint_requests_total",
        "Total health endpoint requests",
        ["endpoint"],
    )
    _LATENCY_HIST = Histogram(
        "health_endpoint_latency_seconds",
        "Latency for health endpoint requests",
        ["endpoint"],
    )
except Exception:  # pragma: no cover - prometheus optional

    class _DummyMetric:
        def labels(self, **_kwargs):  # type: ignore[override]
            return self

        def inc(self, *_args, **_kwargs):  # type: ignore[override]
            pass

        def observe(self, *_args, **_kwargs):  # type: ignore[override]
            pass

    _REQ_COUNTER = _DummyMetric()
    _LATENCY_HIST = _DummyMetric()


# Expose health endpoints under /api/health
router = APIRouter(prefix="/health")


def _record_metrics(endpoint: str, duration_ms: float) -> None:
    """Record Prometheus metrics if available."""
    _REQ_COUNTER.labels(endpoint=endpoint).inc()
    _LATENCY_HIST.labels(endpoint=endpoint).observe(duration_ms / 1000)


def _collect_health(manager: ConnectionHealthManager) -> Dict[str, Any]:
    """Collect health status for all registered services."""
    services: Dict[str, Any] = {}
    for name in list(manager.health_status.keys()):
        try:
            result = manager.health_status[name]
            services[name] = {
                "status": result.status.value,
                "last_check": result.last_check.isoformat(),
                "response_time_ms": result.response_time_ms,
                "degraded_features": result.degraded_features,
            }
        except Exception as exc:  # pragma: no cover - defensive
            services[name] = {"status": "unknown", "error": str(exc)}
    return services


def _check_nlp_assets(model_name: str = "en_core_web_sm") -> Dict[str, Any]:
    """Inspect local NLP asset availability without mutating the environment."""
    nltk_resources = {
        "punkt": False,
        "stopwords": False,
        "wordnet": False,
    }
    spacy_installed = False
    spacy_model_installed = False
    nltk_installed = False

    try:
        import spacy

        spacy_installed = True
        try:
            spacy.load(model_name)
            spacy_model_installed = True
        except Exception:
            spacy_model_installed = False
    except Exception:
        spacy_installed = False

    try:
        import nltk

        nltk_installed = True
        resource_map = {
            "punkt": "tokenizers/punkt",
            "stopwords": "corpora/stopwords",
            "wordnet": "corpora/wordnet",
        }
        for name, resource_path in resource_map.items():
            try:
                nltk.data.find(resource_path)
                nltk_resources[name] = True
            except LookupError:
                nltk_resources[name] = False
    except Exception:
        nltk_installed = False

    runtime_downloads_enabled = (
        str(__import__("os").getenv("KARI_ENABLE_NLTK_DOWNLOADS", "false")).lower()
        == "true"
    )

    return {
        "spacy_installed": spacy_installed,
        "spacy_model_name": model_name,
        "spacy_model_installed": spacy_model_installed,
        "nltk_installed": nltk_installed,
        "nltk_resources": nltk_resources,
        "runtime_downloads_enabled": runtime_downloads_enabled,
        "ready": spacy_model_installed
        and nltk_installed
        and all(nltk_resources.values()),
    }


async def _install_nlp_assets(model_name: str = "en_core_web_sm") -> Dict[str, Any]:
    """Attempt to install missing NLP assets on demand."""
    actions: List[Dict[str, Any]] = []

    try:
        import spacy

        try:
            spacy.load(model_name)
            actions.append(
                {"asset": f"spacy:{model_name}", "status": "already_present"}
            )
        except Exception:
            result = subprocess.run(
                [sys.executable, "-m", "spacy", "download", model_name],
                capture_output=True,
                text=True,
                check=False,
            )
            actions.append(
                {
                    "asset": f"spacy:{model_name}",
                    "status": "installed" if result.returncode == 0 else "failed",
                    "detail": (result.stdout or result.stderr).strip()[-500:],
                }
            )
    except Exception as exc:
        actions.append(
            {"asset": f"spacy:{model_name}", "status": "failed", "detail": str(exc)}
        )

    try:
        import nltk

        resource_map = {
            "punkt": "tokenizers/punkt",
            "stopwords": "corpora/stopwords",
            "wordnet": "corpora/wordnet",
        }
        for name, resource_path in resource_map.items():
            try:
                nltk.data.find(resource_path)
                actions.append({"asset": f"nltk:{name}", "status": "already_present"})
            except LookupError:
                ok = nltk.download(name, quiet=True)
                actions.append(
                    {
                        "asset": f"nltk:{name}",
                        "status": "installed" if ok else "failed",
                    }
                )
    except Exception as exc:
        actions.append({"asset": "nltk", "status": "failed", "detail": str(exc)})

    status = _check_nlp_assets(model_name)
    return {
        "actions": actions,
        "status": status,
        "success": status["ready"],
    }


@router.get("")
async def overall_health(request: Request) -> Dict[str, Any]:
    """Return overall health status for registered services."""
    start = time.time()
    correlation_id = request.headers.get("X-Correlation-Id") or get_request_id()
    manager = get_connection_health_manager()

    # Perform health checks with circuit breaker protection
    for name in list(manager.health_status.keys()):
        try:
            await manager.check_service_health(name)
        except Exception:
            # check_service_health already handles circuit breaker and
            # degraded mode. Failures are reflected in status.
            pass

    services = _collect_health(manager)

    # Check extension system health
    extension_health = {}
    extension_status = "healthy"
    try:
        from server.extension_health_monitor import get_extension_health_monitor

        extension_monitor = get_extension_health_monitor()
        if extension_monitor:
            ext_health = await extension_monitor.get_extension_health_for_api()
            extension_health = {
                "status": ext_health["status"],
                "total_extensions": ext_health["extensions"]["total"],
                "healthy_extensions": ext_health["extensions"]["healthy"],
                "degraded_extensions": ext_health["extensions"]["degraded"],
                "unhealthy_extensions": ext_health["extensions"]["unhealthy"],
                "uptime_seconds": ext_health["uptime_seconds"],
                "supporting_services": ext_health["supporting_services"],
            }
            extension_status = ext_health["status"]

            # Update extension metrics
            extension_monitor.update_extension_metrics(
                await extension_monitor.check_extension_system_health()
            )
        else:
            extension_health = {
                "status": "unknown",
                "error": "Extension monitor not available",
            }
            extension_status = "degraded"
    except Exception as e:
        logger.warning(
            f"Failed to get extension health for overall health endpoint: {e}"
        )
        extension_health = {"status": "error", "error": str(e)}
        extension_status = "degraded"

    # Add extension status to services
    services["extensions"] = {
        "status": extension_status,
        "last_check": datetime.now(timezone.utc).isoformat(),
        "response_time_ms": (time.time() - start) * 1000,
        "degraded_features": []
        if extension_status == "healthy"
        else ["extension_system"],
    }

    # Determine overall status including extensions
    all_statuses = [s["status"] for s in services.values()]
    overall = (
        "healthy" if all(status == "healthy" for status in all_statuses) else "degraded"
    )

    duration_ms = (time.time() - start) * 1000
    _record_metrics("overall", duration_ms)

    get_structured_logging_service().log_api_request(
        method="GET",
        endpoint="/api/health",
        status_code=200,
        duration_ms=duration_ms,
        correlation_id=correlation_id,
    )

    return {
        "status": overall,
        "services": services,
        "nlp_assets": _check_nlp_assets(),
        "extension_system": extension_health,
        "timestamp": time.time(),
        "correlation_id": correlation_id,
    }


async def _check_local_model_capabilities() -> Dict[str, int]:
    """Check which local model systems are actually working."""
    capabilities = {
        "local_gguf_models": 0,
        "transformers_models": 0,
        "spacy_available": 0,
    }

    # Check local GGUF models
    try:
        from pathlib import Path
        models_dir = Path("models/local-gguf")
        if models_dir.exists():
            capabilities["local_gguf_models"] = sum(
                1
                for gguf_file in models_dir.glob("*.gguf")
                if gguf_file.is_file() and gguf_file.stat().st_size > 0
            )
    except Exception:
        pass

    # Check transformers models
    try:
        from pathlib import Path
        import transformers
        from transformers import AutoTokenizer, AutoModelForCausalLM

        models_dir = Path("models/transformers")
        if models_dir.exists():
            model_dirs = [d for d in models_dir.iterdir() if d.is_dir()]
            for model_dir in model_dirs:
                try:
                    # Quick test load
                    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
                    if tokenizer:
                        capabilities["transformers_models"] += 1
                        break  # Found at least one working model
                except Exception:
                    continue
    except Exception:
        pass

    # Check spaCy
    try:
        import spacy

        nlp = spacy.load("en_core_web_sm")
        if nlp:
            capabilities["spacy_available"] = 1
    except Exception:
        pass

    return capabilities


def _collect_remote_provider_outages(
    system_status: Dict[str, Any],
    registry_service: "ProviderRegistryService",
) -> List[str]:
    """Identify remote providers that are currently unavailable."""

    outages: List[str] = []
    provider_details = system_status.get("provider_details", {})

    try:
        base_registry = registry_service.base_registry

        for provider_name, detail in provider_details.items():
            provider_info = base_registry.get_provider_info(provider_name)
            if not provider_info:
                continue

            is_remote = bool(provider_info.requires_api_key)
            if is_remote and not detail.get("is_available", False):
                outages.append(provider_name)
    except Exception:
        # If we fail to inspect provider metadata, fall back to any providers marked unavailable
        outages.extend(
            name
            for name, detail in provider_details.items()
            if not detail.get("is_available", False)
        )

    # Deduplicate while preserving order
    seen = set()
    ordered_outages = []
    for name in outages:
        if name not in seen:
            seen.add(name)
            ordered_outages.append(name)
    return ordered_outages


async def _build_degraded_mode_status() -> Dict[str, Any]:
    """Compute the canonical degraded mode status payload."""

    # Track degraded components surfaced during health evaluation
    degraded_components: List[str] = []
    infrastructure_issues: List[str] = []
    failed_providers: List[str] = []
    remote_provider_outages: List[str] = []

    # Database check
    try:
        from ai_karen_engine.services.database_connection_manager import (
            get_database_manager,
        )

        db_manager = get_database_manager()
        if db_manager.is_degraded():
            degraded_components.append("database")
    except Exception:
        degraded_components.append("database")

    # Extension system check
    extension_system_status = {}
    extension_degraded = False
    try:
        from server.extension_health_monitor import get_extension_health_monitor

        extension_monitor = get_extension_health_monitor()
        if extension_monitor:
            extension_health = await extension_monitor.get_extension_health_for_api()
            extension_system_status = {
                "status": extension_health["status"],
                "total_extensions": extension_health["extensions"]["total"],
                "healthy_extensions": extension_health["extensions"]["healthy"],
                "degraded_extensions": extension_health["extensions"]["degraded"],
                "unhealthy_extensions": extension_health["extensions"]["unhealthy"],
                "authentication_healthy": extension_health["supporting_services"][
                    "authentication"
                ]["healthy"],
                "background_tasks_healthy": extension_health["supporting_services"][
                    "background_tasks"
                ]["healthy"],
                "uptime_seconds": extension_health["uptime_seconds"],
            }

            # Check if extension system is degraded
            if (
                extension_health["status"] in ["degraded", "unhealthy"]
                or extension_health["extensions"]["unhealthy"] > 0
                or not extension_health["supporting_services"]["authentication"][
                    "healthy"
                ]
                or not extension_health["supporting_services"]["background_tasks"][
                    "healthy"
                ]
            ):
                extension_degraded = True
                degraded_components.append("extensions")
        else:
            extension_system_status = {
                "status": "unknown",
                "error": "Extension monitor not available",
            }
            extension_degraded = True
            degraded_components.append("extensions")
    except Exception as e:
        logger.warning(
            f"Failed to check extension system health for degraded mode: {e}"
        )
        extension_system_status = {"status": "error", "error": str(e)}
        extension_degraded = True
        degraded_components.append("extensions")

    # Redis check
    try:
        from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager

        redis_manager = get_redis_manager()
        if redis_manager.is_degraded():
            degraded_components.append("redis")
    except Exception:
        degraded_components.append("redis")

    # Provider health checks with local fallback awareness
    total_ai_capabilities = 0
    local_capabilities = {
        "local_gguf_models": 0,
        "transformers_models": 0,
        "spacy_available": 0,
    }

    try:
        from ai_karen_engine.core.model_runtime.provider_registry_service import (
            get_provider_registry_service,
        )

        provider_service = get_provider_registry_service()
        system_status = provider_service.get_system_status()

        # Remote provider outages (missing keys or unhealthy)
        remote_provider_outages = _collect_remote_provider_outages(
            system_status, provider_service
        )

        # Check canonical provider registry for working models
        llm_models_available = 0
        try:
            from ai_karen_engine.core.model_runtime.provider_registry_service import (
                get_provider_registry_service,
            )

            registry = get_provider_registry_service()
            for provider_name in registry.get_all_provider_names():
                models = registry.get_registered_models(provider_name, healthy_only=True)
                llm_models_available += len(models)
        except Exception as exc:
            logger.debug("Could not check provider registry models: %s", exc)

        # Local capabilities
        from pathlib import Path

        models_dir = Path("models")
        default_model_available = (
            any((models_dir / "local-gguf").glob("*.gguf"))
            if (models_dir / "local-gguf").exists()
            else False
        )

        spacy_available = False
        try:  # pragma: no cover - optional dependency
            import spacy

            _ = spacy.load("en_core_web_sm")
            spacy_available = True
        except Exception:
            spacy_available = False

        local_capabilities = await _check_local_model_capabilities()

        total_ai_capabilities = (
            system_status.get("available_providers", 0)
            + llm_models_available
            + local_capabilities.get("local_gguf_models", 0)
            + local_capabilities.get("transformers_models", 0)
            + (1 if spacy_available else 0)
        )

        if total_ai_capabilities == 0:
            degraded_components.append("ai_providers")
        failed_providers = remote_provider_outages or system_status.get(
            "failed_providers", []
        )
    except Exception:
        try:
            from pathlib import Path

            models_dir = Path("models")
            default_model_available = (
                any((models_dir / "local-gguf").glob("*.gguf"))
                if (models_dir / "local-gguf").exists()
                else False
            )

            import spacy  # type: ignore

            _ = spacy.load("en_core_web_sm")  # type: ignore[attr-defined]
            spacy_available = True
        except Exception:
            default_model_available = False
            spacy_available = False

        if not (default_model_available or spacy_available):
            degraded_components.append("ai_providers")
            failed_providers = ["unknown"]

    ai_degraded = "ai_providers" in degraded_components
    infrastructure_issues = [
        comp for comp in degraded_components if comp != "ai_providers"
    ]

    # Determine canonical degraded status
    is_degraded = ai_degraded
    reason = "all_providers_failed" if is_degraded else None

    # Core helper capability summary
    try:
        from pathlib import Path

        models_dir = Path("models")
        default_model_file_available = (
            any((models_dir / "local-gguf").glob("*.gguf"))
            if (models_dir / "local-gguf").exists()
            else False
        )

        spacy_online = False
        try:  # pragma: no cover - optional dependency
            import spacy

            _ = spacy.load("en_core_web_sm")
            spacy_online = True
        except Exception:
            spacy_online = False

        llm_orchestrator_models = 0
        try:
            from ai_karen_engine.core.model_runtime.provider_registry_service import (
                get_provider_registry_service,
            )

            registry = get_provider_registry_service()
            for provider_name in registry.get_all_provider_names():
                models = registry.get_registered_models(provider_name, healthy_only=True)
                llm_orchestrator_models += len(models)
        except Exception:
            llm_orchestrator_models = 0

        remote_providers_available = 0
        try:
            from ai_karen_engine.core.model_runtime.provider_registry_service import (
                get_provider_registry_service,
            )

            provider_service = get_provider_registry_service()
            system_status = provider_service.get_system_status()
            remote_providers_available = system_status.get("available_providers", 0)
        except Exception:
            remote_providers_available = 0

        local_capabilities = await _check_local_model_capabilities()

        core_helpers_available = {
            "local_nlp": spacy_online,
            "local_llm_file": default_model_file_available,
            "llm_orchestrator_models": llm_orchestrator_models,
            "remote_providers": remote_providers_available,
            "local_gguf_working_models": local_capabilities.get("local_gguf_models", 0),
            "transformers_working_models": local_capabilities.get(
                "transformers_models", 0
            ),
            "spacy_intelligent_responses": local_capabilities.get("spacy_available", 0),
            "fallback_responses": True,
            "basic_analytics": True,
            "file_operations": True,
            "database_fallback": "database" not in degraded_components,
            "total_ai_capabilities": (
                llm_orchestrator_models
                + remote_providers_available
                + local_capabilities.get("local_gguf_models", 0)
                + local_capabilities.get("transformers_models", 0)
                + local_capabilities.get("spacy_available", 0)
            ),
        }
        core_helpers_available["local_fallback_ready"] = bool(
            core_helpers_available["local_gguf_working_models"]
            or core_helpers_available["transformers_working_models"]
            or core_helpers_available["spacy_intelligent_responses"]
            or core_helpers_available["local_llm_file"]
        )
        core_helpers_available["remote_provider_outages"] = remote_provider_outages
    except Exception:
        core_helpers_available = {
            "local_nlp": False,
            "local_llm_file": False,
            "llm_orchestrator_models": 0,
            "remote_providers": 0,
            "fallback_responses": True,
            "basic_analytics": True,
            "file_operations": True,
            "database_fallback": False,
            "total_ai_capabilities": 0,
            "local_fallback_ready": False,
            "remote_provider_outages": remote_provider_outages,
        }

    # Update degraded status to include extension system
    is_degraded = is_degraded or extension_degraded
    ai_status = "degraded" if (is_degraded or remote_provider_outages) else "healthy"

    return {
        "is_active": is_degraded,
        "reason": reason,
        "activated_at": datetime.now(timezone.utc).isoformat() if is_degraded else None,
        "failed_providers": failed_providers,
        "remote_provider_outages": remote_provider_outages,
        "recovery_attempts": 0,
        "last_recovery_attempt": None,
        "core_helpers_available": core_helpers_available,
        "infrastructure_issues": infrastructure_issues,
        "ai_status": ai_status,
        "extension_system": extension_system_status,
        "extension_degraded": extension_degraded,
    }


def _build_compatibility_response(status: Dict[str, Any]) -> Dict[str, Any]:
    """Transform canonical degraded status into the legacy compatibility payload."""

    is_active = bool(status.get("is_active", False))
    ai_status = status.get("ai_status", "unknown")
    infrastructure = status.get("infrastructure_issues", [])
    remote_outages = status.get("remote_provider_outages", [])

    degraded_components: List[str] = []
    if ai_status == "degraded":
        degraded_components.append("ai_providers")
    degraded_components.extend(infrastructure)

    # Include extension system in degraded components if applicable
    extension_system = status.get("extension_system", {})
    if status.get("extension_degraded", False):
        if "extensions" not in degraded_components:
            degraded_components.append("extensions")

    timestamp = status.get("activated_at") or datetime.now(timezone.utc).isoformat()
    core_helpers = status.get("core_helpers_available", {})

    return {
        "degraded_mode": is_active,
        "is_active": is_active,
        "ai_status": ai_status,
        "status": ai_status,
        "reason": status.get("reason"),
        "failed_providers": status.get("failed_providers", []),
        "remote_provider_outages": remote_outages,
        "degraded_components": degraded_components,
        "core_helpers_available": core_helpers,
        "fallback_systems_active": bool(core_helpers.get("fallback_responses", True)),
        "timestamp": timestamp,
        "extension_system": extension_system,
        "extension_degraded": status.get("extension_degraded", False),
        "payload": status,
    }


@router.get("/degraded-mode")
async def degraded_mode_status() -> Dict[str, Any]:
    """Check if system is running in degraded mode."""

    try:
        status = await _build_degraded_mode_status()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Failed to build degraded mode status: %s", exc)
        status = {
            "is_active": True,
            "reason": "resource_exhaustion",
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "failed_providers": ["unknown"],
            "remote_provider_outages": ["unknown"],
            "recovery_attempts": 0,
            "last_recovery_attempt": None,
            "core_helpers_available": {
                "local_nlp": False,
                "local_llm_file": False,
                "fallback_responses": True,
                "basic_analytics": True,
                "file_operations": True,
                "database_fallback": False,
                "total_ai_capabilities": 0,
                "local_fallback_ready": False,
                "remote_provider_outages": ["unknown"],
            },
            "infrastructure_issues": ["unknown"],
            "ai_status": "degraded",
        }

    status["degraded_mode"] = status.get("is_active", False)
    return status


@router.get("/degraded-mode/compat")
async def degraded_mode_status_compat() -> Dict[str, Any]:
    """Compatibility wrapper for legacy clients expecting degraded_mode payload."""

    status = await degraded_mode_status()
    return _build_compatibility_response(status)


@router.get("/extensions")
async def extension_system_health(request: Request) -> Dict[str, Any]:
    """Return comprehensive extension system health status."""
    start = time.time()
    correlation_id = request.headers.get("X-Correlation-Id") or get_request_id()

    try:
        from server.extension_health_monitor import get_extension_health_monitor

        extension_monitor = get_extension_health_monitor()

        if not extension_monitor:
            return {
                "status": "unavailable",
                "error": "Extension health monitor not initialized",
                "correlation_id": correlation_id,
                "timestamp": time.time(),
            }

        # Get comprehensive extension health
        health_data = await extension_monitor.get_extension_health_for_api()

        # Update metrics
        system_health = await extension_monitor.check_extension_system_health()
        extension_monitor.update_extension_metrics(system_health)

        # Get database performance metrics
        db_performance = await extension_monitor.get_database_performance_metrics()

        duration_ms = (time.time() - start) * 1000
        _record_metrics("extensions", duration_ms)

        get_structured_logging_service().log_api_request(
            method="GET",
            endpoint="/api/health/extensions",
            status_code=200,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

        return {
            **health_data,
            "database_performance": db_performance,
            "correlation_id": correlation_id,
            "timestamp": time.time(),
            "response_time_ms": duration_ms,
        }

    except Exception as e:
        logger.error(f"Extension health endpoint failed: {e}")
        duration_ms = (time.time() - start) * 1000

        get_structured_logging_service().log_api_request(
            method="GET",
            endpoint="/api/health/extensions",
            status_code=500,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

        return {
            "status": "error",
            "error": str(e),
            "correlation_id": correlation_id,
            "timestamp": time.time(),
            "response_time_ms": duration_ms,
        }


@router.get("/extensions/{extension_name}")
async def individual_extension_health(
    extension_name: str, request: Request
) -> Dict[str, Any]:
    """Return health status for a specific extension."""
    start = time.time()
    correlation_id = request.headers.get("X-Correlation-Id") or get_request_id()

    try:
        from server.extension_health_monitor import get_extension_health_monitor

        extension_monitor = get_extension_health_monitor()

        if not extension_monitor:
            return {
                "extension": extension_name,
                "status": "unavailable",
                "error": "Extension health monitor not initialized",
                "correlation_id": correlation_id,
                "timestamp": time.time(),
            }

        # Get system health to access individual extension metrics
        system_health = await extension_monitor.check_extension_system_health()

        if extension_name not in system_health.extension_metrics:
            return {
                "extension": extension_name,
                "status": "not_found",
                "error": f"Extension '{extension_name}' not found",
                "correlation_id": correlation_id,
                "timestamp": time.time(),
            }

        metrics = system_health.extension_metrics[extension_name]

        duration_ms = (time.time() - start) * 1000
        _record_metrics(f"extension_{extension_name}", duration_ms)

        get_structured_logging_service().log_api_request(
            method="GET",
            endpoint=f"/api/health/extensions/{extension_name}",
            status_code=200,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

        return {
            "extension": extension_name,
            "status": metrics.status.value,
            "response_time_ms": metrics.response_time_ms,
            "uptime_seconds": metrics.uptime_seconds,
            "error_count": metrics.error_count,
            "success_count": metrics.success_count,
            "background_tasks_active": metrics.background_tasks_active,
            "background_tasks_failed": metrics.background_tasks_failed,
            "api_calls_per_minute": metrics.api_calls_per_minute,
            "memory_usage_mb": metrics.memory_usage_mb,
            "cpu_usage_percent": metrics.cpu_usage_percent,
            "last_check": metrics.last_check.isoformat(),
            "error": metrics.error,
            "correlation_id": correlation_id,
            "timestamp": time.time(),
            "check_duration_ms": duration_ms,
        }

    except Exception as e:
        logger.error(
            f"Individual extension health endpoint failed for {extension_name}: {e}"
        )
        duration_ms = (time.time() - start) * 1000

        get_structured_logging_service().log_api_request(
            method="GET",
            endpoint=f"/api/health/extensions/{extension_name}",
            status_code=500,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
        )

        return {
            "extension": extension_name,
            "status": "error",
            "error": str(e),
            "correlation_id": correlation_id,
            "timestamp": time.time(),
            "check_duration_ms": duration_ms,
        }


@router.get("/nlp-assets")
async def nlp_assets_health() -> Dict[str, Any]:
    """Return NLP asset availability for admin setup workflows."""
    return _check_nlp_assets()


@router.post("/nlp-assets/install")
async def install_nlp_assets() -> Dict[str, Any]:
    """Attempt to install missing NLP assets on demand."""
    return await _install_nlp_assets()


@router.get("/{service_name}")
async def service_health(service_name: str, request: Request) -> Dict[str, Any]:
    """Return health status for a specific service."""
    start = time.time()
    correlation_id = request.headers.get("X-Correlation-Id") or get_request_id()
    manager = get_connection_health_manager()

    try:
        result = await manager.check_service_health(service_name)
        status = {
            "status": result.status.value,
            "last_check": result.last_check.isoformat(),
            "response_time_ms": result.response_time_ms,
            "degraded_features": result.degraded_features,
        }
        code = 200
    except Exception as exc:
        status = {"status": "unknown", "error": str(exc)}
        code = 404

    duration_ms = (time.time() - start) * 1000
    _record_metrics(service_name, duration_ms)

    get_structured_logging_service().log_api_request(
        method="GET",
        endpoint=f"/api/health/{service_name}",
        status_code=code,
        duration_ms=duration_ms,
        correlation_id=correlation_id,
    )

    return {"service": service_name, "result": status, "correlation_id": correlation_id}


__all__ = ["router"]
