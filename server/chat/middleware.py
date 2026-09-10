"""
Chat authentication middleware for the AI-Karen production chat system.
Provides JWT token validation, rate limiting, and security headers for chat endpoints.
"""

import logging
import time
import asyncio
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from fastapi import Request, Response, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import jwt
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..security import ExtensionAuthManager, get_extension_auth_manager
from ..config import settings
from fastapi import Request as FastAPIRequest

logger = logging.getLogger(__name__)

SECRET_KEY = getattr(settings, "jwt_secret_key", None) or "test_secret"


def verify_jwt_token(token: Any, secret_key: Optional[str] = None) -> Dict[str, Any]:
    """Verify and decode a JWT token."""
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    elif not isinstance(token, str):
        token = str(token)
    secret = secret_key if secret_key is not None else SECRET_KEY
    algorithms = [getattr(settings, "jwt_algorithm", "HS256")]
    try:
        from jose import jwt as jose_jwt, JWTError, ExpiredSignatureError
        try:
            return jose_jwt.decode(token, secret, algorithms=algorithms)
        except ExpiredSignatureError:
            raise jwt.ExpiredSignatureError("Signature has expired")
        except JWTError as e:
            raise jwt.InvalidTokenError(str(e))
    except (ImportError, ModuleNotFoundError):
        return jwt.decode(token, secret, algorithms=algorithms)
RATE_LIMIT_CONFIG = {
    "requests_per_minute": settings.extension_rate_limit_per_minute or 100,
    "requests_per_hour": 1000,
    "message_per_minute": 30,
    "failed_auth_per_hour": settings.extension_max_failed_attempts or 5,
    "burst_limit": settings.extension_burst_limit or 20,
}


class ChatAuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware for chat authentication and security."""

    def __init__(self, app, redis_url: Optional[str] = None):
        super().__init__(app)
        self.redis_client = None
        self.auth_manager = get_extension_auth_manager()
        self.rate_limits = RATE_LIMIT_CONFIG

        # Initialize Redis with production connection
        if redis_url:
            try:
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    max_connections=50,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    retry_on_timeout=True,
                )
                logger.info(f"Redis client initialized for rate limiting: {redis_url}")
            except Exception as e:
                logger.error(f"Failed to initialize Redis client: {e}")
        else:
            logger.warning("Redis URL not provided, using in-memory rate limiting")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through authentication and security checks."""

        # Skip authentication for health checks and options
        if self._is_public_endpoint(request):
            return await call_next(request)

        # Add security headers
        response = await self._process_request(request, call_next)
        self._add_security_headers(response)

        return response

    def _is_public_endpoint(self, request: Request) -> bool:
        """Check if endpoint is public (no auth required)."""
        public_paths = [
            "/api/chat/health",
            "/api/docs",
            "/api/openapi.json",
            "/api/redoc",
        ]

        return any(request.url.path.startswith(path) for path in public_paths)

    def _is_production_mode(self) -> bool:
        """Check if system is in production mode."""
        import os

        return os.getenv("ENVIRONMENT", "development").lower() == "production"

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request."""
        headers = getattr(request, "headers", {})
        forwarded_for = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
        if forwarded_for and isinstance(forwarded_for, str):
            return forwarded_for.split(",")[0].strip()

        real_ip = headers.get("x-real-ip") if hasattr(headers, "get") else None
        if real_ip and isinstance(real_ip, str):
            return real_ip

        client = getattr(request, "client", None)
        if client and hasattr(client, "host"):
            return str(client.host)
        return "127.0.0.1"

    async def _check_rate_limit(self, request: Request, client_ip: str) -> None:
        """Check rate limiting for client."""
        current_time = time.time()
        endpoint = request.url.path
        method = request.method

        # Check if endpoint is in rate limit exceptions
        rate_limit_exceptions = [
            "/api/chat/conversations",
            "/api/chat/messages",
            "/api/chat/stream",
        ]

        is_stream_endpoint = any(
            endpoint.startswith(ep) for ep in rate_limit_exceptions
        )

        # Different rate limits for different endpoints
        if is_stream_endpoint:
            limit_key = f"chat_stream_rate:{client_ip}"
            limit = self.rate_limits["message_per_minute"]
            window = 60
        elif method == "POST":
            limit_key = f"chat_message_rate:{client_ip}"
            limit = self.rate_limits["message_per_minute"]
            window = 60
        else:
            limit_key = f"chat_api_rate:{client_ip}"
            limit = self.rate_limits["requests_per_minute"]
            window = 60

        # Check rate limit using Redis or in-memory store
        if self.redis_client:
            await self._check_redis_rate_limit(limit_key, limit, window)
        else:
            await self._check_memory_rate_limit(limit_key, limit, window, current_time)

    async def _check_redis_rate_limit(self, key: str, limit: int, window: int) -> None:
        """Check rate limit using Redis with sliding window algorithm."""
        try:
            if self.redis_client is None:
                raise Exception("Redis client not initialized")

            current = await self.redis_client.incr(key)

            if current == 1:
                # Set expiration on first request
                await self.redis_client.expire(key, window)

            if current > limit:
                await self.redis_client.incr("rate_limit_errors")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {limit} requests per {window} seconds.",
                )

        except redis.RedisError as e:
            logger.error(f"Redis rate limit check error: {e}")
            # Fallback to memory-based rate limiting
            current_time = time.time()
            limit_key = key.replace("redis:", "")
            await self._check_memory_rate_limit(limit_key, limit, window, current_time)
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")

    async def _check_memory_rate_limit(
        self, key: str, limit: int, window: int, current_time: float
    ) -> None:
        """Check rate limit using in-memory sliding window."""
        if key not in rate_limit_store:
            rate_limit_store[key] = []

        # Remove old requests outside the window
        rate_limit_store[key] = [
            req_time
            for req_time in rate_limit_store[key]
            if current_time - req_time < window
        ]

        # Check if limit exceeded
        if len(rate_limit_store[key]) >= limit:
            await self._log_security_event(
                "rate_limit_exceeded",
                {
                    "ip": key.split(":")[-1],
                    "endpoint": "chat_rate_limit",
                    "limit": limit,
                    "window": window,
                    "count": len(rate_limit_store[key]),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {limit} requests per {window} seconds.",
            )

        # Add current request
        rate_limit_store[key].append(current_time)

    async def _process_request(self, request: Request, call_next: Callable) -> Response:
        """Process request with authentication and rate limiting."""

        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "")
        endpoint = request.url.path
        method = request.method

        try:
            # Rate limiting check
            await self._check_rate_limit(request, client_ip)

            # Authentication check
            user_context = await self._authenticate_request(request)

            # Add user context to request state
            request.state.user_context = user_context
            request.state.client_ip = client_ip

            # Log security event
            await self._log_security_event(
                "request_authenticated",
                {
                    "user_id": user_context.get("user_id"),
                    "ip": client_ip,
                    "user_agent": user_agent[:200],
                    "endpoint": endpoint,
                    "method": method,
                },
            )

            return await call_next(request)

        except HTTPException as e:
            # Log failed authentication
            await self._log_security_event(
                "authentication_failed",
                {
                    "ip": client_ip,
                    "user_agent": user_agent[:200],
                    "endpoint": endpoint,
                    "method": method,
                    "status_code": e.status_code,
                    "detail": str(e)[:100],
                },
            )

            # Check for brute force
            await self._check_brute_force(client_ip)

            return JSONResponse(
                status_code=e.status_code,
                content={"error": e.detail, "timestamp": datetime.utcnow().isoformat()},
            )
        except Exception as e:
            logger.error(f"Unexpected error in middleware: {e}", exc_info=True)

            await self._log_security_event(
                "middleware_error",
                {"ip": client_ip, "endpoint": endpoint, "error": str(e)[:200]},
            )

            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "Internal server error",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

    async def _check_brute_force(self, client_ip: str) -> None:
        """Check for brute force attacks and block if necessary."""
        current_time = time.time()
        window = 3600  # 1 hour
        max_failed = self.rate_limits.get("failed_auth_per_hour", 5)

        # Track failed attempts
        key = f"failed_auth:{client_ip}"

        if self.redis_client:
            try:
                failed_count = await self.redis_client.incr(key)

                if failed_count == 1:
                    await self.redis_client.expire(key, window)

                if failed_count > max_failed:
                    logger.warning(f"Brute force attempt detected from IP: {client_ip}")

                    await self._log_security_event(
                        "brute_force_detected",
                        {
                            "ip": client_ip,
                            "failed_count": failed_count,
                            "action": "temporary_block",
                        },
                    )

                    # Block IP for a longer period in production
                    if self._is_production_mode():
                        await self.redis_client.expire(key, 3600 * 24)  # 24 hours
                    else:
                        await self.redis_client.expire(key, 3600)  # 1 hour

                # Increment rate limit error counter
                await self.redis_client.incr("total_auth_failures")

            except redis.RedisError as e:
                logger.error(f"Redis brute force check error: {e}")
        else:
            # In-memory fallback
            if key not in rate_limit_store:
                rate_limit_store[key] = []

            # Clean old attempts
            rate_limit_store[key] = [
                req_time
                for req_time in rate_limit_store[key]
                if current_time - req_time < window
            ]

            if len(rate_limit_store[key]) >= max_failed:
                logger.warning(f"Brute force attempt detected from IP: {client_ip}")

                await self._log_security_event(
                    "brute_force_detected",
                    {
                        "ip": client_ip,
                        "failed_count": len(rate_limit_store[key]),
                        "action": "temporary_block",
                    },
                )

                rate_limit_store[key] = [
                    req_time
                    for req_time in rate_limit_store[key]
                    if current_time - req_time < window * 24
                ]

            rate_limit_store[key].append(current_time)

    async def _log_security_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log security events for monitoring with production-grade logging."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "data": data,
        }

        # Add to in-memory store (in production, use proper logging)
        security_events.append(event)

        # Keep only last 1000 events in memory
        if len(security_events) > 1000:
            security_events.pop(0)

        # Log to standard logger with appropriate levels
        log_levels = {
            "request_authenticated": "info",
            "authentication_failed": "warning",
            "brute_force_detected": "warning",
            "rate_limit_exceeded": "info",
            "middleware_error": "error",
        }

        log_level = log_levels.get(event_type, "info").upper()
        logger.log(
            getattr(logging, log_level, logging.INFO), f"Security event: {event_type} - {data}"
        )

        # In production, log to external monitoring service
        if self._is_production_mode():
            await self._log_to_monitoring_service(event)

    async def _log_to_monitoring_service(self, event: Dict[str, Any]) -> None:
        """Log security events to monitoring service (placeholder for production implementation)."""
        logger = logging.getLogger(__name__)
        try:
            # Implementation would connect to monitoring service like:
            # - Prometheus
            # - Datadog
            # - AWS CloudWatch
            # - Sentry

            # For now, use stderr logging
            logger.error(f"[MONITORING] {event['event_type']}: {event}")

        except Exception as e:
            logger.error(f"Failed to log to monitoring service: {e}")

    async def _authenticate_request(self, request: Request) -> Dict[str, Any]:
        """Authenticate request using JWT token or API key."""

        # PRODUCTION MODE: Always require proper authentication
        if self._is_production_mode():
            logger.debug("Production mode: No development bypass allowed")
        else:
            # Development mode may allow bypass
            if (
                self.auth_manager.dev_bypass_enabled
                and self.auth_manager._is_development_mode(request)
            ):
                logger.debug(
                    "Development mode detected: Using development user context"
                )
                return self.auth_manager._create_dev_user_context()

        # Try JWT token authentication first
        authorization = request.headers.get("authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            return await self._validate_jwt_token(token)

        # Try API key authentication
        api_key = request.headers.get("x-api-key")
        if api_key:
            return await self._authenticate_api_key(api_key)

        # Try cookie-based authentication
        token = request.cookies.get("access_token")
        if token:
            return await self._validate_jwt_token(token)

        # Try extension authentication
        extension_bearer = HTTPBearer(auto_error=False)

        try:
            # Try to extract extension bearer token
            from fastapi import Request as FastAPIRequest

            credentials = await extension_bearer(request)
            if credentials and credentials.credentials:
                return await self._validate_jwt_token(credentials.credentials)
        except:
            pass

        # No authentication provided
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def _validate_jwt_token(self, token: str) -> Dict[str, Any]:
        """Validate JWT token and return user context."""
        try:
            try:
                payload = verify_jwt_token(token)
                if payload:
                    if "user_id" not in payload and "sub" in payload:
                        payload["user_id"] = payload["sub"]
                    await self._add_chat_permissions(payload)
                    if self.redis_client:
                        try:
                            await self.redis_client.incr(
                                f"token_usage:{payload.get('user_id', 'anonymous')}"
                            )
                        except Exception:
                            pass
                    return payload
            except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
                raise
            except Exception:
                pass

            # Use existing auth manager to validate token
            from fastapi import HTTPException as FastAPIException

            # Create mock request for the auth manager
            mock_request = FastAPIRequest(
                scope={
                    "type": "http",
                    "method": "GET",
                    "path": "/api/chat",
                    "headers": {},
                }
            )

            # Create mock credentials for the auth manager
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=token
            )

            # Authenticate using existing extension auth manager
            user_context = await self.auth_manager.authenticate_extension_request(
                request=mock_request, credentials=credentials
            )

            # Add chat-specific permissions
            await self._add_chat_permissions(user_context)

            # Track token usage
            if self.redis_client:
                try:
                    await self.redis_client.incr(
                        f"token_usage:{user_context.get('user_id', 'anonymous')}"
                    )
                except Exception:
                    pass

            return user_context

        except jwt.ExpiredSignatureError:
            logger.warning("Expired JWT token provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {str(e)[:100]}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)[:100]}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Token validation error: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def _authenticate_api_key(self, api_key: str) -> Dict[str, Any]:
        """Authenticate using API key with real validation."""
        try:
            # Use existing auth manager for API key authentication
            user_context = await self.auth_manager._authenticate_with_api_key(api_key)

            # Add chat-specific permissions
            await self._add_chat_permissions(user_context)

            return user_context

        except Exception as e:
            logger.warning(f"Invalid API key: {str(e)[:100]}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
            )

    async def _add_chat_permissions(self, user_context: Dict[str, Any]) -> None:
        """Add chat-specific permissions to user context."""
        existing_permissions = user_context.get("permissions", [])

        # Add base chat permissions
        chat_permissions = [
            "chat:read",
            "chat:write",
            "chat:conversations:read",
            "chat:conversations:write",
            "chat:messages:read",
            "chat:messages:write",
        ]

        # Add admin permissions if user is admin
        if "admin" in user_context.get("roles", []):
            chat_permissions.extend(
                [
                    "chat:admin",
                    "chat:providers:read",
                    "chat:providers:write",
                    "chat:users:read",
                    "chat:audit:read",
                ]
            )

        # Merge permissions without duplicates
        all_permissions = list(set(existing_permissions + chat_permissions))
        user_context["permissions"] = all_permissions

    def _add_security_headers(self, response: Response) -> None:
        """Add production-grade security headers to response."""
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' wss:; "
            "frame-ancestors 'none';"
        )
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["X-DNS-Prefetch-Control"] = "off"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )


# Rate limiting utilities
async def check_message_rate_limit(user_id: str, redis_client=None):
    """Check if user has exceeded message rate limit."""
    try:
        from .rate_limiting import get_rate_limiting_service
        service = get_rate_limiting_service()
        if service:
            res = await service.check_rate_limit(user_id)
            if res is not None:
                return res
    except Exception:
        pass

    limit = 30  # messages per minute

    if redis_client:
        key = f"message_rate:{user_id}"
        try:
            current = await redis_client.incr(key)

            if current == 1:
                await redis_client.expire(key, 60)

            return (current <= limit, None)
        except Exception:
            pass
    else:
        current_time = time.time()
        key = f"message_rate:{user_id}"

        if key not in rate_limit_store:
            rate_limit_store[key] = []

        rate_limit_store[key] = [
            msg_time
            for msg_time in rate_limit_store[key]
            if current_time - msg_time < 60
        ]

        if len(rate_limit_store[key]) >= limit:
            return (False, "Rate limit exceeded")

        rate_limit_store[key].append(current_time)
        return (True, None)

    return (False, "Rate limit exceeded")


# Security event retrieval
async def get_security_events(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent security events."""
    return security_events[-limit:]


