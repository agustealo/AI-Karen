"""Enhanced rate limiting middleware with configurable rules and optimizations."""

import ipaddress
import logging
import os
import socket
import time
from typing import Any, Optional

try:
    from fastapi import Request
    from fastapi.responses import JSONResponse
except Exception:  # pragma: no cover - fallback for tests
    from ai_karen_engine.fastapi_stub import Request, JSONResponse

from ai_karen_engine.server.rate_limiter import (
    DEFAULT_RATE_LIMIT_RULES,
    EnhancedRateLimiter,
    RateLimitAlgorithm,
    RateLimitRule,
    RateLimitScope,
    create_rate_limiter,
)
from ai_karen_engine.services.usage.service import UsageService

logger = logging.getLogger(__name__)

# Global rate limiter instance
_rate_limiter: Optional[EnhancedRateLimiter] = None
_rate_limiter_config: dict[str, Any] = {
    "storage_type": "memory",
    "redis_url": None,
    "trusted_proxy_hosts": (),
}
_proxy_address_cache: dict[str, tuple[float, frozenset[str]]] = {}
_PROXY_ADDRESS_CACHE_TTL_SECONDS = 30.0


def _csv_values(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def configure_rate_limiter(
    storage_type: str = "memory",
    redis_url: Optional[str] = None,
    custom_rules: Optional[list] = None,
    trusted_proxy_hosts: Optional[list[str]] = None,
) -> None:
    """Configure the global rate limiter instance and transport trust boundary."""
    global _rate_limiter, _rate_limiter_config

    configured_proxy_hosts = trusted_proxy_hosts
    if configured_proxy_hosts is None:
        configured_proxy_hosts = _csv_values(
            os.getenv("RATE_LIMIT_TRUSTED_PROXY_HOSTS", "")
        )

    _rate_limiter_config.update(
        {
            "storage_type": storage_type,
            "redis_url": redis_url,
            "trusted_proxy_hosts": tuple(configured_proxy_hosts),
        }
    )
    _proxy_address_cache.clear()

    try:
        _rate_limiter = create_rate_limiter(
            storage_type=storage_type,
            redis_url=redis_url,
            custom_rules=custom_rules,
        )
        logger.info(
            "Rate limiter configured with %s storage and %d trusted proxy host(s)",
            storage_type,
            len(configured_proxy_hosts),
        )
    except Exception as exc:
        logger.error("Failed to configure rate limiter: %s", exc)
        # Fallback to memory storage. This keeps the limiter active rather than
        # silently disabling transport throttling when Redis is unavailable.
        _rate_limiter = create_rate_limiter(storage_type="memory")
        logger.info("Rate limiter configured with memory storage (fallback)")


def get_rate_limiter() -> EnhancedRateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter

    if _rate_limiter is None:
        configure_rate_limiter()

    return _rate_limiter


def _normalize_ip(value: Any) -> Optional[str]:
    """Normalize one IP literal without accepting hostnames or header chains."""
    candidate = str(value or "").strip().strip("[]")
    if not candidate or "," in candidate:
        return None
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return address.compressed


def _resolve_proxy_host(host: str) -> frozenset[str]:
    """Resolve a configured proxy hostname with a short cache for container churn."""
    literal = _normalize_ip(host)
    if literal:
        return frozenset({literal})

    now = time.monotonic()
    cached = _proxy_address_cache.get(host)
    if cached and now - cached[0] < _PROXY_ADDRESS_CACHE_TTL_SECONDS:
        return cached[1]

    resolved: set[str] = set()
    try:
        for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM):
            normalized = _normalize_ip(info[4][0])
            if normalized:
                resolved.add(normalized)
    except OSError:
        logger.warning("Unable to resolve configured rate-limit proxy host %s", host)

    result = frozenset(resolved)
    _proxy_address_cache[host] = (now, result)
    return result


def _peer_is_trusted_proxy(peer_ip: str) -> bool:
    normalized_peer = _normalize_ip(peer_ip)
    if not normalized_peer:
        return False
    for host in _rate_limiter_config.get("trusted_proxy_hosts", ()):
        if normalized_peer in _resolve_proxy_host(str(host)):
            return True
    return False


def _principal_value(principal: Any, key: str) -> Any:
    """Read one field from canonical authenticated principal state."""
    if isinstance(principal, dict):
        return principal.get(key)
    return getattr(principal, key, None)


def _canonical_user_id(principal: Any) -> Optional[str]:
    """Return only a durable authenticated user identifier from principal state."""
    if principal is None:
        return None

    authenticated = _principal_value(principal, "authenticated")
    if authenticated is False:
        return None

    raw_user_id = _principal_value(principal, "user_id") or _principal_value(
        principal, "id"
    )
    user_id = str(raw_user_id or "").strip()
    if not user_id or user_id.lower() == "anonymous":
        return None
    return user_id


def _canonical_user_type(principal: Any) -> Optional[str]:
    """Return user type only when it comes from canonical principal state."""
    if _canonical_user_id(principal) is None:
        return None
    user_type = str(_principal_value(principal, "user_type") or "").strip()
    return user_type or None


