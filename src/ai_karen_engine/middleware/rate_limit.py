"""Enhanced rate limiting middleware with configurable rules and optimizations."""

import logging
import time
from typing import Optional

try:
    from fastapi import Request
    from fastapi.responses import JSONResponse
except Exception:  # pragma: no cover - fallback for tests
    from ai_karen_engine.fastapi_stub import Request, JSONResponse

from ai_karen_engine.server.rate_limiter import (
    EnhancedRateLimiter,
    create_rate_limiter,
    RateLimitRule,
    RateLimitScope,
    RateLimitAlgorithm,
    DEFAULT_RATE_LIMIT_RULES
)
from ai_karen_engine.services.usage.service import UsageService

logger = logging.getLogger(__name__)

# Global rate limiter instance
_rate_limiter: Optional[EnhancedRateLimiter] = None
_rate_limiter_config = {
    "storage_type": "memory",  # Can be configured to "redis"
    "redis_url": None,
}


def configure_rate_limiter(
    storage_type: str = "memory",
    redis_url: Optional[str] = None,
    custom_rules: Optional[list] = None
) -> None:
    """Configure the global rate limiter instance"""
    global _rate_limiter, _rate_limiter_config
    
    _rate_limiter_config.update({
        "storage_type": storage_type,
        "redis_url": redis_url,
    })
    
    try:
        _rate_limiter = create_rate_limiter(
            storage_type=storage_type,
            redis_url=redis_url,
            custom_rules=custom_rules
        )
        logger.info(f"Rate limiter configured with {storage_type} storage")
    except Exception as e:
        logger.error(f"Failed to configure rate limiter: {e}")
        # Fallback to memory storage
        _rate_limiter = create_rate_limiter(storage_type="memory")
        logger.info("Rate limiter configured with memory storage (fallback)")


def get_rate_limiter() -> EnhancedRateLimiter:
    """Get the global rate limiter instance"""
    global _rate_limiter
    
    if _rate_limiter is None:
        configure_rate_limiter()
    
    return _rate_limiter


def _extract_client_info(request: Request) -> tuple[str, Optional[str], Optional[str]]:
    """Extract client information from request"""
    
    # Get IP address
    ip_address = "unknown"
    if request.client:
        ip_address = request.client.host
    
    # Check for forwarded headers
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        ip_address = real_ip
    
    # Get user ID from request state or headers (safely)
    user_id = None
    if hasattr(request, 'state'):
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            user_id = getattr(request.state, "user", None)
    
    # Fallback to headers if state is not available
    if not user_id:
        user_id = request.headers.get("x-user-id")
    
    # Get user type from request state or headers (safely)
    user_type = None
    if hasattr(request, 'state'):
        user_type = getattr(request.state, "user_type", None)
    
    # Fallback to headers if state is not available
    if not user_type:
        user_type = request.headers.get("x-user-type")
    
    return ip_address, user_id, user_type