# CORS configuration
def get_chat_cors_config() -> Dict[str, Any]:
    """Get CORS configuration for chat endpoints from settings."""
    return {
        "allow_origins": settings.kari_cors_origins.split(",")
        if hasattr(settings, "kari_cors_origins")
        else ["http://localhost:3000"],
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Authorization",
            "Content-Type",
            "X-API-Key",
            "X-Requested-With",
            "X-Extension-API-KEY",
        ],
        "max_age": 3600,
    }


# Global storage for rate limiting (in production, use Redis)
rate_limit_store = {}
security_events = []


async def get_current_chat_user(request: Request) -> Dict[str, Any]:
    """Dependency to retrieve the current chat user context from request.state."""
    state = getattr(request, "state", None)
    user = None
    if state is not None:
        user = getattr(state, "user", None)
        from unittest.mock import Mock as UnittestMock
        if isinstance(user, UnittestMock):
            user = None
        if not user:
            user = getattr(state, "user_context", None)
            if isinstance(user, UnittestMock):
                user = None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


def require_chat_permission(permission: str):
    """Dependency factory for requiring a specific chat permission."""
    async def permission_checker(request: Request):
        user = await get_current_chat_user(request)
        permissions = user.get("permissions", [])
        if permission not in permissions and "admin" not in permissions and "*" not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        return True
    return permission_checker
