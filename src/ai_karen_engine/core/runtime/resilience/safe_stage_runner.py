"""
Safe Stage Runner for AI Karen Resilience Layer.

Executes optional stages through a resilient pipeline (flags, timeout, breaker, fallback).
Separates retry semantics from fallback semantics:
- Retry: re-attempting the same stage on transient failures
- Fallback: switching to an alternative strategy when retries are exhausted
Emits observability events for attempts, retries, and fallbacks.
"""

import asyncio
import threading
from typing import Callable, Any, Dict, Optional
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.logging.events import ProviderEvents, RuntimeEvents

from ai_karen_engine.config.performance_config import PerformanceConfig, get_performance_config

from .feature_flags import get_feature_flags
from .circuit_breaker import get_breaker_registry
from .fallback_manager import get_fallback_manager
from .pipeline_policy import get_pipeline_policy

logger = get_logger(__name__)


def _sync_stage_capacity() -> int:
    """Use the canonical performance worker budget, validating before startup."""
    config = get_performance_config() or PerformanceConfig.from_environment()
    value = config.max_worker_threads
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 128:
        raise ValueError("max_worker_threads must be an integer between 1 and 128")
    return value


def _emit_resilience_event(event_name: str, **kwargs):
    """Emit a resilience observability event using structured logging."""
    logger.event(event_name, **kwargs)


class SafeStageRunner:
    """Executes a stage safely, applying resilience patterns.

    Retry semantics: re-attempt the same stage up to max_retries times
    on transient failures (timeout, connection errors).

    Fallback semantics: when retries are exhausted or circuit is open,
    execute an alternative strategy via FallbackManager.
    """

    def __init__(self):
        self.flags = get_feature_flags()
        self.breakers = get_breaker_registry()
        self.fallbacks = get_fallback_manager()
        self.policies = get_pipeline_policy()
        # Capacity is held until the underlying thread actually exits.
        self._sync_slots = threading.BoundedSemaphore(value=_sync_stage_capacity())

    async def run_stage(
        self,
        stage_name: str,
        flag_name: str,
        func: Callable,
        *args,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        request_overrides: Optional[Dict[str, bool]] = None,
        **kwargs
    ) -> Any:
        """
        Execute a stage safely with graceful degradation.
        1. Check feature flag
        2. Check circuit breaker
        3. Enforce timeout and retries (retry semantics)
        4. Provide structured fallback on failure (fallback semantics)
        """
        # 1. Feature Flag Check
        if not self.flags.is_enabled(flag_name, tenant_id, user_id, request_overrides):
            logger.debug(f"Stage '{stage_name}' skipped: Feature flag '{flag_name}' disabled.")
            _emit_resilience_event(
                ProviderEvents.FALLBACK,
                stage_name=stage_name,
                fallback_type="feature_flag_disabled",
                reason=f"flag_disabled:{flag_name}"
            )
            return self.fallbacks.get_fallback(stage_name, *args, **kwargs)

        breaker = self.breakers.get_breaker(stage_name)
        policy = self.policies.get_policy(stage_name)

        # 2. Circuit Breaker Check
        if not breaker.allow_request():
            logger.warning(f"Stage '{stage_name}' blocked: Circuit breaker OPEN.")
            _emit_resilience_event(
                ProviderEvents.FALLBACK,
                stage_name=stage_name,
                fallback_type="circuit_open",
                reason="circuit_breaker_open"
            )
            return self.fallbacks.get_fallback(stage_name, *args, **kwargs)

        # 3. Execution with Timeout & Retries (retry semantics)
        retries_left = policy.max_retries
        # The configured timeout is a total stage budget, not a per-retry reset.
        deadline = asyncio.get_running_loop().time() + policy.timeout_seconds
        attempt = 0
        last_error = None
        while retries_left >= 0:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                last_error = "deadline_exhausted"
                break
            attempt += 1
            _emit_resilience_event(
                ProviderEvents.ATTEMPT_STARTED,
                stage_name=stage_name,
                attempt=attempt,
                retries_remaining=retries_left
            )
            try:
                # Wrap sync functions in thread or assume async
                if asyncio.iscoroutinefunction(func):
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=remaining)
                else:
                    # For sync functions, we use run_in_executor to avoid blocking the event loop
                    if not self._sync_slots.acquire(blocking=False):
                        raise RuntimeError("synchronous_stage_capacity_exhausted")
                    loop = asyncio.get_running_loop()

                    def execute_and_release():
                        try:
                            return func(*args, **kwargs)
                        finally:
                            self._sync_slots.release()

                    try:
                        future = loop.run_in_executor(None, execute_and_release)
                    except BaseException:
                        self._sync_slots.release()
                        raise
                    result = await asyncio.wait_for(asyncio.shield(future), timeout=remaining)

                breaker.record_success()
                _emit_resilience_event(
                    ProviderEvents.ATTEMPT_COMPLETED,
                    stage_name=stage_name,
                    attempt=attempt,
                    retries_used=policy.max_retries - retries_left
                )
                return result

            except asyncio.TimeoutError:
                last_error = "timeout"
                logger.error(f"Stage '{stage_name}' timed out after {policy.timeout_seconds}s.")
                breaker.record_failure()
                _emit_resilience_event(
                    ProviderEvents.ATTEMPT_FAILED,
                    stage_name=stage_name,
                    attempt=attempt,
                    error="timeout",
                    retries_remaining=retries_left
                )
                if retries_left > 0 and deadline > asyncio.get_running_loop().time():
                    _emit_resilience_event(
                        ProviderEvents.RETRY,
                        stage_name=stage_name,
                        attempt=attempt,
                        reason="timeout"
                    )
                retries_left -= 1
            except Exception as exc:
                # Stage errors can include connection credentials, personal
                # memory, or private backend query text. Preserve a stable
                # diagnostic type, never a raw exception message in telemetry.
                last_error = type(exc).__name__
                logger.error(f"Stage '{stage_name}' failed: {last_error}")
                breaker.record_failure()
                _emit_resilience_event(
                    ProviderEvents.ATTEMPT_FAILED,
                    stage_name=stage_name,
                    attempt=attempt,
                    error=last_error,
                    retries_remaining=retries_left
                )
                if retries_left > 0:
                    _emit_resilience_event(
                        ProviderEvents.RETRY,
                        stage_name=stage_name,
                        attempt=attempt,
                        reason="exception"
                    )
                retries_left -= 1

        # 4. Record Failure and Fallback (fallback semantics)
        _emit_resilience_event(
            ProviderEvents.EXHAUSTED,
            stage_name=stage_name,
            total_attempts=attempt,
            last_error=last_error
        )
        _emit_resilience_event(
            RuntimeEvents.DEGRADED,
            stage_name=stage_name,
            reason="all_retries_exhausted"
        )
        return self.fallbacks.get_fallback(stage_name, *args, **kwargs)


safe_runner = SafeStageRunner()


def get_safe_stage_runner() -> SafeStageRunner:
    return safe_runner
