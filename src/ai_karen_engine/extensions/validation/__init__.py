"""
Configuration validation system for extensions.

Provides comprehensive validation, security checks, and health monitoring
for extension configuration across different environments.

Migrated from root server/extension_config_validator.py as part of ROOT-CLEANUP-1A.
"""

from .config import (
    ValidationSeverity,
    HealthStatus,
    ValidationIssue,
    HealthCheckResult,
    ExtensionConfigValidator,
    get_config_validator,
    validate_extension_config,
    quick_validate,
)

__all__ = [
    "ValidationSeverity",
    "HealthStatus",
    "ValidationIssue",
    "HealthCheckResult",
    "ExtensionConfigValidator",
    "get_config_validator",
    "validate_extension_config",
    "quick_validate",
]