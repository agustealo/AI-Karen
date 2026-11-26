"""
Circuit Breaker for AI Karen Resilience Layer.

Per-stage circuit breakers to prevent cascading failures.
Emits observability events for state transitions.
"""

import time
from enum import Enum
from typing import Dict, Optional
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.platform.observability.contracts import EventType
from ai_karen_engine.platform.observability.events import emit_event

logger = get_logger(__name__)


def _emit_circuit_transition(
    name: str, previous: "BreakerState", current: "BreakerState", reason: str,
) -> None:
    """A stage circuit transition is not a provider execution receipt."""
    try:
        emit_event(
            EventType.CIRCUIT_STATE_CHANGED,
            status=current.value,
            execution_layer="resilience",
            metadata={
                "circuit_breaker": name,
                "previous_state": previous.value,
                "new_state": current.value,
                "reason": reason,
            },
        )
    except Exception:
        # The resilience decision is independent of telemetry availability.
        pass


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
            self.state = BreakerState.CLOSED
            _emit_circuit_transition(
                self.name, BreakerState.HALF_OPEN, self.state, "recovery",
            )
        self.failures = 0

    def record_failure(self):
        """Record a failed execution."""
        self.failures += 1
        self.last_failure_time = time.time()

        if self.state == BreakerState.HALF_OPEN:
            logger.warning(
                f"Circuit Breaker '{self.name}' failed during recovery. Setting to OPEN."
            )
            self.state = BreakerState.OPEN
            _emit_circuit_transition(
                self.name, BreakerState.HALF_OPEN, self.state, "recovery_failure",
            )
            return

        if self.state == BreakerState.CLOSED and self.failures >= self.failure_threshold:
            logger.warning(f"Circuit Breaker '{self.name}' tripped. Setting to OPEN.")
            self.state = BreakerState.OPEN
            _emit_circuit_transition(
                self.name, BreakerState.CLOSED, self.state, "tripped",
            )

    def allow_request(self) -> bool:
        """Check if a request is allowed to proceed."""
        if self.state == BreakerState.CLOSED:
            return True

        if self.state == BreakerState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                logger.info(f"Circuit Breaker '{self.name}' attempting recovery. Setting to HALF_OPEN.")
                self.state = BreakerState.HALF_OPEN
                _emit_circuit_transition(
                    self.name, BreakerState.OPEN, self.state, "recovery_probe_allowed",
                )
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
