"""
LLMOrchestrator: Nuclear-Grade LLM Routing Engine for Kari
- Zero-trust model routing with cryptographic validation
- Hardware-isolated execution domains (psutil/sched_setaffinity)
- Adaptive load balancing with circuit breakers
- Military-grade observability and audit trails
- Enhanced with failover strategies and resource monitoring
- Integrated with PerformanceAdaptiveRouter for optimal routing decisions
"""

import hashlib
import hmac
import importlib.util
import logging
import os
import random
import re
import secrets
import sys
import textwrap
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple, Union

from ai_karen_engine.core.errors.exceptions import RateLimitError


# === Constants & Configuration ===
DEFAULT_CONFIG = {
    "max_concurrent_requests": 8,
    "request_timeout": 60,
    "failure_trip_limit": 3,
    "watchdog_interval": 30,
    "cpu_reservation": 0.2,  # Reserve 20% CPU capacity
    "memory_threshold": 0.8,  # 80% memory usage threshold
    "circuit_base_delay": 2.0,
    "circuit_max_delay": 60.0,
    "rate_limit_base_delay": 5.0,
    "rate_limit_max_delay": 180.0,
    "max_rate_limit_queue": 256,
}


# === Enhanced Logging ===
class SecureLogger:
    """Logging with redaction and secure handling"""

    REDACTION_KEYS = {"api_key", "token", "password", "secret"}

    def __init__(self):
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        log_file = self._resolve_log_path()
        logger = logging.getLogger("llm_orchestrator")
        logger.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S%z",
        )

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(self._security_filter)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(self._security_filter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def _security_filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive information from logs"""
        try:
            msg = record.getMessage()
            for sensitive in self.REDACTION_KEYS:
                if sensitive in msg.lower():
                    record.msg = "[REDACTED]"
                    record.args = ()
                    break
        except Exception:
            pass
        return True

    def _resolve_log_path(self) -> Path:
        """Resolve log file path with fallbacks"""
        paths = [
            os.getenv("KARI_LOG_DIR"),
            "/var/log/kari",
            Path.home() / ".kari" / "logs",
        ]

        for path in paths:
            if not path:
                continue
            try:
                log_dir = Path(path)
                log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                log_file = log_dir / "llm_orchestrator.log"
                log_file.touch(exist_ok=True)
                os.chmod(log_file, 0o600)
                return log_file
            except (OSError, PermissionError):
                continue

        raise RuntimeError("Could not establish secure logging location")


logger = SecureLogger().logger


# === Security Core ===
class SecurityEngine:
    """Centralized security operations"""

    def __init__(self):
        self._signing_key = self._load_signing_key()

    def _load_signing_key(self) -> bytes:
        """Load and validate signing key

        Falls back to an ephemeral key in non-production environments if the
        environment variable is missing. This is intended only for local
        development; production environments must always provide a valid key.
        """
        key = os.getenv("KARI_MODEL_SIGNING_KEY")
        if key:
            if len(key) < 32:
                raise RuntimeError(
                    "KARI_MODEL_SIGNING_KEY must be at least 32 characters long"
                )
            return key.encode("utf-8")

        env = os.getenv("KARI_ENV", "local").lower()
        if env == "production":
            raise RuntimeError(
                "KARI_MODEL_SIGNING_KEY is required in production environments"
            )

        logger.warning(
            "KARI_MODEL_SIGNING_KEY not set; generating ephemeral key for development."
            " Do NOT use this in production."
        )
        return secrets.token_bytes(32)

    def generate_signature(self, *parts: str) -> str:
        """Generate HMAC-SHA256 signature"""
        message = "|".join(parts).encode("utf-8")
        return hmac.new(self._signing_key, message, hashlib.sha256).hexdigest()

    def verify_signature(self, signature: str, *parts: str) -> bool:
        """Verify HMAC-SHA256 signature"""
        expected = self.generate_signature(*parts)
        return hmac.compare_digest(signature, expected)


# === Hardware Isolation ===
class HardwareManager:
    """Manage hardware resources and isolation"""

    def __init__(self):
        self.cpu_count = self._detect_cpu_count()
        self.psutil_available = self._check_psutil()

    def _detect_cpu_count(self) -> int:
        """Get available CPU count with safety margin"""
        total = os.cpu_count() or 4
        reserved = max(1, int(total * DEFAULT_CONFIG["cpu_reservation"]))
        return max(1, total - reserved)

    def _check_psutil(self) -> bool:
        """Check if psutil is available"""
        try:
            return importlib.util.find_spec("psutil") is not None
        except Exception:
            return False

    def set_affinity(self, cpu_id: int) -> bool:
        """Set CPU affinity for current thread"""
        try:
            if self.psutil_available:
                import psutil

                p = psutil.Process(os.getpid())
                p.cpu_affinity([cpu_id])
            elif hasattr(os, "sched_setaffinity"):
                os.sched_setaffinity(0, {cpu_id})
            else:
                return False
            return True
        except Exception as e:
            logger.warning(f"CPU affinity setting failed: {e}")
            return False

    def check_memory(self) -> bool:
        """Check if memory usage is within safe thresholds"""
        try:
            if self.psutil_available:
                import psutil

                mem = psutil.virtual_memory()
                return mem.percent < (DEFAULT_CONFIG["memory_threshold"] * 100)
            return True
        except Exception:
            return True


# === Model Definitions ===
class ModelStatus(Enum):
    ACTIVE = auto()
    DEGRADED = auto()
    RATE_LIMITED = auto()
    FAILED = auto()
    CIRCUIT_BROKEN = auto()


@dataclass
class LLMRouteResult:
    """Structured result returned from routing a prompt to a provider."""

    content: str
    model_id: Optional[str]
    provider: Optional[str]
    model_name: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    is_degraded: bool = False
    attempted_models: List[str] = field(default_factory=list)
    failure_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> Dict[str, Any]:
        """Return a serialisable dictionary for downstream consumers."""

        metadata_failure_reason = None
        if isinstance(self.metadata, dict):
            preferred = self.metadata.get("preferred_failure_reason")
            override = self.metadata.get("failure_reason")
            if isinstance(preferred, str) and preferred.strip():
                metadata_failure_reason = preferred.strip()
            elif isinstance(override, str) and override.strip():
                metadata_failure_reason = override.strip()

        data: Dict[str, Any] = {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "provider": self.provider,
            "tags": list(self.tags),
            "is_degraded": self.is_degraded,
        }

        if self.attempted_models:
            data["attempted_models"] = list(self.attempted_models)
        if metadata_failure_reason:
            data["failure_reason"] = metadata_failure_reason
            if self.failure_reason and self.failure_reason != metadata_failure_reason:
                data["raw_failure_reason"] = self.failure_reason
        elif self.failure_reason:
            data["failure_reason"] = self.failure_reason
        
        # Flatten metadata into the main dictionary
        if self.metadata:
            for k, v in self.metadata.items():
                if k == "failure_reason" and metadata_failure_reason:
                    continue
                if k not in data:
                    data[k] = v
                else:
                    data[f"meta_{k}"] = v

        return data


@dataclass
class ModelInfo:
    model_id: str
    model: Any
    capabilities: List[str]
    weight: int = 1
    tags: List[str] = field(default_factory=list)
    signature: str = ""
    failure_count: int = 0
    consecutive_failures: int = 0
    last_used: float = 0.0
    created: float = field(default_factory=time.time)
    status: ModelStatus = ModelStatus.ACTIVE
    latency_samples: List[float] = field(default_factory=list)
    warmed: bool = False
    cooldown_until: float = 0.0
    rate_limit_until: float = 0.0
    last_error: Optional[str] = None
    degradation_notes: List[str] = field(default_factory=list)

    def record_latency(self, latency: float, max_samples: int = 50) -> None:
        self.latency_samples.append(latency)
        if len(self.latency_samples) > max_samples:
            self.latency_samples.pop(0)

    def p95_latency(self) -> float:
        if not self.latency_samples:
            return float("inf")
        samples = sorted(self.latency_samples)
        idx = max(0, int(0.95 * (len(samples) - 1)))
        return samples[idx]


# === Circuit Breaker State ===


class CircuitOpenError(RuntimeError):
    """Raised when attempting to use a model whose circuit breaker is open."""

    def __init__(
        self,
        model_id: str,
        retry_after: float,
        reason: str = "",
        rate_limited: bool = False,
    ) -> None:
        message = (
            f"Circuit open for model {model_id}. Retry after {retry_after:.2f}s"
        )
        if reason:
            message = f"{message} (reason: {reason})"
        super().__init__(message)
        self.model_id = model_id
        self.retry_after = retry_after
        self.reason = reason
        self.rate_limited = rate_limited


@dataclass
class CircuitState:
    failure_count: int = 0
    opened_until: float = 0.0
    last_failure: float = 0.0
    reason: str = ""
    rate_limited: bool = False
    retry_after: float = 0.0

    def is_open(self) -> bool:
        if self.opened_until <= 0:
            return False
        return time.time() < self.opened_until

    def remaining(self) -> float:
        return max(0.0, self.opened_until - time.time())


# === Enhanced Model Registry ===
class ModelRegistry:
    """Secure model registry with enhanced management"""

    def __init__(self, security: SecurityEngine):
        self._models: Dict[str, ModelInfo] = {}
        self._lock = threading.RLock()
        self.security = security

    def register(self, model_id: str, model: Any, capabilities: List[str], **kwargs):
        """Register a new model with cryptographic validation"""
        with self._lock:
            if model_id in self._models:
                raise ValueError(f"Model {model_id} already registered")

            signature = self._generate_signature(
                model_id, capabilities, kwargs.get("weight", 1)
            )
            self._models[model_id] = ModelInfo(
                model_id=model_id,
                model=model,
                capabilities=capabilities,
                signature=signature,
                **kwargs,
            )
            logger.info(
                f"Registered model {model_id} with capabilities: {capabilities}"
            )

    def _generate_signature(
        self, model_id: str, capabilities: List[str], weight: int
    ) -> str:
        """Generate cryptographic signature for model"""
        return self.security.generate_signature(
            model_id, ",".join(sorted(capabilities)), str(weight)
        )

    def verify(self, model_id: str) -> bool:
        """Verify model integrity"""
        with self._lock:
            if model_id not in self._models:
                return False
            model = self._models[model_id]
            expected = self._generate_signature(
                model_id, model.capabilities, model.weight
            )
            return hmac.compare_digest(expected, model.signature)

    def get(self, model_id: str) -> Optional[ModelInfo]:
        """Get model info if it exists and is valid"""
        with self._lock:
            if model_id in self._models and self.verify(model_id):
                return self._models[model_id]
            return None

    def get_provider_info(self, provider_name: str) -> Optional[Dict[str, Any]]:
        """Return information for the requested provider if any models are registered."""
        with self._lock:
            for model_id, info in self._models.items():
                if model_id.startswith(f"{provider_name}:"):
                    return {
                        "provider": provider_name,
                        "status": info.status.name,
                        "capabilities": info.capabilities,
                        "error_message": getattr(info.model, "initialization_error", None)
                    }
            return None

    def list_models(self) -> List[Dict[str, Any]]:
        """Get list of all valid models"""
        with self._lock:
            return [
                {
                    "model_id": model.model_id,
                    "capabilities": model.capabilities,
                    "tags": model.tags,
                    "status": model.status.name,
                    "last_used": model.last_used,
                    "failure_count": model.failure_count,
                }
                for model in self._models.values()
                if self.verify(model.model_id)
            ]


# === Execution Pool with Enhanced Features ===
class ExecutionPool:
    """Secure execution environment with resource management"""

    def __init__(self, hardware: HardwareManager):
        self.hardware = hardware
        self.executor = ThreadPoolExecutor(
            max_workers=DEFAULT_CONFIG["max_concurrent_requests"],
            thread_name_prefix="llm_worker",
        )
        self.circuit_states: Dict[str, CircuitState] = {}
        self.lock = threading.RLock()

    @staticmethod
    def _is_local_model(model_id: str) -> bool:
        """Return whether the target model runs inside the API process.

        Ollama is an external HTTP runtime from Karen's perspective, even when
        it is deployed as a sidecar container. Guarding it behind the API
        container's in-process memory threshold incorrectly degrades requests
        before any Ollama call is attempted.
        """
        normalized = (model_id or "").strip().lower()
        return normalized.startswith(("local:", "local_gguf:"))

    @staticmethod
    def _is_resource_pressure_error(error: Exception) -> bool:
        """Return whether an exception represents local resource pressure."""
        return "system memory threshold exceeded" in str(error).strip().lower()

    def execute(self, model_id: str, fn: Callable, *args, **kwargs) -> Future:
        """Execute function in secure environment"""
        if self._is_local_model(model_id) and not self.hardware.check_memory():
            raise RuntimeError("System memory threshold exceeded")

        state = self._check_circuit(model_id)
        if state:
            raise CircuitOpenError(
                model_id,
                state.remaining(),
                reason=state.reason,
                rate_limited=state.rate_limited,
            )

        cpu_id = random.randint(0, self.hardware.cpu_count - 1)
        job_id = str(uuid.uuid4())[:8]

        def _wrapped():
            try:
                self.hardware.set_affinity(cpu_id)
                logger.info(f"[{job_id}] Executing on CPU {cpu_id}")
                return fn(*args, **kwargs)
            except Exception as e:
                logger.error(f"[{job_id}] Execution failed: {str(e)}")
                raise
            finally:
                logger.info(f"[{job_id}] Execution completed")

        future = self.executor.submit(_wrapped)
        future.model_id = model_id  # type: ignore
        future.job_id = job_id  # type: ignore
        return future

    def _check_circuit(self, model_id: str) -> Optional[CircuitState]:
        """Return circuit state if breaker is currently open."""
        with self.lock:
            state = self.circuit_states.get(model_id)
            if not state:
                return None
            if state.is_open():
                return state
            # Circuit is no longer open; reset transient flags
            if state.rate_limited:
                state.rate_limited = False
                state.reason = ""
                state.retry_after = 0.0
            if state.failure_count == 0:
                return None
            return None

    def _record_outcome(
        self, model_id: str, success: bool, error: Optional[Exception] = None
    ) -> None:
        """Update circuit breaker state with exponential backoff handling."""

        with self.lock:
            state = self.circuit_states.setdefault(model_id, CircuitState())
            if success:
                state.failure_count = 0
                state.opened_until = 0.0
                state.reason = ""
                state.rate_limited = False
                state.retry_after = 0.0
                return

            state.failure_count += 1
            state.last_failure = time.time()

            reason = str(error) if error else "Unknown failure"
            state.reason = reason

            base_delay = DEFAULT_CONFIG.get("circuit_base_delay", 2.0)
            max_delay = DEFAULT_CONFIG.get("circuit_max_delay", 60.0)
            exponent = min(state.failure_count - 1, 6)
            jitter = random.uniform(0, base_delay)
            delay = min(max_delay, base_delay * (2 ** exponent)) + jitter

            retry_after = getattr(error, "retry_after", None)
            is_rate_limited = isinstance(error, RateLimitError) or (
                isinstance(reason, str) and "rate limit" in reason.lower()
            )
            if is_rate_limited:
                rate_base = DEFAULT_CONFIG.get("rate_limit_base_delay", base_delay)
                delay = max(delay, rate_base)
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except (TypeError, ValueError):
                        pass
                delay = min(
                    DEFAULT_CONFIG.get("rate_limit_max_delay", max_delay), delay
                )
                state.rate_limited = True
            else:
                state.rate_limited = False

            state.retry_after = delay
            state.opened_until = time.time() + delay


# === Core Orchestrator ===
class LLMOrchestrator:
    """Enhanced LLM routing engine with failover strategies"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.__init__()
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self.security = SecurityEngine()
            self.hardware = HardwareManager()
            self.registry = ModelRegistry(self.security)
            self.pool = ExecutionPool(self.hardware)
            queue_size = int(DEFAULT_CONFIG.get("max_rate_limit_queue", 256))
            self._rate_limit_queue: Deque[Dict[str, Any]] = deque(maxlen=queue_size)
            self._degraded_events: Deque[Dict[str, Any]] = deque(maxlen=64)
            
            self._setup_watchdog()
            self._initialized = True
            
            # Ensure minimum models are available for health probes before returning
            self._ensure_minimum_models_registered()
            
            # Provider warmup can load local model runtimes and pin the
            # interpreter long enough to make the API stop answering health
            # checks. Keep it opt-in; chat runtime fallback is owned by the
            # provider router and should not depend on legacy warmup.
            if os.getenv("KARI_ENABLE_PROVIDER_PRELOAD", "").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }:
                preload_thread = threading.Thread(
                    target=self._preload_providers_safe,
                    daemon=True,
                    name="orchestrator-preloader",
                )
                preload_thread.start()
            else:
                logger.info("Legacy provider preload disabled")
            
            self._initialized = True

    def _setup_watchdog(self):
        """Start monitoring thread"""

        def _monitor():
            while True:
                time.sleep(DEFAULT_CONFIG["watchdog_interval"])
                self._audit_models()

        thread = threading.Thread(
            target=_monitor, daemon=True, name="orchestrator-watchdog"
        )
        thread.start()

    def _audit_models(self):
        """Periodically verify all models"""
        with self.registry._lock:
            for model_id in list(self.registry._models.keys()):
                if not self.registry.verify(model_id):
                    logger.warning(f"Model integrity check failed: {model_id}")
                    del self.registry._models[model_id]

    def _preload_providers_safe(self) -> None:
        """Safe wrapper for preloading to catch and log errors."""
        try:
            logger.info("Starting background provider preloading")
            self._preload_providers()
            logger.info("Background provider preloading completed")
        except Exception as e:
            logger.error(f"Background preloading failed: {e}")

    def _preload_providers(self) -> None:
        """Initialize providers at startup and warm their caches."""
        from ai_karen_engine.integrations.provider_registry import (
            ModelInfo as ProviderModelInfo,
            get_provider_registry,
        )

        registry = get_provider_registry()
        for provider_name in registry.list_providers():
            info = registry.get_provider_info(provider_name)
            if not info:
                continue
            models: List[ProviderModelInfo] = info.models or []
            if not models:
                default_name = info.default_model or provider_name
                models = [ProviderModelInfo(name=default_name, capabilities=["generic"])]
            elif info.default_model:
                default_models = [m for m in models if m.name == info.default_model]
                if default_models:
                    # Avoid registering and warming an entire cloud catalog at startup.
                    # One representative model per provider is enough for health and routing bootstrap.
                    models = default_models

            warm_provider = self._should_warm_provider(provider_name)
            for m in models:
                try:
                    provider = registry.get_provider(provider_name, model=m.name)
                    model_id = f"{provider_name}:{m.name}"
                    capabilities = m.capabilities or ["generic"]
                    register_kwargs = {}
                    if provider_name.lower() == "fallback":
                        # Ensure fallback provider is always tried last
                        register_kwargs["weight"] = 100
                        register_kwargs["tags"] = ["fallback", "deterministic"]
                    elif provider_name.lower() == "builtin_transformers":
                        # Tag built-in runtimes for live fallback in degraded mode
                        register_kwargs["tags"] = ["local", "fallback", "runtime"]
                        register_kwargs["weight"] = 20
                    self.registry.register(
                        model_id,
                        provider,
                        capabilities,
                        **register_kwargs,
                    )
                    latency = self._warm_model(model_id, provider) if warm_provider else None
                    if latency is not None:
                        info = self.registry._models.get(model_id)
                        if info:
                            info.warmed = True
                            info.record_latency(latency)
                except Exception as e:  # pragma: no cover - warmup is best effort
                    logger.warning(f"Provider preload failed for {provider_name}:{m.name}: {e}")

        # Register local models as fallback
        self._register_local_models()
        # Ensure we always have a deterministic fallback available
        self._ensure_fallback_provider()

    def _ensure_fallback_provider(self) -> None:
        """Guarantee that a deterministic fallback model is available."""
        try:
            from ai_karen_engine.integrations.providers.fallback_provider import (
                FallbackProvider,
            )
        except Exception as exc:  # pragma: no cover - import should always succeed
            logger.error("Failed to import fallback provider: %s", exc)
            return

        fallback_provider = FallbackProvider()
        fallback_model_id = f"fallback:{fallback_provider.model}"
        fallback_caps = ["generic", "conversation", "text"]

        # If already registered, refresh the instance to keep it healthy
        with self.registry._lock:
            existing = self.registry._models.get(fallback_model_id)
            if existing:
                existing.model = fallback_provider
                existing.status = ModelStatus.ACTIVE
                existing.tags = list({*existing.tags, "fallback", "offline"})
                logger.debug("Refreshed fallback provider instance")
                return

        try:
            self.registry.register(
                fallback_model_id,
                fallback_provider,
                fallback_caps,
                weight=1,
                tags=["fallback", "offline"],
            )
            logger.info("Registered deterministic fallback provider")
        except ValueError:
            # Another thread may have registered it concurrently; refresh and exit
            with self.registry._lock:
                existing = self.registry._models.get(fallback_model_id)
                if existing:
                    existing.model = fallback_provider
                    existing.status = ModelStatus.ACTIVE
                    existing.tags = list({*existing.tags, "fallback", "offline"})
            return

        latency = self._warm_model(fallback_model_id, fallback_provider)
        if latency is not None:
            info = self.registry._models.get(fallback_model_id)
            if info:
                info.warmed = True
                info.record_latency(latency)

    def _should_warm_provider(self, provider_name: str) -> bool:
        """Warm only cheap/local providers by default.

        Cloud providers often trigger expensive network calls and large model
        catalog initialization during startup, which can interfere with active
        requests and exhaust memory on constrained dev hosts.
        """
        if os.getenv("KARI_WARM_CLOUD_PROVIDERS", "").lower() in {"1", "true", "yes", "on"}:
            return True

        localish_providers = {
            "fallback",
            "local",
            "local_gguf",
            "transformers",
            "huggingface-local",
        }
        return provider_name.lower() in localish_providers

    def _ensure_minimum_models_registered(self) -> None:
        """Synchronously ensure the registry is never empty during routing."""
        with self.registry._lock:
            if self.registry._models:
                return

        logger.warning(
            "LLM registry empty at request time; attempting synchronous local/fallback registration"
        )

        try:
            self._register_local_models()
        except Exception as exc:
            logger.warning("Synchronous local model registration failed: %s", exc)

        try:
            self._ensure_fallback_provider()
        except Exception as exc:
            logger.warning("Synchronous fallback provider registration failed: %s", exc)

    def _register_local_models(self) -> None:
        """Register local models as fallback options."""
        try:
            from pathlib import Path
            from ai_karen_engine.inference.local_gguf_runtime import LocalGGUFRuntime
            
            # First, register the SmallLanguageModelService if enabled
            try:
                from ai_karen_engine.core.reasoning.synthesis.small_language_model_service import SmallLanguageModelService

                logger.info("Initializing SmallLanguageModelService")

                # Create a wrapper class for the SmallLanguageModelService to match the provider interface
                class SmallLanguageModelProvider:
                    def __init__(self):
                        self.service = SmallLanguageModelService()
                        self._ensure_model_loaded()

                    def _ensure_model_loaded(self):
                        """Ensure a model is loaded."""
                        if not self.service.current_model:
                            available_models = self.service.get_available_models()
                            for model_info in available_models:
                                if model_info.is_available:
                                    self.service.switch_model(model_info.name)
                                    break

                    def _run_scaffold(self, prompt: str, task_type: str) -> str:
                        import asyncio
                        import concurrent.futures

                        self._ensure_model_loaded()
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                with concurrent.futures.ThreadPoolExecutor() as executor:
                                    future = executor.submit(
                                        asyncio.run,
                                        self.service.generate_scaffold(prompt, task_type),
                                    )
                                    result = future.result(timeout=30.0)
                            else:
                                result = asyncio.run(self.service.generate_scaffold(prompt, task_type))
                            return result.content if hasattr(result, "content") else str(result)
                        except Exception:
                            return f"SmallLanguageModel response to: {prompt[:100]}..."

                    def generate_text(self, prompt: str, **kwargs) -> str:
                        return self._run_scaffold(prompt, "reasoning")

                    def generate_response(self, prompt: str, **kwargs) -> str:
                        return self._run_scaffold(prompt, "reasoning")

                    def enhanced_generate_response(self, prompt: str, **kwargs) -> str:
                        return self._run_scaffold(prompt, "analysis")

                    def is_loaded(self) -> bool:
                        return self.service.current_model is not None or self.service.fallback_mode

                slm_provider = SmallLanguageModelProvider()
                current_model = slm_provider.service.current_model or "default-lightweight-model"
                model_id = f"small_language_model:{current_model}"
                capabilities = [
                    "conversation",
                    "generic",
                    "text",
                    "scaffolding",
                    "outlining",
                    "summarization",
                ]
                with self.registry._lock:
                    existing = self.registry._models.get(model_id)
                    if existing:
                        existing.model = slm_provider
                        existing.status = ModelStatus.ACTIVE
                        existing.tags = list({*existing.tags, "small-language-model", "local"})
                    else:
                        self.registry.register(
                            model_id,
                            slm_provider,
                            capabilities,
                            weight=5,
                            tags=["small-language-model", "local"],
                        )
                logger.info(f"Successfully registered SmallLanguageModelService: {model_id}")
            except Exception as e:
                logger.warning(f"Failed to register SmallLanguageModelService: {e}")
            
            # Check if the local GGUF runtime is available
            if not LocalGGUFRuntime.is_available():
                logger.debug("Local GGUF runtime not available, skipping local model registration")
                return
            
            # Discover any local GGUF models dynamically
            models_dir = Path("models/local-gguf")
            ggufs = []
            if models_dir.exists():
                try:
                    ggufs = [p for p in models_dir.glob("*.gguf") if p.is_file()]
                    # Basic validity: header magic
                    valid = []
                    for p in ggufs:
                        try:
                            with open(p, "rb") as f:
                                if f.read(4) == b"GGUF":
                                    valid.append(p)
                        except Exception:
                            continue
                    ggufs = valid
                except Exception:
                    ggufs = []

            if ggufs:
                ggufs.sort(key=lambda p: p.stat().st_size, reverse=True)
                chosen = ggufs[0]
                logger.info(f"Registering local GGUF model: {chosen}")
                
                class LocalGGUFProvider:
                    def __init__(self, path: str):
                        self.runtime = None
                        self.model_path = path
                    
                    def generate_text(self, prompt: str, **kwargs) -> str:
                        if not self.runtime:
                            self.runtime = LocalGGUFRuntime(
                                model_path=self.model_path,
                                n_ctx=2048,
                                n_batch=512,
                                n_gpu_layers=0,
                                verbose=False
                            )
                        
                        response = self.runtime.generate(
                            prompt=prompt,
                            max_tokens=kwargs.get("max_tokens", 256),
                            temperature=kwargs.get("temperature", 0.7),
                            top_p=kwargs.get("top_p", 0.9),
                            stream=False
                        )
                        return response if isinstance(response, str) else str(response)
                    
                    def generate_response(self, prompt: str, **kwargs) -> str:
                        return self.generate_text(prompt, **kwargs)
                    
                    def enhanced_generate_response(self, prompt: str, **kwargs) -> str:
                        return self.generate_text(prompt, **kwargs)
                # Register the local model
                local_provider = LocalGGUFProvider(str(chosen))
                model_id = f"local:{chosen.name}"
                capabilities = ["generic", "conversation", "text"]
                with self.registry._lock:
                    existing = self.registry._models.get(model_id)
                    if existing:
                        existing.model = local_provider
                        existing.status = ModelStatus.ACTIVE
                        existing.tags = list({*existing.tags, "local", "fallback"})
                    else:
                        self.registry.register(model_id, local_provider, capabilities, weight=10, tags=["local", "fallback"])
                logger.info(f"Successfully registered local model: {model_id}")
            else:
                logger.debug("No local GGUF models found under models/local-gguf/")

            # Register vLLM and Transformers runtimes if available
            try:
                from ai_karen_engine.inference.factory import get_inference_service_factory
                factory = get_inference_service_factory()
                
                # Transformers check
                try:
                    # Check if transformers is installed
                    import importlib.util
                    transformers_installed = importlib.util.find_spec("transformers") is not None
                    
                    if transformers_installed:
                        transformers_rt = factory.get_runtime("transformers") or factory.create_transformers_runtime()
                        if transformers_rt:
                            model_id = "local:transformers-fallback"
                            with self.registry._lock:
                                if model_id not in self.registry._models:
                                    self.registry.register(
                                        model_id, transformers_rt, ["generic", "conversation", "text"], 
                                        weight=20, tags=["local", "fallback", "transformers"]
                                    )
                                    logger.info(f"Registered Transformers fallback runtime: {model_id}")
                except Exception as e:
                    logger.debug(f"Transformers runtime registration skipped: {e}")
            except Exception as e:
                logger.warning(f"Failed to register factory runtimes: {e}")
                
        except Exception as e:
            logger.warning(f"Failed to register local models: {e}")

    def _warm_model(self, model_id: str, provider: Any) -> Optional[float]:
        """Warm a model and return latency in seconds if successful."""
        start = time.time()
        try:
            # Skip warming if the model seems unhealthy or already warmed
            info = self.registry._models.get(model_id)
            if info and (info.warmed or info.status != ModelStatus.ACTIVE):
                return None

            if hasattr(provider, "warm_cache"):
                # Use a timeout if supported, otherwise just call it
                provider.warm_cache()
            else:  # Fallback minimal generation
                # We use a very small max_tokens to minimize impact
                # In production, we might want to skip this if it causes hangs
                try:
                    # Try to call generate_text with a timeout if it's a wrapper
                    # Local providers may block; keep warmup best-effort.
                    from ai_karen_engine.core.model_runtime.model_manager import (
                        ModelManager,
                    )

                    ModelManager.invoke_provider_sync(
                        provider,
                        "hello",
                        max_tokens=1,
                    )
                except Exception as e:
                    logger.debug(f"Minimal generation warmup failed for {model_id}: {e}")
                    return None
            
            latency = time.time() - start
            logger.info(f"Warmed {model_id} in {latency:.3f}s")
            return latency
        except Exception as e:
            logger.warning(f"Warmup failed for {model_id}: {e}")
            return None

    def _track_latency(self, model_id: str, latency: float) -> None:
        info = self.registry._models.get(model_id)
        if info:
            info.record_latency(latency)
            info.warmed = True

    def route(
        self,
        prompt: str,
        skill: Optional[str] = None,
        *,
        return_metadata: bool = False,
        **kwargs,
    ) -> Union[str, LLMRouteResult]:
        """Route request to appropriate model with advanced fallback handling."""

        result = self._route_request(
            prompt,
            skill,
            mode="text",
            context=None,
            **kwargs,
        )

        return result if return_metadata else result.content

    def route_with_copilotkit(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        return_metadata: bool = False,
        **kwargs,
    ) -> Union[str, LLMRouteResult]:
        """Route request specifically to CopilotKit provider with enhanced context."""

        result = self._route_request(
            prompt,
            None,
            mode="copilotkit",
            context=context,
            **kwargs,
        )

        return result if return_metadata else result.content

    async def enhanced_route(
        self,
        prompt: str,
        skill: Optional[str] = None,
        *,
        return_metadata: bool = False,
        **kwargs,
    ) -> Union[str, LLMRouteResult]:
        """Enhanced routing with instruction-aware providers and fallback orchestration."""

        result = self._route_request(
            prompt,
            skill,
            mode="enhanced",
            context=None,
            **kwargs,
        )

        return result if return_metadata else result.content

    @staticmethod
    def _provider_aliases(provider: Optional[str]) -> List[str]:
        raw = (provider or "").strip()
        if not raw:
            return []

        aliases: List[str] = [raw]
        normalized = raw.replace("_", "-").lower()
        canonical_map = {
            "local-gguf": "local_gguf",
            "local_gguf": "local_gguf",
            "local": "local",
        }
        canonical = canonical_map.get(normalized)
        if canonical and canonical not in aliases:
            aliases.append(canonical)
        if canonical == "local_gguf" and "local" not in aliases:
            aliases.append("local")
        return aliases

    def _ensure_requested_model_registered(
        self,
        provider: Optional[str],
        model_id: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Lazily instantiate/register a specifically requested provider model.

        Returns a tuple of `(registered_model_id, failure_reason)`.
        """
        requested_provider = (provider or "").strip()
        requested_model = (model_id or "").strip()
        if not requested_provider or not requested_model:
            return None, None

        registration_failures: List[str] = []

        for provider_name in self._provider_aliases(requested_provider) or [requested_provider]:
            candidate_id = f"{provider_name}:{requested_model}"
            with self.registry._lock:
                existing = self.registry._models.get(candidate_id)
                if existing:
                    init_error = getattr(existing.model, "initialization_error", None)
                    if not init_error:
                        return candidate_id, None
                    logger.info(
                        "Refreshing stale requested provider model %s after initialization error: %s",
                        candidate_id,
                        init_error,
                    )
                    self.registry._models.pop(candidate_id, None)

            try:
                from ai_karen_engine.integrations.provider_registry import (
                    get_provider_registry,
                )

                provider_registry = get_provider_registry()
                provider_instance = provider_registry.get_provider(
                    provider_name,
                    model=requested_model,
                )
                if provider_instance is None:
                    # Attempt to resolve info/error from registry
                    provider_info = self.registry.get_provider_info(provider_name) or {}
                    info_error = str(provider_info.get("error_message") or "").strip()
                    if not info_error:
                        try:
                            # Try legacy provider registry directly for error metadata
                            legacy_registry = get_provider_registry()
                            legacy_info = legacy_registry.get_provider_info(provider_name)
                            if legacy_info and legacy_info.error_message:
                                info_error = str(legacy_info.error_message).strip()
                        except Exception:
                            pass
                    
                    if info_error:
                        registration_failures.append(info_error)
                    continue

                init_error = getattr(provider_instance, "initialization_error", None)
                if init_error:
                    return None, f"Provider error: {init_error}"

                capabilities = ["generic", "conversation", "text"]
                try:
                    if hasattr(provider_instance, "get_provider_info"):
                        provider_info = provider_instance.get_provider_info() or {}
                        caps = provider_info.get("capabilities")
                        if isinstance(caps, list) and caps:
                            capabilities = [str(cap) for cap in caps if cap]
                except Exception:
                    pass

                self.registry.register(
                    model_id=candidate_id,
                    model=provider_instance,
                    capabilities=capabilities,
                    weight=1,
                    status=ModelStatus.ACTIVE,
                    tags=["requested"],
                )
                return candidate_id, None
            except ValueError:
                with self.registry._lock:
                    if candidate_id in self.registry._models:
                        return candidate_id, None
            except Exception as exc:
                registration_failures.append(str(exc).strip())
                logger.warning(
                    "Failed to lazily register requested provider/model %s/%s: %s",
                    provider_name,
                    requested_model,
                    exc,
                )

        resolved_failure = next((reason for reason in registration_failures if reason), None)
        if resolved_failure:
            return None, resolved_failure

        provider_info = self.registry.get_provider_info(requested_provider)
        if not provider_info:
            return None, f"Provider '{requested_provider}' is not configured or recognized in the system."

        return None, (
            f"Requested provider/model {requested_provider}/{requested_model} failed to "
            "initialize or is currently offline."
        )

    async def generate_response(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        correlation_id: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Public entry point for generating a response with full orchestration."""
        
        # 1. Format prompt from messages
        # Simple join for now; providers will handle specific templates
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        if not prompt.lower().strip().endswith("assistant:"):
            prompt += "\nassistant:"
            
        # 2. Add provider/model choice if explicit
        kwargs["model"] = model_id
        kwargs["provider"] = provider
        
        # 3. Route and Execute
        # Note: In a fully async world, we'd make _route_request async.
        # For now, we wrap the existing synchronous logic.
        import asyncio
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._route_request(
                prompt=prompt,
                skill=kwargs.get("skill"),
                mode=kwargs.get("mode", "default"),
                context=kwargs.get("context"),
                **kwargs
            )
        )
        
        return {
            "content": result.content,
            "structured_content": result.metadata.get("structured_content") or {},
            "actions": result.metadata.get("actions") or [],
            "metadata": result.to_metadata()
        }

    async def generate_response_stream(
        self,
        model_id: str,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        correlation_id: Optional[str] = None,
        **kwargs
    ):
        """Public entry point for token-by-token generation."""
        prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        if not prompt.lower().strip().endswith("assistant:"):
            prompt += "\nassistant:"
            
        kwargs["model"] = model_id
        kwargs["provider"] = provider
        kwargs["stream"] = True
        
        # We find the best model first
        import asyncio
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._route_request(
                prompt=prompt,
                skill=kwargs.get("skill"),
                mode=kwargs.get("mode", "default"),
                context=kwargs.get("context"),
                **kwargs
            )
        )
        
        # Determine which model we're actually using
        final_model_id = result.model_id
        if not final_model_id:
            yield "I encountered a routing error. Please check the logs."
            return
            
        with self.registry._lock:
            model_info = self.registry._models.get(final_model_id)
            if not model_info:
                yield "The selected model is unavailable."
                return
                
        # Execute the stream helper
        stream_kwargs = dict(kwargs)
        stream_kwargs.pop("model", None)
        stream_kwargs.pop("provider", None)
        async for chunk in self._execute_model_stream(
            final_model_id, 
            model_info, 
            prompt, 
            **stream_kwargs
        ):
            yield chunk

    def _route_request(
        self,
        prompt: str,
        skill: Optional[str],
        *,
        mode: str,
        context: Optional[Dict[str, Any]],
        **kwargs,
    ) -> LLMRouteResult:
        """Core routing pipeline with retry, backoff, and degraded-mode handling."""

        attempted_models: List[str] = []
        last_error: Optional[Exception] = None
        preferred_models: Deque[str] = deque()
        routing_decision: Any = None

        self._ensure_minimum_models_registered()

        if mode == "copilotkit":
            with self.registry._lock:
                for mid, info in self.registry._models.items():
                    if "copilotkit" in mid.lower() and self._model_ready(mid, info):
                        preferred_models.append(mid)

        # Explicit model preference from kwargs (User Selection)
        pref_provider = kwargs.get("provider")
        pref_model = kwargs.get("model")
        if pref_provider and pref_model:
            registered_id, registration_error = self._ensure_requested_model_registered(
                pref_provider,
                pref_model,
            )
            if registered_id:
                preferred_models.appendleft(registered_id)

            # Try both name-based and ID-based matching
            potential_ids: List[Optional[str]] = [
                f"{provider_id}:{pref_model}"
                for provider_id in self._provider_aliases(pref_provider)
            ]
            potential_ids.extend(
                [
                    f"local:{pref_model}",
                    pref_model if ":" in pref_model else None,
                ]
            )
            for pid in filter(None, potential_ids):
                if pid in self.registry._models:
                    preferred_models.appendleft(pid)
                    logger.info(f"Routing: Prioritizing user-selected model {pid}")
                    break
            else:
                if registration_error:
                    last_error = RuntimeError(registration_error)
                    logger.warning(
                        "Routing: requested provider/model unavailable: %s",
                        registration_error,
                    )

        start_time = time.time()
        while True:
            if preferred_models:
                candidate_id = preferred_models.popleft()
                if candidate_id in attempted_models:
                    continue
                with self.registry._lock:
                    model = self.registry._models.get(candidate_id)
                    if not model or not self._model_ready(candidate_id, model):
                        continue
                model_id = candidate_id
            else:
                model_id, model = self._select_model(skill)

            if not model or model_id is None or model_id in attempted_models:
                # Enhanced logging for no models available scenario
                if not attempted_models:
                    with self.registry._lock:
                        total_models = len(self.registry._models)
                        ready_models = sum(
                            1 for mid, m in self.registry._models.items()
                            if self._model_ready(mid, m)
                        )
                    logger.error(
                        "No LLM models available for routing. Registry status: "
                        f"{ready_models}/{total_models} models ready, skill={skill}, mode={mode}"
                    )
                    if total_models == 0:
                        logger.critical(
                            "LLM Registry is empty! No models have been registered. "
                            "Please ensure model discovery has run or models are manually registered."
                        )
                break

            if model_id is not None:
                attempted_models.append(model_id)
            self._log_request_event(
                "attempt",
                model_id,
                prompt,
                mode=mode,
                metadata={"skill": skill},
            )

            try:
                execution_kwargs = dict(kwargs)
                execution_kwargs.pop("model", None)
                execution_kwargs.pop("provider", None)
                response_text = self._execute_model(
                    model_id,
                    model,
                    prompt,
                    mode=mode,
                    context=context,
                    **execution_kwargs,
                )

                provider_name = (
                    model_id.split(":", 1)[0] if ":" in model_id else model_id
                )

                duration = time.time() - start_time
                usage = getattr(model.model, "last_usage", {})

                return LLMRouteResult(
                    content=response_text,
                    model_id=model_id,
                    provider=provider_name,
                    tags=list(model.tags),
                    is_degraded=False,
                    attempted_models=list(attempted_models),
                    metadata={
                        "mode": mode,
                        "skill": skill,
                        "context_provided": bool(context),
                        "usage": usage,
                        "duration": duration,
                        "routing_confidence": getattr(routing_decision, 'confidence', 0.0) if routing_decision else 0.0,
                        "routing_rationale": getattr(routing_decision, 'rationale', None) if routing_decision else None,
                        "routing_strategy": getattr(routing_decision.strategy, 'value', str(routing_decision.strategy)) if routing_decision and hasattr(routing_decision, 'strategy') else None,
                    },
                )
            except CircuitOpenError as circuit_error:
                last_error = circuit_error
                self._log_request_event(
                    "circuit_open",
                    model_id,
                    prompt,
                    mode=mode,
                    metadata={
                        "retry_after": circuit_error.retry_after,
                        "reason": circuit_error.reason,
                        "rate_limited": circuit_error.rate_limited,
                    },
                )
                self._handle_circuit_open(model_id, model, circuit_error)
            except RateLimitError as rate_limit_error:
                last_error = rate_limit_error
                self._log_request_event(
                    "rate_limited",
                    model_id,
                    prompt,
                    mode=mode,
                    metadata={
                        "retry_after": getattr(rate_limit_error, "retry_after", None),
                        "error": str(rate_limit_error),
                    },
                )
                self._handle_rate_limit(model_id, model, rate_limit_error, prompt)
            except Exception as generic_error:
                last_error = generic_error
                error_text = str(generic_error)
                lower_error = error_text.lower()
                rate_limit_keywords = (
                    "rate limit",
                    "quota",
                    "too many requests",
                    "429",
                )

                if any(keyword in lower_error for keyword in rate_limit_keywords):
                    synthetic_error = RateLimitError(message=error_text)
                    retry_hint = getattr(generic_error, "retry_after", None)
                    if retry_hint is None:
                        retry_hint = self._extract_retry_after(error_text)
                    if retry_hint is not None:
                        try:
                            setattr(synthetic_error, "retry_after", float(retry_hint))
                        except (TypeError, ValueError):
                            pass
                    self._log_request_event(
                        "rate_limited",
                        model_id,
                        prompt,
                        mode=mode,
                        metadata={
                            "retry_after": getattr(synthetic_error, "retry_after", None),
                            "error": error_text,
                        },
                    )
                    self._handle_rate_limit(model_id, model, synthetic_error, prompt)
                    continue

                self._log_request_event(
                    "failure",
                    model_id,
                    prompt,
                    mode=mode,
                    metadata={
                        "error": error_text,
                        "exception": generic_error.__class__.__name__,
                    },
                )
                self._handle_model_failure(model_id, model, generic_error)

        return self._generate_degraded_response(
            prompt,
            attempted_models,
            last_error,
            mode,
            skill,
            routing_decision=routing_decision,
        )

    def _execute_model(
        self,
        model_id: str,
        model: ModelInfo,
        prompt: str,
        *,
        mode: str,
        context: Optional[Dict[str, Any]],
        **kwargs,
    ) -> str:
        """Execute a provider call with instrumentation and recovery handling."""

        if hasattr(model.model, "is_loaded") and not model.model.is_loaded():
            logger.warning(
                "Model %s not loaded, attempting to load before execution", model_id
            )
            if hasattr(model.model, "load_model"):
                model.model.load_model()
            elif hasattr(model.model, "runtime") and getattr(model.model, "runtime") is None:
                logger.info("Initializing runtime for %s before retry", model_id)
                raise CircuitOpenError(
                    model_id,
                    DEFAULT_CONFIG.get("circuit_base_delay", 2.0),
                    "runtime initialization",
                )

        provider_kwargs = dict(kwargs)
        if mode == "copilotkit" and context:
            provider_kwargs.setdefault("conversation_context", context)

        if mode == "enhanced" and hasattr(model.model, "enhanced_generate_response"):
            target_fn = model.model.enhanced_generate_response
        elif hasattr(model.model, "generate_response"):
            target_fn = model.model.generate_response
        elif hasattr(model.model, "generate_text"):
            target_fn = model.model.generate_text
        else:
            raise RuntimeError(f"Model {model_id} does not implement a generation method")

        start = time.time()

        try:
            future = self.pool.execute(model_id, target_fn, prompt, **provider_kwargs)
            result = future.result(timeout=DEFAULT_CONFIG["request_timeout"])
        except CircuitOpenError:
            raise
        except Exception as exec_error:
            if not (
                self.pool._is_resource_pressure_error(exec_error)
                and self.pool._is_local_model(model_id)
            ):
                self.pool._record_outcome(model_id, False, exec_error)
            raise

        self.pool._record_outcome(model_id, True)
        latency = time.time() - start
        self._track_latency(model_id, latency)

        return result

    async def _execute_model_stream(
        self,
        model_id: str,
        model: ModelInfo,
        prompt: str,
        **kwargs,
    ):
        """Execute a provider call in streaming mode."""
        # Ensure model is ready
        if hasattr(model.model, "is_loaded") and not model.model.is_loaded():
            if hasattr(model.model, "load_model"):
                model.model.load_model()
                
        target_model = model.model
        
        # Local GGUF specific streaming bridge
        if hasattr(target_model, "chat") and kwargs.get("stream"):
            # Local GGUF runtime returns an iterator when stream=True
            def sync_stream():
                mock_messages = [{"role": "user", "content": prompt}]
                return target_model.chat(
                    messages=mock_messages,
                    stream=True,
                    **kwargs
                )

            import asyncio
            loop = asyncio.get_running_loop()
            iterator = await loop.run_in_executor(None, sync_stream)
            
            for token in iterator:
                # Handle different token formats (string vs dict)
                chunk = token if isinstance(token, str) else str(token)
                yield chunk
                await asyncio.sleep(0) # Yield control
            
            self.pool._record_outcome(model_id, True)
        else:
            # Fallback for models that don't support streaming
            # Recurse through non-streaming generate_response
            response = await self.generate_response(
                model_id=model_id, 
                messages=[{"role": "user", "content": prompt}], 
                **kwargs
            )
            yield response.get("content", "")
        self._handle_model_recovery(model_id, model)

    def _log_request_event(
        self,
        event_type: str,
        model_id: str,
        prompt: str,
        *,
        mode: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit structured logs for routing events with redacted prompt context."""

        payload: Dict[str, Any] = {
            "event": event_type,
            "model": model_id,
            "mode": mode,
            "prompt_digest": self._sanitize_prompt(prompt),
        }
        if metadata:
            payload.update({k: v for k, v in metadata.items() if v is not None})
        logger.info("[LLM_ROUTER] %s", payload)

    def _handle_model_recovery(self, model_id: str, model: ModelInfo) -> None:
        """Reset model health metadata after a successful request."""

        if model.status != ModelStatus.ACTIVE:
            logger.info(
                "Model %s recovered from %s state", model_id, model.status.name
            )
        model.status = ModelStatus.ACTIVE
        model.cooldown_until = 0.0
        model.rate_limit_until = 0.0
        model.consecutive_failures = 0
        model.last_error = None

    def _apply_response_formatting(
        self, 
        prompt: str, 
        response: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Apply intelligent response formatting to the model response.
        
        Args:
            prompt: The original user prompt
            response: The raw model response
            context: Additional context for formatting
            
        Returns:
            Formatted response or original response if formatting fails
        """
        try:
            # Import response formatting integration from new core services path
            from ai_karen_engine.services.formatting.ResponseFormattingClass.Specialized.Integration import get_specialized_integration
            import asyncio
            
            integration = get_specialized_integration()
            
            # Get theme context from existing theme manager if available
            theme_context = {'current_theme': 'light'}  # Default fallback
            try:
                from src.ui_logic.themes.theme_manager import get_available_themes
                available_themes = get_available_themes()
                if available_themes:
                    # Use the first available theme or default to light
                    theme_context = {
                        'current_theme': 'light' if 'light' in available_themes else list(available_themes.keys())[0],
                        'available_themes': list(available_themes.keys())
                    }
            except ImportError:
                pass
            
            # Since the new integration is async, we need to run it synchronously here
            # as this method is currently synchronous.
            try:
                # Check if there's an event loop already
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                if loop.is_running():
                    # If we're already in an event loop, we'll try to run the coro
                    # this might be tricky without nest_asyncio
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            lambda: asyncio.run(integration.format_response(
                                user_query=prompt,
                                response_content=response,
                                theme_context=theme_context,
                                user_preferences=context or {}
                            ))
                        )
                        formatted_response = future.result()
                else:
                    formatted_response = loop.run_until_complete(integration.format_response(
                        user_query=prompt,
                        response_content=response,
                        theme_context=theme_context,
                        user_preferences=context or {}
                    ))
                
                return formatted_response.content
            except Exception as e:
                # Fallback for async execution failure
                logger.debug(f"Async formatting execution failed, using raw response: {e}")
                return response
        except Exception as e:
            logger.error(f"Error applying response formatting: {e}")
            return response
    def _update_formatting_metrics(self, success: bool, formatter_name: Optional[str]) -> None:
        """Update response formatting metrics."""
        if not hasattr(self, '_formatting_metrics'):
            self._formatting_metrics = {
                'total_attempts': 0,
                'successful_formats': 0,
                'failed_formats': 0,
                'formatter_usage': {}
            }
        
        self._formatting_metrics['total_attempts'] += 1
        
        if success:
            self._formatting_metrics['successful_formats'] += 1
            if formatter_name:
                self._formatting_metrics['formatter_usage'][formatter_name] = (
                    self._formatting_metrics['formatter_usage'].get(formatter_name, 0) + 1
                )
        else:
            self._formatting_metrics['failed_formats'] += 1

    def _handle_model_failure(
        self, model_id: str, model: ModelInfo, error: Exception
    ) -> None:
        """Apply exponential backoff and circuit logic for generic failures."""

        now = time.time()
        reason = str(error)
        model.failure_count += 1
        model.consecutive_failures += 1
        model.last_error = reason

        note = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}: {reason}"[:256]
        model.degradation_notes.append(note)
        if len(model.degradation_notes) > 10:
            model.degradation_notes.pop(0)

        base_delay = DEFAULT_CONFIG.get("circuit_base_delay", 2.0)
        max_delay = DEFAULT_CONFIG.get("circuit_max_delay", 60.0)
        exponent = min(model.consecutive_failures, 6)
        jitter = random.uniform(0.5, base_delay)
        cooldown = min(max_delay, base_delay * (2 ** exponent)) + jitter

        model.cooldown_until = now + cooldown
        logger.warning(
            "Model %s entering degraded state for %.2fs due to: %s",
            model_id,
            cooldown,
            reason,
        )

        if model.consecutive_failures >= DEFAULT_CONFIG["failure_trip_limit"]:
            model.status = ModelStatus.CIRCUIT_BROKEN
        else:
            model.status = ModelStatus.DEGRADED

        if model.failure_count >= DEFAULT_CONFIG["failure_trip_limit"] * 2:
            model.status = ModelStatus.FAILED

    def _handle_rate_limit(
        self,
        model_id: str,
        model: ModelInfo,
        error: RateLimitError,
        prompt: str,
    ) -> None:
        """Special handling for rate limiting errors with queue management."""

        now = time.time()
        retry_after = getattr(error, "retry_after", None)
        parsed_retry = self._extract_retry_after(str(error)) if retry_after is None else retry_after

        base_delay = DEFAULT_CONFIG.get("rate_limit_base_delay", 5.0)
        cooldown = float(base_delay)
        if parsed_retry is not None:
            try:
                cooldown = max(cooldown, float(parsed_retry))
            except (TypeError, ValueError):
                cooldown = max(cooldown, base_delay)

        cooldown = min(
            DEFAULT_CONFIG.get("rate_limit_max_delay", 180.0),
            cooldown + random.uniform(0.5, 1.5),
        )

        model.status = ModelStatus.RATE_LIMITED
        model.rate_limit_until = now + cooldown
        model.cooldown_until = model.rate_limit_until
        model.consecutive_failures += 1
        model.failure_count += 1
        model.last_error = str(error)

        self._record_rate_limit_event(
            model_id,
            cooldown,
            self._sanitize_prompt(prompt),
            str(error),
        )

        logger.warning(
            "Rate limit triggered for %s; retrying after %.2fs", model_id, cooldown
        )

    def _handle_circuit_open(
        self, model_id: str, model: ModelInfo, error: CircuitOpenError
    ) -> None:
        """Handle attempts on models with open circuits."""

        cooldown = max(error.retry_after, DEFAULT_CONFIG.get("circuit_base_delay", 2.0))
        model.cooldown_until = time.time() + cooldown
        model.consecutive_failures += 1
        if error.rate_limited:
            model.status = ModelStatus.RATE_LIMITED
            model.rate_limit_until = model.cooldown_until
        else:
            model.status = ModelStatus.CIRCUIT_BROKEN
        if error.reason:
            model.last_error = error.reason
        logger.debug(
            "Circuit open for %s; delaying retries for %.2fs", model_id, cooldown
        )

    def _record_rate_limit_event(
        self, model_id: str, retry_after: float, prompt_digest: str, message: str
    ) -> None:
        """Add a rate limiting event to the in-memory queue for monitoring."""

        event = {
            "model_id": model_id,
            "retry_after": round(retry_after, 2),
            "timestamp": time.time(),
            "prompt_digest": prompt_digest,
            "message": message[:256],
        }
        self._rate_limit_queue.append(event)

    def _extract_retry_after(self, message: str) -> Optional[float]:
        """Best-effort extraction of retry-after values from provider errors."""

        if not message:
            return None

        retry_after_match = re.search(r"retry[- ]?after[:\s]*(\d+(?:\.\d+)?)", message, re.I)
        if retry_after_match:
            try:
                return float(retry_after_match.group(1))
            except ValueError:
                return None

        seconds_match = re.search(r"(\d+(?:\.\d+)?)\s*(seconds|sec|s)\b", message, re.I)
        if seconds_match:
            try:
                return float(seconds_match.group(1))
            except ValueError:
                return None

        return None

    def _sanitize_prompt(self, prompt: str) -> str:
        """Return a stable digest of the prompt for logging without raw text."""

        if not prompt:
            return ""
        cleaned = " ".join(prompt.strip().split())
        return hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:12]

    def _get_fallback_model(self) -> Optional[Tuple[str, ModelInfo]]:
        """Retrieve the deterministic fallback provider if available."""

        best_fallback: Optional[Tuple[str, ModelInfo]] = None
        best_weight = float("inf")

        with self.registry._lock:
            for model_id, info in self.registry._models.items():
                if info.status != ModelStatus.ACTIVE:
                    continue
                if model_id.startswith("fallback:") or "fallback" in info.tags:
                    weight = info.weight or 100
                    if weight < best_weight:
                        best_weight = weight
                        best_fallback = (model_id, info)
        return best_fallback

    def _generate_degraded_response(
        self,
        prompt: str,
        attempted_models: List[str],
        last_error: Optional[Exception],
        mode: str,
        skill: Optional[str],
        routing_decision: Any = None,
    ) -> LLMRouteResult:
        """Generate a graceful degraded response when all providers fail."""

        reason = str(last_error) if last_error else "Unknown provider failure"
        attempted = attempted_models or ["<none>"]

        # Enhanced error logging with registry status
        with self.registry._lock:
            total_models = len(self.registry._models)
            active_models = sum(
                1 for m in self.registry._models.values()
                if m.status == ModelStatus.ACTIVE
            )

        if not attempted_models:
            logger.error(
                "Entering degraded mode - NO MODELS ATTEMPTED. Registry status: "
                f"{active_models}/{total_models} active models. "
                "This indicates the model registry is empty or no models are ready."
            )
        else:
            logger.error(
                "All providers failed; entering degraded mode. "
                f"Attempted: {attempted} | Reason: {reason} | "
                f"Registry status: {active_models}/{total_models} active models"
            )

        event = {
            "timestamp": time.time(),
            "attempted_models": list(attempted),
            "reason": reason[:256],
            "prompt_digest": self._sanitize_prompt(prompt),
        }
        self._degraded_events.append(event)

        enable_model_degraded_fallback = (
            os.getenv("KARI_ENABLE_MODEL_DEGRADED_FALLBACK", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

        fallback_entry = self._get_fallback_model()
        if enable_model_degraded_fallback and fallback_entry:
            fallback_id, fallback_model = fallback_entry
            
            # Use a prompt that encourages direct answering while acknowledging the mode
            fallback_prompt = textwrap.dedent(
                f"""
                System Notice: Primary LLM services are temporarily unavailable.
                You are currently operating in Karen's Degraded Mode.
                
                Instruction: Answer the user's prompt as accurately as possible using your available knowledge and context.
                Be helpful, concise, and professional.

                User prompt:
                {prompt}
                """
            ).strip()
            
            try:
                fallback_start = time.time()
                response = fallback_model.model.generate_text(fallback_prompt)
                
                # Cleanup common fallback prefixes if the model adds them redundantly
                response = re.sub(r"^(Assistant:|Karen:)", "", response, flags=re.IGNORECASE).strip()
                
                fallback_duration = time.time() - fallback_start
                usage = getattr(fallback_model.model, "last_usage", {})
                
                # Use specific model ID and confidence from fallback provider if available
                actual_model_id = usage.get("model_id", fallback_id)
                response_confidence = usage.get("confidence", 0.45) # Slightly higher base for actual model
                
                self._log_request_event(
                    "fallback_success",
                    actual_model_id,
                    prompt,
                    mode="degraded",
                    metadata={"original_models": attempted, "duration": fallback_duration},
                )
                return LLMRouteResult(
                    content=response,
                    model_id=actual_model_id,
                    provider=(
                        actual_model_id.split(":", 1)[0]
                        if ":" in actual_model_id
                        else fallback_id.split(":", 1)[0]
                    ),
                    tags=list(fallback_model.tags),
                    is_degraded=True,
                    attempted_models=list(attempted),
                    failure_reason=reason,
                    metadata={
                        "mode": mode,
                        "skill": skill,
                        "fallback_type": "model",
                        "preferred_failure_reason": reason,
                        "failure_reason": reason,
                        "usage": usage,
                        "duration": fallback_duration,
                        "routing_confidence": getattr(routing_decision, 'confidence', 0.0) if routing_decision else 0.0,
                        "routing_rationale": getattr(routing_decision, 'rationale', None) if routing_decision else "System fallback active",
                        "confidence_score": response_confidence,
                    },
                )
            except Exception as fallback_error:
                logger.error(
                    "Fallback provider %s failed during degraded mode: %s",
                    fallback_id,
                    fallback_error,
                )
        elif fallback_entry:
            logger.info(
                "Skipping model-based degraded fallback for %s; using immediate rule-based degraded response",
                fallback_entry[0],
            )

        self._log_request_event(
            "fallback_rule_based",
            "rule_based",
            prompt,
            mode="degraded",
            metadata={"original_models": attempted},
        )
        rule_based = self._build_rule_based_response(prompt, attempted, reason)

        return LLMRouteResult(
            content=rule_based,
            model_id="degraded:rule_based",
            provider="degraded",
            tags=["degraded", "fallback"],
            is_degraded=True,
            attempted_models=list(attempted),
            failure_reason=reason,
            metadata={
                "mode": mode,
                "skill": skill,
                "fallback_type": "rule_based",
                "preferred_failure_reason": reason,
                "failure_reason": reason,
            },
        )

    def _build_rule_based_response(
        self, prompt: str, attempted_models: List[str], reason: str
    ) -> str:
        """Create a deterministic acknowledgement message as ultimate fallback."""

        summary = textwrap.shorten(" ".join(prompt.split()), width=200, placeholder="…") if prompt else "(empty request)"
        attempted = ", ".join(attempted_models) if attempted_models else "none (no models available)"

        # Determine the specific issue and provide appropriate guidance
        if not attempted_models:
            # No models were even attempted - registry is likely empty
            guidance = [
                "Initialize the system using: python -m ai_karen_engine.initialize_kire_kro",
                "Ensure model discovery has run to detect available models",
                "Verify that at least one LLM provider is configured and accessible",
                "Check logs for model registration errors"
            ]
            issue_description = "No language models are currently available in the system registry"
        else:
            # Models were attempted but all failed
            guidance = [
                "Retry in a few minutes or switch to a different provider in settings",
                "Review provider API keys and quotas to ensure availability",
                "Check network connectivity to LLM provider endpoints",
                "Verify that provider services are not experiencing outages"
            ]
            issue_description = "I couldn't reach the configured language models"

        return (
            f"⚠️ I'm in degraded mode because {issue_description}.\n"
            f"Models attempted: {attempted}.\n"
            f"Last error: {reason}.\n\n"
            "Troubleshooting steps:\n"
            f"- {guidance[0]}\n"
            f"- {guidance[1]}\n"
            f"- {guidance[2]}\n"
            f"- {guidance[3]}\n\n"
            f"Your request summary: {summary}"
        )

    async def get_code_suggestions(
        self, code: str, language: str = "python", **kwargs
    ) -> List[Dict[str, Any]]:
        """Get code suggestions from CopilotKit provider or enhanced providers"""
        # First try CopilotKit provider
        copilotkit_model = None
        for model_id, model in self.registry._models.items():
            if "copilotkit" in model_id.lower() and model.status == ModelStatus.ACTIVE:
                copilotkit_model = (model_id, model)
                break

        if copilotkit_model:
            model_id, model = copilotkit_model
            try:
                if hasattr(model.model, "get_code_suggestions"):
                    return await model.model.get_code_suggestions(
                        code, language, **kwargs
                    )
            except Exception as e:
                logger.warning(f"CopilotKit code suggestions failed: {e}")

        # Fallback to any provider with code assistance capabilities
        for model_id, model in self.registry._models.items():
            if model.status == ModelStatus.ACTIVE:
                try:
                    if hasattr(model.model, "get_code_suggestions"):
                        return await model.model.get_code_suggestions(
                            code, language, **kwargs
                        )
                except Exception as e:
                    logger.debug(f"Provider {model_id} code suggestions failed: {e}")
                    continue

        logger.warning("No providers available for code suggestions")
        return []

    async def get_debugging_assistance(
        self, code: str, error_message: str = "", language: str = "python", **kwargs
    ) -> Dict[str, Any]:
        """Get debugging assistance from enhanced providers"""
        # Try providers with debugging assistance capabilities
        for model_id, model in self.registry._models.items():
            if model.status == ModelStatus.ACTIVE:
                try:
                    if hasattr(model.model, "get_debugging_assistance"):
                        return await model.model.get_debugging_assistance(
                            code=code,
                            error_message=error_message,
                            language=language,
                            **kwargs,
                        )
                except Exception as e:
                    logger.debug(
                        f"Provider {model_id} debugging assistance failed: {e}"
                    )
                    continue

        logger.warning("No providers available for debugging assistance")
        return {"suggestions": [], "analysis": "No debugging assistance available"}

    async def generate_documentation(
        self,
        code: str,
        language: str = "python",
        style: str = "comprehensive",
        **kwargs,
    ) -> str:
        """Generate documentation using enhanced providers"""
        # Try providers with documentation generation capabilities
        for model_id, model in self.registry._models.items():
            if model.status == ModelStatus.ACTIVE:
                try:
                    if hasattr(model.model, "generate_documentation"):
                        return await model.model.generate_documentation(
                            code=code, language=language, style=style, **kwargs
                        )
                except Exception as e:
                    logger.debug(
                        f"Provider {model_id} documentation generation failed: {e}"
                    )
                    continue

        logger.warning("No providers available for documentation generation")
        return f"Documentation generation unavailable for {language} code"

    async def get_contextual_suggestions(
        self, message: str, context: Dict[str, Any], **kwargs
    ) -> List[Dict[str, Any]]:
        """Get contextual suggestions from CopilotKit provider or enhanced providers"""
        # First try CopilotKit provider
        copilotkit_model = None
        for model_id, model in self.registry._models.items():
            if "copilotkit" in model_id.lower() and model.status == ModelStatus.ACTIVE:
                copilotkit_model = (model_id, model)
                break

        if copilotkit_model:
            model_id, model = copilotkit_model
            try:
                if hasattr(model.model, "get_contextual_suggestions"):
                    return await model.model.get_contextual_suggestions(
                        message, context, **kwargs
                    )
            except Exception as e:
                logger.warning(f"CopilotKit contextual suggestions failed: {e}")

        # Fallback to any provider with contextual suggestions capabilities
        for model_id, model in self.registry._models.items():
            if model.status == ModelStatus.ACTIVE:
                try:
                    if hasattr(model.model, "get_contextual_suggestions"):
                        return await model.model.get_contextual_suggestions(
                            message, context, **kwargs
                        )
                except Exception as e:
                    logger.debug(
                        f"Provider {model_id} contextual suggestions failed: {e}"
                    )
                    continue

        logger.warning("No providers available for contextual suggestions")
        return []

    async def enhanced_route_with_fallback(
        self, prompt: str, skill: Optional[str] = None, **kwargs
    ) -> str:
        """Enhanced routing with CopilotKit code assistance integration and automatic fallback"""
        # Try multiple models in order of preference
        attempted_models = []
        
        while True:
            model_id, model = self._select_model(skill)
            if not model or model_id is None or model_id in attempted_models:
                break
                
            if model_id is not None:
                attempted_models.append(model_id)
            
            try:
                # Check if model is properly loaded
                if hasattr(model.model, 'is_loaded') and not model.model.is_loaded():
                    logger.warning(f"Model {model_id} not loaded, attempting to load...")
                    if hasattr(model.model, 'load_model'):
                        model.model.load_model()
                    elif hasattr(model.model, 'runtime') and model.model.runtime is None:
                        # For models that need runtime initialization
                        logger.info(f"Initializing runtime for {model_id}")
                        continue  # Skip this model and try next
                
                # Use enhanced response generation if available
                if hasattr(model.model, "enhanced_generate_response"):
                    future = self.pool.execute(
                        model_id, model.model.enhanced_generate_response, prompt, **kwargs  # type: ignore
                    )
                else:
                    # Fallback to regular generation
                    future = self.pool.execute(
                        model_id, model.model.generate_response, prompt, **kwargs  # type: ignore
                    )

                result = future.result(timeout=DEFAULT_CONFIG["request_timeout"])
                self.pool._record_outcome(model_id, True)  # type: ignore
                return result
                
            except Exception as e:
                self.pool._record_outcome(model_id, False)  # type: ignore
                logger.warning(f"Enhanced model {model_id} failed: {str(e)}, trying next model...")

                # Resource pressure on local inference should not be treated as a
                # generic provider breakage signal for the routing layer.
                if not (
                    self.pool._is_resource_pressure_error(e)
                    and self.pool._is_local_model(model_id)
                ):
                    model.status = ModelStatus.CIRCUIT_BROKEN
                continue
        
        # All models failed
        raise RuntimeError(f"All available models failed. Attempted: {attempted_models}")

    def _model_ready(
        self, model_id: str, model: ModelInfo, *, now: Optional[float] = None
    ) -> bool:
        """Determine if a model is available for routing, updating status if recovered."""

        if now is None:
            now = time.time()
        if model.status == ModelStatus.ACTIVE:
            return True
        if model.status == ModelStatus.FAILED:
            return False
        if model.cooldown_until and model.cooldown_until <= now:
            logger.info(
                "Model %s exiting %s state after cooldown", model_id, model.status.name
            )
            model.status = ModelStatus.ACTIVE
            model.cooldown_until = 0.0
            model.rate_limit_until = 0.0
            model.consecutive_failures = 0
            return True
        return False

    def _select_model(
        self, skill: Optional[str]
    ) -> Tuple[Optional[str], Optional[ModelInfo]]:
        """Select best model for the task respecting cooldowns and statuses."""

        now = time.time()

        with self.registry._lock:
            def _candidate_filter(predicate: Callable[[ModelInfo], bool]):
                return [
                    (mid, model)
                    for mid, model in self.registry._models.items()
                    if predicate(model) and self._model_ready(mid, model, now=now)
                ]

            candidates: List[Tuple[str, ModelInfo]] = []
            if skill:
                candidates = _candidate_filter(lambda m: skill in m.capabilities)

            if not candidates:
                candidates = _candidate_filter(lambda m: "generic" in m.capabilities)

            if candidates:
                warmed = [c for c in candidates if c[1].warmed]
                if warmed:
                    candidates = warmed
                candidates.sort(
                    key=lambda x: (
                        x[1].p95_latency(),
                        x[1].weight,
                        x[1].last_used,
                    )
                )
                selected = candidates[0]
                selected[1].last_used = time.time()
                return selected

            return None, None

    def health_check(self) -> Dict[str, Any]:
        """System health status"""
        health_data = {
            "status": "operational",
            "models": len(self.registry._models),
            "active_workers": self.pool.executor._work_queue.qsize(),
            "memory_ok": self.hardware.check_memory(),
            "timestamp": time.time(),
        }
        
        health_data["performance_adaptive_router"] = {
            "status": "retired",
            "detail": "Routing authority migrated to ChatRuntimeControlPlane / ProviderRouter",
        }
        
        # Add response formatting health
        try:
            from extensions.response_formatting.integration import get_response_formatting_integration
            integration = get_response_formatting_integration()
            formatting_metrics = integration.get_integration_metrics()
            
            # Get orchestrator-level formatting metrics
            orchestrator_metrics = self.get_formatting_metrics()
            
            health_data["response_formatting"] = {
                "available": True,
                "formatters_registered": len(integration.get_available_formatters()),
                "supported_content_types": integration.get_supported_content_types(),
                "integration_metrics": {
                    "total_requests": formatting_metrics.get('total_requests', 0),
                    "successful_formats": formatting_metrics.get('successful_formats', 0),
                    "failed_formats": formatting_metrics.get('failed_formats', 0),
                    "fallback_uses": formatting_metrics.get('fallback_uses', 0),
                    "success_rate": (
                        formatting_metrics.get('successful_formats', 0) / 
                        max(1, formatting_metrics.get('total_requests', 1))
                    )
                },
                "orchestrator_metrics": orchestrator_metrics,
                "content_type_distribution": formatting_metrics.get('content_type_detections', {}),
                "formatter_usage": formatting_metrics.get('registry_stats', {}).get('formatter_usage', {})
            }
        except Exception as e:
            health_data["response_formatting"] = {
                "available": False,
                "error": str(e)
            }
        
        return health_data
    
    def reset_circuit_breakers(self) -> None:
        """Reset circuit breakers for all models to allow retry"""
        with self.registry._lock:
            for model_id, model in self.registry._models.items():
                if model.status == ModelStatus.CIRCUIT_BROKEN:
                    model.status = ModelStatus.ACTIVE
                    logger.info(f"Reset circuit breaker for model: {model_id}")
    
    def get_model_status(self) -> Dict[str, str]:
        """Get status of all registered models"""
        with self.registry._lock:
            return {
                model_id: model.status.name
                for model_id, model in self.registry._models.items()
            }

    def get_formatting_metrics(self) -> Dict[str, Any]:
        """Get response formatting metrics."""
        if not hasattr(self, '_formatting_metrics'):
            return {
                'total_attempts': 0,
                'successful_formats': 0,
                'failed_formats': 0,
                'formatter_usage': {},
                'success_rate': 0.0
            }
        
        metrics = dict(self._formatting_metrics)
        total = metrics['total_attempts']
        metrics['success_rate'] = (
            metrics['successful_formats'] / max(1, total)
        )
        
        return metrics

    def get_detailed_formatting_stats(self) -> Dict[str, Any]:
        """Get detailed response formatting statistics."""
        orchestrator_metrics = self.get_formatting_metrics()
        
        try:
            from extensions.response_formatting.integration import get_response_formatting_integration
            integration = get_response_formatting_integration()
            integration_metrics = integration.get_integration_metrics()
            
            return {
                'orchestrator_level': orchestrator_metrics,
                'integration_level': integration_metrics,
                'available_formatters': integration.get_available_formatters(),
                'supported_content_types': integration.get_supported_content_types(),
                'theme_requirements': {
                    content_type: integration.get_theme_requirements(
                        getattr(integration.content_detector, 'ContentType', type('ContentType', (), {content_type: content_type}))
                    ) for content_type in integration.get_supported_content_types()
                }
            }
        except Exception as e:
            return {
                'orchestrator_level': orchestrator_metrics,
                'integration_level': {'error': str(e)},
                'available_formatters': [],
                'supported_content_types': [],
                'theme_requirements': {}
            }

    def reset_formatting_metrics(self) -> None:
        """Reset response formatting metrics."""
        if hasattr(self, '_formatting_metrics'):
            self._formatting_metrics = {
                'total_attempts': 0,
                'successful_formats': 0,
                'failed_formats': 0,
                'formatter_usage': {}
            }
        
        try:
            from extensions.response_formatting.integration import get_response_formatting_integration
            integration = get_response_formatting_integration()
            integration.reset_metrics()
            logger.info("Response formatting metrics reset")
        except Exception as e:
            logger.warning(f"Failed to reset integration metrics: {e}")


# === Singleton Access ===
_llm_orchestrator: Optional[LLMOrchestrator] = None


def get_orchestrator() -> LLMOrchestrator:
    """Get (or create) the orchestrator singleton."""
    global _llm_orchestrator
    if _llm_orchestrator is None:
        _llm_orchestrator = LLMOrchestrator()
    return _llm_orchestrator
