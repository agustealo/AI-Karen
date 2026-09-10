"""
Rate limiting and abuse protection for AI-Karen production chat system.
"""

import time
import asyncio
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
import logging
from datetime import datetime, timedelta
import ipaddress
import hashlib

from .security import ThreatLevel, SecurityLevel

logger = logging.getLogger(__name__)


class RateLimitType(Enum):
    """Types of rate limiting."""
    MESSAGES_PER_MINUTE = "messages_per_minute"
    MESSAGES_PER_HOUR = "messages_per_hour"
    MESSAGES_PER_DAY = "messages_per_day"
    CONVERSATIONS_PER_HOUR = "conversations_per_hour"
    CONVERSATIONS_PER_DAY = "conversations_per_day"
    FILE_UPLOADS_PER_HOUR = "file_uploads_per_hour"
    API_REQUESTS_PER_MINUTE = "api_requests_per_minute"
    LOGIN_ATTEMPTS_PER_MINUTE = "login_attempts_per_minute"
    FAILED_AUTH_PER_HOUR = "failed_auth_per_hour"
    WS_CONNECTIONS_PER_MINUTE = "ws_connections_per_minute"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    limit_type: RateLimitType
    max_requests: int
    window_seconds: int
    penalty_seconds: int = 300  # 5 minutes default penalty
    enabled: bool = True


@dataclass
class RateLimitEntry:
    """Entry for tracking rate limit violations."""
    identifier: str
    limit_type: RateLimitType
    timestamp: datetime
    violation_count: int = 0
    penalty_until: Optional[datetime] = None
    threat_level: ThreatLevel = ThreatLevel.LOW


@dataclass
class AbuseDetectionConfig:
    """Configuration for abuse detection."""
    enabled: bool = True
    suspicious_patterns: List[str] = field(default_factory=lambda: [
        r'(union|select|insert|update|delete|drop|create|alter|exec|execute)\b',
        r'<script[^>]*>.*?</script>',
        r'javascript:',
        r'eval\(',
        r'exec\(',
        r'system\('
    ])
    max_pattern_matches: int = 3
    pattern_window_seconds: int = 300  # 5 minutes
    auto_ban_threshold: int = 5
    auto_ban_duration_hours: int = 24


@dataclass
class AbuseEntry:
    """Entry for tracking abuse detection."""
    identifier: str
    timestamp: datetime
    pattern_matches: List[str] = field(default_factory=list)
    violation_count: int = 0
    banned_until: Optional[datetime] = None
    threat_level: ThreatLevel = ThreatLevel.LOW


class RateLimiter:
    """Rate limiting implementation with sliding window."""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.requests: deque = deque()
        self._lock = asyncio.Lock()
    
    async def is_allowed(self, identifier: str) -> Tuple[bool, Optional[int]]:
        """Check if request is allowed."""
        async with self._lock:
            now = datetime.now()
            
            # Clean old requests
            cutoff_time = now - timedelta(seconds=self.config.window_seconds)
            while self.requests and self.requests[0] < cutoff_time:
                self.requests.popleft()
            
            # Check if under limit
            if len(self.requests) < self.config.max_requests:
                self.requests.append(now)
                return True, None
            
            # Calculate retry time
            oldest_request = self.requests[0]
            retry_time = oldest_request + timedelta(seconds=self.config.window_seconds)
            retry_seconds = int((retry_time - now).total_seconds())
            
            return False, retry_seconds
    
    def get_current_count(self) -> int:
        """Get current request count."""
        now = datetime.now()
        cutoff_time = now - timedelta(seconds=self.config.window_seconds)
        return sum(1 for req_time in self.requests if req_time >= cutoff_time)
    
    def reset(self):
        """Reset rate limiter."""
        self.requests.clear()