def _extract_client_info(request: Request) -> tuple[str, Optional[str], Optional[str]]:
    """Extract trusted transport identity plus canonical authenticated identity.

    Direct clients are identified by the ASGI socket peer and cannot override
    that identity with forwarding headers. When the peer resolves to an
    explicitly configured trusted proxy host, exactly one valid
    ``X-Forwarded-For`` address is accepted. The canonical production web
    ingress overwrites that header from its own socket before Next.js handles
    the request, so browser-supplied forwarding headers never become authority.
    """

    raw_peer = request.client.host if request.client else ""
    peer_ip = _normalize_ip(raw_peer) or ""
    trusted_proxy = _peer_is_trusted_proxy(peer_ip)

    if trusted_proxy:
        forwarded_ip = _normalize_ip(request.headers.get("x-forwarded-for"))
        # Fail away from a shared proxy-wide IP bucket when the trusted ingress
        # contract is missing or malformed. Auth's credential-failure limiter
        # still applies while the global limiter falls through to non-IP rules.
        ip_address = forwarded_ip or ""
    else:
        ip_address = peer_ip

    principal = getattr(request.state, "user", None)
    user_id = _canonical_user_id(principal)
    user_type = _canonical_user_type(principal)
    return ip_address, user_id, user_type


def _rate_limit_endpoint(path: str) -> str:
    """Normalize mounted API paths to the rule registry's route-path contract."""
    if path.startswith("/api/"):
        return path[4:]
    return path


def _calculate_request_size(request: Request) -> int:
    """Calculate request size/weight for rate limiting."""

    size = 1
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
            size += max(0, (length - 1024) // 1024)
        except ValueError:
            pass

    path = str(request.url.path).lower()
    if any(
        expensive in path
        for expensive in ["/search", "/export", "/report", "/analyze"]
    ):
        size += 5

    return min(size, 10)


async def rate_limit_middleware(request: Request, call_next):
    """Apply canonical transport rate limiting before request execution."""

    start_time = time.time()

    try:
        logger.debug("Rate limit middleware: Starting")

        request_path = str(request.url.path)
        if request_path in ["/health", "/metrics", "/docs", "/openapi.json", "/redoc"]:
            logger.debug(
                "Rate limit middleware: Skipping rate limiting for system endpoint: %s",
                request_path,
            )
            return await call_next(request)

        limiter = get_rate_limiter()
        logger.debug("Rate limit middleware: Got rate limiter")

        ip_address, user_id, user_type = _extract_client_info(request)
        logger.debug(
            "Rate limit middleware: Extracted canonical client info - IP: %s, User: %s, Type: %s",
            ip_address or "unavailable",
            user_id,
            user_type,
        )

        endpoint = _rate_limit_endpoint(request_path)
        request_size = _calculate_request_size(request)
        logger.debug(
            "Rate limit middleware: Endpoint: %s, Size: %s",
            endpoint,
            request_size,
        )

        result = await limiter.check_rate_limit(
            ip_address=ip_address,
            endpoint=endpoint,
            user_id=user_id,
            user_type=user_type,
            request_size=request_size,
        )
        logger.debug("Rate limit middleware: Rate limit check completed")

        if not result.allowed:
            try:
                UsageService.increment(
                    "rate_limit_exceeded",
                    user_id=user_id or ip_address or "anonymous",
                )
            except Exception:
                pass

            logger.warning(
                "Rate limit exceeded for client on %s",
                request_path,
                extra={
                    "ip_address": ip_address or None,
                    "user_id": user_id,
                    "endpoint": request_path,
                    "rule_name": result.rule_name,
                    "current_count": result.current_count,
                    "limit": result.limit,
                    "window_seconds": result.window_seconds,
                    "retry_after": result.retry_after_seconds,
                },
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": (
                        "Too many requests. Try again in "
                        f"{result.retry_after_seconds} seconds."
                    ),
                    "details": {
                        "rule": result.rule_name,
                        "limit": result.limit,
                        "window_seconds": result.window_seconds,
                        "current_count": result.current_count,
                        "reset_time": result.reset_time.isoformat(),
                    },
                },
                headers={
                    "Retry-After": str(result.retry_after_seconds),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": str(
                        max(0, result.limit - result.current_count)
                    ),
                    "X-RateLimit-Reset": str(int(result.reset_time.timestamp())),
                    "X-RateLimit-Rule": result.rule_name,
                },
            )

        await limiter.record_request(
            ip_address=ip_address,
            endpoint=endpoint,
            user_id=user_id,
            user_type=user_type,
            request_size=request_size,
        )

        response = await call_next(request)
        if request_path.startswith("/api/copilot/assist"):
            logger.warning(
                "rate_limit_middleware received response: %s",
                type(response).__name__ if response is not None else "None",
            )

        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, result.limit - result.current_count - request_size)
        )
        response.headers["X-RateLimit-Reset"] = str(int(result.reset_time.timestamp()))
        response.headers["X-RateLimit-Rule"] = result.rule_name

        processing_time = time.time() - start_time
        if processing_time > 1.0:
            logger.info(
                "Slow request processed: %s took %.2fs",
                request_path,
                processing_time,
                extra={
                    "ip_address": ip_address or None,
                    "user_id": user_id,
                    "endpoint": request_path,
                    "processing_time": processing_time,
                    "request_size": request_size,
                },
            )

        return response

    except Exception as exc:
        error_message = str(exc).lower()
        if "authentication required" in error_message or "authentication" in error_message:
            logger.debug(
                "Rate limiting middleware encountered authentication dependency: %s",
                exc,
            )
            return await call_next(request)

        logger.error("Rate limiting middleware error: %s", exc, exc_info=True)
        logger.error("Error type: %s", type(exc).__name__)
        logger.error("Error args: %s", exc.args)
        return await call_next(request)


async def legacy_rate_limit_middleware(request: Request, call_next):
    """Compatibility wrapper around the canonical rate-limit middleware."""
    return await rate_limit_middleware(request, call_next)
