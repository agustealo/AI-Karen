"""
Security utilities for the AI-Karen production chat system.
Provides input validation, sanitization, encryption, and security monitoring.
"""

import logging
import re
import html
import hashlib
import secrets
import time
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

import bleach
from pydantic import BaseModel, validator
import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

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
    user_id: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    details: Dict[str, Any]
    resolved: bool = False


@dataclass
class ValidationResult:
    """Result of input validation."""
    is_valid: bool
    sanitized_content: Optional[str]
    threats_detected: List[str]
    security_level: SecurityLevel
    metadata: Dict[str, Any]


class ContentValidator:
    """Validates and sanitizes user input content."""
    
    def __init__(self, security_level: SecurityLevel = SecurityLevel.MEDIUM):
        self.security_level = security_level
        self.threat_patterns = self._load_threat_patterns()
        
        # Configure bleach based on security level
        self.allowed_tags = self._get_allowed_tags()
        self.allowed_attributes = self._get_allowed_attributes()
    
    def _load_threat_patterns(self) -> Dict[str, List[str]]:
        """Load threat detection patterns."""
        return {
            "xss": [
                r'<script[^>]*>.*?</script>',
                r'javascript:',
                r'on\w+\s*=',
                r'<iframe[^>]*>',
                r'<object[^>]*>',
                r'<embed[^>]*>',
                r'<form[^>]*>',
                r'<input[^>]*>',
                r'<link[^>]*>',
                r'<meta[^>]*>',
                r'expression\s*\(',
                r'url\s*\(',
                r'@import'
            ],
            "sql_injection": [
                r'(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION|SCRIPT)\b)',
                r'(--|#|\/\*|\*\/)',
                r'(\bOR\b|\bAND\b)\s+\w+\s*=\s*\w+',
                r'(\'\s*OR\s*\'.*\'.*\')|(\".*OR.*\")',
                r'\;\s*(DROP|DELETE|UPDATE|INSERT)',
                r'UNION\s+SELECT',
                r'EXEC\s*\(',
                r'SPIDER\s*',
                r'SYSTEM\s*'
            ],
            "command_injection": [
                r'[;&|`$()]',
                r'\b(curl|wget|nc|netcat|telnet|ssh|ftp|scp)\b',
                r'\b(rm|mv|cp|cat|ls|ps|kill|chmod|chown)\b',
                r'\b(python|perl|ruby|bash|sh|cmd|powershell)\b',
                r'\/dev\/(null|zero|random|urandom)',
                r'\.\.\/',
                r'\/etc\/(passwd|shadow|hosts)'
            ],
            "path_traversal": [
                r'\.\.[\/\\]',
                r'%2e%2e[\/\\]',
                r'%252e%252e[\/\\]',
                r'\.\.%2f',
                r'\.\.%5c',
                r'\/etc\/',
                r'\/proc\/',
                r'\/sys\/',
                r'windows\/system32'
            ],
            "sensitive_data": [
                r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',  # Credit card
                r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
                r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # Email
                r'\b(?:\d{1,3}\.){3}\d{1,3}\b'  # IP addresses
            ]
        }
    
    def _get_allowed_tags(self) -> List[str]:
        """Get allowed HTML tags based on security level."""
        if self.security_level == SecurityLevel.LOW:
            return ['p', 'br', 'strong', 'em', 'u', 'i', 'b', 'a', 'img', 'div', 'span']
        elif self.security_level == SecurityLevel.MEDIUM:
            return ['p', 'br', 'strong', 'em', 'u', 'i', 'b', 'a', 'ul', 'ol', 'li']
        elif self.security_level == SecurityLevel.HIGH:
            return ['p', 'br', 'strong', 'em']
        else:  # STRICT
            return ['p', 'br']
    
    def _get_allowed_attributes(self) -> Dict[str, List[str]]:
        """Get allowed HTML attributes based on security level."""
        if self.security_level == SecurityLevel.LOW:
            return {
                '*': ['class', 'id'],
                'a': ['href', 'title'],
                'img': ['src', 'alt', 'width', 'height']
            }
        elif self.security_level == SecurityLevel.MEDIUM:
            return {
                'a': ['href'],
                '*': ['class']
            }
        else:  # HIGH, STRICT
            return {}
    
    def validate_content(self, content: str, content_type: str = "text") -> ValidationResult:
        """
        Validate and sanitize content.
        
        Args:
            content: The content to validate
            content_type: Type of content (text, html, markdown)
            
        Returns:
            ValidationResult with validation results
        """
        threats_detected = []
        sanitized_content = content
        
        # Check for threats
        for threat_type, patterns in self.threat_patterns.items():
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    threats_detected.append(f"{threat_type}: {pattern}")
        
        # Sanitize content based on type
        if content_type == "html":
            sanitized_content = self._sanitize_html(content)
        elif content_type == "markdown":
            sanitized_content = self._sanitize_markdown(content)
        else:
            sanitized_content = self._sanitize_text(content)
        
        # Check content length
        max_length = self._get_max_content_length()
        if len(sanitized_content) > max_length:
            threats_detected.append(f"content_too_long: {len(sanitized_content)} > {max_length}")
            sanitized_content = sanitized_content[:max_length]
        
        # Determine if valid
        is_valid = len(threats_detected) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            sanitized_content=sanitized_content,
            threats_detected=threats_detected,
            security_level=self.security_level,
            metadata={
                "original_length": len(content),
                "sanitized_length": len(sanitized_content),
                "content_type": content_type,
                "validation_time": datetime.utcnow().isoformat()
            }
        )
    
    def _sanitize_html(self, content: str) -> str:
        """Sanitize HTML content using bleach."""
        return bleach.clean(
            content,
            tags=self.allowed_tags,
            attributes=self.allowed_attributes,
            strip=True
        )
    
    def _sanitize_markdown(self, content: str) -> str:
        """Sanitize markdown content."""
        # First convert markdown-like patterns that could be dangerous
        content = re.sub(r'!\[.*?\]\(javascript:.*?\)', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\[.*?\]\(javascript:.*?\)', '', content, flags=re.IGNORECASE)
        
        # Then sanitize as text
        return self._sanitize_text(content)
    
    def _sanitize_text(self, content: str) -> str:
        """Sanitize plain text content."""
        # HTML escape
        content = html.escape(content)
        
        # Remove dangerous patterns
        for patterns in self.threat_patterns.values():
            for pattern in patterns:
                content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        return content
    
    def _get_max_content_length(self) -> int:
        """Get maximum content length based on security level."""
        if self.security_level == SecurityLevel.LOW:
            return 10000
        elif self.security_level == SecurityLevel.MEDIUM:
            return 5000
        elif self.security_level == SecurityLevel.HIGH:
            return 2000
        else:  # STRICT
            return 1000


class EncryptionManager:
    """Manages encryption for sensitive data."""
    
    def __init__(self, key: Optional[str] = None):
        if key:
            self.key = key.encode()
        else:
            self.key = self._generate_key()
        
        self.cipher_suite = Fernet(self.key)
    
    def _generate_key(self) -> bytes:
        """Generate a new encryption key."""
        return Fernet.generate_key()
    
    def encrypt(self, data: str) -> str:
        """Encrypt data."""
        try:
            return self.cipher_suite.encrypt(data.encode()).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise ValueError("Encryption failed")
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt data."""
        try:
            return self.cipher_suite.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise ValueError("Decryption failed")
    
    def encrypt_sensitive_fields(self, data: Dict[str, Any], sensitive_fields: List[str]) -> Dict[str, Any]:
        """Encrypt specific fields in a dictionary."""
        encrypted_data = data.copy()
        
        for field in sensitive_fields:
            if field in encrypted_data and encrypted_data[field]:
                encrypted_data[field] = self.encrypt(str(encrypted_data[field]))
        
        return encrypted_data
    
    def decrypt_sensitive_fields(self, data: Dict[str, Any], sensitive_fields: List[str]) -> Dict[str, Any]:
        """Decrypt specific fields in a dictionary."""
        decrypted_data = data.copy()
        
        for field in sensitive_fields:
            if field in decrypted_data and decrypted_data[field]:
                try:
                    decrypted_data[field] = self.decrypt(decrypted_data[field])
                except Exception as e:
                    logger.warning(f"Failed to decrypt field {field}: {e}")
        
        return decrypted_data


class SecurityMonitor:
    """Monitors security events and detects anomalies."""
    
    def __init__(self):
        self.events: List[SecurityEvent] = []
        self.anomaly_thresholds = {
            "failed_auth_per_minute": 5,
            "failed_auth_per_hour": 20,
            "suspicious_requests_per_minute": 10,
            "rate_limit_exceeded_per_hour": 5
        }
    
    def log_event(self, event: SecurityEvent) -> None:
        """Log a security event."""
        self.events.append(event)
        
        # Keep only last 1000 events in memory
        if len(self.events) > 1000:
            self.events = self.events[-1000:]
        
        # Check for anomalies
        self._check_anomalies(event)
        
        # Log to standard logger
        logger.warning(
            f"Security event: {event.event_type} - "
            f"Threat: {event.threat_level.value} - "
            f"User: {event.user_id} - "
            f"IP: {event.ip_address} - "
            f"Details: {event.details}"
        )
    
    def _check_anomalies(self, current_event: SecurityEvent) -> None:
        """Check for security anomalies."""
        current_time = datetime.utcnow()
        
        # Check for failed authentication patterns
        failed_auth_events = [
            e for e in self.events 
            if e.event_type == "authentication_failed" 
            and (current_time - e.timestamp).total_seconds() < 3600
        ]
        
        if len(failed_auth_events) >= self.anomaly_thresholds["failed_auth_per_hour"]:
            self._create_anomaly_alert(
                "high_failed_auth_rate",
                ThreatLevel.HIGH,
                {
                    "count": len(failed_auth_events),
                    "timeframe": "1 hour"
                }
            )
        
        # Check for rate limit violations
        rate_limit_events = [
            e for e in self.events 
            if e.event_type == "rate_limit_exceeded" 
            and (current_time - e.timestamp).total_seconds() < 3600
        ]
        
        if len(rate_limit_events) >= self.anomaly_thresholds["rate_limit_exceeded_per_hour"]:
            self._create_anomaly_alert(
                "high_rate_limit_violations",
                ThreatLevel.HIGH,
                {
                    "count": len(rate_limit_events),
                    "timeframe": "1 hour"
                }
            )
    
    def _create_anomaly_alert(self, anomaly_type: str, threat_level: ThreatLevel, details: Dict[str, Any]) -> None:
        """Create an anomaly alert."""
        alert = SecurityEvent(
            timestamp=datetime.utcnow(),
            event_type=f"anomaly_{anomaly_type}",
            threat_level=threat_level,
            user_id=None,
            ip_address=None,
            user_agent=None,
            details=details
        )
        
        self.events.append(alert)
        
        # In production, this would trigger notifications
        logger.critical(f"SECURITY ANOMALY: {anomaly_type} - {details}")
    
    def get_events(self, limit: int = 100, event_type: Optional[str] = None) -> List[SecurityEvent]:
        """Get security events with optional filtering."""
        events = self.events
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        return events[-limit:]
    
    def get_threat_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get threat summary for the specified time period."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        recent_events = [e for e in self.events if e.timestamp > cutoff_time]
        
        threat_counts = {}
        for threat_level in ThreatLevel:
            threat_counts[threat_level.value] = len([
                e for e in recent_events 
                if e.threat_level == threat_level
            ])
        
        event_types = {}
        for event in recent_events:
            event_types[event.event_type] = event_types.get(event.event_type, 0) + 1
        
        return {
            "timeframe_hours": hours,
            "total_events": len(recent_events),
            "threat_levels": threat_counts,
            "event_types": event_types,
            "most_active_ips": self._get_most_active_ips(recent_events),
            "top_threats": self._get_top_threats(recent_events)
        }
    
    def _get_most_active_ips(self, events: List[SecurityEvent]) -> List[Dict[str, Any]]:
        """Get most active IP addresses from events."""
        ip_counts = {}
        for event in events:
            if event.ip_address:
                ip_counts[event.ip_address] = ip_counts.get(event.ip_address, 0) + 1
        
        sorted_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {"ip": ip, "count": count}
            for ip, count in sorted_ips[:10]
        ]
    
    def _get_top_threats(self, events: List[SecurityEvent]) -> List[Dict[str, Any]]:
        """Get top threat types from events."""
        threat_counts = {}
        for event in events:
            threat_counts[event.event_type] = threat_counts.get(event.event_type, 0) + 1
        
        sorted_threats = sorted(threat_counts.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {"threat_type": threat, "count": count}
            for threat, count in sorted_threats[:10]
        ]


class InputValidator(BaseModel):
    """Pydantic model for input validation."""
    
    content: str
    conversation_id: Optional[str] = None
    provider_id: Optional[str] = None
    options: Optional[Dict[str, Any]] = {}
    
    @validator('content')
    def validate_content_length(cls, v):
        if not v or not v.strip():
            raise ValueError('Content cannot be empty')
        
        if len(v) > 10000:
            raise ValueError('Content too long (max 10000 characters)')
        
        return v.strip()
    
    @validator('conversation_id')
    def validate_conversation_id(cls, v):
        if v and not re.match(r'^[a-f0-9-]{36}$', v):
            raise ValueError('Invalid conversation ID format')
        
        return v
    
    @validator('provider_id')
    def validate_provider_id(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9_-]{1,50}$', v):
            raise ValueError('Invalid provider ID format')
        
        return v


# Global instances
content_validator = ContentValidator()
encryption_manager = EncryptionManager()
security_monitor = SecurityMonitor()


def get_content_validator(security_level: SecurityLevel = SecurityLevel.MEDIUM) -> ContentValidator:
    """Get a content validator instance."""
    return ContentValidator(security_level)


def get_encryption_manager() -> EncryptionManager:
    """Get the encryption manager instance."""
    return encryption_manager


def get_security_monitor() -> SecurityMonitor:
    """Get the security monitor instance."""
    return security_monitor


# Utility functions
def generate_session_token() -> str:
    """Generate a secure session token."""
    return secrets.token_urlsafe(32)


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash a password with salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode(),
        iterations=100000,
    )
    
    hashed = kdf.derive(password.encode())
    return base64.b64encode(hashed).decode(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against hash."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode(),
        iterations=100000,
    )
    
    try:
        kdf.verify(password.encode(), base64.b64decode(hashed))
        return True
    except Exception:
        return False


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename for security."""
    # Remove path components
    filename = filename.replace('\\', '/').split('/')[-1]
    
    # Remove dangerous characters
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:255-len(ext)-1] + '.' + ext if ext else name[:255]
    
    return filename


