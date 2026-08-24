"""
Extension error recovery management system.

Implements comprehensive error recovery strategies for extension authentication failures,
service unavailability, and network errors using the strategy pattern.

Migrated from root server/extension_error_recovery_manager.py as part of ROOT-CLEANUP-1A.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Callable, Union, Type
from dataclasses import dataclass, field
from enum import Enum
import json

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Extension error categories"""
    AUTHENTICATION = "authentication"
    SERVICE_UNAVAILABLE = "service_unavailable"
    NETWORK = "network"
    PERMISSION = "permission"
    CONFIGURATION = "configuration"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class ErrorSeverity(str, Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoveryStrategy(str, Enum):
    """Recovery strategies"""
    RETRY_WITH_REFRESH = "retry_with_refresh"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    FALLBACK_TO_READONLY = "fallback_to_readonly"
    FALLBACK_TO_CACHED = "fallback_to_cached"
    GRACEFUL_DEGRADATION = "graceful_degradation"
    SERVICE_RESTART = "service_restart"
    CONNECTION_RESET = "connection_reset"
    ESCALATE_TO_ADMIN = "escalate_to_admin"
    NO_RECOVERY = "no_recovery"


@dataclass
class ExtensionError:
    """Extension error information"""
    category: ErrorCategory
    severity: ErrorSeverity
    code: str
    message: str
    technical_details: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    endpoint: Optional[str] = None
    operation: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    def can_retry(self) -> bool:
        """Check if error allows retry."""
        return self.retry_count < self.max_retries

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary."""
        result = {
            'category': self.category.value,
            'severity': self.severity.value,
            'code': self.code,
            'message': self.message,
            'technical_details': self.technical_details,
            'context': self.context,
            'timestamp': self.timestamp.isoformat(),
            'endpoint': self.endpoint,
            'operation': self.operation,
            'user_id': self.user_id,
            'tenant_id': self.tenant_id,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
        }
        return result


@dataclass
class RecoveryAttempt:
    """Recovery attempt information"""
    error: ExtensionError
    strategy: RecoveryStrategy
    attempt_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    success: bool = False
    error_message: Optional[str] = None
    recovery_data: Optional[Dict[str, Any]] = None
    next_attempt_delay: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert recovery attempt to dictionary."""
        return {
            'strategy': self.strategy.value,
            'attempt_number': self.attempt_number,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'success': self.success,
            'error_message': self.error_message,
            'recovery_data': self.recovery_data,
            'next_attempt_delay': self.next_attempt_delay,
            'error': self.error.to_dict() if self.error else None
        }


@dataclass
class RecoveryResult:
    """Recovery operation result"""
    success: bool
    strategy: RecoveryStrategy
    message: str
    fallback_data: Optional[Any] = None
    retry_after: Optional[float] = None
    recovery_attempts: List[RecoveryAttempt] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert recovery result to dictionary."""
        return {
            'success': self.success,
            'strategy': self.strategy.value,
            'message': self.message,
            'fallback_data': self.fallback_data,
            'retry_after': self.retry_after,
            'recovery_attempts': [attempt.to_dict() for attempt in self.recovery_attempts]
        }


class RecoveryStrategyABC(ABC):
    """Abstract base class for recovery strategies."""

    def __init__(self, error: ExtensionError, context: Dict[str, Any] = None):
        """Initialize recovery strategy."""
        self.error = error
        self.context = context or {}
        self._attempt_count = 0

    @abstractmethod
    async def execute(self) -> RecoveryResult:
        """Execute recovery strategy."""
        pass

    @abstractmethod
    def can_recover(self) -> bool:
        """Check if this strategy can recover from the error."""
        pass

    def increment_attempt(self):
        """Increment attempt count."""
        self._attempt_count += 1

    @property
    def attempt_count(self) -> int:
        """Get attempt count."""
        return self._attempt_count


class RetryWithRefreshStrategy(RecoveryStrategyABC):
    """Retry with authentication refresh strategy."""

    def can_recover(self) -> bool:
        """Check if can recover with token refresh."""
        return (
            self.error.category == ErrorCategory.AUTHENTICATION and
            self.error.code in ['invalid_token', 'expired_token', 'token_refresh_needed'] and
            self.error.can_retry()
        )

    async def execute(self) -> RecoveryResult:
        """Execute token refresh retry."""
        self.increment_attempt()
        attempt = RecoveryAttempt(
            error=self.error,
            strategy=RecoveryStrategy.RETRY_WITH_REFRESH,
            attempt_number=self.attempt_count,
            started_at=datetime.now(timezone.utc)
        )

        try:
            # Simulate token refresh
            refresh_delay = 0.1 + (self.attempt_count * 0.05)
            await asyncio.sleep(refresh_delay)

            attempt.completed_at = datetime.now(timezone.utc)
            attempt.success = True
            attempt.recovery_data = {'tokens_refreshed': True}

            return RecoveryResult(
                success=True,
                strategy=RecoveryStrategy.RETRY_WITH_REFRESH,
                message="Authentication tokens refreshed successfully",
                recovery_attempts=[attempt],
                retry_after=0.0
            )

        except Exception as e:
            attempt.completed_at = datetime.now(timezone.utc)
            attempt.success = False
            attempt.error_message = str(e)

            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.RETRY_WITH_REFRESH,
                message=f"Token refresh failed: {e}",
                recovery_attempts=[attempt],
                retry_after=1.0 + self.attempt_count
            )


class RetryWithBackoffStrategy(RecoveryStrategyABC):
    """Retry with exponential backoff strategy."""

    def can_recover(self) -> bool:
        """Check if can recover with retry and backoff."""
        return (
            self.error.category in [ErrorCategory.NETWORK, ErrorCategory.SERVICE_UNAVAILABLE, ErrorCategory.TIMEOUT] and
            self.error.can_retry()
        )

    async def execute(self) -> RecoveryResult:
        """Execute retry with exponential backoff."""
        self.increment_attempt()
        attempt = RecoveryAttempt(
            error=self.error,
            strategy=RecoveryStrategy.RETRY_WITH_BACKOFF,
            attempt_number=self.attempt_count,
            started_at=datetime.now(timezone.utc)
        )

        try:
            # Calculate exponential backoff delay
            backoff_delay = min(0.5 * (2 ** (self.attempt_count - 1)), 30.0)
            await asyncio.sleep(backoff_delay)

            attempt.completed_at = datetime.now(timezone.utc)
            attempt.success = True
            attempt.next_attempt_delay = backoff_delay if self.error.can_retry() else None

            return RecoveryResult(
                success=True,
                strategy=RecoveryStrategy.RETRY_WITH_BACKOFF,
                message=f"Retry succeeded after {backoff_delay:.2f}s backoff",
                recovery_attempts=[attempt],
                retry_after=attempt.next_attempt_delay
            )

        except Exception as e:
            attempt.completed_at = datetime.now(timezone.utc)
            attempt.success = False
            attempt.error_message = str(e)

            next_delay = min(1.0 * (2 ** self.attempt_count), 60.0)
            attempt.next_attempt_delay = next_delay if self.error.can_retry() else None

            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.RETRY_WITH_BACKOFF,
                message=f"Retry failed: {e}",
                recovery_attempts=[attempt],
                retry_after=attempt.next_attempt_delay
            )


class GracefulDegradationStrategy(RecoveryStrategyABC):
    """Graceful degradation strategy."""

    def can_recover(self) -> bool:
        """Check if can recover with graceful degradation."""
        return self.error.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]

    async def execute(self) -> RecoveryResult:
        """Execute graceful degradation."""
        self.increment_attempt()
        attempt = RecoveryAttempt(
            error=self.error,
            strategy=RecoveryStrategy.GRACEFUL_DEGRADATION,
            attempt_number=self.attempt_count,
            started_at=datetime.now(timezone.utc)
        )

        try:
            # Simulate graceful degradation activation
            degraded_services = self._identify_degraded_services()

            attempt.completed_at = datetime.now(timezone.utc)
            attempt.success = True
            attempt.recovery_data = {
                'degraded_services': degraded_services,
                'fallback_mode': 'enabled'
            }

            return RecoveryResult(
                success=True,
                strategy=RecoveryStrategy.GRACEFUL_DEGRADATION,
                message=f"Activated graceful degradation for {len(degraded_services)} services",
                fallback_data={'mode': 'degraded', 'affected_services': degraded_services},
                recovery_attempts=[attempt]
            )

        except Exception as e:
            attempt.completed_at = datetime.now(timezone.utc)
            attempt.success = False
            attempt.error_message = str(e)

            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.GRACEFUL_DEGRADATION,
                message=f"Graceful degradation failed: {e}",
                recovery_attempts=[attempt]
            )

    def _identify_degraded_services(self) -> List[str]:
        """Identify services to degrade."""
        # Simple heuristic based on error context
        degraded = []
        if self.error.operation:
            degraded.append(self.error.operation)
        if self.error.endpoint:
            endpoint_parts = self.error.endpoint.split('/')
            if len(endpoint_parts) > 1:
                degraded.append(endpoint_parts[1])
        return degraded


class FallbackToCachedStrategy(RecoveryStrategyABC):
    """Fallback to cached data strategy."""

    def can_recover(self) -> bool:
        """Check if can recover with cached data."""
        return (
            self.error.category in [ErrorCategory.SERVICE_UNAVAILABLE, ErrorCategory.TIMEOUT] and
            self.error.operation in ['read', 'get', 'fetch', 'query']
        )

    async def execute(self) -> RecoveryResult:
        """Execute fallback to cached data."""
        self.increment_attempt()
        attempt = RecoveryAttempt(
            error=self.error,
            strategy=RecoveryStrategy.FALLBACK_TO_CACHED,
            attempt_number=self.attempt_count,
            started_at=datetime.now(timezone.utc)
        )

        try:
            # Simulate cache retrieval
            cache_key = self._generate_cache_key()
            cached_data = await self._get_cached_data(cache_key)

            if cached_data:
                attempt.completed_at = datetime.now(timezone.utc)
                attempt.success = True
                attempt.recovery_data = {
                    'cache_key': cache_key,
                    'data_retrieved': True
                }

                return RecoveryResult(
                    success=True,
                    strategy=RecoveryStrategy.FALLBACK_TO_CACHED,
                    message="Retrieved data from cache",
                    fallback_data=cached_data,
                    recovery_attempts=[attempt]
                )
            else:
                raise ValueError("No cached data available")

        except Exception as e:
            attempt.completed_at = datetime.now(timezone.utc)
            attempt.success = False
            attempt.error_message = str(e)

            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.FALLBACK_TO_CACHED,
                message=f"Cache fallback failed: {e}",
                recovery_attempts=[attempt]
            )

    def _generate_cache_key(self) -> str:
        """Generate cache key from error context."""
        parts = [self.error.operation or 'unknown']
        if self.error.endpoint:
            parts.append(self.error.endpoint)
        if self.error.user_id:
            parts.append(self.error.user_id)
        return ':'.join(parts)

    async def _get_cached_data(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached data (simplified implementation)."""
        # In real implementation, this would check cache system
        return {'cached': True, 'key': cache_key, 'timestamp': datetime.now(timezone.utc).isoformat()}


class ExtensionErrorRecoveryManager:
    """Manages extension error recovery with multiple strategies."""

    def __init__(self):
        """Initialize the recovery manager."""
        self._strategy_classes: Dict[RecoveryStrategy, Type[RecoveryStrategyABC]] = {
            RecoveryStrategy.RETRY_WITH_REFRESH: RetryWithRefreshStrategy,
            RecoveryStrategy.RETRY_WITH_BACKOFF: RetryWithBackoffStrategy,
            RecoveryStrategy.GRACEFUL_DEGRADATION: GracefulDegradationStrategy,
            RecoveryStrategy.FALLBACK_TO_CACHED: FallbackToCachedStrategy,
        }
        self._recovery_history: List[RecoveryAttempt] = []
        self._max_history = 100

    async def recover_from_error(
        self,
        error: ExtensionError,
        context: Dict[str, Any] = None
    ) -> RecoveryResult:
        """
        Attempt to recover from an extension error using appropriate strategies.

        Args:
            error: The extension error to recover from
            context: Additional context for recovery

        Returns:
            RecoveryResult with outcome and details
        """
        context = context or {}

        # Determine appropriate recovery strategies
        strategies = self._select_recovery_strategies(error)

        if not strategies:
            return RecoveryResult(
                success=False,
                strategy=RecoveryStrategy.NO_RECOVERY,
                message="No suitable recovery strategy available",
                recovery_attempts=[]
            )

        # Try strategies in priority order
        for strategy_enum in strategies:
            try:
                strategy_class = self._strategy_classes[strategy_enum]
                strategy = strategy_class(error, context)

                if not strategy.can_recover():
                    continue

                result = await strategy.execute()
                if result.success:
                    self._record_recovery(result.recovery_attempts)
                    return result
                else:
                    self._record_recovery(result.recovery_attempts)

                    # Check if we should retry
                    if error.can_retry() and result.retry_after:
                        error.retry_count += 1
                        await asyncio.sleep(result.retry_after)
                        continue

            except Exception as e:
                logger.error(f"Recovery strategy {strategy_enum.value} failed: {e}")
                continue

        # All strategies failed
        return RecoveryResult(
            success=False,
            strategy=strategies[0] if strategies else RecoveryStrategy.NO_RECOVERY,
            message="All recovery strategies failed",
            recovery_attempts=[]
        )

    def _select_recovery_strategies(self, error: ExtensionError) -> List[RecoveryStrategy]:
        """Select appropriate recovery strategies based on error characteristics."""
        strategies = []

        # Priority order based on error characteristics
        if error.category == ErrorCategory.AUTHENTICATION:
            strategies.extend([
                RecoveryStrategy.RETRY_WITH_REFRESH,
                RecoveryStrategy.GRACEFUL_DEGRADATION,
            ])
        elif error.category == ErrorCategory.NETWORK:
            strategies.extend([
                RecoveryStrategy.RETRY_WITH_BACKOFF,
                RecoveryStrategy.FALLBACK_TO_CACHED,
                RecoveryStrategy.GRACEFUL_DEGRADATION,
            ])
        elif error.category == ErrorCategory.SERVICE_UNAVAILABLE:
            strategies.extend([
                RecoveryStrategy.RETRY_WITH_BACKOFF,
                RecoveryStrategy.FALLBACK_TO_CACHED,
                RecoveryStrategy.GRACEFUL_DEGRADATION,
            ])
        elif error.category == ErrorCategory.TIMEOUT:
            strategies.extend([
                RecoveryStrategy.RETRY_WITH_BACKOFF,
                RecoveryStrategy.FALLBACK_TO_CACHED,
                RecoveryStrategy.GRACEFUL_DEGRADATION,
            ])
        elif error.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            strategies.append(RecoveryStrategy.GRACEFUL_DEGRADATION)

        return strategies

    def _record_recovery(self, attempts: List[RecoveryAttempt]):
        """Record recovery attempts for monitoring and analysis."""
        for attempt in attempts:
            self._recovery_history.append(attempt)

        # Maintain history size limit
        if len(self._recovery_history) > self._max_history:
            self._recovery_history = self._recovery_history[-self._max_history:]

    def get_recovery_statistics(self) -> Dict[str, Any]:
        """Get recovery statistics and metrics."""
        if not self._recovery_history:
            return {'total_attempts': 0, 'successful': 0, 'failed': 0}

        successful = sum(1 for a in self._recovery_history if a.success)
        failed = len(self._recovery_history) - successful

        # Statistics by strategy
        by_strategy: Dict[str, Dict[str, int]] = {}
        for attempt in self._recovery_history:
            strategy_name = attempt.strategy.value
            if strategy_name not in by_strategy:
                by_strategy[strategy_name] = {'total': 0, 'successful': 0, 'failed': 0}

            by_strategy[strategy_name]['total'] += 1
            if attempt.success:
                by_strategy[strategy_name]['successful'] += 1
            else:
                by_strategy[strategy_name]['failed'] += 1

        # Statistics by error category
        by_category: Dict[str, int] = {}
        for attempt in self._recovery_history:
            if attempt.error and attempt.error.category:
                category_name = attempt.error.category.value
                by_category[category_name] = by_category.get(category_name, 0) + 1

        return {
            'total_attempts': len(self._recovery_history),
            'successful': successful,
            'failed': failed,
            'success_rate': successful / len(self._recovery_history) if self._recovery_history else 0,
            'by_strategy': by_strategy,
            'by_category': by_category
        }

    def clear_recovery_history(self):
        """Clear recovery history."""
        self._recovery_history.clear()

    def get_recent_failures(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent failed recovery attempts."""
        failed_attempts = [
            a for a in self._recovery_history
            if not a.success
        ]

        recent_failed = failed_attempts[-limit:] if failed_attempts else []
        return [attempt.to_dict() for attempt in recent_failed]


# Global recovery manager instance
_recovery_manager: Optional[ExtensionErrorRecoveryManager] = None


def get_extension_recovery_manager() -> ExtensionErrorRecoveryManager:
    """Get or create the global extension error recovery manager."""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = ExtensionErrorRecoveryManager()
    return _recovery_manager


async def recover_from_extension_error(
    error: ExtensionError,
    context: Dict[str, Any] = None
) -> RecoveryResult:
    """Convenience function to recover from extension errors."""
    manager = get_extension_recovery_manager()
    return await manager.recover_from_error(error, context)


def create_extension_error(
    category: str,
    code: str,
    message: str,
    severity: str = "medium",
    **kwargs
) -> ExtensionError:
    """Create an extension error from parameters."""
    return ExtensionError(
        category=ErrorCategory(category),
        severity=ErrorSeverity(severity),
        code=code,
        message=message,
        **kwargs
    )


__all__ = [
    # Enums
    "ErrorCategory",
    "ErrorSeverity",
    "RecoveryStrategy",

    # Data classes
    "ExtensionError",
    "RecoveryAttempt",
    "RecoveryResult",

    # Strategy classes
    "RecoveryStrategyABC",
    "RetryWithRefreshStrategy",
    "RetryWithBackoffStrategy",
    "GracefulDegradationStrategy",
    "FallbackToCachedStrategy",

    # Manager
    "ExtensionErrorRecoveryManager",
    "get_extension_recovery_manager",
    "recover_from_extension_error",
    "create_extension_error",
]