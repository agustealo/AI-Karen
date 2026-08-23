"""
Error Response Service

Deterministic rule-based error classification and user-friendly response
generation for the AI Karen system.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field

from ai_karen_engine.services.error_response_schemas import WebAPIErrorCode
from ai_karen_engine.core.model_runtime.provider_health_monitor import (
    get_health_monitor,
    ProviderHealthInfo,
    HealthStatus,
)
from ai_karen_engine.core.model_runtime.provider_registry_service import (
    get_provider_registry_service,
)
from ai_karen_engine.services.cache import get_response_cache
from ai_karen_engine.services.audit.audit_logging import get_audit_logger

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Categories for error classification"""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    API_KEY_MISSING = "api_key_missing"
    API_KEY_INVALID = "api_key_invalid"
    RATE_LIMIT = "rate_limit"
    PROVIDER_DOWN = "provider_down"
    NETWORK_ERROR = "network_error"
    VALIDATION_ERROR = "validation_error"
    DATABASE_ERROR = "database_error"
    SYSTEM_ERROR = "system_error"
    UNKNOWN = "unknown"


class ErrorSeverity(str, Enum):
    """Error severity levels"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ErrorContext:
    """Context information for error analysis"""

    error_message: str
    error_type: Optional[str] = None
    status_code: Optional[int] = None
    provider_name: Optional[str] = None
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    request_path: Optional[str] = None
    timestamp: Optional[datetime] = None
    additional_data: Optional[Dict[str, Any]] = None


class IntelligentErrorResponse(BaseModel):
    """Intelligent error response model"""

    title: str = Field(..., description="Brief, user-friendly error title")
    summary: str = Field(..., description="Clear explanation of what went wrong")
    category: ErrorCategory = Field(
        ..., description="Error category for classification"
    )
    severity: ErrorSeverity = Field(..., description="Error severity level")
    next_steps: List[str] = Field(
        ..., description="Actionable steps to resolve the issue"
    )
    provider_health: Optional[Dict[str, Any]] = Field(
        None, description="Current provider health status"
    )
    contact_admin: bool = Field(False, description="Whether user should contact admin")
    retry_after: Optional[int] = Field(
        None, description="Seconds to wait before retrying"
    )
    help_url: Optional[str] = Field(None, description="URL to relevant documentation")
    technical_details: Optional[str] = Field(
        None, description="Technical details for debugging"
    )


class ErrorClassificationRule:
    """Rule for classifying errors"""

    def __init__(
        self,
        name: str,
        patterns: List[str],
        category: ErrorCategory,
        severity: ErrorSeverity,
        title_template: str,
        summary_template: str,
        next_steps: List[str],
        contact_admin: bool = False,
        retry_after: Optional[int] = None,
        help_url: Optional[str] = None,
    ):
        self.name = name
        self.patterns = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        self.category = category
        self.severity = severity
        self.title_template = title_template
        self.summary_template = summary_template
        self.next_steps = next_steps
        self.contact_admin = contact_admin
        self.retry_after = retry_after
        self.help_url = help_url

    def matches(self, error_message: str, error_type: Optional[str] = None) -> bool:
        """Check if this rule matches the given error"""
        text_to_check = f"{error_message} {error_type or ''}"
        return any(pattern.search(text_to_check) for pattern in self.patterns)

    def format_response(self, context: ErrorContext) -> Dict[str, Any]:
        """Format the response using context data"""
        return {
            "title": self._format_template(self.title_template, context),
            "summary": self._format_template(self.summary_template, context),
            "category": self.category,
            "severity": self.severity,
            "next_steps": [
                self._format_template(step, context) for step in self.next_steps
            ],
            "contact_admin": self.contact_admin,
            "retry_after": self.retry_after,
            "help_url": self.help_url,
        }

    def _format_template(self, template: str, context: ErrorContext) -> str:
        """Format template string with context data"""
        replacements = {
            "{provider}": context.provider_name or "the provider",
            "{error_type}": context.error_type or "error",
            "{status_code}": str(context.status_code)
            if context.status_code
            else "unknown",
        }

        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)

        return result


class ErrorResponseService:
    """Service for generating error responses using rule-based classification"""

    def __init__(self):
        self.classification_rules = self._initialize_classification_rules()
        self._provider_health_cache: Dict[str, ProviderHealthInfo] = {}
        self._cache_ttl = 300  # 5 minutes
        self._response_cache = get_response_cache()
        self.logger = logging.getLogger(__name__)
        self._audit_logger = get_audit_logger()

    def analyze_error(
        self,
        error_message: str,
        error_type: Optional[str] = None,
        status_code: Optional[int] = None,
        provider_name: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None,
        use_ai_analysis: bool = True,
    ) -> IntelligentErrorResponse:
        """
        Analyze an error and generate a response with caching

        Args:
            error_message: The error message to analyze
            error_type: Optional error type/class name
            status_code: Optional HTTP status code
            provider_name: Optional provider name that caused the error
            additional_context: Optional additional context data
            use_ai_analysis: Ignored (AI analysis was retired)

        Returns:
            IntelligentErrorResponse with analysis and guidance
        """
        # Check cache first for common error patterns
        cached_response = self._response_cache.get_cached_response(
            error_message, error_type, provider_name
        )
        if cached_response:
            logger.debug("Serving cached error response")

            # Audit log cache hit
            self._audit_logger.log_response_cache_event(
                cache_hit=True,
                error_category=cached_response.get("category"),
                additional_context=additional_context,
            )

            return IntelligentErrorResponse(**cached_response)

        context = ErrorContext(
            error_message=error_message,
            error_type=error_type,
            status_code=status_code,
            provider_name=provider_name,
            timestamp=datetime.utcnow(),
            additional_data=additional_context,
        )

        # Try to classify the error using rules
        for rule in self.classification_rules:
            if rule.matches(error_message, error_type):
                logger.info(f"Error classified as: {rule.name}")
                response_data = rule.format_response(context)

                # Add provider health information if available
                if provider_name:
                    provider_health = self._get_provider_health(provider_name)
                    if provider_health:
                        response_data["provider_health"] = {
                            "name": provider_health.name,
                            "status": provider_health.status.value,
                            "success_rate": provider_health.success_rate,
                            "response_time": provider_health.response_time,
                            "error_message": provider_health.error_message,
                            "last_check": provider_health.last_check.isoformat()
                            if provider_health.last_check
                            else None,
                        }

                        # Add alternative provider suggestions if current provider is unhealthy
                        if provider_health.status in [
                            HealthStatus.DEGRADED,
                            HealthStatus.UNHEALTHY,
                        ]:
                            health_monitor = get_health_monitor()
                            alternatives = get_provider_registry_service().get_provider_recommendations(
                                provider_name
                            ).get("alternatives", [])
                            if alternatives:
                                response_data["next_steps"].append(
                                    f"Try using {alternatives[0]} as an alternative provider"
                                )

                response = IntelligentErrorResponse(**response_data)

                # Audit log rule-based response
                self._audit_logger.log_error_response_generated(
                    error_category=response.category.value,
                    error_severity=response.severity.value,
                    provider_name=provider_name,
                    ai_analysis_used=False,
                    response_cached=True,
                    user_id=additional_context.get("user_id")
                    if additional_context
                    else None,
                    tenant_id=additional_context.get("tenant_id")
                    if additional_context
                    else None,
                    correlation_id=additional_context.get("correlation_id")
                    if additional_context
                    else None,
                )

                # Cache rule-based response
                self._cache_response_if_cacheable(
                    response, error_message, error_type, provider_name
                )
                return response

        # Fallback for unclassified errors using local classification
        logger.info(f"Using rule-based fallback for error: {error_message}")
        fallback_response = self._create_fallback_response(context)

        # Audit log fallback response
        self._audit_logger.log_error_response_generated(
            error_category=fallback_response.category.value,
            error_severity=fallback_response.severity.value,
            provider_name=provider_name,
            ai_analysis_used=False,
            response_cached=False,
            user_id=additional_context.get("user_id") if additional_context else None,
            tenant_id=additional_context.get("tenant_id")
            if additional_context
            else None,
            correlation_id=additional_context.get("correlation_id")
            if additional_context
            else None,
        )

        # Cache fallback responses only if they're category-specific (not UNKNOWN)
        if fallback_response.category != ErrorCategory.UNKNOWN:
            self._cache_response_if_cacheable(
                fallback_response, error_message, error_type, provider_name
            )

        return fallback_response

    def get_fallback_response(self, category: ErrorCategory) -> Dict[str, Any]:
        """Get a rule-based fallback response for a specific error category"""
        fallback_responses = {
            ErrorCategory.AUTHENTICATION: {
                "title": "Authentication Required",
                "summary": "You need to log in to access this feature.",
                "next_steps": [
                    "Click the login button to sign in",
                    "Check your credentials if login fails",
                    "Contact admin if you continue having issues",
                ],
                "severity": ErrorSeverity.MEDIUM,
                "contact_admin": False,
            },
            ErrorCategory.AUTHORIZATION: {
                "title": "Access Denied",
                "summary": "You don't have permission to perform this action.",
                "next_steps": [
                    "Contact your administrator for access",
                    "Verify you're using the correct account",
                    "Check if your permissions have changed",
                ],
                "severity": ErrorSeverity.MEDIUM,
                "contact_admin": True,
            },
            ErrorCategory.API_KEY_MISSING: {
                "title": "API Configuration Missing",
                "summary": "Required API keys are not configured.",
                "next_steps": [
                    "Add the required API keys to your .env file",
                    "Restart the application after adding keys",
                    "Contact admin for configuration assistance",
                ],
                "severity": ErrorSeverity.HIGH,
                "contact_admin": True,
            },
            ErrorCategory.API_KEY_INVALID: {
                "title": "Invalid API Configuration",
                "summary": "The configured API keys appear to be invalid.",
                "next_steps": [
                    "Verify your API keys are correct",
                    "Check if your API keys have expired",
                    "Generate new API keys if needed",
                ],
                "severity": ErrorSeverity.HIGH,
                "contact_admin": False,
            },
            ErrorCategory.RATE_LIMIT: {
                "title": "Rate Limit Exceeded",
                "summary": "You've made too many requests. Please wait before trying again.",
                "next_steps": [
                    "Wait a few minutes before retrying",
                    "Reduce the frequency of your requests",
                    "Contact admin if limits seem too restrictive",
                ],
                "severity": ErrorSeverity.MEDIUM,
                "contact_admin": False,
                "retry_after": 300,
            },
            ErrorCategory.PROVIDER_DOWN: {
                "title": "Service Temporarily Unavailable",
                "summary": "The requested service is currently unavailable.",
                "next_steps": [
                    "Try again in a few minutes",
                    "Check service status pages for updates",
                    "Use alternative features if available",
                ],
                "severity": ErrorSeverity.HIGH,
                "contact_admin": False,
                "retry_after": 180,
            },
            ErrorCategory.NETWORK_ERROR: {
                "title": "Connection Problem",
                "summary": "There was a problem connecting to the service.",
                "next_steps": [
                    "Check your internet connection",
                    "Try refreshing the page",
                    "Contact admin if problems persist",
                ],
                "severity": ErrorSeverity.MEDIUM,
                "contact_admin": False,
                "retry_after": 60,
            },
            ErrorCategory.VALIDATION_ERROR: {
                "title": "Invalid Input",
                "summary": "The information provided is not valid.",
                "next_steps": [
                    "Check that all required fields are filled",
                    "Verify the format of your input",
                    "Try again with corrected information",
                ],
                "severity": ErrorSeverity.LOW,
                "contact_admin": False,
            },
            ErrorCategory.DATABASE_ERROR: {
                "title": "Database Error",
                "summary": "There was a problem with the database.",
                "next_steps": [
                    "Contact admin immediately",
                    "Try again later",
                    "Check if the system is under maintenance",
                ],
                "severity": ErrorSeverity.CRITICAL,
                "contact_admin": True,
            },
            ErrorCategory.SYSTEM_ERROR: {
                "title": "System Error",
                "summary": "An internal system error occurred.",
                "next_steps": [
                    "Try refreshing the page",
                    "Contact admin if the problem persists",
                    "Check system status for known issues",
                ],
                "severity": ErrorSeverity.HIGH,
                "contact_admin": True,
            },
        }

        return fallback_responses.get(
            category,
            {
                "title": "Unexpected Error",
                "summary": "An unexpected error occurred.",
                "next_steps": [
                    "Try refreshing the page",
                    "Contact admin if the problem persists",
                ],
                "severity": ErrorSeverity.MEDIUM,
                "contact_admin": True,
            },
        )

    def classify_error_locally(
        self, error_message: str, error_type: Optional[str] = None
    ) -> ErrorCategory:
        """Classify error using local rules without external dependencies"""
        # Use existing classification rules to determine category
        for rule in self.classification_rules:
            if rule.matches(error_message, error_type):
                return rule.category

        # Additional heuristic classification for common patterns
        error_text = f"{error_message} {error_type or ''}".lower()

        # Authentication patterns
        if any(
            pattern in error_text
            for pattern in ["auth", "login", "token", "session", "unauthorized", "401"]
        ):
            return ErrorCategory.AUTHENTICATION

        # API key patterns
        if any(
            pattern in error_text
            for pattern in ["api key", "api_key", "openai_api_key", "anthropic_api_key"]
        ):
            if (
                "missing" in error_text
                or "not found" in error_text
                or "not set" in error_text
            ):
                return ErrorCategory.API_KEY_MISSING
            elif "invalid" in error_text or "incorrect" in error_text:
                return ErrorCategory.API_KEY_INVALID

        # Rate limiting patterns
        if any(
            pattern in error_text
            for pattern in ["rate limit", "too many requests", "quota", "429"]
        ):
            return ErrorCategory.RATE_LIMIT

        # Provider/service patterns
        if any(
            pattern in error_text
            for pattern in [
                "service unavailable",
                "provider",
                "connection refused",
                "503",
            ]
        ):
            return ErrorCategory.PROVIDER_DOWN

        # Network patterns
        if any(
            pattern in error_text
            for pattern in ["timeout", "network", "connection", "504"]
        ):
            return ErrorCategory.NETWORK_ERROR

        # Database patterns
        if any(
            pattern in error_text
            for pattern in ["database", "db", "sql", "relation", "table"]
        ):
            return ErrorCategory.DATABASE_ERROR

        # Validation patterns
        if any(
            pattern in error_text
            for pattern in ["validation", "invalid", "required", "missing field", "400"]
        ):
            return ErrorCategory.VALIDATION_ERROR

        # Default to unknown
        return ErrorCategory.UNKNOWN

    def _create_fallback_response(
        self, context: ErrorContext
    ) -> IntelligentErrorResponse:
        """Create a fallback response for unclassified errors using local classification"""
        # Try to classify the error locally first
        category = self.classify_error_locally(
            context.error_message, context.error_type
        )

        # Get fallback response for the category
        fallback_data = self.get_fallback_response(category)

        response_data = {
            "title": fallback_data["title"],
            "summary": fallback_data["summary"],
            "category": category,
            "severity": fallback_data["severity"],
            "next_steps": fallback_data["next_steps"],
            "contact_admin": fallback_data.get("contact_admin", False),
            "retry_after": fallback_data.get("retry_after"),
            "help_url": fallback_data.get("help_url"),
            "technical_details": f"Error: {context.error_message}",
        }

        # Add provider health information if available
        if context.provider_name:
            provider_health = self._get_provider_health(context.provider_name)
            if provider_health:
                response_data["provider_health"] = {
                    "name": provider_health.name,
                    "status": provider_health.status.value,
                    "success_rate": provider_health.success_rate,
                    "response_time": provider_health.response_time,
                    "error_message": provider_health.error_message,
                    "last_check": provider_health.last_check.isoformat()
                    if provider_health.last_check
                    else None,
                }

                # Add alternative provider suggestions if current provider is unhealthy
                if provider_health.status in [
                    HealthStatus.DEGRADED,
                    HealthStatus.UNHEALTHY,
                ]:
                    registry = get_provider_registry_service()
                    alternatives = registry.get_provider_recommendations(
                        context.provider_name
                    ).get("alternatives", [])
                    if alternatives:
                        response_data["next_steps"].append(
                            f"Try using {alternatives[0]} as an alternative provider"
                        )

        return IntelligentErrorResponse(**response_data)

    def _get_provider_health(self, provider_name: str) -> Optional[ProviderHealthInfo]:
        """Get cached provider health status"""
        health_monitor = get_health_monitor()
        return health_monitor.get_provider_health(provider_name)

    def _cache_response_if_cacheable(
        self,
        response: IntelligentErrorResponse,
        error_message: str,
        error_type: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> None:
        """Cache response if it's a cacheable error type to prevent repeated failures"""
        # Cache responses for stable error categories
        cacheable_categories = [
            ErrorCategory.API_KEY_MISSING,
            ErrorCategory.API_KEY_INVALID,
            ErrorCategory.AUTHENTICATION,
            ErrorCategory.AUTHORIZATION,
            ErrorCategory.VALIDATION_ERROR,
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.DATABASE_ERROR,
            ErrorCategory.SYSTEM_ERROR,
        ]

        if response.category in cacheable_categories:
            response_dict = {
                "title": response.title,
                "summary": response.summary,
                "category": response.category,
                "severity": response.severity,
                "next_steps": response.next_steps,
                "provider_health": response.provider_health,
                "contact_admin": response.contact_admin,
                "retry_after": response.retry_after,
                "help_url": response.help_url,
                "technical_details": response.technical_details,
            }

            # Set cache TTL based on error category
            cache_ttl = self._get_cache_ttl_for_category(response.category)

            self._response_cache.cache_response(
                error_message,
                response_dict,
                error_type,
                provider_name,
                custom_ttl=cache_ttl,
            )
            logger.debug(
                f"Cached response for error category: {response.category} (TTL: {cache_ttl}s)"
            )

            # Audit log response caching
            self._audit_logger.log_response_cache_event(
                cache_hit=False, error_category=response.category.value
            )

    def _get_cache_ttl_for_category(self, category: ErrorCategory) -> int:
        """Get appropriate cache TTL based on error category"""
        # Different categories have different cache durations
        cache_ttls = {
            ErrorCategory.API_KEY_MISSING: 3600,  # 1 hour - stable until config changes
            ErrorCategory.API_KEY_INVALID: 1800,  # 30 minutes - may be fixed quickly
            ErrorCategory.AUTHENTICATION: 300,  # 5 minutes - session issues change frequently
            ErrorCategory.AUTHORIZATION: 1800,  # 30 minutes - permissions change less frequently
            ErrorCategory.VALIDATION_ERROR: 600,  # 10 minutes - input validation is stable
            ErrorCategory.RATE_LIMIT: 900,  # 15 minutes - rate limits reset periodically
            ErrorCategory.DATABASE_ERROR: 180,  # 3 minutes - database issues may be transient
            ErrorCategory.SYSTEM_ERROR: 300,  # 5 minutes - system errors may be transient
            ErrorCategory.PROVIDER_DOWN: 120,  # 2 minutes - provider status changes quickly
            ErrorCategory.NETWORK_ERROR: 60,  # 1 minute - network issues are often transient
        }

        return cache_ttls.get(category, self._cache_ttl)  # Default to 5 minutes

    def _initialize_classification_rules(self) -> List[ErrorClassificationRule]:
        """Initialize error classification rules"""
        return [
            # Authentication errors
            ErrorClassificationRule(
                name="session_expired",
                patterns=[
                    r"token.*expired",
                    r"session.*expired",
                    r"authentication.*expired",
                ],
                category=ErrorCategory.AUTHENTICATION,
                severity=ErrorSeverity.MEDIUM,
                title_template="Session Expired",
                summary_template="Your session has expired and you need to log in again.",
                next_steps=[
                    "Click the login button to sign in again",
                    "Your work will be saved automatically",
                ],
            ),
            ErrorClassificationRule(
                name="invalid_credentials",
                patterns=[
                    r"invalid.*credentials",
                    r"authentication.*failed",
                    r"login.*failed",
                    r"unauthorized",
                ],
                category=ErrorCategory.AUTHENTICATION,
                severity=ErrorSeverity.MEDIUM,
                title_template="Login Failed",
                summary_template="The email or password you entered is incorrect.",
                next_steps=[
                    "Double-check your email address and password",
                    "Use the 'Forgot Password' link if needed",
                    "Contact admin if you continue having issues",
                ],
            ),
            # API Key errors
            ErrorClassificationRule(
                name="openai_api_key_missing",
                patterns=[
                    r"openai.*api.*key.*not.*found",
                    r"openai.*api.*key.*missing",
                    r"OPENAI_API_KEY.*not.*set",
                ],
                category=ErrorCategory.API_KEY_MISSING,
                severity=ErrorSeverity.HIGH,
                title_template="OpenAI API Key Missing",
                summary_template="The OpenAI API key is not configured in your environment.",
                next_steps=[
                    "Add OPENAI_API_KEY to your .env file",
                    "Get your API key from https://platform.openai.com/api-keys",
                    "Restart the application after adding the key",
                ],
                help_url="https://platform.openai.com/docs/quickstart",
            ),
            ErrorClassificationRule(
                name="anthropic_api_key_missing",
                patterns=[
                    r"anthropic.*api.*key.*not.*found",
                    r"anthropic.*api.*key.*missing",
                    r"ANTHROPIC_API_KEY.*not.*set",
                ],
                category=ErrorCategory.API_KEY_MISSING,
                severity=ErrorSeverity.HIGH,
                title_template="Anthropic API Key Missing",
                summary_template="The Anthropic API key is not configured in your environment.",
                next_steps=[
                    "Add ANTHROPIC_API_KEY to your .env file",
                    "Get your API key from https://console.anthropic.com/",
                    "Restart the application after adding the key",
                ],
                help_url="https://console.anthropic.com/docs/quickstart",
            ),
            ErrorClassificationRule(
                name="api_key_invalid",
                patterns=[
                    r"invalid.*api.*key",
                    r"api.*key.*invalid",
                    r"incorrect.*api.*key",
                ],
                category=ErrorCategory.API_KEY_INVALID,
                severity=ErrorSeverity.HIGH,
                title_template="Invalid API Key",
                summary_template="The configured API key is invalid or has expired.",
                next_steps=[
                    "Verify your API key is correct",
                    "Check if your API key has expired",
                    "Generate a new API key if needed",
                ],
            ),
            # Rate limiting
            ErrorClassificationRule(
                name="rate_limit_exceeded",
                patterns=[
                    r"rate.*limit",
                    r"too.*many.*requests",
                    r"429",
                ],
                category=ErrorCategory.RATE_LIMIT,
                severity=ErrorSeverity.MEDIUM,
                title_template="Rate Limit Reached",
                summary_template="You've made too many requests. Please wait before trying again.",
                next_steps=[
                    "Wait a few minutes before retrying",
                    "Reduce the frequency of your requests",
                ],
                retry_after=300,
            ),
            # Provider errors
            ErrorClassificationRule(
                name="provider_unavailable",
                patterns=[
                    r"service.*unavailable",
                    r"provider.*unavailable",
                    r"503",
                ],
                category=ErrorCategory.PROVIDER_DOWN,
                severity=ErrorSeverity.HIGH,
                title_template="Service Unavailable",
                summary_template="{provider} is currently unavailable.",
                next_steps=[
                    "Try again in a few minutes",
                    "Check the provider's status page",
                ],
                retry_after=180,
            ),
            # Network errors
            ErrorClassificationRule(
                name="network_timeout",
                patterns=[
                    r"timeout",
                    r"connection.*timed.*out",
                    r"request.*timed.*out",
                ],
                category=ErrorCategory.NETWORK_ERROR,
                severity=ErrorSeverity.MEDIUM,
                title_template="Connection Timeout",
                summary_template="The request timed out while connecting to {provider}.",
                next_steps=[
                    "Check your internet connection",
                    "Try again in a moment",
                ],
                retry_after=60,
            ),
            # Database errors
            ErrorClassificationRule(
                name="database_connection",
                patterns=[
                    r"database.*connection",
                    r"db.*connection.*failed",
                    r"could.*not.*connect.*to.*database",
                ],
                category=ErrorCategory.DATABASE_ERROR,
                severity=ErrorSeverity.CRITICAL,
                title_template="Database Connection Error",
                summary_template="Could not connect to the database.",
                next_steps=[
                    "Contact admin immediately",
                    "Check if the database service is running",
                ],
                contact_admin=True,
            ),
            # Validation errors
            ErrorClassificationRule(
                name="validation_error",
                patterns=[
                    r"validation.*error",
                    r"invalid.*input",
                    r"required.*field",
                    r"400",
                ],
                category=ErrorCategory.VALIDATION_ERROR,
                severity=ErrorSeverity.LOW,
                title_template="Invalid Input",
                summary_template="The information provided is not valid.",
                next_steps=[
                    "Check that all required fields are filled",
                    "Verify the format of your input",
                ],
            ),
        ]

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error classification statistics"""
        return {
            "total_rules": len(self.classification_rules),
            "categories": [category.value for category in ErrorCategory],
            "cache_size": len(self._provider_health_cache),
        }

    def add_classification_rule(self, rule: ErrorClassificationRule) -> None:
        """Add a new classification rule"""
        self.classification_rules.append(rule)
        logger.info(f"Added new classification rule: {rule.name}")

    def remove_classification_rule(self, rule_name: str) -> bool:
        """Remove a classification rule by name"""
        initial_count = len(self.classification_rules)
        self.classification_rules = [
            rule for rule in self.classification_rules if rule.name != rule_name
        ]
        removed = len(self.classification_rules) < initial_count
        if removed:
            logger.info(f"Removed classification rule: {rule_name}")
        return removed

    def validate_response_quality(self, response: IntelligentErrorResponse) -> bool:
        """Validate that an error response meets quality standards"""
        try:
            # Check title quality
            if not response.title or len(response.title.strip()) < 5:
                return False

            # Check summary quality
            if not response.summary or len(response.summary.strip()) < 10:
                return False

            # Check next steps quality
            if not response.next_steps or len(response.next_steps) == 0:
                return False

            # Ensure next steps are actionable (contain action words)
            action_words = [
                "add",
                "check",
                "verify",
                "try",
                "contact",
                "update",
                "restart",
                "wait",
                "use",
                "configure",
                "click",
            ]
            actionable_steps = 0
            for step in response.next_steps:
                if any(word in step.lower() for word in action_words):
                    actionable_steps += 1

            if actionable_steps == 0:
                return False

            # Check for appropriate severity assignment
            critical_keywords = [
                "database",
                "connection",
                "failed",
                "unavailable",
                "critical",
            ]
            high_keywords = ["api", "key", "missing", "invalid", "unauthorized"]

            if response.severity == ErrorSeverity.CRITICAL:
                if not any(
                    keyword in response.summary.lower() for keyword in critical_keywords
                ):
                    return False

            # Ensure contact_admin is set appropriately
            if (
                response.category in [ErrorCategory.DATABASE_ERROR]
                and not response.contact_admin
            ):
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error validating response quality: {e}")
            return False

    def get_provider_fallback_suggestions(self, failed_provider: str) -> List[str]:
        """Get suggestions for alternative providers when one fails"""
        try:
            registry = get_provider_registry_service()
            alternatives = registry.get_provider_recommendations(failed_provider).get("alternatives", [])
            return alternatives[:3]  # Return top 3 alternatives
        except Exception as e:
            self.logger.warning(f"Failed to get provider alternatives: {e}")
            return []


# Utility functions for response formatting
def format_error_for_user(response: IntelligentErrorResponse) -> Dict[str, Any]:
    """Format an intelligent error response for user consumption"""
    return {
        "title": response.title,
        "message": response.summary,
        "severity": response.severity.value,
        "next_steps": response.next_steps,
        "contact_admin": response.contact_admin,
        "retry_after": response.retry_after,
        "help_url": response.help_url,
    }


def format_error_for_api(response: IntelligentErrorResponse) -> Dict[str, Any]:
    """Format an intelligent error response for API consumption"""
    return {
        "error": response.title,
        "message": response.summary,
        "category": response.category.value,
        "severity": response.severity.value,
        "next_steps": response.next_steps,
        "provider_health": response.provider_health,
        "contact_admin": response.contact_admin,
        "retry_after": response.retry_after,
        "help_url": response.help_url,
        "technical_details": response.technical_details,
    }
