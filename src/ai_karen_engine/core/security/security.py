"""
Security utilities for the AI-Karen production chat system.
Provides input validation, sanitization, encryption, and security monitoring.
"""

import base64
import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import bleach
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ai_karen_engine.auth.auth_middleware import get_current_user as _get_current_user

logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """Security levels for content validation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    STRICT = "strict"


class ThreatLevel(Enum):
    """Threat levels for security events."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityEvent:
    """Security event data structure."""

    timestamp: datetime
    event_type: str
    threat_level: ThreatLevel
    user_id: str | None
    conversation_id: str | None
    client_ip: str | None
    metadata: dict[str, Any]
    session_id: str | None = None
    user_agent: str | None = None


class SecurityValidator:
    """Input validation and sanitization utilities."""

    # Content patterns
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    PHONE_PATTERN = re.compile(r"^\+?1?\d{9,15}$")
    URL_PATTERN = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
    HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

    # Security patterns
    MALICIOUS_PATTERN = re.compile(
        r"(?:script|javascript|eval|iframe|object|embed|style)", re.IGNORECASE
    )
    INJECTION_PATTERN = re.compile(
        r"(?:(?:union\s+select|drop\s+table|insert\s+into|delete\s+from).*)",
        re.IGNORECASE,
    )

    # Allowed HTML tags and attributes
    ALLOWED_TAGS = [
        "p",
        "br",
        "strong",
        "em",
        "u",
        "ol",
        "ul",
        "li",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "code",
        "pre",
        "a",
    ]

    ALLOWED_ATTRIBUTES = {"a": ["href", "title"], "code": ["class"], "pre": ["class"]}

    @classmethod
    def sanitize_html(
        cls, content: str, security_level: SecurityLevel = SecurityLevel.MEDIUM
    ) -> str:
        """Sanitize HTML content based on security level."""
        if security_level == SecurityLevel.STRICT:
            # Remove all HTML tags
            return cls.HTML_TAG_PATTERN.sub("", content)
        elif security_level == SecurityLevel.HIGH:
            # Only allow safe HTML tags
            return bleach.clean(
                content,
                tags=cls.ALLOWED_TAGS,
                attributes=cls.ALLOWED_ATTRIBUTES,
                strip=True,
            )
        elif security_level == SecurityLevel.MEDIUM:
            # Allow more tags but still sanitize
            extended_tags = cls.ALLOWED_TAGS + ["div", "span", "img"]
            extended_attrs = cls.ALLOWED_ATTRIBUTES.copy()
            extended_attrs.update(
                {"img": ["src", "alt", "title"], "div": ["class"], "span": ["class"]}
            )
            return bleach.clean(
                content, tags=extended_tags, attributes=extended_attrs, strip=True
            )
        else:
            # Low security level - minimal sanitization
            return content

    @classmethod
    def validate_input(
        cls, content: str, security_level: SecurityLevel = SecurityLevel.MEDIUM
    ) -> dict[str, Any]:
        """Validate and sanitize input content."""
        result: dict[str, Any] = {
            "is_valid": True,
            "sanitized_content": content,
            "threats": [],
            "warnings": [],
        }

        # Check for malicious patterns
        if cls.MALICIOUS_PATTERN.search(content):
            result["is_valid"] = False
            result["threats"].append("malicious_content")
            logger.warning(f"Malicious content detected: {content[:100]}...")

        # Check for injection patterns
        if cls.INJECTION_PATTERN.search(content):
            result["is_valid"] = False
            result["threats"].append("injection_attempt")
            logger.warning(f"Injection attempt detected: {content[:100]}...")

        # Sanitize HTML
        result["sanitized_content"] = cls.sanitize_html(content, security_level)

        # Check content length
        if len(content) > 100000:  # 100k characters
            result["warnings"].append("content_too_long")

        # Check for excessive whitespace
        if len(content.split()) > 10000:
            result["warnings"].append("excessive_whitespace")

        return result

    @classmethod
    def validate_email(cls, email: str) -> bool:
        """Validate email format."""
        return bool(cls.EMAIL_PATTERN.match(email))

    @classmethod
    def validate_phone(cls, phone: str) -> bool:
        """Validate phone number format."""
        return bool(cls.PHONE_PATTERN.match(phone))

    @classmethod
    def validate_url(cls, url: str) -> bool:
        """Validate URL format."""
        return bool(cls.URL_PATTERN.match(url))

    @classmethod
    def generate_secure_token(cls, length: int = 32) -> str:
        """Generate a secure random token."""
        return secrets.token_urlsafe(length)

    @classmethod
    def hash_content(cls, content: str) -> str:
        """Generate SHA-256 hash of content."""
        return hashlib.sha256(content.encode()).hexdigest()


