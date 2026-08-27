"""Secure authentication middleware with explicit tenant scope."""

from __future__ import annotations

import base64
import os
import secrets
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import jwt
import redis
from fastapi import Request
from fastapi.security import HTTPBearer

from ai_karen_engine.config.config_manager import get_config_manager
from ai_karen_engine.core.logging import get_logger, get_structured_logger
from ai_karen_engine.platform.observability.metrics import (
    get_metrics_collector as get_metrics_manager,
)

logger = get_logger(__name__)
security = HTTPBearer()


def _load_auth_jwt_secret() -> str:
    """Resolve the JWT secret using the shared config-layer precedence."""
    from ai_karen_engine.config.config_manager import resolve_jwt_secret

    secret = resolve_jwt_secret()
    if not secret:
        env = os.getenv("ENVIRONMENT", "development").lower()
        if env == "production":
            logger.error("CRITICAL: No JWT secret configured in production environment!")
            raise RuntimeError("Authentication secret must be configured in production")
        return "fallback_secret_key_for_development_only"
    return secret


def _explicit_tenant_id(value: Any) -> str:
    tenant_id = str(value or "").strip()
    if not tenant_id or tenant_id == "default":
        raise AuthenticationError("Explicit non-default tenant scope is required", 403)
    return tenant_id


class TokenStatus(Enum):
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"
    REVOKED = "revoked"
    RATE_LIMITED = "rate_limited"


