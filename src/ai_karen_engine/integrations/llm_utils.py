"""
Kari LLM Utils - Production Enterprise Version

- Centralized, DI-driven LLM orchestration for Kari AI
- Supports multiple providers (local, remote, plugins) and prompt-first hooks
- Metrics, tracing, RBAC, error trace, and observability built-in
"""

import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy.exc import SQLAlchemyError

# Database dependencies are optional during early startup or offline testing
get_db_session_context = None  # type: ignore[assignment]
LLMProvider = None  # type: ignore[assignment]
LLMRequest = None  # type: ignore[assignment]
_DB_AVAILABLE = False
_DB_IMPORT_ERROR: Optional[Exception] = None
_DB_IMPORT_ATTEMPTED = False


def _db_logging_enabled() -> bool:
    """Return ``True`` when database logging should be attempted."""

    flag = os.getenv("AI_KAREN_ENABLE_DB_LOGGING")
    if flag is None:
        return False

    return flag.lower() in {"1", "true", "yes", "on"}


def _ensure_db_dependencies() -> bool:
    """Lazy loader for optional database dependencies used for request logging."""

    global _DB_AVAILABLE, _DB_IMPORT_ERROR, _DB_IMPORT_ATTEMPTED
    global get_db_session_context, LLMProvider, LLMRequest

    if _DB_AVAILABLE:
        return True

    if _DB_IMPORT_ATTEMPTED:
        return False

    _DB_IMPORT_ATTEMPTED = True

    if not _db_logging_enabled():
        _DB_IMPORT_ERROR = RuntimeError(
            "LLM request logging disabled (AI_KAREN_ENABLE_DB_LOGGING not set)."
        )
        logger.debug("Skipping DB logging imports: %s", _DB_IMPORT_ERROR)
        return False

    try:
        from ai_karen_engine.database.client import get_db_session_context as _get_ctx
        from ai_karen_engine.database.models import LLMProvider as _LLMProvider
        from ai_karen_engine.database.models import LLMRequest as _LLMRequest

        get_db_session_context = _get_ctx  # type: ignore[assignment]
        LLMProvider = _LLMProvider  # type: ignore[assignment]
        LLMRequest = _LLMRequest  # type: ignore[assignment]
        _DB_AVAILABLE = True
        _DB_IMPORT_ERROR = None
        logger.info("LLM request logging enabled via database instrumentation")
        return True
    except Exception as db_import_error:  # pragma: no cover - optional dependency path
        _DB_IMPORT_ERROR = db_import_error
        logger.warning(
            "Database instrumentation for LLM logging unavailable: %s",
            db_import_error,
        )
        return False


def _has_local_model() -> bool:
    """Return ``True`` when a local model appears to be available."""

    try:
        try:
            from ai_karen_engine.config.runtime import get_runtime_settings

            model_dir = Path(get_runtime_settings().endpoints.models_dir) / "local-gguf"
        except Exception:
            model_dir = Path(os.getenv("AI_KAREN_LOCAL_MODEL_DIR", "models/local-gguf"))
        if not model_dir.exists():
            return False
        for path in model_dir.glob("*.gguf"):
            if path.is_file():
                return True
    except Exception:
        return False
    return False


