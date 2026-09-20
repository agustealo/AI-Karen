"""
Enhanced Rate Limiting System for HTTP Request Validation

This module provides a comprehensive rate limiting system with:
- Configurable rules and thresholds
- Multiple storage backends (memory, Redis)
- Sliding window and fixed window algorithms
- Hierarchical rate limiting (IP, user, endpoint-specific)
- Performance optimizations and monitoring
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from abc import ABC, abstractmethod

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.monitoring.validation_metrics import (
    get_validation_metrics_collector,
    ValidationEventType,
    ThreatLevel,
    ValidationMetricsData
)

try:
    import redis.asyncio as redis_asyncio
    REDIS_AVAILABLE = True
except ImportError:
    redis_asyncio = None
    REDIS_AVAILABLE = False


class RateLimitAlgorithm(Enum):
    """Rate limiting algorithms"""
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"


class RateLimitScope(Enum):
    """Rate limiting scopes"""
    GLOBAL = "global"
    IP = "ip"
    USER = "user"
    ENDPOINT = "endpoint"
    IP_ENDPOINT = "ip_endpoint"
    USER_ENDPOINT = "user_endpoint"


@dataclass
class RateLimitRule:
    """Rate limiting rule configuration"""
    name: str
    scope: RateLimitScope
    algorithm: RateLimitAlgorithm
    limit: int  # Maximum requests
    window_seconds: int  # Time window in seconds
    burst_limit: Optional[int] = None  # Burst allowance for token bucket
    enabled: bool = True
    priority: int = 0  # Higher priority rules are checked first
    endpoints: Optional[List[str]] = None  # Specific endpoints this rule applies to
    user_types: Optional[List[str]] = None  # User types this rule applies to
    description: str = ""


@dataclass
class RateLimitResult:
    """Result of rate limit check"""
    allowed: bool
    rule_name: str
    current_count: int
    limit: int
    window_seconds: int
    reset_time: datetime
    retry_after_seconds: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


class RateLimitStorage(ABC):
    """Abstract storage interface for rate limiting data"""
    
    @abstractmethod
    async def get_count(self, key: str, window_seconds: int) -> int:
        """Get current request count for a key within the window"""
        pass
    
    @abstractmethod
    async def increment_count(self, key: str, window_seconds: int, amount: int = 1) -> int:
        """Increment request count and return new count"""
        pass
    
    @abstractmethod
    async def get_window_start(self, key: str) -> Optional[datetime]:
        """Get the start time of the current window"""
        pass
    
    @abstractmethod
    async def set_window_start(self, key: str, start_time: datetime, ttl_seconds: int) -> None:
        """Set the start time of the current window"""
        pass
    
    @abstractmethod
    async def add_request_timestamp(self, key: str, timestamp: float, ttl_seconds: int) -> None:
        """Add a request timestamp for sliding window"""
        pass
    
    @abstractmethod
    async def get_request_timestamps(self, key: str, since: float) -> List[float]:
        """Get request timestamps since a given time"""
        pass
    
    @abstractmethod
    async def cleanup_expired(self, cutoff_time: float) -> None:
        """Clean up expired entries"""
        pass
    
    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        pass


class MemoryRateLimitStorage(RateLimitStorage):
    """In-memory storage for rate limiting (single instance only)"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self._counts: Dict[str, int] = defaultdict(int)
        self._window_starts: Dict[str, datetime] = {}
        self._timestamps: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 minutes
    
    async def get_count(self, key: str, window_seconds: int) -> int:
        await self._maybe_cleanup()
        return self._counts.get(key, 0)
    
    async def increment_count(self, key: str, window_seconds: int, amount: int = 1) -> int:
        await self._maybe_cleanup()
        self._counts[key] += amount
        return self._counts[key]
    
    async def get_window_start(self, key: str) -> Optional[datetime]:
        return self._window_starts.get(key)
    
    async def set_window_start(self, key: str, start_time: datetime, ttl_seconds: int) -> None:
        self._window_starts[key] = start_time
    
    async def add_request_timestamp(self, key: str, timestamp: float, ttl_seconds: int) -> None:
        await self._maybe_cleanup()
        self._timestamps[key].append(timestamp)
    
    async def get_request_timestamps(self, key: str, since: float) -> List[float]:
        timestamps = self._timestamps.get(key, deque())
        return [ts for ts in timestamps if ts >= since]
    
    async def cleanup_expired(self, cutoff_time: float) -> None:
        # Clean up expired timestamps
        for key in list(self._timestamps.keys()):
            timestamps = self._timestamps[key]
            while timestamps and timestamps[0] < cutoff_time:
                timestamps.popleft()
            if not timestamps:
                del self._timestamps[key]
        
        # Clean up expired window starts and counts
        current_time = datetime.now(timezone.utc)
        for key in list(self._window_starts.keys()):
            window_start = self._window_starts[key]
            if (current_time - window_start).total_seconds() > 3600:  # 1 hour
                del self._window_starts[key]
                self._counts.pop(key, None)
    
    async def get_stats(self) -> Dict[str, Any]:
        return {
            "storage_type": "memory",
            "tracked_keys": len(self._counts),
            "total_timestamps": sum(len(ts) for ts in self._timestamps.values()),
            "window_starts": len(self._window_starts),
        }
    
    async def _maybe_cleanup(self) -> None:
        current_time = time.time()
        if current_time - self._last_cleanup > self._cleanup_interval:
            await self.cleanup_expired(current_time - 3600)  # Clean up entries older than 1 hour
            self._last_cleanup = current_time