class AuthenticationError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class SecureAuthMiddleware:
    """Authentication middleware with JWT, revocation, rate limits, and audit."""

    def __init__(self):
        self.config_manager: Optional[Any] = None
        self.structured_logger: Optional[Any] = None
        self.metrics_manager: Optional[Any] = None
        self.jwt_secret = _load_auth_jwt_secret()
        self.jwt_algorithm: str = "HS256"
        self.jwt_expiration_hours: int = 8
        self.refresh_token_expiration_days: int = 30
        self.redis_client: Optional[Union[redis.Redis, Any]] = None

        try:
            self.config_manager = get_config_manager()
            self.structured_logger = get_structured_logger()
            self.metrics_manager = get_metrics_manager()
            if self.config_manager is not None:
                config = self.config_manager.get_config()
                if config is not None:
                    if hasattr(config, "security") and hasattr(
                        config.security, "jwt_secret"
                    ):
                        cfg_secret = config.security.jwt_secret
                        if cfg_secret and cfg_secret != "your-secret-key":
                            self.jwt_secret = cfg_secret
                        self.jwt_algorithm = config.security.jwt_algorithm
                        if hasattr(config.security, "access_token_expire_minutes"):
                            self.jwt_expiration_hours = (
                                config.security.access_token_expire_minutes // 60
                            )
                        else:
                            self.jwt_expiration_hours = config.security.jwt_expiration // 3600
                    elif hasattr(config, "secret_key"):
                        cfg_secret = config.secret_key
                        if cfg_secret:
                            self.jwt_secret = cfg_secret
                        self.jwt_algorithm = getattr(config, "algorithm", "HS256")
                        self.jwt_expiration_hours = (
                            getattr(config, "access_token_expire_minutes", 30 * 24 * 60)
                            // 60
                        )
                    elif hasattr(config, "auth") and hasattr(config.auth, "secret_key"):
                        cfg_secret = config.auth.secret_key
                        if cfg_secret and cfg_secret != "changeme":
                            self.jwt_secret = cfg_secret
                        self.jwt_algorithm = getattr(config.auth, "algorithm", "HS256")
                        self.jwt_expiration_hours = (
                            getattr(config.auth, "access_token_expire_minutes", 30) // 60
                        )
                self._init_redis()
            logger.info("SecureAuthMiddleware initialized with full services")
        except Exception as exc:
            logger.warning(
                "Failed to initialize full auth services, using fallback mode: %s",
                exc,
            )

        self.auth_rate_limits = {
            "login_attempts": {"window": 300, "limit": 5},
            "token_refresh": {"window": 3600, "limit": 10},
            "password_reset": {"window": 3600, "limit": 3},
        }
        self.failed_attempts: Dict[str, List[Dict[str, Any]]] = {}

    def _init_redis(self) -> None:
        """Initialize the auth-only Redis client for revocation/rate-limit state."""
        try:
            if self.config_manager is None:
                self.redis_client = None
                return
            config = self.config_manager.get_config()
            if config is None or not hasattr(config, "redis"):
                self.redis_client = None
                return

            redis_host = config.redis.host
            redis_port = config.redis.port
            redis_password = config.redis.password
            redis_url = f"redis://{redis_host}:{redis_port}/0"
            if redis_password:
                redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/0"

            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=False,
            )
            try:
                self.redis_client.ping()
                logger.info("Connected to auth token revocation store")
            except Exception as exc:
                logger.warning(
                    "Could not connect to auth Redis store; revocation checks may degrade: %s",
                    exc,
                )
        except Exception as exc:
            logger.error("Failed to initialize auth Redis client: %s", exc)
            self.redis_client = None

    def _get_redis_key(self, key_type: str, identifier: str) -> str:
        return f"auth:{key_type}:{identifier}"

    def _hash_password(self, password: str, salt: str) -> str:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt.encode(),
            iterations=100000,
        )
        return kdf.derive(password.encode()).hex()

    def _verify_password(self, password: str, hashed_password: str, salt: str) -> bool:
        return self._hash_password(password, salt) == hashed_password

    def _generate_token_id(self) -> str:
        return secrets.token_urlsafe(32)

    def _create_jwt_payload(
        self, user_data: Dict[str, Any], token_id: str
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        tenant_id = _explicit_tenant_id(user_data.get("tenant_id"))
        return {
            "sub": user_data["user_id"],
            "email": user_data.get("email", ""),
            "user_type": user_data.get("user_type", "user"),
            "permissions": user_data.get("permissions", []),
            "tenant_id": tenant_id,
            "roles": user_data.get("roles", []),
            "token_id": token_id,
            "iat": now,
            "exp": now + timedelta(hours=self.jwt_expiration_hours),
            "iss": "ai-karen",
            "aud": "ai-karen-users",
        }

    def _create_refresh_token_payload(
        self, user_data: Dict[str, Any], token_id: str
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        return {
            "sub": user_data["user_id"],
            "tenant_id": _explicit_tenant_id(user_data.get("tenant_id")),
            "token_id": token_id,
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(days=self.refresh_token_expiration_days),
            "iss": "ai-karen",
            "aud": "ai-karen-refresh",
        }

    def _encode_jwt(self, payload: Dict[str, Any]) -> str:
        return jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)

    def _decode_jwt(self, token: str) -> Dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm],
                audience="ai-karen-users",
                issuer="ai-karen",
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            logger.debug("JWT decode failed using configured algorithm")
            raise AuthenticationError(f"Invalid token: {exc}") from exc

    def _decode_refresh_token(self, token: str) -> Dict[str, Any]:
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm],
                audience="ai-karen-refresh",
                issuer="ai-karen",
            )
            payload["tenant_id"] = _explicit_tenant_id(payload.get("tenant_id"))
            return payload
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Refresh token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError(f"Invalid refresh token: {exc}") from exc

    def _is_token_revoked(self, token_id: str) -> bool:
        if self.redis_client is None:
            return False
        try:
            return bool(self.redis_client.exists(self._get_redis_key("revoked", token_id)))
        except Exception as exc:
            logger.warning("Failed to check token revocation: %s", exc)
            return False

    def _revoke_token(self, token_id: str, exp: datetime) -> bool:
        if self.redis_client is None:
            return False
        try:
            ttl = max(1, int((exp - datetime.utcnow()).total_seconds()))
            self.redis_client.setex(self._get_redis_key("revoked", token_id), ttl, "1")
            return True
        except Exception as exc:
            logger.warning("Failed to revoke token: %s", exc)
            return False

    def _check_rate_limit(self, user_id: str, action: str) -> bool:
        limit_config = self.auth_rate_limits.get(action)
        if not limit_config:
            return True
        if self.redis_client:
            try:
                key = self._get_redis_key(f"rate_limit:{action}", user_id)
                count = self.redis_client.get(key)
                if count and int(count) >= limit_config["limit"]:
                    return False
                return True
            except Exception as exc:
                logger.warning("Redis rate limit check failed: %s", exc)
        now = time.time()
        attempts = self.failed_attempts.get(user_id, [])
        attempts = [
            attempt
            for attempt in attempts
            if now - attempt["timestamp"] < limit_config["window"]
        ]
        self.failed_attempts[user_id] = attempts
        return len(attempts) < limit_config["limit"]

    def _record_failed_attempt(self, user_id: str, action: str, reason: str) -> None:
        limit_config = self.auth_rate_limits.get(action)
        if not limit_config:
            return
        if self.redis_client:
            try:
                key = self._get_redis_key(f"rate_limit:{action}", user_id)
                pipe = self.redis_client.pipeline()
                pipe.incr(key)
                pipe.expire(key, limit_config["window"])
                pipe.execute()
                return
            except Exception as exc:
                logger.warning("Redis failed attempt recording failed: %s", exc)
        attempts = self.failed_attempts.setdefault(user_id, [])
        attempts.append({"timestamp": time.time(), "action": action, "reason": reason})

    def _extract_token_from_request(self, request: Request) -> Optional[str]:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]
        cookie_token = request.cookies.get("kari_session")
        if cookie_token:
            return cookie_token
        return request.cookies.get("access_token")

    def _extract_session_token_from_request(self, request: Request) -> Optional[str]:
        session_token = request.cookies.get("kari_session")
        if session_token:
            return session_token
        return request.cookies.get("session_token") or request.cookies.get("access_token")

    def _extract_basic_auth(self, request: Request) -> Optional[tuple[str, str]]:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            return None
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            return username, password
        except Exception:
            return None

    def is_public_endpoint(self, path: str) -> bool:
        public_patterns = [
            "/health",
            "/api/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/auth/validate-session",
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/refresh",
            "/api/auth/forgot-password",
            "/api/auth/reset-password",
            "/api/auth/first-run",
            "/api/auth/first-run/setup",
            "/api/public",
            "/ws",
        ]
        allow_public_copilot = os.getenv("ALLOW_PUBLIC_COPILOT", "false").lower() in (
            "1",
            "true",
            "yes",
        )
        if allow_public_copilot:
            public_patterns.extend(
                [
                    "/api/copilot",
                    "/api/conversations/ensure-session",
                    "/api/conversations/by-session",
                    "/api/auth/me",
                ]
            )
        return any(path.startswith(pattern) for pattern in public_patterns)

    async def validate_token(self, token: str) -> Dict[str, Any]:
        try:
            payload = self._verify_access_token(token)
            return {"status": TokenStatus.VALID, "payload": payload}
        except AuthenticationError as exc:
            if "expired" in str(exc).lower():
                return {"status": TokenStatus.EXPIRED, "error": str(exc)}
            return {"status": TokenStatus.INVALID, "error": str(exc)}
        except Exception as exc:
            return {"status": TokenStatus.INVALID, "error": str(exc)}

    def _verify_access_token(self, token: str) -> Dict[str, Any]:
        payload = self._decode_jwt(token)
        payload["tenant_id"] = _explicit_tenant_id(payload.get("tenant_id"))
        token_id = payload.get("token_id")
        if token_id and self._is_token_revoked(token_id):
            raise AuthenticationError("Token has been revoked")
        return payload

    def _get_user_from_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "user_id": payload["sub"],
            "email": payload.get("email"),
            "user_type": payload.get("user_type", "user"),
            "permissions": payload.get("permissions", []),
            "tenant_id": _explicit_tenant_id(payload.get("tenant_id")),
            "token_id": payload.get("token_id"),
            "roles": payload.get("roles", []),
        }

    async def authenticate_request(self, request: Request) -> Dict[str, Any]:
        return await self.get_current_user(request)

    async def get_current_user(self, request: Request) -> Dict[str, Any]:
        path = request.url.path
        is_public = self.is_public_endpoint(path)
        try:
            token = self._extract_token_from_request(request)
            if token:
                try:
                    payload = self._verify_access_token(token)
                    return self._get_user_from_payload(payload)
                except AuthenticationError as exc:
                    if not is_public:
                        logger.warning(
                            "Access token verification failed for %s: %s", path, exc
                        )
                except Exception as exc:
                    logger.error(
                        "Unexpected error verifying access token for %s: %s", path, exc
                    )

            session_token = self._extract_session_token_from_request(request)
            if session_token:
                token_result = await self.validate_token(session_token)
                if token_result["status"] == TokenStatus.VALID:
                    return self._get_user_from_payload(token_result["payload"])
                if not is_public:
                    raise AuthenticationError(
                        token_result.get("error") or "Session token invalid"
                    )

            if is_public:
                return {
                    "user_id": "anonymous",
                    "email": None,
                    "user_type": "anonymous",
                    "permissions": [],
                    "tenant_id": None,
                    "authenticated": False,
                }
            raise AuthenticationError("No authentication token provided")
        except AuthenticationError:
            raise
        except Exception as exc:
            logger.error("Error authenticating request: %s", exc)
            if is_public:
                return {
                    "user_id": "anonymous",
                    "email": None,
                    "user_type": "anonymous",
                    "permissions": [],
                    "tenant_id": None,
                    "authenticated": False,
                }
            raise AuthenticationError("Failed to authenticate user") from exc


_auth_middleware: Optional[SecureAuthMiddleware] = None


def get_auth_middleware() -> SecureAuthMiddleware:
    global _auth_middleware
    if _auth_middleware is None:
        _auth_middleware = SecureAuthMiddleware()
    return _auth_middleware


async def get_current_user(request: Request) -> Dict[str, Any]:
    state_user = getattr(request.state, "user", None)
    if isinstance(state_user, dict):
        return state_user
    return await get_auth_middleware().get_current_user(request)


async def get_rate_limiter() -> SecureAuthMiddleware:
    return get_auth_middleware()


__all__ = [
    "AuthenticationError",
    "SecureAuthMiddleware",
    "TokenStatus",
    "get_auth_middleware",
    "get_current_user",
    "get_rate_limiter",
]