def _should_use_registry() -> bool:
    """Determine whether the full LLM registry should be initialized."""

    if os.getenv("AI_KAREN_FORCE_SIMPLE_LLM", "").lower() in {"1", "true", "yes", "on"}:
        logger.info("Simple LLM mode forced via AI_KAREN_FORCE_SIMPLE_LLM")
        return False

    if os.getenv("AI_KAREN_ENABLE_FULL_REGISTRY", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if os.getenv("OPENAI_API_KEY"):
        return True

    if _has_local_model():
        return True

    logger.info(
        "LLM registry disabled automatically (no API keys or local models detected)"
    )
    return False


# Lazy imports to avoid circular import issues
# Providers will be imported when needed in get_provider_class()

try:
    from prometheus_client import CollectorRegistry, Counter, Histogram

    PROM_REGISTRY = CollectorRegistry()
    _LLM_COUNT = Counter(
        "llm_requests_total",
        "Total LLM requests",
        ["event", "provider", "success"],
        registry=PROM_REGISTRY,
    )
    _LLM_LATENCY = Histogram(
        "llm_request_latency_seconds",
        "LLM request latency",
        ["event", "provider", "success"],
        registry=PROM_REGISTRY,
    )
    METRICS_ENABLED = True
except Exception:  # pragma: no cover - optional dep

    class _DummyMetric:
        def labels(self, **kwargs):
            return self

        def inc(self, n: int = 1) -> None:
            pass

        def observe(self, v: float) -> None:
            pass

    METRICS_ENABLED = False
    PROM_REGISTRY = None  # type: ignore
    _LLM_COUNT = _LLM_LATENCY = _DummyMetric()

logger = logging.getLogger("kari.llm_utils")


# ========== Helpers ==========
def _get_metrics_service_safe():
    """Lazily import the metrics service to avoid circular dependencies."""

    try:
        from ai_karen_engine.monitoring.metrics_service import get_metrics_service

        return get_metrics_service()
    except Exception:  # pragma: no cover - optional dependency path
        logger.debug("Metrics service unavailable during import", exc_info=True)
        return None


# ========== Exceptions ==========
class LLMError(Exception):
    pass


class ProviderNotAvailable(LLMError):
    pass


class GenerationFailed(LLMError):
    pass


class EmbeddingFailed(LLMError):
    pass


# ========== Metrics/Observability (Stub for Prometheus) ==========
def record_llm_metric(
    event: str, duration: float, success: bool, provider: str, **extra
) -> None:
    """Record a metric for an LLM event.

    Parameters
    ----------
    event:
        Event name such as ``generate_text`` or ``embed``.
    duration:
        Duration of the call in seconds.
    success:
        ``True`` if the call succeeded.
    provider:
        Name of the LLM provider.
    extra:
        Additional metadata ignored by the metrics layer.
    """

    logger.info(
        f"[METRIC] event={event} duration={duration:.3f}s success={success} provider={provider} extra={extra}"
    )

    label_success = "true" if success else "false"
    try:
        _LLM_COUNT.labels(event=event, provider=provider, success=label_success).inc()
        _LLM_LATENCY.labels(
            event=event, provider=provider, success=label_success
        ).observe(duration)
    except Exception:  # pragma: no cover - safety guard
        logger.info("Prometheus metrics disabled or failed")


def trace_llm_event(event: str, correlation_id: str, meta: Dict[str, Any]):
    logger.info(f"[TRACE] event={event} correlation_id={correlation_id} meta={meta}")


# ========== Provider Base ==========
class LLMProviderBase:
    def generate_text(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError

    def embed(self, text: Union[str, List[str]], **kwargs) -> List[float]:
        raise NotImplementedError

    def warm_cache(self) -> None:
        """Warm provider caches by issuing a tiny generation request.

        Providers may override this for custom behaviour. The default
        implementation makes a best-effort call to :meth:`generate_text` with a
        single-token prompt and ignores all errors so that warmup never blocks
        startup.
        """
        try:
            self.generate_text("hello", max_tokens=1)
        except Exception:  # pragma: no cover - warmup is best-effort
            logger.debug("warm_cache failed", exc_info=True)


# ========== Main Utility Class ==========


class LLMUtils:
    """
    Centralized interface for all LLM operations—preferred for dependency injection.
    """

    def __init__(
        self,
        providers: Optional[Dict[str, LLMProviderBase]] = None,
        default: Optional[str] = None,
        use_registry: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        if default is None:
            try:
                from ai_karen_engine.config.runtime import get_runtime_settings

                default = get_runtime_settings().llm.default_provider
            except Exception:
                default = "builtin_transformers"

        self.config = config or {}
        self.use_registry = use_registry
        self.default = default

        # Runtime safety controls for retry/backoff and circuit breaking
        self.max_retries = int(self._get_config_value("max_retries", 3))
        self.base_retry_delay = float(self._get_config_value("base_retry_delay", 0.6))
        self.max_retry_delay = float(self._get_config_value("max_retry_delay", 8.0))
        self.circuit_breaker_threshold = int(
            self._get_config_value("circuit_breaker_threshold", 3)
        )
        self.circuit_breaker_cooldown = float(
            self._get_config_value("circuit_breaker_cooldown", 45.0)
        )
        self.rate_limit_cooldown = float(
            self._get_config_value("rate_limit_cooldown", 20.0)
        )
        self.max_rate_limit_cooldown = float(
            self._get_config_value("max_rate_limit_cooldown", 90.0)
        )
        self.rate_limit_retry_window = float(
            self._get_config_value("rate_limit_retry_window", 1.5)
        )

        # Provider state cache for circuit breaker / rate limiting metadata
        self._provider_state: Dict[str, Dict[str, Any]] = {}

        if self.use_registry and not _should_use_registry():
            self.use_registry = False

        if self.use_registry:
            try:
                # Use registry for provider management (import here to avoid circular import)
                from ai_karen_engine.integrations.llm_registry import get_registry

                self.registry = get_registry()
                self.providers = {}  # Cache for instantiated providers

                # Prefer first available provider when the configured default is unavailable
                try:
                    available = set(self.registry.get_available_providers())
                    if self.default not in available:
                        picked = self.registry.auto_select_provider({})
                        if picked:
                            logger.info(
                                "Default provider '%s' unavailable; using first available: '%s'",
                                self.default,
                                picked,
                            )
                            self.default = picked
                except Exception:
                    logger.debug(
                        "Default provider auto-select probe failed", exc_info=True
                    )
            except Exception as registry_error:
                logger.warning(
                    "LLM registry unavailable (%s); falling back to simple provider mode",
                    registry_error,
                )
                self.use_registry = False

        if not self.use_registry:
            if providers is None:
                from ai_karen_engine.integrations.providers.fallback_provider import (
                    FallbackProvider,
                )

                providers = {"fallback": FallbackProvider()}

            self.providers = providers
            self.registry = None

            if self.default not in self.providers:
                self.default = next(iter(self.providers))

    def get_provider(self, provider: Optional[str] = None) -> LLMProviderBase:
        provider_name = provider or self.default

        if self.use_registry:
            # Get provider from registry
            if provider_name in self.providers:
                return self.providers[provider_name]

            # Create provider instance via registry
            provider_instance = self.registry.get_provider(provider_name)
            if not provider_instance:
                raise ProviderNotAvailable(
                    f"Provider '{provider_name}' not available in registry."
                )

            # Cache the instance
            self.providers[provider_name] = provider_instance
            return provider_instance
        else:
            # Legacy mode
            if provider_name not in self.providers:
                raise ProviderNotAvailable(
                    f"Provider '{provider_name}' not registered."
                )
            return self.providers[provider_name]

    def list_available_providers(self) -> List[str]:
        """Get list of available providers."""
        if self.use_registry:
            return self.registry.get_available_providers()
        else:
            return list(self.providers.keys())

    def health_check_provider(self, provider: str) -> Dict[str, Any]:
        """Perform health check on a specific provider."""
        if self.use_registry:
            return self.registry.health_check(provider)
        else:
            # Basic health check for legacy mode
            try:
                provider_instance = self.get_provider(provider)
                if hasattr(provider_instance, "health_check"):
                    return provider_instance.health_check()
                else:
                    return {"status": "healthy", "message": "Provider available"}
            except Exception as ex:
                return {"status": "unhealthy", "error": str(ex)}

    def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Perform health check on all providers."""
        if self.use_registry:
            return self.registry.health_check_all()
        else:
            results = {}
            for provider_name in self.providers.keys():
                results[provider_name] = self.health_check_provider(provider_name)
            return results

    def auto_select_provider(
        self, requirements: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Automatically select best available provider."""
        if self.use_registry:
            return self.registry.auto_select_provider(requirements)
        else:
            # Simple fallback for legacy mode
            available = self.list_available_providers()
            return available[0] if available else None

    def _record_request(
        self,
        provider_name: str,
        model: Optional[str],
        usage: Dict[str, Any],
        latency: float,
        user_ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist request metrics for cost reporting."""
        if (
            not _ensure_db_dependencies()
            or not get_db_session_context
            or not LLMRequest
        ):
            if _DB_IMPORT_ERROR:
                logger.debug(
                    "Database dependencies unavailable; skipping LLM request recording: %s",
                    _DB_IMPORT_ERROR,
                )
            return

        try:
            with get_db_session_context() as session:  # type: ignore[misc]
                provider_rec = (
                    session.query(LLMProvider).filter_by(name=provider_name).first()
                    if LLMProvider
                    else None
                )
                provider_id = provider_rec.id if provider_rec else None
                req = LLMRequest(
                    provider_id=provider_id,
                    provider_name=provider_name,
                    model=model,
                    tenant_id=(user_ctx or {}).get("tenant_id"),
                    user_id=(user_ctx or {}).get("user_id"),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    cost=usage.get("cost"),
                    latency_ms=int(latency * 1000),
                )
                session.add(req)
                session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to record LLM request")

    def generate_text(
        self,
        prompt: str,
        provider: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_ctx: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> str:
        requested_provider = provider or self.default
        requested_model = kwargs.get("model")
        trace_id = trace_id or str(uuid.uuid4())
        start_time = time.time()
        overall_provider = requested_provider or self.default
        overall_model = requested_model or ""
        overall_status = "error"

        provider_chain = self._build_provider_chain(requested_provider)
        metrics_service = _get_metrics_service_safe()
        meta_base = {
            "prompt": prompt[:100],
            "provider_chain": provider_chain,
            "requested_provider": requested_provider,
            "requested_model": requested_model,
            "user_roles": user_ctx.get("roles") if user_ctx else None,
            "trace_id": trace_id,
            "kwargs": kwargs,
        }
        trace_llm_event("generate_text_start", trace_id, meta_base)
        logger.info(
            "LLM request start",
            extra={
                "event": "llm_request_start",
                "trace_id": trace_id,
                "provider_chain": provider_chain,
                "requested_provider": requested_provider,
            },
        )

        errors: List[str] = []
        base_kwargs = dict(kwargs)

        try:
            for provider_name in provider_chain:
                state = self._get_provider_state(provider_name)
                if self._is_circuit_open(provider_name, state):
                    remaining = state.get("open_until", 0) - time.monotonic()
                    logger.warning(
                        "Circuit open for provider %s – skipping attempt (%.1fs remaining)",
                        provider_name,
                        max(0.0, remaining),
                    )
                    errors.append(f"{provider_name}: circuit_open")
                    continue

                if self._should_skip_for_rate_limit(provider_name, state):
                    wait_remaining = (
                        state.get("rate_limited_until", 0) - time.monotonic()
                    )
                    logger.info(
                        "Provider %s is cooling down after rate limit (%.1fs remaining)",
                        provider_name,
                        max(0.0, wait_remaining),
                    )
                    errors.append(f"{provider_name}: rate_limited")
                    continue

                provider_kwargs = dict(base_kwargs)
                if provider_name != requested_provider:
                    provider_kwargs.pop("model", None)

                try:
                    provider_obj = self._resolve_provider(
                        provider_name, provider_kwargs
                    )
                except ProviderNotAvailable as exc:
                    logger.warning("Provider %s unavailable: %s", provider_name, exc)
                    errors.append(f"{provider_name}: unavailable")
                    continue

                effective_provider = (
                    "fallback"
                    if provider_obj.__class__.__name__ == "FallbackProvider"
                    else provider_name
                )

                if effective_provider != provider_name:
                    effective_state = self._get_provider_state(effective_provider)
                    if self._is_circuit_open(effective_provider, effective_state):
                        remaining = (
                            effective_state.get("open_until", 0) - time.monotonic()
                        )
                        logger.warning(
                            "Circuit open for fallback provider %s – skipping (%.1fs remaining)",
                            effective_provider,
                            max(0.0, remaining),
                        )
                        errors.append(f"{effective_provider}: circuit_open")
                        continue
                    if self._should_skip_for_rate_limit(
                        effective_provider, effective_state
                    ):
                        wait_remaining = (
                            effective_state.get("rate_limited_until", 0)
                            - time.monotonic()
                        )
                        logger.info(
                            "Fallback provider %s cooling down after rate limit (%.1fs remaining)",
                            effective_provider,
                            max(0.0, wait_remaining),
                        )
                        errors.append(f"{effective_provider}: rate_limited")
                        continue

                model_name = provider_kwargs.get("model") or getattr(
                    provider_obj, "model", None
                )

                for attempt in range(1, self.max_retries + 1):
                    attempt_start = time.time()
                    status = "success"
                    attempt_meta = {
                        **meta_base,
                        "provider": effective_provider,
                        "model": model_name,
                        "attempt": attempt,
                    }
                try:
                    output = provider_obj.generate_text(prompt, **provider_kwargs)
                    duration = time.time() - attempt_start
                    usage = getattr(provider_obj, "last_usage", {})
                    self._record_request(
                        effective_provider,
                        model_name,
                        usage,
                        duration,
                        user_ctx,
                    )
                    if metrics_service:
                        metrics_service.record_llm_latency(
                            duration,
                            provider=effective_provider,
                            model=model_name or "",
                            status="success",
                            correlation_id=trace_id,
                        )
                    self._record_success(effective_provider)
                    attempt_meta["duration"] = duration
                    trace_llm_event("generate_text_success", trace_id, attempt_meta)
                    logger.info(
                        "LLM provider %s succeeded on attempt %d (%.3fs)",
                        effective_provider,
                        attempt,
                        duration,
                        extra={
                            "event": "llm_request_success",
                            "trace_id": trace_id,
                            "provider": effective_provider,
                            "model": model_name,
                            "attempt": attempt,
                            "duration": duration,
                        },
                    )
                    overall_provider = effective_provider
                    if model_name:
                        overall_model = model_name
                    overall_status = "success"
                    return output
                except (
                    Exception
                ) as ex:  # pragma: no cover - provider specific errors vary
                    status = "error"
                    duration = time.time() - attempt_start
                    if metrics_service:
                        metrics_service.record_llm_latency(
                            duration,
                            provider=effective_provider,
                            model=model_name or "",
                            status="error",
                            correlation_id=trace_id,
                        )
                    self._record_failure(effective_provider, ex)
                    attempt_meta.update(
                        {
                            "duration": duration,
                            "error": str(ex),
                            "status": status,
                        }
                    )
                    trace_llm_event("generate_text_error", trace_id, attempt_meta)
                    logger.warning(
                        "Provider %s attempt %d failed: %s",
                        effective_provider,
                        attempt,
                        ex,
                        extra={
                            "event": "llm_request_failure",
                            "trace_id": trace_id,
                            "provider": effective_provider,
                            "model": model_name,
                            "attempt": attempt,
                            "duration": duration,
                        },
                    )
                    errors.append(f"{effective_provider} attempt {attempt}: {ex}")
                    overall_provider = effective_provider
                    if model_name:
                        overall_model = model_name

                    if self._is_rate_limit_error(ex):
                        cooldown = self._mark_rate_limited(effective_provider, attempt)
                        logger.warning(
                            "Rate limit detected for provider %s (cooldown %.1fs)",
                            effective_provider,
                            cooldown,
                        )
                        break

                    if attempt >= self.max_retries:
                        break

                    delay = self._compute_backoff(attempt)
                    logger.debug(
                        "Retrying provider %s in %.2fs (attempt %d)",
                        provider_name,
                        delay,
                        attempt + 1,
                    )
                    time.sleep(delay)

            detail = "; ".join(errors[-5:]) if errors else "no additional details"
            logger.error(
                "All providers failed for trace %s: %s",
                trace_id,
                detail,
                extra={
                    "event": "llm_request_exhausted",
                    "trace_id": trace_id,
                    "provider_chain": provider_chain,
                    "errors": errors,
                },
            )
            raise GenerationFailed(f"All providers failed. Details: {detail}")
        finally:
            total_duration = time.time() - start_time
            metrics_service_final = _get_metrics_service_safe()
            if metrics_service_final:
                metrics_service_final.record_llm_latency(
                    total_duration,
                    provider=overall_provider,
                    model=overall_model or "",
                    status=overall_status,
                    correlation_id=trace_id,
                )

    def _resolve_provider(
        self, provider_name: str, provider_kwargs: Dict[str, Any]
    ) -> LLMProviderBase:
        model_name = provider_kwargs.get("model")
        provider_obj: Optional[LLMProviderBase]
        if self.use_registry:
            try:
                provider_obj = self.registry.get_provider(
                    provider_name, model=model_name
                )  # type: ignore[arg-type]
            except GenerationFailed as exc:
                logger.warning(
                    "Provider %s failed during initialization: %s",
                    provider_name,
                    exc,
                )
                self._record_failure(provider_name, exc)
                raise ProviderNotAvailable(
                    f"Provider '{provider_name}' not available in registry."
                ) from exc
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Unexpected error initializing provider %s: %s",
                    provider_name,
                    exc,
                )
                self._record_failure(provider_name, exc)
                raise ProviderNotAvailable(
                    f"Provider '{provider_name}' not available in registry."
                ) from exc

            if provider_obj is None:
                raise ProviderNotAvailable(
                    f"Provider '{provider_name}' not available in registry."
                )
            if provider_obj.__class__.__name__ == "FallbackProvider":
                provider_kwargs.setdefault(
                    "model", getattr(provider_obj, "model", None)
                )
            return provider_obj

        provider_obj = self.get_provider(provider_name)
        if provider_obj is None:
            raise ProviderNotAvailable(f"Provider '{provider_name}' not registered.")
        return provider_obj

    def _build_provider_chain(self, requested_provider: str) -> List[str]:
        chain: List[str] = []
        if requested_provider:
            chain.append(requested_provider)

        if self.use_registry:
            try:
                defaults = self.registry.default_chain(healthy_only=False)
            except Exception:
                defaults = []
            for name in defaults:
                if name not in chain:
                    chain.append(name)
            if "fallback" not in chain and hasattr(self.registry, "list_providers"):
                try:
                    if "fallback" in self.registry.list_providers():
                        chain.append("fallback")
                except Exception:
                    pass
        else:
            for name in self.providers.keys():
                if name not in chain:
                    chain.append(name)

        return chain

    def _get_provider_state(self, provider: str) -> Dict[str, Any]:
        state = self._provider_state.setdefault(
            provider,
            {
                "failures": 0,
                "open_until": None,
                "rate_limited_until": None,
                "last_error": None,
            },
        )
        return state

    def _record_success(self, provider: str) -> None:
        state = self._get_provider_state(provider)
        state["failures"] = 0
        state["open_until"] = None
        state["last_error"] = None
        state["rate_limited_until"] = None

    def _record_failure(self, provider: str, error: Exception) -> None:
        state = self._get_provider_state(provider)
        state["failures"] = state.get("failures", 0) + 1
        state["last_error"] = str(error)
        if state["failures"] >= self.circuit_breaker_threshold:
            state["open_until"] = time.monotonic() + self.circuit_breaker_cooldown
            logger.warning(
                "Circuit breaker opened for provider %s after %d failures",
                provider,
                state["failures"],
            )

    def _is_circuit_open(self, provider: str, state: Dict[str, Any]) -> bool:
        open_until = state.get("open_until")
        if not open_until:
            return False
        if time.monotonic() >= open_until:
            state["open_until"] = None
            state["failures"] = 0
            return False
        return True

    def _mark_rate_limited(self, provider: str, attempt: int) -> float:
        cooldown = min(
            self.rate_limit_cooldown * attempt,
            self.max_rate_limit_cooldown,
        )
        state = self._get_provider_state(provider)
        state["rate_limited_until"] = time.monotonic() + cooldown
        return cooldown

    def _should_skip_for_rate_limit(self, provider: str, state: Dict[str, Any]) -> bool:
        until = state.get("rate_limited_until")
        if not until:
            return False
        remaining = until - time.monotonic()
        if remaining <= 0:
            state["rate_limited_until"] = None
            return False
        if remaining <= self.rate_limit_retry_window:
            time.sleep(max(0.0, remaining))
            state["rate_limited_until"] = None
            return False
        return True

    def _compute_backoff(self, attempt: int) -> float:
        base = min(self.base_retry_delay * (2 ** (attempt - 1)), self.max_retry_delay)
        jitter = random.uniform(0, base * 0.25)
        return base + jitter

    def _is_rate_limit_error(self, error: Exception) -> bool:
        message = str(error).lower()
        if "rate limit" in message or "429" in message:
            return True
        status = getattr(error, "status", None) or getattr(error, "status_code", None)
        return status == 429

    def _get_config_value(self, key: str, default: Any) -> Any:
        if key in self.config:
            return self.config[key]
        env_key = f"AI_KAREN_LLM_{key.upper()}"
        value = os.getenv(env_key)
        if value is None:
            return default
        try:
            if isinstance(default, bool):
                return value.lower() in {"1", "true", "yes", "on"}
            if isinstance(default, int):
                return int(value)
            if isinstance(default, float):
                return float(value)
        except ValueError:
            logger.debug("Invalid environment override for %s: %s", key, value)
            return default
        return value

    def embed(
        self,
        text: Union[str, List[str]],
        provider: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_ctx: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> List[float]:
        provider_name = provider or self.default
        model_name = kwargs.get("model")
        if self.use_registry:
            provider_obj = self.registry.get_provider(provider_name, model=model_name)  # type: ignore[arg-type]
            if not provider_obj:
                raise ProviderNotAvailable(
                    f"Provider '{provider_name}' not available in registry."
                )
        else:
            provider_obj = self.get_provider(provider)
        trace_id = trace_id or str(uuid.uuid4())
        model_name = model_name or getattr(provider_obj, "model", None)
        t0 = time.time()
        status = "success"
        meta = {
            "provider": provider_name,
            "trace_id": trace_id,
            "kwargs": kwargs,
        }
        trace_llm_event("embed_start", trace_id, meta)
        try:
            out = provider_obj.embed(text, **kwargs)
            duration = time.time() - t0
            usage = getattr(provider_obj, "last_usage", {})
            self._record_request(
                provider_name,
                model_name,
                usage,
                duration,
                user_ctx,
            )
            meta["duration"] = duration
            trace_llm_event("embed_success", trace_id, meta)
            return out
        except Exception as ex:
            status = "error"
            meta.update({"duration": time.time() - t0, "error": str(ex)})
            trace_llm_event("embed_error", trace_id, meta)
            raise EmbeddingFailed(f"Provider '{provider}' failed: {ex}")
        finally:
            duration = time.time() - t0
            metrics_service = _get_metrics_service_safe()
            if metrics_service:
                metrics_service.record_llm_latency(
                    duration,
                    provider=provider_name,
                    model=model_name or "",
                    status=status,
                )


# ========== Prompt-First Plugin API ==========
def get_llm_manager(
    providers: Optional[Dict[str, LLMProviderBase]] = None,
    default: Optional[str] = None,
    use_registry: bool = True,
) -> LLMUtils:
    return LLMUtils(providers, default=default, use_registry=use_registry)


def generate_text(
    prompt: str,
    provider: Optional[str] = None,
    user_ctx: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> str:
    mgr = get_llm_manager()
    return mgr.generate_text(prompt, provider=provider, user_ctx=user_ctx, **kwargs)


def embed_text(
    text: Union[str, List[str]], provider: Optional[str] = None, **kwargs
) -> List[float]:
    mgr = get_llm_manager()
    return mgr.embed(text, provider=provider, **kwargs)


# ========== __all__ ==========
__all__ = [
    "LLMError",
    "ProviderNotAvailable",
    "GenerationFailed",
    "EmbeddingFailed",
    "PROM_REGISTRY",
    "LLMProviderBase",
    "LLMUtils",
    "get_llm_manager",
    "generate_text",
    "embed_text",
    "record_llm_metric",
]
