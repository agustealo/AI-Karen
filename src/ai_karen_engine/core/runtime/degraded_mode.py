"""Degraded Mode compatibility shim owned by Core runtime.

The shim never manufactures assistant text and never imports a concrete fallback
provider. It delegates model execution to ExpressionGateway and returns an honest
unavailable envelope when all runtime providers fail.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class DegradedModeReason(Enum):
    ALL_PROVIDERS_FAILED = "all_providers_failed"
    NETWORK_ISSUES = "network_issues"
    API_RATE_LIMITS = "api_rate_limits"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    MANUAL_ACTIVATION = "manual_activation"


@dataclass
class DegradedModeStatus:
    is_active: bool = False
    reason: Optional[DegradedModeReason] = None
    activated_at: Optional[datetime] = None
    failed_providers: Optional[List[str]] = None
    recovery_attempts: int = 0
    last_recovery_attempt: Optional[datetime] = None
    core_helpers_available: Optional[Dict[str, bool]] = None

    def __post_init__(self) -> None:
        if self.failed_providers is None:
            self.failed_providers = []
        if self.core_helpers_available is None:
            self.core_helpers_available = {}


class DegradedModeManager:
    def __init__(self) -> None:
        import os
        from ai_karen_engine.config.config_manager import get_default_model, get_default_provider

        self._fallback_provider = os.getenv("KARI_DEGRADED_PROVIDER", get_default_provider())
        self._fallback_model = os.getenv("KARI_DEGRADED_MODEL", get_default_model())

    def get_fallback_provider(self) -> Tuple[str, str]:
        return self._fallback_provider, self._fallback_model

    def activate_degraded_mode(
        self,
        reason: DegradedModeReason,
        failed_providers: Optional[List[str]] = None,
    ) -> None:
        logger.warning(
            "Legacy degraded-mode activation requested",
            extra={"reason": reason.value, "failed_providers": failed_providers or []},
        )

    def deactivate_degraded_mode(self) -> None:
        logger.info("Legacy degraded-mode deactivation requested")

    def attempt_recovery(self) -> bool:
        return False

    async def generate_degraded_response(self, user_input: str, **kwargs: Any) -> Dict[str, Any]:
        return await generate_degraded_mode_response(user_input, **kwargs)

    def get_status(self) -> DegradedModeStatus:
        return DegradedModeStatus(
            is_active=False,
            reason=None,
            core_helpers_available={"runtime_control_plane": True},
        )

    def get_health_summary(self) -> Dict[str, Any]:
        return {
            "degraded_mode_active": False,
            "core_helpers": {"runtime_control_plane": {"is_healthy": True}},
            "note": "Managed by ChatRuntimeControlPlane",
        }


_degraded_mode_manager: Optional[DegradedModeManager] = None


def get_degraded_mode_manager() -> DegradedModeManager:
    global _degraded_mode_manager
    if _degraded_mode_manager is None:
        _degraded_mode_manager = DegradedModeManager()
    return _degraded_mode_manager


async def generate_degraded_mode_response(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    from ai_karen_engine.core.expression.contracts import ExpressionTask
    from ai_karen_engine.core.expression.gateway import ExpressionGateway
    from ai_karen_engine.core.langgraph_orchestrator.formatting.response_formatter_pipeline import (
        ResponseFormatterPipeline,
    )

    requested_provider = kwargs.get("requested_provider", "auto")
    requested_model = kwargs.get("requested_model", "auto")
    failure_reason = kwargs.get("failure_reason", "Requested provider unavailable")

    try:
        result = await ExpressionGateway().generate(
            ExpressionTask(
                task_id=f"degraded_{int(time.time())}",
                kind="chat",
                correlation_id=kwargs.get("correlation_id", "degraded"),
                request_id=kwargs.get("request_id", "degraded"),
                messages=[{"role": "user", "content": user_input}],
                preferred_provider=requested_provider,
                preferred_model=requested_model,
                max_tokens=256,
                temperature=0.7,
                timeout_ms=10000,
                required_capabilities=["text_generation"],
                forbidden_capabilities=[],
                response_mode="text",
                metadata={"degraded_mode": True, "failure_reason": failure_reason},
            )
        )
        if not result.text.strip() or not result.provider:
            raise RuntimeError("No model provider produced degraded output")
        return ResponseFormatterPipeline().build_response_envelope(
            result.text,
            result.provider,
            result.model or requested_model,
            metadata={
                "degraded_mode": True,
                "degraded_mode_active": True,
                "requested_provider": requested_provider,
                "requested_model": requested_model,
                "actual_provider": result.provider,
                "actual_model": result.model,
                "response_source": result.response_source,
                "latency_ms": result.latency_ms,
                "failure_reason": failure_reason,
            },
            status="ok",
        )
    except Exception as exc:
        logger.warning("All degraded runtime providers failed: %s", exc)
        return ResponseFormatterPipeline().build_response_envelope(
            "",
            None,
            None,
            metadata={
                "degraded_mode": True,
                "degraded_mode_active": True,
                "requested_provider": requested_provider,
                "requested_model": requested_model,
                "actual_provider": None,
                "actual_model": None,
                "response_source": "model_unavailable",
                "failure_reason": failure_reason,
                "error_type": type(exc).__name__,
            },
            status="unavailable",
        )


class DegradedMode:
    @staticmethod
    def activate(
        reason: DegradedModeReason,
        failed_providers: Optional[List[str]] = None,
    ) -> None:
        get_degraded_mode_manager().activate_degraded_mode(reason, failed_providers)

    @staticmethod
    def deactivate() -> None:
        get_degraded_mode_manager().deactivate_degraded_mode()

    @staticmethod
    def get_status() -> DegradedModeStatus:
        return get_degraded_mode_manager().get_status()

    @staticmethod
    def get_fallback_provider() -> Tuple[str, str]:
        return get_degraded_mode_manager().get_fallback_provider()

    @staticmethod
    async def generate_response(user_input: str, **kwargs: Any) -> Dict[str, Any]:
        return await generate_degraded_mode_response(user_input, **kwargs)