def validate_file_upload(file_data: bytes, filename: str) -> ValidationResult:
    """Validate uploaded file for security."""
    threats_detected = []
    
    # Check file size (max 10MB)
    if len(file_data) > 10 * 1024 * 1024:
        threats_detected.append("file_too_large")
    
    # Check file extension
    allowed_extensions = ['.txt', '.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.gif']
    file_ext = '.' + filename.split('.')[-1].lower() if '.' in filename else ''
    
    if file_ext not in allowed_extensions:
        threats_detected.append(f"disallowed_file_type: {file_ext}")
    
    # Check for malicious content patterns
    content_str = file_data[:1024].decode('utf-8', errors='ignore')
    malicious_patterns = [
        r'<script[^>]*>',
        r'javascript:',
        r'vbscript:',
        r'on\w+\s*=',
        r'<?php',
        r'<%',
        r'eval\s*\(',
        r'exec\s*\('
    ]
    
    for pattern in malicious_patterns:
        if re.search(pattern, content_str, re.IGNORECASE):
            threats_detected.append(f"malicious_content: {pattern}")
    
    return ValidationResult(
        is_valid=len(threats_detected) == 0,
        sanitized_content=filename,
        threats_detected=threats_detected,
        security_level=SecurityLevel.MEDIUM,
        metadata={
            "file_size": len(file_data),
            "file_extension": file_ext,
            "validation_time": datetime.utcnow().isoformat()
        }
    )


_content_validators: Dict[SecurityLevel, ContentValidator] = {}


def get_content_validator(security_level: SecurityLevel = SecurityLevel.MEDIUM) -> ContentValidator:
    """Get or create a ContentValidator instance for the given security level."""
    if security_level not in _content_validators:
        _content_validators[security_level] = ContentValidator(security_level)
    return _content_validators[security_level]


def validate_content(content: str, security_level: SecurityLevel = SecurityLevel.MEDIUM) -> ValidationResult:
    """Validate content using the specified security level."""
    validator = get_content_validator(security_level)
    return validator.validate_content(content)


def sanitize_content(content: str, security_level: SecurityLevel = SecurityLevel.MEDIUM) -> str:
    """Sanitize content using the specified security level."""
    validator = get_content_validator(security_level)
    result = validator.validate_content(content)
    return result.sanitized_content or content