class AbuseDetector:
    """Abuse detection system."""
    
    def __init__(self, config: AbuseDetectionConfig):
        self.config = config
        self.pattern_matches: Dict[str, List[datetime]] = defaultdict(list)
        self.violations: Dict[str, List[AbuseEntry]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def check_content(self, identifier: str, content: str) -> Tuple[bool, List[str]]:
        """Check content for abusive patterns."""
        if not self.config.enabled:
            return True, []
        
        async with self._lock:
            now = datetime.now()
            matched_patterns = []
            
            # Check for suspicious patterns
            import re
            for pattern in self.config.suspicious_patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    matched_patterns.append(pattern)
                    self.pattern_matches[identifier].append(now)
            
            # Clean old pattern matches
            cutoff_time = now - timedelta(seconds=self.config.pattern_window_seconds)
            self.pattern_matches[identifier] = [
                match_time for match_time in self.pattern_matches[identifier]
                if match_time >= cutoff_time
            ]
            
            # Check if threshold exceeded or patterns matched
            if matched_patterns or len(self.pattern_matches[identifier]) > self.config.max_pattern_matches:
                await self._record_violation(identifier, matched_patterns)
                return False, matched_patterns
            
            return True, matched_patterns
    
    async def _record_violation(self, identifier: str, patterns: List[str]):
        """Record abuse violation."""
        now = datetime.now()
        
        # Create abuse entry
        entry = AbuseEntry(
            identifier=identifier,
            timestamp=now,
            pattern_matches=patterns,
            violation_count=len(self.violations[identifier]) + 1
        )
        
        # Check for auto-ban
        if entry.violation_count >= self.config.auto_ban_threshold:
            entry.banned_until = now + timedelta(hours=self.config.auto_ban_duration_hours)
            entry.threat_level = ThreatLevel.CRITICAL
        else:
            entry.threat_level = ThreatLevel.HIGH
        
        self.violations[identifier].append(entry)
        
        # Clean old violations
        cutoff_time = now - timedelta(hours=24)
        self.violations[identifier] = [
            violation for violation in self.violations[identifier]
            if violation.timestamp >= cutoff_time
        ]
        
        logger.warning(f"Abuse detected from {identifier}: {patterns}")
    
    def is_banned(self, identifier: str) -> Tuple[bool, Optional[datetime]]:
        """Check if identifier is banned."""
        if not self.config.enabled:
            return False, None
        
        violations = self.violations.get(identifier, [])
        now = datetime.now()
        
        for violation in violations:
            if violation.banned_until and violation.banned_until > now:
                return True, violation.banned_until
        
        return False, None
    
    def get_violation_count(self, identifier: str) -> int:
        """Get violation count for identifier."""
        return len(self.violations.get(identifier, []))


class ChatRateLimitingService:
    """Comprehensive rate limiting and abuse protection service."""
    
    def __init__(self):
        self.rate_limiters: Dict[str, Dict[RateLimitType, RateLimiter]] = defaultdict(dict)
        self.abuse_detectors: Dict[str, AbuseDetector] = {}
        self.ip_reputation: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self.user_reputation: Dict[str, Dict[str, Any]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        
        # Default rate limit configurations
        self.rate_limit_configs = {
            RateLimitType.MESSAGES_PER_MINUTE: RateLimitConfig(
                RateLimitType.MESSAGES_PER_MINUTE, 10, 60, 60
            ),
            RateLimitType.MESSAGES_PER_HOUR: RateLimitConfig(
                RateLimitType.MESSAGES_PER_HOUR, 100, 3600, 300
            ),
            RateLimitType.MESSAGES_PER_DAY: RateLimitConfig(
                RateLimitType.MESSAGES_PER_DAY, 1000, 86400, 900
            ),
            RateLimitType.CONVERSATIONS_PER_HOUR: RateLimitConfig(
                RateLimitType.CONVERSATIONS_PER_HOUR, 20, 3600, 300
            ),
            RateLimitType.CONVERSATIONS_PER_DAY: RateLimitConfig(
                RateLimitType.CONVERSATIONS_PER_DAY, 100, 86400, 600
            ),
            RateLimitType.FILE_UPLOADS_PER_HOUR: RateLimitConfig(
                RateLimitType.FILE_UPLOADS_PER_HOUR, 10, 3600, 600
            ),
            RateLimitType.API_REQUESTS_PER_MINUTE: RateLimitConfig(
                RateLimitType.API_REQUESTS_PER_MINUTE, 60, 60, 60
            ),
            RateLimitType.LOGIN_ATTEMPTS_PER_MINUTE: RateLimitConfig(
                RateLimitType.LOGIN_ATTEMPTS_PER_MINUTE, 5, 60, 300
            ),
            RateLimitType.FAILED_AUTH_PER_HOUR: RateLimitConfig(
                RateLimitType.FAILED_AUTH_PER_HOUR, 10, 3600, 900
            ),
            RateLimitType.WS_CONNECTIONS_PER_MINUTE: RateLimitConfig(
                RateLimitType.WS_CONNECTIONS_PER_MINUTE, 3, 60, 120
            )
        }
        
        # Default abuse detection configuration
        self.abuse_config = AbuseDetectionConfig()
    
    def get_rate_limiter(self, identifier: str, limit_type: RateLimitType) -> Optional[RateLimiter]:
        """Get or create rate limiter for identifier and type."""
        if identifier not in self.rate_limiters:
            self.rate_limiters[identifier] = {}
        
        if limit_type not in self.rate_limiters[identifier]:
            config = self.rate_limit_configs.get(limit_type)
            if config and config.enabled:
                self.rate_limiters[identifier][limit_type] = RateLimiter(config)
        
        return self.rate_limiters[identifier].get(limit_type)
    
    def get_abuse_detector(self, identifier: str) -> AbuseDetector:
        """Get or create abuse detector for identifier."""
        if identifier not in self.abuse_detectors:
            self.abuse_detectors[identifier] = AbuseDetector(self.abuse_config)
        return self.abuse_detectors[identifier]
    
    async def check_rate_limit(
        self, 
        identifier: str, 
        limit_type: RateLimitType
    ) -> Tuple[bool, Optional[int], Optional[str]]:
        """Check rate limit for identifier and type."""
        limiter = self.get_rate_limiter(identifier, limit_type)
        if not limiter:
            return True, None, None
        
        allowed, retry_seconds = await limiter.is_allowed(identifier)
        
        if not allowed:
            penalty_message = f"Rate limit exceeded for {limit_type.value}"
            if retry_seconds:
                penalty_message += f". Retry in {retry_seconds} seconds"
            
            # Update reputation
            await self._update_reputation(identifier, "rate_limit_violation")
            
            return False, retry_seconds, penalty_message
        
        return True, None, None
    
    async def check_abuse(
        self, 
        identifier: str, 
        content: str
    ) -> Tuple[bool, List[str], Optional[str]]:
        """Check content for abuse patterns."""
        detector = self.get_abuse_detector(identifier)
        allowed, matched_patterns = await detector.check_content(identifier, content)
        
        if not allowed:
            # Update reputation
            await self._update_reputation(identifier, "abuse_detected")
            
            return False, matched_patterns, "Abusive content detected"
        
        # Check if banned
        is_banned, banned_until = detector.is_banned(identifier)
        if is_banned:
            ban_message = "Account temporarily suspended due to abuse"
            if banned_until:
                ban_message += f". Suspension until {banned_until}"
            
            return False, matched_patterns, ban_message
        
        return True, matched_patterns, None
    
    async def check_ip_reputation(self, ip_address: str) -> Tuple[bool, Optional[str]]:
        """Check IP address reputation."""
        try:
            # Basic IP validation
            ip = ipaddress.ip_address(ip_address)
            
            # Check for private/internal IPs
            if ip.is_private or ip.is_loopback:
                return True, None
            
            # Check reputation cache
            if ip_address in self.ip_reputation:
                reputation = self.ip_reputation[ip_address]
                if reputation.get("banned_until"):
                    banned_until = reputation["banned_until"]
                    if banned_until > datetime.now():
                        return False, f"IP address banned until {banned_until}"
                    else:
                        # Clear expired ban
                        reputation["banned_until"] = None
            
            # Check for suspicious patterns in IP
            if self._is_suspicious_ip(ip_address):
                await self._update_ip_reputation(ip_address, "suspicious_ip")
                return False, "Suspicious IP address detected"
            
            return True, None
            
        except ValueError:
            return False, "Invalid IP address"
    
    async def check_user_reputation(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """Check user reputation."""
        if user_id not in self.user_reputation:
            return True, None
        
        reputation = self.user_reputation[user_id]
        
        # Check for ban
        if reputation.get("banned_until"):
            banned_until = reputation["banned_until"]
            if banned_until > datetime.now():
                return False, f"User banned until {banned_until}"
            else:
                # Clear expired ban
                reputation["banned_until"] = None
        
        # Check reputation score
        score = reputation.get("score", 100)
        if score < 50:
            return False, "Low reputation score"
        
        return True, None
    
    async def record_successful_action(self, identifier: str, action_type: str):
        """Record successful action for reputation tracking."""
        await self._update_reputation(identifier, f"successful_{action_type}")
    
    async def record_failed_action(self, identifier: str, action_type: str):
        """Record failed action for reputation tracking."""
        await self._update_reputation(identifier, f"failed_{action_type}")
    
    async def _update_reputation(self, identifier: str, event_type: str):
        """Update reputation score based on event type."""
        async with self._lock:
            if identifier not in self.user_reputation:
                self.user_reputation[identifier] = {
                    "score": 100,
                    "violations": 0,
                    "last_updated": datetime.now()
                }
            
            reputation = self.user_reputation[identifier]
            
            # Update score based on event type
            if event_type == "rate_limit_violation":
                reputation["score"] = max(0, reputation["score"] - 5)
                reputation["violations"] += 1
            elif event_type == "abuse_detected":
                reputation["score"] = max(0, reputation["score"] - 10)
                reputation["violations"] += 1
            elif event_type.startswith("successful_"):
                reputation["score"] = min(100, reputation["score"] + 1)
            elif event_type.startswith("failed_"):
                reputation["score"] = max(0, reputation["score"] - 2)
            
            reputation["last_updated"] = datetime.now()
            
            # Auto-ban if score too low
            if reputation["score"] < 20:
                reputation["banned_until"] = datetime.now() + timedelta(hours=24)
    
    async def _update_ip_reputation(self, ip_address: str, event_type: str):
        """Update IP reputation based on event type."""
        async with self._lock:
            if ip_address not in self.ip_reputation:
                self.ip_reputation[ip_address] = {
                    "score": 100,
                    "violations": 0,
                    "last_updated": datetime.now()
                }
            
            reputation = self.ip_reputation[ip_address]
            
            # Update score based on event type
            if event_type == "suspicious_ip":
                reputation["score"] = max(0, reputation["score"] - 20)
                reputation["violations"] += 1
            elif event_type == "abuse_detected":
                reputation["score"] = max(0, reputation["score"] - 15)
                reputation["violations"] += 1
            
            reputation["last_updated"] = datetime.now()
            
            # Auto-ban if score too low
            if reputation["score"] < 30:
                reputation["banned_until"] = datetime.now() + timedelta(hours=6)
    
    def _is_suspicious_ip(self, ip_address: str) -> bool:
        """Check if IP address is suspicious."""
        try:
            ip = ipaddress.ip_address(ip_address)
            
            # Check for known suspicious ranges (simplified)
            # In production, this would integrate with threat intelligence feeds
            suspicious_ranges = [
                # Tor exit nodes (simplified example)
                ipaddress.ip_network("185.100.87.0/24"),
                # Known proxy ranges (simplified example)
                ipaddress.ip_network("107.150.0.0/16"),
            ]
            
            for suspicious_range in suspicious_ranges:
                if ip in suspicious_range:
                    return True
            
            return False
            
        except ValueError:
            return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get rate limiting and abuse detection statistics."""
        stats = {
            "active_rate_limiters": sum(
                len(limiters) for limiters in self.rate_limiters.values()
            ),
            "active_abuse_detectors": len(self.abuse_detectors),
            "ip_reputation_entries": len(self.ip_reputation),
            "user_reputation_entries": len(self.user_reputation),
            "total_violations": sum(
                detector.get_violation_count(identifier)
                for identifier, detector in self.abuse_detectors.items()
            )
        }
        
        return stats
    
    def reset_user_limits(self, identifier: str):
        """Reset all rate limits for a user."""
        if identifier in self.rate_limiters:
            for limiter in self.rate_limiters[identifier].values():
                limiter.reset()
    
    def ban_user(self, identifier: str, duration_hours: int = 24):
        """Manually ban a user."""
        if identifier not in self.user_reputation:
            self.user_reputation[identifier] = {}
        
        self.user_reputation[identifier]["banned_until"] = (
            datetime.now() + timedelta(hours=duration_hours)
        )
        self.user_reputation[identifier]["score"] = 0
        
        logger.warning(f"User {identifier} manually banned for {duration_hours} hours")
    
    def unban_user(self, identifier: str):
        """Manually unban a user."""
        if identifier in self.user_reputation:
            self.user_reputation[identifier]["banned_until"] = None
            self.user_reputation[identifier]["score"] = 50
            
            logger.info(f"User {identifier} manually unbanned")


# Global rate limiting service
rate_limiting_service = ChatRateLimitingService()


def get_rate_limiting_service() -> ChatRateLimitingService:
    """Get the global rate limiting service."""
    return rate_limiting_service


async def check_message_rate_limit(user_id: str) -> Tuple[bool, Optional[int], Optional[str]]:
    """Check message rate limit for user."""
    service = get_rate_limiting_service()
    return await service.check_rate_limit(user_id, RateLimitType.MESSAGES_PER_MINUTE)


async def check_conversation_rate_limit(user_id: str) -> Tuple[bool, Optional[int], Optional[str]]:
    """Check conversation rate limit for user."""
    service = get_rate_limiting_service()
    return await service.check_rate_limit(user_id, RateLimitType.CONVERSATIONS_PER_HOUR)


async def check_file_upload_rate_limit(user_id: str) -> Tuple[bool, Optional[int], Optional[str]]:
    """Check file upload rate limit for user."""
    service = get_rate_limiting_service()
    return await service.check_rate_limit(user_id, RateLimitType.FILE_UPLOADS_PER_HOUR)


async def check_content_abuse(user_id: str, content: str) -> Tuple[bool, List[str], Optional[str]]:
    """Check content for abuse patterns."""
    service = get_rate_limiting_service()
    return await service.check_abuse(user_id, content)


async def check_login_rate_limit(ip_address: str) -> Tuple[bool, Optional[int], Optional[str]]:
    """Check login rate limit for IP."""
    service = get_rate_limiting_service()
    
    # Check IP reputation first
    ip_allowed, ip_message = await service.check_ip_reputation(ip_address)
    if not ip_allowed:
        return False, None, ip_message
    
    # Check rate limit
    return await service.check_rate_limit(ip_address, RateLimitType.LOGIN_ATTEMPTS_PER_MINUTE)


async def check_websocket_rate_limit(user_id: str) -> Tuple[bool, Optional[int], Optional[str]]:
    """Check WebSocket connection rate limit for user."""
    service = get_rate_limiting_service()
    return await service.check_rate_limit(user_id, RateLimitType.WS_CONNECTIONS_PER_MINUTE)


async def record_successful_message(user_id: str):
    """Record successful message for reputation."""
    service = get_rate_limiting_service()
    await service.record_successful_action(user_id, "message")


async def record_failed_login(ip_address: str):
    """Record failed login attempt."""
    service = get_rate_limiting_service()
    await service.record_failed_action(ip_address, "login")