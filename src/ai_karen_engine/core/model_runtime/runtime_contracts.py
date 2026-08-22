from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class ExecutionAttemptKind(str, Enum):
    PRIMARY = "primary"
    RETRY = "retry"
    FALLBACK_PROVIDER = "fallback_provider"
    FALLBACK_MODEL = "fallback_model"
    EMERGENCY_STATIC = "emergency_static"


class ExecutionOutcome(str, Enum):
    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    NON_RETRYABLE_FAILURE = "non_retryable_failure"
    FALLBACK_ACTIVATED = "fallback_activated"
    CIRCUIT_OPEN = "circuit_open"
    POLICY_DENIED = "policy_denied"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ProviderRouteDecision:
    """Canonical contract for an LLM provider/model routing decision."""

    decision_id: str = ""
    requested_provider: Optional[str] = None
    requested_model: Optional[str] = None

    selected_provider: Optional[str] = None
    selected_model: Optional[str] = None

    provider_category: Optional[str] = None
    compatibility_profile: Optional[str] = None
    runtime_engine: Optional[str] = None
    transport: Optional[str] = None

    selection_source: str = "unknown"
    selection_strategy: str = "unknown"
    fallback_level: int = 0

    degraded_mode: bool = False
    degradation_type: Optional[str] = None
    degradation_reason: Optional[str] = None

    provider_healthy: bool = True
    model_available: bool = True
    runtime_compatible: bool = True
    allowed_for_current_user: bool = True

    required_capabilities: List[str] = field(default_factory=list)
    matched_capabilities: List[str] = field(default_factory=list)

    provider_catalog_version: Optional[str] = None
    runtime_config_hash: Optional[str] = None
    correlation_id: str = ""
    policy_decision_id: str = ""

    routing_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderExecutionResult:
    """Canonical contract for the result of an LLM provider execution."""
    text: str

    requested_provider: Optional[str]
    requested_model: Optional[str]

    selected_provider: Optional[str]
    selected_model: Optional[str]

    actual_provider: Optional[str]
    actual_model: Optional[str]

    provider_category: Optional[str] = None
    compatibility_profile: Optional[str] = None
    runtime_engine: Optional[str] = None
    transport: Optional[str] = None

    response_source: str = "unknown" # e.g., "provider_runtime", "fallback_provider_runtime", "emergency_static"
    fallback_level: int = 0

    degraded_mode: bool = False
    degradation_type: Optional[str] = None
    degradation_reason: Optional[str] = None

    latency_ms: float = 0.0
    correlation_id: str = ""

    provider_attempts: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None


@dataclass(frozen=True)
class ExecutionAttempt:
    """Canonical contract for a single provider execution attempt."""
    attempt_index: int
    attempt_kind: ExecutionAttemptKind
    provider: str
    model: Optional[str]
    outcome: ExecutionOutcome
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    correlation_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