class RedisRateLimitStorage(RateLimitStorage):
    """Redis-based storage for rate limiting (distributed)"""
    
    def __init__(self, redis_client: "redis_asyncio.Redis"):
        if not REDIS_AVAILABLE:
            raise RuntimeError("Redis is not available. Install redis package.")
        
        self.redis = redis_client
        self.logger = get_logger(__name__)
        self._key_prefix = "rl:"
    
    def _make_key(self, key: str, suffix: str = "") -> str:
        """Create a Redis key with prefix"""
        return f"{self._key_prefix}{key}{suffix}"
    
    async def get_count(self, key: str, window_seconds: int) -> int:
        redis_key = self._make_key(key, ":count")
        count = await self.redis.get(redis_key)
        return int(count) if count else 0
    
    async def increment_count(self, key: str, window_seconds: int, amount: int = 1) -> int:
        redis_key = self._make_key(key, ":count")
        
        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()
        pipe.incrby(redis_key, amount)
        pipe.expire(redis_key, window_seconds * 2)  # TTL is 2x window for safety
        results = await pipe.execute()
        
        return results[0]
    
    async def get_window_start(self, key: str) -> Optional[datetime]:
        redis_key = self._make_key(key, ":window_start")
        timestamp = await self.redis.get(redis_key)
        if timestamp:
            return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        return None
    
    async def set_window_start(self, key: str, start_time: datetime, ttl_seconds: int) -> None:
        redis_key = self._make_key(key, ":window_start")
        timestamp = start_time.timestamp()
        await self.redis.setex(redis_key, ttl_seconds, timestamp)
    
    async def add_request_timestamp(self, key: str, timestamp: float, ttl_seconds: int) -> None:
        redis_key = self._make_key(key, ":timestamps")
        
        # Use sorted set with timestamp as both member and score
        pipe = self.redis.pipeline()
        pipe.zadd(redis_key, {str(timestamp): timestamp})
        pipe.expire(redis_key, ttl_seconds)
        await pipe.execute()
    
    async def get_request_timestamps(self, key: str, since: float) -> List[float]:
        redis_key = self._make_key(key, ":timestamps")
        
        # Remove old timestamps and get remaining ones
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(redis_key, "-inf", since)
        pipe.zrange(redis_key, 0, -1, withscores=True)
        results = await pipe.execute()
        
        # Extract timestamps from sorted set results
        timestamps = []
        for member, score in results[1]:
            timestamps.append(float(score))
        
        return timestamps
    
    async def cleanup_expired(self, cutoff_time: float) -> None:
        # Redis handles expiration automatically, but we can clean up old timestamps
        pattern = self._make_key("*", ":timestamps")
        async for key in self.redis.scan_iter(match=pattern):
            await self.redis.zremrangebyscore(key, "-inf", cutoff_time)
    
    async def get_stats(self) -> Dict[str, Any]:
        # Get approximate statistics
        pattern = self._make_key("*")
        keys = []
        async for key in self.redis.scan_iter(match=pattern):
            keys.append(key)
        
        return {
            "storage_type": "redis",
            "tracked_keys": len(keys),
            "redis_info": await self.redis.info("memory"),
        }


