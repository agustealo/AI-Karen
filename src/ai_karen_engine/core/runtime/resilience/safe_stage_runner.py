"""
Safe Stage Runner for AI Karen Resilience Layer.

Executes optional stages through a resilient pipeline (flags, timeout, breaker, fallback).
Separates retry semantics from fallback semantics:
- Retry: re-attempting the same stage on transient failures
- Fallback: switching to an alternative strategy when retries are exhausted
Emits observability events for attempts, retries, and fallbacks.
"""

import asyncio
from typing import Callable, Any, Dict, Optional
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.logging.events import ProviderEvents, RuntimeEvents

from .feature_flags import get_feature_flags
from .circuit_breaker import get_breaker_registry
from .fallback_manager import get_fallback_manager
from .pipeline_policy import get_pipeline_policy

logger = get_logger(__name__)


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
        attempt = 0
        last_error = None
        while retries_left >= 0:
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
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=policy.timeout_seconds)
                else:
                    # For sync functions, we use run_in_executor to avoid blocking the event loop
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                        timeout=policy.timeout_seconds
                    )

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
                if retries_left > 0:
                    _emit_resilience_event(
                        ProviderEvents.RETRY,
                        stage_name=stage_name,
                        attempt=attempt,
                        reason="timeout"
                    )
                retries_left -= 1
            except Exception as e:
                last_error = str(e)
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
