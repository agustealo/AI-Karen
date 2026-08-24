"""
Admin Observability Metrics — lightweight wrapper for admin operation metrics.

Emits structured log events for:
- admin.request.received
- admin.authorization.allowed
- admin.authorization.denied
- admin.action.executed
- admin.action.failed
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AdminMetrics:
    """Lightweight admin metrics collector."""

    def __init__(self) -> None:
        self._request_count = 0
        self._authorization_allowed = 0
        self._authorization_denied = 0
        self._action_executed = 0
        self._action_failed = 0

    def record_request(self, endpoint: str, method: str, user_id: Optional[str] = None) -> None:
        self._request_count += 1
        logger.info(
            "admin.request.received",
            extra={
                "admin_metric": "request_received",
                "endpoint": endpoint,
                "method": method,
                "user_id": user_id,
            },
        )

    def record_authorization_allowed(
        self,
        endpoint: str,
        permission: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        self._authorization_allowed += 1
        logger.info(
            "admin.authorization.allowed",
            extra={
                "admin_metric": "authorization_allowed",
                "endpoint": endpoint,
                "permission": permission,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
        )

    def record_authorization_denied(
        self,
        endpoint: str,
        permission: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        self._authorization_denied += 1
        logger.warning(
            "admin.authorization.denied",
            extra={
                "admin_metric": "authorization_denied",
                "endpoint": endpoint,
                "permission": permission,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
        )

    def record_action_executed(
        self,
        endpoint: str,
        action: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        self._action_executed += 1
        logger.info(
            "admin.action.executed",
            extra={
                "admin_metric": "action_executed",
                "endpoint": endpoint,
                "action": action,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "latency_ms": latency_ms,
            },
        )

    def record_action_failed(
        self,
        endpoint: str,
        action: str,
        error: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        self._action_failed += 1
        logger.error(
            "admin.action.failed",
            extra={
                "admin_metric": "action_failed",
                "endpoint": endpoint,
                "action": action,
                "error": error,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
        )

    def get_stats(self) -> Dict[str, int]:
        return {
            "request_count": self._request_count,
            "authorization_allowed": self._authorization_allowed,
            "authorization_denied": self._authorization_denied,
            "action_executed": self._action_executed,
            "action_failed": self._action_failed,
        }


_admin_metrics = AdminMetrics()


def get_admin_metrics() -> AdminMetrics:
    return _admin_metrics
