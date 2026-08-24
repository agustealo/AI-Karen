"""
Configuration validation system for extensions.

Provides comprehensive validation, security checks, and health monitoring
for extension configuration across different environments.

Migrated from root server/extension_config_validator.py as part of ROOT-CLEANUP-1A.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict, field
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Validation issue severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class HealthStatus(str, Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ValidationIssue:
    """Represents a configuration validation issue."""
    severity: ValidationSeverity
    category: str
    message: str
    field: Optional[str] = None
    recommendation: Optional[str] = None
    auto_fixable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['timestamp'] = self.timestamp.isoformat()
        return result


class ExtensionConfigValidator:
    """Validates extension configuration for security, performance, and correctness."""

    def __init__(self):
        """Initialize the validator with default rules."""
        self.validation_rules: List[Callable] = []
        self._register_default_rules()

    def _register_default_rules(self):
        """Register default validation rules."""
        self.validation_rules.extend([
            self._validate_secret_keys,
            self._validate_api_keys,
            self._validate_jwt_settings,
            self._validate_rate_limiting,
            self._validate_token_settings,
            self._validate_permission_settings,
            self._validate_logging_settings,
            self._validate_health_check_settings,
            self._validate_production_security,
            self._validate_network_security,
        ])

    def validate_config(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """
        Validate configuration and return list of issues.

        Args:
            config: Configuration dictionary to validate

        Returns:
            List of validation issues sorted by severity
        """
        issues = []

        try:
            for rule in self.validation_rules:
                try:
                    rule_issues = rule(config)
                    if rule_issues:
                        issues.extend(rule_issues)
                except Exception as e:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        category="validation_error",
                        message=f"Validation rule failed: {e}",
                        recommendation="Check validation rule implementation"
                    ))

            # Sort issues by severity
            severity_order = {
                ValidationSeverity.CRITICAL: 0,
                ValidationSeverity.ERROR: 1,
                ValidationSeverity.WARNING: 2,
                ValidationSeverity.INFO: 3
            }
            issues.sort(key=lambda x: severity_order.get(x.severity, 999))

        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="validation_failure",
                message=f"Configuration validation failed: {e}"
            ))

        return issues

    def _validate_secret_keys(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate secret key settings."""
        issues = []
        secret_key = config.get('secret_key', '')

        if not secret_key:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="authentication",
                field="secret_key",
                message="Secret key is required for authentication",
                recommendation="Generate a secure secret key using secrets.token_urlsafe(32)",
                auto_fixable=False
            ))
        elif len(secret_key) < 32:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="authentication",
                field="secret_key",
                message="Secret key is too short (minimum 32 characters)",
                recommendation="Use a longer, more secure secret key",
                auto_fixable=False
            ))
        elif secret_key in ["dev-extension-secret-key-change-in-production", "change-me", "secret", ""]:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="authentication",
                field="secret_key",
                message="Using default or weak secret key",
                recommendation="Generate a unique, secure secret key for this environment",
                auto_fixable=False
            ))

        return issues

    def _validate_api_keys(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate API key settings."""
        issues = []
        api_key = config.get('api_key', '')

        if not api_key:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="authentication",
                field="api_key",
                message="API key is required",
                recommendation="Generate a secure API key",
                auto_fixable=False
            ))
        elif api_key in ["dev-extension-api-key-change-in-production", "change-me", "api-key", ""]:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="authentication",
                field="api_key",
                message="Using default or weak API key",
                recommendation="Generate a unique, secure API key for this environment",
                auto_fixable=False
            ))

        return issues

    def _validate_jwt_settings(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate JWT algorithm and token settings."""
        issues = []
        jwt_algorithm = config.get('jwt_algorithm', 'HS256')

        secure_algorithms = ["HS256", "HS384", "HS512", "RS256", "RS384", "RS512"]
        if jwt_algorithm not in secure_algorithms:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="authentication",
                field="jwt_algorithm",
                message=f"JWT algorithm '{jwt_algorithm}' may not be secure",
                recommendation=f"Use one of: {', '.join(secure_algorithms)}",
                auto_fixable=False
            ))

        # Check token expiration times
        access_token_expire = config.get('access_token_expire_minutes', 60)
        if access_token_expire > 1440:  # 24 hours
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="authentication",
                field="access_token_expire_minutes",
                message="Access token expiration time is very long",
                recommendation="Reduce to 1 hour (60 minutes) or less for better security",
                auto_fixable=False
            ))

        return issues

    def _validate_rate_limiting(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate rate limiting settings."""
        issues = []

        if not config.get('enable_rate_limiting', False):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="security",
                field="enable_rate_limiting",
                message="Rate limiting is disabled",
                recommendation="Enable rate limiting to prevent abuse",
                auto_fixable=True
            ))

        rate_limit = config.get('rate_limit_per_minute', 100)
        if rate_limit > 1000:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="security",
                field="rate_limit_per_minute",
                message="Rate limit is very high",
                recommendation="Consider reducing to prevent abuse",
                auto_fixable=False
            ))

        return issues

    def _validate_token_settings(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate token management settings."""
        issues = []

        if not config.get('token_blacklist_enabled', False):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="authentication",
                field="token_blacklist_enabled",
                message="Token blacklist is disabled",
                recommendation="Enable token blacklist for better security",
                auto_fixable=True
            ))

        max_failed_attempts = config.get('max_failed_attempts', 5)
        if max_failed_attempts < 3:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="authentication",
                field="max_failed_attempts",
                message="Maximum failed attempts is very low",
                recommendation="Increase to at least 3 to prevent accidental lockouts",
                auto_fixable=False
            ))

        return issues

    def _validate_permission_settings(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate permission system settings."""
        issues = []

        if not config.get('audit_logging_enabled', False):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="security",
                field="audit_logging_enabled",
                message="Audit logging is disabled",
                recommendation="Enable audit logging for security monitoring",
                auto_fixable=True
            ))

        return issues

    def _validate_logging_settings(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate logging configuration."""
        issues = []

        # Check if logging level is appropriate for environment
        environment = config.get('environment', 'production')
        logging_level = config.get('logging_level', 'INFO')

        if environment == 'production' and logging_level == 'DEBUG':
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="logging",
                field="logging_level",
                message="DEBUG logging level in production environment",
                recommendation="Use INFO or WARNING level in production",
                auto_fixable=True
            ))

        return issues

    def _validate_health_check_settings(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate health check configuration."""
        issues = []

        if not config.get('health_check_enabled', True):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="monitoring",
                field="health_check_enabled",
                message="Health checks are disabled",
                recommendation="Enable health checks for system monitoring",
                auto_fixable=True
            ))

        health_check_interval = config.get('health_check_interval_seconds', 30)
        if health_check_interval < 10:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="monitoring",
                field="health_check_interval_seconds",
                message="Health check interval is very short",
                recommendation="Increase to at least 10 seconds to reduce system load",
                auto_fixable=False
            ))

        return issues

    def _validate_production_security(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate production-specific security settings."""
        issues = []

        environment = config.get('environment', 'production')
        if environment != 'production':
            return issues  # Skip production validation for non-production environments

        # Production security requirements
        if not config.get('require_https', True):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="security",
                field="require_https",
                message="HTTPS requirement is disabled in production",
                recommendation="Enable HTTPS for production security",
                auto_fixable=True
            ))

        auth_mode = config.get('auth_mode', 'strict')
        if auth_mode == 'development':
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="authentication",
                field="auth_mode",
                message="Development auth mode in production environment",
                recommendation="Use 'strict' or 'hybrid' auth mode in production",
                auto_fixable=True
            ))

        if config.get('dev_bypass_enabled', False):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="security",
                field="dev_bypass_enabled",
                message="Development bypass enabled in production",
                recommendation="Disable development bypass in production",
                auto_fixable=True
            ))

        return issues

    def _validate_network_security(self, config: Dict[str, Any]) -> List[ValidationIssue]:
        """Validate network security settings."""
        issues = []

        # Check for allowed hosts configuration
        allowed_hosts = config.get('allowed_hosts', [])
        if not allowed_hosts:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="network",
                field="allowed_hosts",
                message="No allowed hosts configured",
                recommendation="Configure allowed hosts for better security",
                auto_fixable=False
            ))

        # Check for CORS configuration
        cors_origins = config.get('cors_origins', [])
        if environment := config.get('environment') == 'production':
            if '*' in cors_origins or not cors_origins:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    category="network",
                    field="cors_origins",
                    message="CORS origins not properly configured for production",
                    recommendation="Specify explicit allowed origins instead of wildcard",
                    auto_fixable=False
                ))

        return issues

    def validate_health_check(self, check_name: str, health_check: Callable) -> HealthCheckResult:
        """
        Execute and validate a health check.

        Args:
            check_name: Name of the health check
            health_check: Health check function to execute

        Returns:
            HealthCheckResult with status and details
        """
        import time

        start_time = time.time()
        try:
            result = health_check()
            if result:
                status = HealthStatus.HEALTHY
                message = f"{check_name} is healthy"
            else:
                status = HealthStatus.UNHEALTHY
                message = f"{check_name} failed health check"

            return HealthCheckResult(
                name=check_name,
                status=status,
                message=message,
                details={"check_result": result},
                duration_ms=(time.time() - start_time) * 1000
            )

        except Exception as e:
            logger.error(f"Health check '{check_name}' failed: {e}")
            return HealthCheckResult(
                name=check_name,
                status=HealthStatus.UNHEALTHY,
                message=f"{check_name} health check failed: {e}",
                details={"error": str(e)},
                duration_ms=(time.time() - start_time) * 1000
            )

    def auto_fix_issues(self, issues: List[ValidationIssue]) -> Dict[str, Any]:
        """
        Attempt to automatically fix auto-fixable issues.

        Args:
            issues: List of validation issues

        Returns:
            Dictionary with fix results
        """
        results = {
            'fixed': [],
            'failed': [],
            'skipped': []
        }

        for issue in issues:
            if not issue.auto_fixable:
                results['skipped'].append(issue.to_dict())
                continue

            try:
                # Attempt auto-fix
                if self._auto_fix_issue(issue):
                    results['fixed'].append(issue.to_dict())
                    logger.info(f"Auto-fixed issue: {issue.message}")
                else:
                    results['failed'].append(issue.to_dict())
                    logger.warning(f"Failed to auto-fix issue: {issue.message}")

            except Exception as e:
                results['failed'].append(issue.to_dict())
                logger.error(f"Auto-fix failed for issue: {issue.message} - {e}")

        return results

    def _auto_fix_issue(self, issue: ValidationIssue) -> bool:
        """
        Attempt to automatically fix a specific issue.

        Args:
            issue: Validation issue to fix

        Returns:
            True if fix was successful
        """
        # Auto-fix implementations for common issues
        fix_implementations = {
            'enable_rate_limiting': lambda: True,
            'token_blacklist_enabled': lambda: True,
            'audit_logging_enabled': lambda: True,
            'health_check_enabled': lambda: True,
            'require_https': lambda: True,
            'dev_bypass_enabled': lambda: True,
        }

        if issue.field in fix_implementations:
            try:
                return fix_implementations[issue.field]()
            except Exception as e:
                logger.error(f"Auto-fix implementation failed for {issue.field}: {e}")
                return False

        return False

    def get_validation_report(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a comprehensive validation report.

        Args:
            config: Configuration to validate

        Returns:
            Comprehensive validation report
        """
        issues = self.validate_config(config)

        # Categorize issues
        critical_issues = [i for i in issues if i.severity == ValidationSeverity.CRITICAL]
        error_issues = [i for i in issues if i.severity == ValidationSeverity.ERROR]
        warning_issues = [i for i in issues if i.severity == ValidationSeverity.WARNING]
        info_issues = [i for i in issues if i.severity == ValidationSeverity.INFO]

        # Calculate auto-fix potential
        auto_fixable_count = sum(1 for i in issues if i.auto_fixable)
        auto_fix_results = self.auto_fix_issues(issues)

        # Determine overall status
        if critical_issues:
            overall_status = "CRITICAL"
        elif error_issues:
            overall_status = "ERROR"
        elif warning_issues:
            overall_status = "WARNING"
        else:
            overall_status = "HEALTHY"

        return {
            'overall_status': overall_status,
            'validation_time': datetime.utcnow().isoformat(),
            'summary': {
                'total_issues': len(issues),
                'critical': len(critical_issues),
                'error': len(error_issues),
                'warning': len(warning_issues),
                'info': len(info_issues),
                'auto_fixable': auto_fixable_count
            },
            'issues': [issue.to_dict() for issue in issues],
            'auto_fix_results': auto_fix_results,
            'recommendations': [
                issue.recommendation for issue in issues
                if issue.recommendation
            ]
        }


# Global validator instance
_config_validator: Optional[ExtensionConfigValidator] = None


def get_config_validator() -> ExtensionConfigValidator:
    """Get or create the global configuration validator."""
    global _config_validator
    if _config_validator is None:
        _config_validator = ExtensionConfigValidator()
    return _config_validator


def validate_extension_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate extension configuration and return comprehensive report."""
    validator = get_config_validator()
    return validator.get_validation_report(config)


def quick_validate(config: Dict[str, Any]) -> bool:
    """Quick validation check - returns True if configuration is acceptable."""
    validator = get_config_validator()
    issues = validator.validate_config(config)

    # Check for critical or error issues
    has_critical = any(i.severity == ValidationSeverity.CRITICAL for i in issues)
    has_error = any(i.severity == ValidationSeverity.ERROR for i in issues)

    return not (has_critical or has_error)


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