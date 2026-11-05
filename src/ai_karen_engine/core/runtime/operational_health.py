from __future__ import annotations

"""Operational liveness and readiness authority for the canonical runtime.

Liveness deliberately proves only that the process can answer requests.
Readiness proves that production-critical runtime dependencies and safety
invariants are satisfied. Optional model/provider availability is not a
readiness requirement unless a deployment explicitly promotes it to one.
"""

import asyncio
import ipaddress
import os
import time
from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import urlsplit


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_INSECURE_SECRET_MARKERS = {
    "",
    "change-me",
    "changeme",
    "default",
    "secret",
    "password",
    "super-secret-key-change-me",
    "your-super-secret-jwt-key-change-in-production",
    "dev-extension-secret-key-change-in-production",
    "dev-extension-api-key-change-in-production",
}
_INSECURE_SECRET_FRAGMENTS = ("change_me", "change-me", "changeme", "example")


@dataclass(frozen=True)
class OperationalHealthResult:
    """Serializable operational probe result."""

    status: str
    ready: bool
    checks: Dict[str, Dict[str, Any]]
    timestamp: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ready": self.ready,
            "checks": self.checks,
            "timestamp": self.timestamp,
        }


class OperationalHealthService:
    """Own process liveness and production readiness evaluation."""

    _production_forbidden_flags = (
        "AUTH_DEV_MODE",
        "AUTH_ALLOW_DEV_LOGIN",
        "KARI_AUTH_BYPASS",
        "EXTENSION_DEV_BYPASS_ENABLED",
        "KARI_SKIP_STARTUP_CHECK",
        "KARI_SKIP_AUTO_INIT",
        "KARI_DEFER_ROUTER_WIRING",
    )

    _production_required_secrets = (
        "SECRET_KEY",
        "AUTH_SECRET_KEY",
        "EXTENSION_SECRET_KEY",
        "EXTENSION_API_KEY",
    )

    @staticmethod
    def liveness() -> Dict[str, Any]:
        """Return process-level liveness without dependency fan-out."""
        return {
            "status": "alive",
            "alive": True,
            "timestamp": time.time(),
        }

    async def readiness(self, *, environment: str) -> OperationalHealthResult:
        """Evaluate production-critical safety and dependency readiness."""
        checks: Dict[str, Dict[str, Any]] = {}
        normalized_environment = (environment or "development").strip().lower()
        production = normalized_environment in {"production", "prod"}

        checks["configuration"] = self._configuration_check(production=production)
        checks["database"] = await self._database_check()

        memory_required = self._env_bool("KARI_ENABLE_MEMORY_SERVICE", default=True)
        checks["redis"] = await self._redis_check(required=memory_required)

        ready = all(bool(check.get("ready")) for check in checks.values())
        return OperationalHealthResult(
            status="ready" if ready else "not_ready",
            ready=ready,
            checks=checks,
            timestamp=time.time(),
        )

    def _configuration_check(self, *, production: bool) -> Dict[str, Any]:
        if not production:
            return {"ready": True, "environment": "non-production"}

        violations = []
        for name in self._production_forbidden_flags:
            if self._env_bool(name, default=False):
                violations.append(f"{name}=true")

        if self._env_bool("KARI_FAST_STARTUP", default=False):
            violations.append("KARI_FAST_STARTUP=true")

        for name in self._production_required_secrets:
            value = os.getenv(name)
            if self._is_insecure_secret(value):
                violations.append(f"{name}=missing_or_insecure")

        # Redis is configured by its canonical connection URL, not by an
        # unrelated REDIS_PASSWORD that RedisConnectionManager never consumes.
        # Passwordless transport is permitted ONLY on a single-label private
        # service hostname. Public targets require authenticated TLS.
        if not self._redis_target_secure(os.getenv("REDIS_URL")):
            violations.append("REDIS_URL=missing_or_insecure")

        return {
            "ready": not violations,
            "environment": "production",
            "violations": violations,
        }

    @staticmethod
    async def _database_check() -> Dict[str, Any]:
        try:
            from ai_karen_engine.database.client import get_database_client

            database_client = get_database_client()
            degraded = bool(database_client.is_degraded())
            return {
                "ready": not degraded,
                "status": "degraded" if degraded else "healthy",
            }
        except Exception as exc:
            return {
                "ready": False,
                "status": "unavailable",
                "error_type": type(exc).__name__,
            }

    @staticmethod
    async def _redis_check(*, required: bool) -> Dict[str, Any]:
        if not required:
            return {"ready": True, "status": "not_required"}

        try:
            from ai_karen_engine.platform.memory.redis import get_redis_manager

            # Do not infer readiness from the manager's initial degraded flag:
            # it starts False before any connection has been established.
            # The canonical manager actively checks the existing connection.
            healthy = await asyncio.wait_for(
                get_redis_manager().is_healthy(), timeout=3.0,
            )
            return {
                "ready": bool(healthy),
                "status": "healthy" if healthy else "degraded",
            }
        except Exception as exc:
            return {
                "ready": False,
                "status": "unavailable",
                "error_type": type(exc).__name__,
            }

    @classmethod
    def _redis_target_secure(cls, value: str | None) -> bool:
        """Enforce private-network Redis or authenticated TLS, without a URL leak."""
        if not value or value != value.strip() or any(ord(c) <= 32 for c in value):
            return False
        try:
            target = urlsplit(value)
            host = target.hostname
            port = target.port
            if (
                target.scheme not in {"redis", "rediss"}
                or not host or port not in (None, 6379)
                or target.fragment or target.query
                or target.path not in {"", "/"} | {f"/{n}" for n in range(16)}
            ):
                return False
            if target.username and not target.password:
                return False
            password = target.password
            if password and cls._is_insecure_secret(password):
                return False
            try:
                ipaddress.ip_address(host)
                private_name = False
            except ValueError:
                private_name = (
                    "." not in host and host.lower() not in {
                        "localhost", "localdomain", "host.docker.internal",
                    }
                    and host.replace("-", "").replace("_", "").isalnum()
                )
            # A single-label private service name resolves only within the
            # container/private network. Other destinations need TLS and
            # a strong credential embedded in the actual consumed URL.
            if private_name:
                return True
            return target.scheme == "rediss" and bool(password)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _env_bool(name: str, *, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in _TRUE_VALUES

    @staticmethod
    def _is_insecure_secret(value: str | None) -> bool:
        if value is None:
            return True
        normalized = value.strip().lower()
        if normalized in _INSECURE_SECRET_MARKERS:
            return True
        if any(fragment in normalized for fragment in _INSECURE_SECRET_FRAGMENTS):
            return True
        return len(value.strip()) < 16


_operational_health_service = OperationalHealthService()


def get_operational_health_service() -> OperationalHealthService:
    """Return the process-wide operational health authority."""
    return _operational_health_service


__all__ = [
    "OperationalHealthResult",
    "OperationalHealthService",
    "get_operational_health_service",
]