class ContentEncryption:
    """Content encryption utilities."""

    def __init__(self, key: bytes | None = None):
        """Initialize with optional encryption key."""
        if key:
            self.cipher = Fernet(key)
        else:
            # Generate a new key (not recommended for production)
            self.cipher = Fernet(Fernet.generate_key())

    @classmethod
    def generate_key(cls, password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
        """Generate encryption key from password."""
        if salt is None:
            salt = secrets.token_bytes(16)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode())), salt

    def encrypt(self, content: str) -> bytes:
        """Encrypt content."""
        return self.cipher.encrypt(content.encode())

    def decrypt(self, encrypted_content: bytes) -> str:
        """Decrypt content."""
        return self.cipher.decrypt(encrypted_content).decode()


class SecurityMonitor:
    """Security monitoring and threat detection."""

    def __init__(self):
        self.security_events: list[SecurityEvent] = []
        self.thresholds = {
            "failed_attempts": 5,
            "suspicious_ips": 10,
            "content_threats": 3,
        }

    def log_event(self, event: SecurityEvent) -> None:
        """Log a security event."""
        self.security_events.append(event)
        logger.warning(
            f"Security event: {event.event_type} - {event.threat_level.value}"
        )

        # Check thresholds
        self._check_thresholds(event)

    def _check_thresholds(self, event: SecurityEvent) -> None:
        """Check if event thresholds are exceeded."""
        if event.threat_level == ThreatLevel.CRITICAL:
            logger.critical(f"CRITICAL security event: {event.event_type}")

        # Check for suspicious patterns
        recent_events = [
            e
            for e in self.security_events
            if (
                e.timestamp > datetime.now() - timedelta(hours=1)
                and e.client_ip == event.client_ip
            )
        ]

        failed_attempts = len(
            [e for e in recent_events if e.event_type == "authentication_failed"]
        )
        if failed_attempts > self.thresholds["failed_attempts"]:
            logger.warning(
                f"Failed authentication threshold exceeded for IP {event.client_ip}"
            )

        suspicious_ips = len(set([e.client_ip for e in recent_events]))
        if suspicious_ips > self.thresholds["suspicious_ips"]:
            logger.warning(f"Suspicious IP threshold exceeded: {suspicious_ips} IPs")

    def get_security_report(self, hours: int = 24) -> dict[str, Any]:
        """Generate security report for specified time period."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_events = [e for e in self.security_events if e.timestamp > cutoff_time]

        threat_counts: dict[str, int] = {}
        for event in recent_events:
            threat_level = event.threat_level.value
            threat_counts[threat_level] = threat_counts.get(threat_level, 0) + 1

        event_types: dict[str, int] = {}
        for event in recent_events:
            event_type = event.event_type
            event_types[event_type] = event_types.get(event_type, 0) + 1

        return {
            "total_events": len(recent_events),
            "threat_counts": threat_counts,
            "event_types": event_types,
            "time_period": f"{hours} hours",
            "thresholds": self.thresholds,
        }


# Global security monitor instance
security_monitor = SecurityMonitor()


def log_security_event(
    event_type: str,
    threat_level: ThreatLevel,
    user_id: str | None = None,
    conversation_id: str | None = None,
    client_ip: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Log a security event."""
    event = SecurityEvent(
        timestamp=datetime.now(),
        event_type=event_type,
        threat_level=threat_level,
        user_id=user_id,
        conversation_id=conversation_id,
        client_ip=client_ip,
        metadata=metadata or {},
        session_id=session_id,
        user_agent=user_agent,
    )

    security_monitor.log_event(event)


def validate_request_content(
    content: str, security_level: SecurityLevel = SecurityLevel.MEDIUM
) -> dict[str, Any]:
    """Validate request content with security monitoring."""
    result = SecurityValidator.validate_input(content, security_level)

    if result["threats"]:
        log_security_event(
            event_type="content_validation_failed",
            threat_level=ThreatLevel.MEDIUM,
            metadata={
                "threats": result["threats"],
                "warnings": result["warnings"],
                "content_length": len(content),
            },
        )

    return result


def encrypt_sensitive_data(content: str, password: str) -> bytes:
    """Encrypt sensitive data with password."""
    key, _ = ContentEncryption.generate_key(password)
    encryptor = ContentEncryption(key)
    return encryptor.encrypt(content)


def decrypt_sensitive_data(encrypted_content: bytes, password: str) -> str:
    """Decrypt sensitive data with password."""
    key, _ = ContentEncryption.generate_key(password)
    decryptor = ContentEncryption(key)
    return decryptor.decrypt(encrypted_content)


from uuid import UUID

from fastapi import Request


async def get_current_user(request: Request) -> str:
    user = await _get_current_user(request)
    return user.get("user_id", "")


async def get_tenant_id(request: Request) -> UUID:
    user = await _get_current_user(request)
    tenant_id = user.get("tenant_id", "default")
    if isinstance(tenant_id, UUID):
        return tenant_id
    return UUID(str(tenant_id))