class EnhancedRateLimiter:
    """
    Enhanced rate limiter with configurable rules and multiple algorithms
    """
    
    def __init__(
        self,
        storage: RateLimitStorage,
        rules: List[RateLimitRule],
        default_rule: Optional[RateLimitRule] = None
    ):
        self.storage = storage
        self.rules = sorted(rules, key=lambda r: r.priority, reverse=True)
        self.default_rule = default_rule or RateLimitRule(
            name="default",
            scope=RateLimitScope.IP,
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            limit=100,
            window_seconds=60,
            description="Default rate limit rule"
        )
        self.logger = get_logger(__name__)
        self.metrics_collector = get_validation_metrics_collector()
        
        # Performance optimization: cache rule lookups
        self._rule_cache: Dict[str, RateLimitRule] = {}
        self._cache_ttl = 300  # 5 minutes
        self._cache_timestamps: Dict[str, float] = {}
    
    async def check_rate_limit(
        self,
        ip_address: str,
        endpoint: str,
        user_id: Optional[str] = None,
        user_type: Optional[str] = None,
        request_size: int = 1
    ) -> RateLimitResult:
        """
        Check if request should be rate limited
        
        Args:
            ip_address: Client IP address
            endpoint: Request endpoint
            user_id: User identifier (optional)
            user_type: User type (optional)
            request_size: Request size/weight (default: 1)
        
        Returns:
            RateLimitResult with decision and details
        """
        # Find applicable rule
        rule = await self._find_applicable_rule(ip_address, endpoint, user_id, user_type)
        
        # Generate rate limit key
        key = self._generate_key(rule, ip_address, endpoint, user_id)
        
        # Check rate limit based on algorithm
        if rule.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
            return await self._check_fixed_window(rule, key, request_size)
        elif rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
            return await self._check_sliding_window(rule, key, request_size)
        elif rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            return await self._check_token_bucket(rule, key, request_size)
        else:
            # Fallback to sliding window
            return await self._check_sliding_window(rule, key, request_size)
    
    async def record_request(
        self,
        ip_address: str,
        endpoint: str,
        user_id: Optional[str] = None,
        user_type: Optional[str] = None,
        request_size: int = 1
    ) -> None:
        """
        Record a request for rate limiting
        
        Args:
            ip_address: Client IP address
            endpoint: Request endpoint
            user_id: User identifier (optional)
            user_type: User type (optional)
            request_size: Request size/weight (default: 1)
        """
        rule = await self._find_applicable_rule(ip_address, endpoint, user_id, user_type)
        key = self._generate_key(rule, ip_address, endpoint, user_id)
        
        current_time = time.time()
        
        if rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
            await self.storage.add_request_timestamp(key, current_time, rule.window_seconds * 2)
        else:
            await self.storage.increment_count(key, rule.window_seconds, request_size)
    
    async def _find_applicable_rule(
        self,
        ip_address: str,
        endpoint: str,
        user_id: Optional[str],
        user_type: Optional[str]
    ) -> RateLimitRule:
        """Find the most applicable rate limiting rule"""
        
        # Check cache first
        cache_key = f"{ip_address}:{endpoint}:{user_id}:{user_type}"
        current_time = time.time()
        
        if (cache_key in self._rule_cache and 
            current_time - self._cache_timestamps.get(cache_key, 0) < self._cache_ttl):
            return self._rule_cache[cache_key]
        
        # Find matching rule (rules are already sorted by priority)
        for rule in self.rules:
            if not rule.enabled:
                continue
            
            # Check endpoint match
            if rule.endpoints and endpoint not in rule.endpoints:
                continue
            
            # Check user type match
            if rule.user_types and user_type not in rule.user_types:
                continue
            
            # Check scope match - more specific scopes should match first
            scope_matches = False
            
            if rule.scope == RateLimitScope.USER_ENDPOINT and user_id and endpoint:
                scope_matches = True
            elif rule.scope == RateLimitScope.IP_ENDPOINT and ip_address and endpoint:
                scope_matches = True
            elif rule.scope == RateLimitScope.USER and user_id:
                scope_matches = True
            elif rule.scope == RateLimitScope.IP and ip_address:
                scope_matches = True
            elif rule.scope == RateLimitScope.ENDPOINT and endpoint:
                scope_matches = True
            elif rule.scope == RateLimitScope.GLOBAL:
                scope_matches = True
            
            if not scope_matches:
                continue
            
            # Cache the result
            self._rule_cache[cache_key] = rule
            self._cache_timestamps[cache_key] = current_time
            
            return rule
        
        # No specific rule found, use default
        self._rule_cache[cache_key] = self.default_rule
        self._cache_timestamps[cache_key] = current_time
        
        return self.default_rule
    
    def _generate_key(
        self,
        rule: RateLimitRule,
        ip_address: str,
        endpoint: str,
        user_id: Optional[str]
    ) -> str:
        """Generate storage key for rate limiting"""
        
        if rule.scope == RateLimitScope.GLOBAL:
            return f"global:{rule.name}"
        elif rule.scope == RateLimitScope.IP:
            return f"ip:{ip_address}:{rule.name}"
        elif rule.scope == RateLimitScope.USER:
            return f"user:{user_id}:{rule.name}"
        elif rule.scope == RateLimitScope.ENDPOINT:
            return f"endpoint:{endpoint}:{rule.name}"
        elif rule.scope == RateLimitScope.IP_ENDPOINT:
            return f"ip_endpoint:{ip_address}:{endpoint}:{rule.name}"
        elif rule.scope == RateLimitScope.USER_ENDPOINT:
            return f"user_endpoint:{user_id}:{endpoint}:{rule.name}"
        else:
            return f"default:{ip_address}:{rule.name}"
    
    async def _check_fixed_window(
        self,
        rule: RateLimitRule,
        key: str,
        request_size: int
    ) -> RateLimitResult:
        """Check rate limit using fixed window algorithm"""
        
        current_time = datetime.now(timezone.utc)
        window_start = await self.storage.get_window_start(key)
        
        # Initialize or reset window if needed
        if not window_start or (current_time - window_start).total_seconds() >= rule.window_seconds:
            window_start = current_time
            await self.storage.set_window_start(key, window_start, rule.window_seconds * 2)
            current_count = 0
        else:
            current_count = await self.storage.get_count(key, rule.window_seconds)
        
        # Check if request would exceed limit
        if current_count + request_size > rule.limit:
            reset_time = window_start + timedelta(seconds=rule.window_seconds)
            retry_after = int((reset_time - current_time).total_seconds())
            
            return RateLimitResult(
                allowed=False,
                rule_name=rule.name,
                current_count=current_count,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
                reset_time=reset_time,
                retry_after_seconds=max(1, retry_after),
                details={
                    "algorithm": rule.algorithm.value,
                    "scope": rule.scope.value,
                    "window_start": window_start.isoformat(),
                }
            )
        
        # Request is allowed
        reset_time = window_start + timedelta(seconds=rule.window_seconds)
        
        return RateLimitResult(
            allowed=True,
            rule_name=rule.name,
            current_count=current_count,
            limit=rule.limit,
            window_seconds=rule.window_seconds,
            reset_time=reset_time,
            details={
                "algorithm": rule.algorithm.value,
                "scope": rule.scope.value,
                "window_start": window_start.isoformat(),
            }
        )
    
    async def _check_sliding_window(
        self,
        rule: RateLimitRule,
        key: str,
        request_size: int
    ) -> RateLimitResult:
        """Check rate limit using sliding window algorithm"""
        
        current_time = time.time()
        window_start_time = current_time - rule.window_seconds
        
        # Get recent timestamps within the window
        timestamps = await self.storage.get_request_timestamps(key, window_start_time)
        current_count = len(timestamps)
        
        # Check if request would exceed limit
        if current_count + request_size > rule.limit:
            # Calculate when the oldest request will expire
            if timestamps:
                oldest_timestamp = min(timestamps)
                retry_after = int(oldest_timestamp + rule.window_seconds - current_time) + 1
            else:
                retry_after = rule.window_seconds
            
            reset_time = datetime.fromtimestamp(current_time + retry_after, tz=timezone.utc)
            
            return RateLimitResult(
                allowed=False,
                rule_name=rule.name,
                current_count=current_count,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
                reset_time=reset_time,
                retry_after_seconds=max(1, retry_after),
                details={
                    "algorithm": rule.algorithm.value,
                    "scope": rule.scope.value,
                    "window_start_time": window_start_time,
                    "timestamps_count": len(timestamps),
                }
            )
        
        # Request is allowed
        reset_time = datetime.fromtimestamp(current_time + rule.window_seconds, tz=timezone.utc)
        
        return RateLimitResult(
            allowed=True,
            rule_name=rule.name,
            current_count=current_count,
            limit=rule.limit,
            window_seconds=rule.window_seconds,
            reset_time=reset_time,
            details={
                "algorithm": rule.algorithm.value,
                "scope": rule.scope.value,
                "window_start_time": window_start_time,
                "timestamps_count": len(timestamps),
            }
        )
    
    async def _check_token_bucket(
        self,
        rule: RateLimitRule,
        key: str,
        request_size: int
    ) -> RateLimitResult:
        """Check rate limit using token bucket algorithm"""
        
        current_time = time.time()
        bucket_key = f"{key}:bucket"
        last_refill_key = f"{key}:last_refill"
        
        # Get current token count and last refill time
        current_tokens = await self.storage.get_count(bucket_key, rule.window_seconds)
        last_refill_time = await self.storage.get_window_start(last_refill_key)
        
        if not last_refill_time:
            # Initialize bucket with full tokens
            last_refill_time = datetime.fromtimestamp(current_time, tz=timezone.utc)
            max_tokens = rule.burst_limit or rule.limit
            current_tokens = max_tokens
            await self.storage.increment_count(bucket_key, rule.window_seconds, max_tokens)
            await self.storage.set_window_start(
                last_refill_key,
                last_refill_time,
                rule.window_seconds * 2
            )
        else:
            # Calculate tokens to add based on time elapsed
            time_elapsed = current_time - last_refill_time.timestamp()
            tokens_to_add = int(time_elapsed * (rule.limit / rule.window_seconds))
            
            if tokens_to_add > 0:
                # Refill tokens (up to limit)
                max_tokens = rule.burst_limit or rule.limit
                new_token_count = min(max_tokens, current_tokens + tokens_to_add)
                
                if new_token_count > current_tokens:
                    # Update token count in storage
                    await self.storage.increment_count(
                        bucket_key, 
                        rule.window_seconds, 
                        new_token_count - current_tokens
                    )
                    current_tokens = new_token_count
                
                # Update last refill time
                await self.storage.set_window_start(
                    last_refill_key,
                    datetime.fromtimestamp(current_time, tz=timezone.utc),
                    rule.window_seconds * 2
                )
        
        # Check if we have enough tokens
        if current_tokens < request_size:
            # Calculate retry after time
            tokens_needed = request_size - current_tokens
            retry_after = int(tokens_needed * (rule.window_seconds / rule.limit)) + 1
            
            reset_time = datetime.fromtimestamp(current_time + retry_after, tz=timezone.utc)
            
            return RateLimitResult(
                allowed=False,
                rule_name=rule.name,
                current_count=rule.limit - current_tokens,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
                reset_time=reset_time,
                retry_after_seconds=retry_after,
                details={
                    "algorithm": rule.algorithm.value,
                    "scope": rule.scope.value,
                    "tokens_available": current_tokens,
                    "tokens_needed": request_size,
                }
            )
        
        # Consume tokens
        new_token_count = current_tokens - request_size
        await self.storage.increment_count(bucket_key, rule.window_seconds, -request_size)
        
        reset_time = datetime.fromtimestamp(current_time + rule.window_seconds, tz=timezone.utc)
        
        return RateLimitResult(
            allowed=True,
            rule_name=rule.name,
            current_count=rule.limit - new_token_count,
            limit=rule.limit,
            window_seconds=rule.window_seconds,
            reset_time=reset_time,
            details={
                "algorithm": rule.algorithm.value,
                "scope": rule.scope.value,
                "tokens_remaining": new_token_count,
                "tokens_consumed": request_size,
            }
        )
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics"""
        storage_stats = await self.storage.get_stats()
        
        return {
            "rules_count": len(self.rules),
            "default_rule": {
                "name": self.default_rule.name,
                "scope": self.default_rule.scope.value,
                "algorithm": self.default_rule.algorithm.value,
                "limit": self.default_rule.limit,
                "window_seconds": self.default_rule.window_seconds,
            },
            "cache_size": len(self._rule_cache),
            "storage": storage_stats,
        }
    
    async def cleanup(self) -> None:
        """Clean up expired entries"""
        current_time = time.time()
        await self.storage.cleanup_expired(current_time - 3600)  # Clean up entries older than 1 hour
        
        # Clean up rule cache
        expired_keys = [
            key for key, timestamp in self._cache_timestamps.items()
            if current_time - timestamp > self._cache_ttl
        ]
        for key in expired_keys:
            self._rule_cache.pop(key, None)
            self._cache_timestamps.pop(key, None)


STRICT_AUTH_ENDPOINTS = (
    "/auth/first-run/setup",
    "/auth/login",
    "/auth/refresh",
)


# Default rate limiting rules
DEFAULT_RATE_LIMIT_RULES = [
    # High priority rule for unauthenticated credential/session-minting edges.
    RateLimitRule(
        name="auth_strict",
        scope=RateLimitScope.IP_ENDPOINT,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        limit=10,
        window_seconds=60,
        priority=100,
        endpoints=list(STRICT_AUTH_ENDPOINTS),
        description=(
            "Strict IP and endpoint throttling for public authentication "
            "credential/session-minting endpoints"
        )
    ),
    
    # User-specific limits
    RateLimitRule(
        name="user_general",
        scope=RateLimitScope.USER,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        limit=1000,
        window_seconds=3600,  # 1 hour
        burst_limit=100,
        priority=50,
        description="General rate limiting per user"
    ),
    
    # IP-based limits
    RateLimitRule(
        name="ip_general",
        scope=RateLimitScope.IP,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        limit=300,
        window_seconds=60,
        priority=25,
        description="General rate limiting per IP address"
    ),
    
    # Global fallback
    RateLimitRule(
        name="global_fallback",
        scope=RateLimitScope.GLOBAL,
        algorithm=RateLimitAlgorithm.FIXED_WINDOW,
        limit=10000,
        window_seconds=60,
        priority=1,
        description="Global rate limiting fallback"
    ),
]


def create_rate_limiter(
    storage_type: str = "memory",
    redis_url: Optional[str] = None,
    custom_rules: Optional[List[RateLimitRule]] = None
) -> EnhancedRateLimiter:
    """
    Factory function to create a rate limiter with appropriate storage
    
    Args:
        storage_type: "memory" or "redis"
        redis_url: Redis connection URL (required for Redis storage)
        custom_rules: Custom rate limiting rules (optional)
    
    Returns:
        Configured EnhancedRateLimiter instance
    """
    
    # Create storage
    if storage_type == "redis":
        if not REDIS_AVAILABLE:
            raise RuntimeError("Redis is not available. Install redis package.")
        if not redis_url:
            raise ValueError("redis_url is required for Redis storage")
        
        redis_client = redis_asyncio.from_url(redis_url, decode_responses=True)
        storage = RedisRateLimitStorage(redis_client)
    else:
        storage = MemoryRateLimitStorage()
    
    # Use custom rules or defaults
    rules = custom_rules or DEFAULT_RATE_LIMIT_RULES
    
    return EnhancedRateLimiter(storage, rules)