"""
Safety Middleware for CoPilot requests.

This module provides safety validation for CoPilot requests before passing
to agent architecture, including content safety checks and authorization checks.
"""

import logging
import re
from typing import Dict, List, Any, Optional, Set
from datetime import datetime

from ai_karen_engine.copilotkit.models import AgentTask, AgentUIServiceError
from ai_karen_engine.agents.models import AgentRequest

logger = logging.getLogger(__name__)


class SafetyCheckResult:
    """Result of a safety check."""

    def __init__(
        self,
        is_safe: bool = True,
        risk_score: float = 0.0,
        blocked_content: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.is_safe = is_safe
        self.risk_score = max(0.0, min(10.0, risk_score))  # Clamp 0-10
        self.blocked_content = blocked_content or []
        self.warnings = warnings or []
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_safe": self.is_safe,
            "risk_score": self.risk_score,
            "blocked_content": self.blocked_content,
            "warnings": self.warnings,
            "details": self.details,
        }


class AuthorizationResult:
    """Result of an authorization check."""

    def __init__(
        self,
        authorized: bool = True,
        granted_permissions: Optional[List[str]] = None,
        denied_permissions: Optional[List[str]] = None,
        reason: Optional[str] = None,
    ):
        self.authorized = authorized
        self.granted_permissions = granted_permissions or []
        self.denied_permissions = denied_permissions or []
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "authorized": self.authorized,
            "granted_permissions": self.granted_permissions,
            "denied_permissions": self.denied_permissions,
            "reason": self.reason,
        }


class SafetyValidationResult:
    """Combined result of safety and authorization validation."""

    def __init__(
        self,
        is_safe: bool = True,
        safety_check: Optional[SafetyCheckResult] = None,
        authorization_check: Optional[AuthorizationResult] = None,
        overall_risk_score: float = 0.0,
        can_proceed: bool = True,
        requires_moderation: bool = False,
    ):
        self.is_safe = is_safe
        self.safety_check = safety_check
        self.authorization_check = authorization_check
        self.overall_risk_score = max(0.0, min(10.0, overall_risk_score))  # Clamp 0-10
        self.can_proceed = can_proceed
        self.requires_moderation = requires_moderation

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_safe": self.is_safe,
            "safety_check": self.safety_check.to_dict() if self.safety_check else None,
            "authorization_check": self.authorization_check.to_dict()
            if self.authorization_check
            else None,
            "overall_risk_score": self.overall_risk_score,
            "can_proceed": self.can_proceed,
            "requires_moderation": self.requires_moderation,
        }


