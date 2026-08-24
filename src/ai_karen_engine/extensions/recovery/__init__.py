"""
Extension error recovery system.

Provides comprehensive error recovery strategies for extension authentication failures,
service unavailability, and network errors using the strategy pattern.

Migrated from root server/extension_error_recovery_manager.py as part of ROOT-CLEANUP-1A.
"""

from .manager import (
    ErrorCategory,
    ErrorSeverity,
    RecoveryStrategy,
    ExtensionError,
    RecoveryAttempt,
    RecoveryResult,
    RecoveryStrategyABC,
    RetryWithRefreshStrategy,
    RetryWithBackoffStrategy,
    GracefulDegradationStrategy,
    FallbackToCachedStrategy,
    ExtensionErrorRecoveryManager,
    get_extension_recovery_manager,
    recover_from_extension_error,
    create_extension_error,
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