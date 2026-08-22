"""
Circuit Breaker for AI Karen Resilience Layer.

Per-stage circuit breakers to prevent cascading failures.
Emits observability events for state transitions.
"""

import time
from enum import Enum
from typing import Dict, Optional
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.logging.events import ProviderEvents

logger = get_logger(__name__)


def _emit_provider_event(event_name: str, **kwargs):
    """Emit a provider observability event using structured logging."""
    logger.event(event_name, **kwargs)


class BreakerState(Enum):
    CLOSED = "CLOSED"     # Normal operation
    OPEN = "OPEN"         # Failing, fallback immediately
    HALF_OPEN = "HALF_OPEN" # Testing recovery


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self.state = BreakerState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0

    def record_success(self):
        """Record a successful execution."""
        if self.state == BreakerState.HALF_OPEN:
            logger.info(f"Circuit Breaker '{self.name}' recovered. Setting to CLOSED.")
            _emit_provider_event(
                ProviderEvents.ATTEMPT_COMPLETED,
                circuit_breaker=self.name,
                state=BreakerState.CLOSED.value,
                event="recovery"
            )
            self.state = BreakerState.CLOSED
        self.failures = 0

    def record_failure(self):
        """Record a failed execution."""
        self.failures += 1
        self.last_failure_time = time.time()

        if self.state == BreakerState.HALF_OPEN:
            logger.warning(
                f"Circuit Breaker '{self.name}' failed during recovery. Setting to OPEN."
            )
            _emit_provider_event(
                ProviderEvents.ATTEMPT_FAILED,
                circuit_breaker=self.name,
                state=BreakerState.OPEN.value,
                event="recovery_failure",
                failures=self.failures
            )
            self.state = BreakerState.OPEN
            return

        if self.state == BreakerState.CLOSED and self.failures >= self.failure_threshold:
            logger.warning(f"Circuit Breaker '{self.name}' tripped. Setting to OPEN.")
            _emit_provider_event(
                ProviderEvents.CIRCUIT_OPEN,
                circuit_breaker=self.name,
                state=BreakerState.OPEN.value,
                event="tripped",
                failures=self.failures,
                threshold=self.failure_threshold
            )
            self.state = BreakerState.OPEN

    def allow_request(self) -> bool:
        """Check if a request is allowed to proceed."""
        if self.state == BreakerState.CLOSED:
            return True

        if self.state == BreakerState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                logger.info(f"Circuit Breaker '{self.name}' attempting recovery. Setting to HALF_OPEN.")
                self.state = BreakerState.HALF_OPEN
                return True
            return False

        # HALF_OPEN: allow 1 request to test
        return True


class CircuitBreakerRegistry:
    """Registry for managing per-stage circuit breakers."""
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._initialize_default_breakers()
        
    def _initialize_default_breakers(self):
        # Default breakers defined by the Karen architecture
        defaults = [
            "spacy",
            "distilbert",
            "milvus_retrieval",
            "elasticsearch",
            "leangraph_projection",
            "profile_synthesis",
            "echocore_batch",
            "reasoning_retrieval",
            "reasoning_causal",
            "reasoning_graph",
            "reasoning_soft",
            "reasoning_synthesis",
            "kro_orchestrator",
        ]
        for name in defaults:
            self._breakers[name] = CircuitBreaker(name)
            
    def get_breaker(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name)
        return self._breakers[name]
        
    def get_all_states(self) -> Dict[str, str]:
        return {name: breaker.state.value for name, breaker in self._breakers.items()}

# Singleton registry
breaker_registry = CircuitBreakerRegistry()

def get_breaker_registry() -> CircuitBreakerRegistry:
    return breaker_registry