class CopilotSafetyMiddleware:
    """
    Middleware for safety validation of CoPilot requests.

    Validates all requests for security and safety
    before passing to agent architecture.
    """

    def __init__(self, safety_system=None, security_system=None):
        """Initialize safety middleware with dependencies."""
        self.safety_system = safety_system
        self.security_system = security_system

        # Safety configuration
        self.content_filters = self._initialize_content_filters()
        self.permission_requirements = self._initialize_permission_requirements()
        self.rate_limits = self._initialize_rate_limits()

        # Blocked patterns
        self.blocked_patterns = self._initialize_blocked_patterns()

        # Statistics
        self.validation_stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "warning_requests": 0,
            "allowed_requests": 0,
        }

        logger.info("CoPilot Safety Middleware initialized")

    async def validate_request(self, request: AgentTask) -> SafetyValidationResult:
        """
        Validate a CoPilot request for safety and security.

        Args:
            request: AgentTask to validate

        Returns:
            SafetyValidationResult with validation outcome
        """
        try:
            logger.info(f"Validating request for task {request.task_id}")

            # Update statistics
            self.validation_stats["total_requests"] += 1

            # Perform content safety check
            safety_check = await self._check_content_safety(request)

            # Perform authorization check
            authorization_check = await self._check_authorization(request)

            # Calculate overall risk score
            overall_risk_score = self._calculate_overall_risk(
                safety_check, authorization_check
            )

            # Determine if request can proceed
            can_proceed = (
                safety_check.is_safe
                and authorization_check.authorized
                and overall_risk_score < 7.0  # High risk threshold
            )

            # Check if moderation is required
            requires_moderation = (
                not safety_check.is_safe
                or overall_risk_score >= 5.0  # Moderation threshold
            )

            # Create validation result
            result = SafetyValidationResult(
                is_safe=can_proceed,
                safety_check=safety_check,
                authorization_check=authorization_check,
                overall_risk_score=overall_risk_score,
                can_proceed=can_proceed,
                requires_moderation=requires_moderation,
            )

            # Update statistics
            if not can_proceed:
                self.validation_stats["blocked_requests"] += 1
            elif requires_moderation or safety_check.warnings:
                self.validation_stats["warning_requests"] += 1
            else:
                self.validation_stats["allowed_requests"] += 1

            logger.info(
                f"Request validation completed for task {request.task_id}: safe={can_proceed}"
            )
            return result

        except Exception as e:
            logger.error(
                f"Error validating request for task {request.task_id}: {e}",
                exc_info=True,
            )
            self.validation_stats["blocked_requests"] += 1

            return SafetyValidationResult(
                is_safe=False,
                overall_risk_score=10.0,
                can_proceed=False,
                requires_moderation=True,
            )

    async def _check_content_safety(self, request: AgentTask) -> SafetyCheckResult:
        """Check content safety of request."""
        try:
            content = request.content.lower()
            blocked_content = []
            warnings = []
            risk_score = 0.0

            # Check against blocked patterns
            for pattern_name, pattern in self.blocked_patterns.items():
                if re.search(pattern, content):
                    blocked_content.append(f"Blocked content: {pattern_name}")
                    risk_score += 3.0

            # Check for sensitive information
            sensitive_patterns = [
                r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",  # Credit card numbers
                r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",  # SSN
                r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",  # Email addresses
                r"password\s*[:=]\s*\S+",  # Passwords
                r"api[_-]?key\s*[:=]\s*\S+",  # API keys
                r"token\s*[:=]\s*\S+",  # Tokens
            ]

            for pattern in sensitive_patterns:
                if re.search(pattern, content):
                    warnings.append("Potentially sensitive information detected")
                    risk_score += 2.0

            # Check for malicious content indicators
            malicious_indicators = [
                "drop table",
                "exec(",
                "eval(",
                "system(",
                "union select",
                "javascript:",
                "vbscript:",
                "<script",
                "onclick=",
                "onerror=",
                "document.cookie",
                "window.location",
                "xss",
                "sql injection",
            ]

            for indicator in malicious_indicators:
                if indicator in content:
                    blocked_content.append(f"Malicious content indicator: {indicator}")
                    risk_score += 5.0

            # Check content length limits
            max_content_length = self.rate_limits.get("max_content_length", 10000)
            if len(content) > max_content_length:
                warnings.append(
                    f"Content exceeds maximum length ({max_content_length} characters)"
                )
                risk_score += 1.0

            # Check for excessive repetition
            words = content.split()
            if len(words) > 10:
                unique_words = set(words)
                repetition_ratio = (len(words) - len(unique_words)) / len(words)
                if repetition_ratio > 0.7:
                    warnings.append("Excessive content repetition detected")
                    risk_score += 1.5

            # Determine if content is safe
            is_safe = risk_score < 5.0 and len(blocked_content) == 0

            return SafetyCheckResult(
                is_safe=is_safe,
                risk_score=risk_score,
                blocked_content=blocked_content,
                warnings=warnings,
                details={
                    "content_length": len(content),
                    "word_count": len(words),
                    "unique_words": len(set(words)) if words else 0,
                    "checks_performed": [
                        "blocked_patterns",
                        "sensitive_info",
                        "malicious_indicators",
                        "content_length",
                        "repetition",
                    ],
                },
            )

        except Exception as e:
            logger.error(f"Error in content safety check: {e}", exc_info=True)
            return SafetyCheckResult(
                is_safe=False,
                risk_score=10.0,
                blocked_content=["Safety check error"],
                details={"error": str(e)},
            )

    async def _check_authorization(self, request: AgentTask) -> AuthorizationResult:
        """Check user authorization for request."""
        try:
            # Get user permissions from context
            user_permissions = request.context.get("user_permissions", [])
            user_roles = request.context.get("user_roles", ["user"])
            tenant_id = request.context.get("tenant_id", "default")

            # Get required permissions for task type
            required_permissions = self.permission_requirements.get(
                request.task_type, ["read"]
            )

            # Check role-based access
            role_permissions = self._get_role_permissions(user_roles)
            effective_permissions = list(set(user_permissions + role_permissions))

            # Check if user has required permissions
            granted_permissions = []
            denied_permissions = []

            for permission in required_permissions:
                if permission in effective_permissions:
                    granted_permissions.append(permission)
                else:
                    denied_permissions.append(permission)

            # Special checks for sensitive operations
            if request.task_type in ["code_refactor", "code_audit", "system_admin"]:
                if "admin" not in user_roles and "developer" not in user_roles:
                    return AuthorizationResult(
                        authorized=False,
                        denied_permissions=required_permissions,
                        reason="Insufficient privileges for sensitive operation",
                    )

            # Check tenant access
            if tenant_id != "default" and "tenant_access" not in effective_permissions:
                return AuthorizationResult(
                    authorized=False,
                    denied_permissions=["tenant_access"],
                    reason="No tenant access permissions",
                )

            # Determine if authorized
            authorized = len(denied_permissions) == 0

            return AuthorizationResult(
                authorized=authorized,
                granted_permissions=granted_permissions,
                denied_permissions=denied_permissions,
                reason=None
                if authorized
                else f"Missing required permissions: {', '.join(denied_permissions)}",
            )

        except Exception as e:
            logger.error(f"Error in authorization check: {e}", exc_info=True)
            return AuthorizationResult(
                authorized=False,
                denied_permissions=["authorization_check"],
                reason=f"Authorization check error: {str(e)}",
            )

    def _calculate_overall_risk(
        self, safety_check: SafetyCheckResult, authorization_check: AuthorizationResult
    ) -> float:
        """Calculate overall risk score from safety and authorization checks."""
        # Start with safety risk score
        overall_risk = safety_check.risk_score

        # Add authorization risk if not authorized
        if not authorization_check.authorized:
            overall_risk += 3.0

        # Add risk for denied sensitive permissions
        sensitive_permissions = [
            "admin",
            "tenant_access",
            "system_modify",
            "user_delete",
        ]
        for permission in authorization_check.denied_permissions:
            if permission in sensitive_permissions:
                overall_risk += 2.0

        # Cap at maximum
        return min(10.0, overall_risk)

    def _get_role_permissions(self, roles: List[str]) -> List[str]:
        """Get permissions associated with user roles."""
        role_permissions_map = {
            "admin": [
                "read",
                "write",
                "delete",
                "admin",
                "tenant_access",
                "system_modify",
                "user_delete",
            ],
            "developer": ["read", "write", "code_execute", "debug"],
            "moderator": ["read", "write", "content_moderate"],
            "user": ["read", "write"],
            "guest": ["read"],
        }

        permissions = []
        for role in roles:
            permissions.extend(role_permissions_map.get(role, []))

        return list(set(permissions))  # Remove duplicates

    def _initialize_content_filters(self) -> Dict[str, Any]:
        """Initialize content filtering configuration."""
        return {
            "enabled": True,
            "strict_mode": False,
            "custom_patterns": [],
            "allowed_languages": ["en", "es", "fr", "de", "it", "pt", "zh"],
            "blocked_languages": [],
            "min_confidence_threshold": 0.7,
        }

    def _initialize_permission_requirements(self) -> Dict[str, List[str]]:
        """Initialize permission requirements for task types."""
        return {
            "conversation": ["read"],
            "text_transform": ["read", "write"],
            "code_generation": ["read", "write", "code_execute"],
            "code_refactor": ["read", "write", "code_execute", "admin"],
            "code_audit": ["read", "code_execute", "admin"],
            "research": ["read", "research"],
            "analysis": ["read", "analyze"],
            "documentation": ["read", "write"],
            "debugging": ["read", "debug"],
            "custom": ["read", "write"],
        }

    def _initialize_rate_limits(self) -> Dict[str, Any]:
        """Initialize rate limiting configuration."""
        return {
            "max_content_length": 10000,
            "max_requests_per_minute": 60,
            "max_requests_per_hour": 1000,
            "max_tasks_per_session": 50,
            "max_concurrent_tasks": 5,
        }

    def _initialize_blocked_patterns(self) -> Dict[str, str]:
        """Initialize blocked content patterns."""
        return {
            "hate_speech": r"\b(hate|racist|sexist|homophobic|transphobic)\b",
            "violence": r"\b(kill|murder|violence|attack|harm|destroy)\b",
            "adult_content": r"\b(porn|adult|sex|nude|explicit)\b",
            "illegal_activities": r"\b(drug|illegal|hack|crack|steal|terror)\b",
            "personal_info": r"\b(ssn|social security|credit card|bank account)\b",
            "spam": r"\b(spam|scam|phishing|malware)\b",
        }

    def update_configuration(self, config: Dict[str, Any]) -> bool:
        """
        Update safety middleware configuration.

        Args:
            config: Configuration updates

        Returns:
            True if updated successfully, False otherwise
        """
        try:
            # Update content filters
            if "content_filters" in config:
                self.content_filters.update(config["content_filters"])

            # Update permission requirements
            if "permission_requirements" in config:
                self.permission_requirements.update(config["permission_requirements"])

            # Update rate limits
            if "rate_limits" in config:
                self.rate_limits.update(config["rate_limits"])

            # Update blocked patterns
            if "blocked_patterns" in config:
                self.blocked_patterns.update(config["blocked_patterns"])

            logger.info("Safety middleware configuration updated")
            return True

        except Exception as e:
            logger.error(f"Error updating safety configuration: {e}", exc_info=True)
            return False

    def get_validation_statistics(self) -> Dict[str, Any]:
        """Get safety validation statistics."""
        total = self.validation_stats["total_requests"]
        if total == 0:
            return {
                **self.validation_stats,
                "blocked_percentage": 0,
                "warning_percentage": 0,
                "allowed_percentage": 0,
            }

        return {
            **self.validation_stats,
            "blocked_percentage": (self.validation_stats["blocked_requests"] / total)
            * 100,
            "warning_percentage": (self.validation_stats["warning_requests"] / total)
            * 100,
            "allowed_percentage": (self.validation_stats["allowed_requests"] / total)
            * 100,
        }

    def reset_statistics(self) -> None:
        """Reset validation statistics."""
        self.validation_stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "warning_requests": 0,
            "allowed_requests": 0,
        }
        logger.info("Safety validation statistics reset")

    async def check_rate_limit(
        self, user_id: Optional[str], tenant_id: Optional[str]
    ) -> bool:
        """
        Check if user/tenant has exceeded rate limits.

        Args:
            user_id: User ID to check
            tenant_id: Tenant ID to check

        Returns:
            True if within limits, False if exceeded
        """
        # In real implementation, this would check against actual usage data
        # For now, always return True (within limits)
        return True

    def create_error_response(
        self, request: AgentRequest, validation_result: SafetyValidationResult
    ) -> AgentUIServiceError:
        """
        Create standardized error response for failed validation.

        Args:
            request: Original request
            validation_result: Validation result

        Returns:
            AgentUIServiceError with error details
        """
        error_code = "SAFETY_VALIDATION_FAILED"
        error_message = "Request failed safety validation"

        if validation_result.requires_moderation:
            error_code = "CONTENT_REQUIRES_MODERATION"
            error_message = "Content requires moderation before processing"
        elif not validation_result.can_proceed:
            error_code = "REQUEST_BLOCKED"
            error_message = "Request blocked due to safety concerns"

        # Build details
        details = {
            "validation_result": validation_result.to_dict(),
            "task_type": request.task_type,
            "risk_score": validation_result.overall_risk_score,
        }

        # Add specific reasons
        if validation_result.safety_check:
            details["safety_issues"] = validation_result.safety_check.blocked_content
            details["safety_warnings"] = validation_result.safety_check.warnings

        if validation_result.authorization_check:
            details["auth_issues"] = (
                validation_result.authorization_check.denied_permissions
            )
            details["auth_reason"] = validation_result.authorization_check.reason

        return AgentUIServiceError(
            error_code=error_code,
            error_message=error_message,
            details=details,
            request_id=request.task_id,
            retry_suggested=validation_result.overall_risk_score < 5.0,
            retry_after_seconds=300 if validation_result.requires_moderation else 60,
        )


# Alias for backward-compatibility
SafetyMiddleware = CopilotSafetyMiddleware