def _calculate_request_size(request: Request) -> int:
    """Calculate request size/weight for rate limiting"""
    
    # Base size
    size = 1
    
    # Add weight based on content length
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
            # Add 1 point per 1KB of content
            size += max(0, (length - 1024) // 1024)
        except ValueError:
            pass
    
    # Add weight for expensive operations
    path = str(request.url.path).lower()
    if any(expensive in path for expensive in ["/search", "/export", "/report", "/analyze"]):
        size += 5
    
    return min(size, 10)  # Cap at 10 to prevent abuse


async def rate_limit_middleware(request: Request, call_next):
    """Enhanced rate limiting middleware with configurable rules and optimizations."""
    
    start_time = time.time()
    
    try:
        logger.debug("Rate limit middleware: Starting")
        
        # Skip rate limiting for health and system endpoints
        endpoint = str(request.url.path)
        if endpoint in ["/health", "/metrics", "/docs", "/openapi.json", "/redoc"]:
            logger.debug(f"Rate limit middleware: Skipping rate limiting for system endpoint: {endpoint}")
            return await call_next(request)
        
        # Get rate limiter
        limiter = get_rate_limiter()
        logger.debug("Rate limit middleware: Got rate limiter")
        
        # Extract client information
        ip_address, user_id, user_type = _extract_client_info(request)
        logger.debug(f"Rate limit middleware: Extracted client info - IP: {ip_address}, User: {user_id}, Type: {user_type}")
        
        request_size = _calculate_request_size(request)
        logger.debug(f"Rate limit middleware: Endpoint: {endpoint}, Size: {request_size}")
        
        # Check rate limit
        logger.debug("Rate limit middleware: About to check rate limit")
        result = await limiter.check_rate_limit(
            ip_address=ip_address,
            endpoint=endpoint,
            user_id=user_id,
            user_type=user_type,
            request_size=request_size
        )
        logger.debug("Rate limit middleware: Rate limit check completed")
        
        if not result.allowed:
            # Rate limit exceeded
            try:
                UsageService.increment("rate_limit_exceeded", user_id=user_id or ip_address)
            except Exception:
                pass  # Don't fail if usage service is unavailable
            
            # Log rate limit violation
            logger.warning(
                f"Rate limit exceeded for {ip_address} (user: {user_id}) on {endpoint}",
                extra={
                    "ip_address": ip_address,
                    "user_id": user_id,
                    "endpoint": endpoint,
                    "rule_name": result.rule_name,
                    "current_count": result.current_count,
                    "limit": result.limit,
                    "window_seconds": result.window_seconds,
                    "retry_after": result.retry_after_seconds,
                }
            )
            
            # Return rate limit response
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Try again in {result.retry_after_seconds} seconds.",
                    "details": {
                        "rule": result.rule_name,
                        "limit": result.limit,
                        "window_seconds": result.window_seconds,
                        "current_count": result.current_count,
                        "reset_time": result.reset_time.isoformat(),
                    }
                },
                headers={
                    "Retry-After": str(result.retry_after_seconds),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": str(max(0, result.limit - result.current_count)),
                    "X-RateLimit-Reset": str(int(result.reset_time.timestamp())),
                    "X-RateLimit-Rule": result.rule_name,
                }
            )
        
        # Record the request
        await limiter.record_request(
            ip_address=ip_address,
            endpoint=endpoint,
            user_id=user_id,
            user_type=user_type,
            request_size=request_size
        )
        
        # Process the request
        response = await call_next(request)
        if str(request.url.path).startswith("/api/copilot/assist"):
            logger.warning(
                "rate_limit_middleware received response: %s",
                type(response).__name__ if response is not None else "None",
            )
        
        # Add rate limit headers to successful responses
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, result.limit - result.current_count - request_size))
        response.headers["X-RateLimit-Reset"] = str(int(result.reset_time.timestamp()))
        response.headers["X-RateLimit-Rule"] = result.rule_name
        
        # Log successful request processing time
        processing_time = time.time() - start_time
        if processing_time > 1.0:  # Log slow requests
            logger.info(
                f"Slow request processed: {endpoint} took {processing_time:.2f}s",
                extra={
                    "ip_address": ip_address,
                    "user_id": user_id,
                    "endpoint": endpoint,
                    "processing_time": processing_time,
                    "request_size": request_size,
                }
            )
        
        return response
        
    except Exception as e:
        # Check if this is an authentication error that we can safely ignore
        error_message = str(e).lower()
        if "authentication required" in error_message or "authentication" in error_message:
            # This is likely an authentication error from a dependency
            # Log as debug instead of error since it's not critical to rate limiting
            logger.debug(f"Rate limiting middleware encountered authentication dependency: {e}")
            # Continue with request processing without rate limiting
            return await call_next(request)
        
        # Log other errors but don't block requests
        logger.error(f"Rate limiting middleware error: {e}", exc_info=True)
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error args: {e.args}")
        
        # Continue with request processing
        return await call_next(request)


# Backward compatibility function
async def legacy_rate_limit_middleware(request: Request, call_next):
    """Legacy rate limit middleware for backward compatibility"""
    return await rate_limit_middleware(request, call_next)
