"""
Provider Health Monitor Service

This service monitors the health status of various AI providers and services
to provide context-aware error responses and intelligent routing decisions.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from ai_karen_engine.services.cache import get_provider_cache

from ai_karen_engine.core.logging import get_logger
logger = get_logger(__name__)


class HealthStatus(str, Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ProviderHealthInfo:
    """Extended provider health information"""
    name: str
    status: HealthStatus
    last_check: datetime
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    consecutive_failures: int = 0
    success_rate: float = 1.0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class ProviderHealthMonitor:
    """Service for monitoring provider health status"""
    
    def __init__(self, check_interval: int = 300):  # 5 minutes default
        self.check_interval = check_interval
        self._health_cache: Dict[str, ProviderHealthInfo] = {}
        self._cache_ttl = 300  # 5 minutes
        self._monitoring_active = False
        self._enhanced_cache = get_provider_cache()
        self._known_providers = [
            "builtin_vllm",
            "builtin_transformers",
            "openai",
            "anthropic",
            "google",
            "huggingface",
            "cohere",
        ]
    
    def get_provider_health(self, provider_name: str) -> Optional[ProviderHealthInfo]:
        """
        Get cached health status for a provider with enhanced caching
        
        Args:
            provider_name: Name of the provider to check
            
        Returns:
            ProviderHealthInfo if available, None otherwise
        """
        provider_key = provider_name.lower()
        
        # Check enhanced cache first
        cached_health = self._enhanced_cache.get_provider_health(provider_key)
        if cached_health:
            return ProviderHealthInfo(
                name=cached_health["name"],
                status=HealthStatus(cached_health["status"]),
                last_check=datetime.fromisoformat(cached_health["last_check"]),
                response_time=cached_health.get("response_time"),
                error_message=cached_health.get("error_message"),
                consecutive_failures=cached_health.get("consecutive_failures", 0),
                success_rate=cached_health.get("success_rate", 1.0),
                last_success=datetime.fromisoformat(cached_health["last_success"]) if cached_health.get("last_success") else None,
                last_failure=datetime.fromisoformat(cached_health["last_failure"]) if cached_health.get("last_failure") else None,
                metadata=cached_health.get("metadata")
            )
        
        # Fallback to legacy cache
        if provider_key in self._health_cache:
            health_info = self._health_cache[provider_key]
            
            # Check if cache is still valid
            cache_age = (datetime.utcnow() - health_info.last_check).total_seconds()
            if cache_age < self._cache_ttl:
                return health_info
            else:
                logger.debug(f"Health cache expired for {provider_name}")
        
        # Return unknown status if not cached or expired
        return ProviderHealthInfo(
            name=provider_name,
            status=HealthStatus.UNKNOWN,
            last_check=datetime.utcnow(),
            metadata={"cache_miss": True}
        )
    
    def update_provider_health(
        self,
        provider_name: str,
        is_healthy: bool,
        response_time: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Update health status for a provider
        
        Args:
            provider_name: Name of the provider
            is_healthy: Whether the provider is currently healthy
            response_time: Response time in seconds
            error_message: Error message if unhealthy
        """
        provider_key = provider_name.lower()
        now = datetime.utcnow()
        
        # Get existing health info or create new
        if provider_key in self._health_cache:
            health_info = self._health_cache[provider_key]
        else:
            health_info = ProviderHealthInfo(
                name=provider_name,
                status=HealthStatus.UNKNOWN,
                last_check=now,
                consecutive_failures=0,
                success_rate=1.0
            )
        
        # Capture previous status for change detection
        prev_status = health_info.status if 'health_info' in locals() else HealthStatus.UNKNOWN

        # Update health status
        if is_healthy:
            health_info.status = HealthStatus.HEALTHY
            health_info.consecutive_failures = 0
            health_info.last_success = now
            health_info.error_message = None
        else:
            health_info.consecutive_failures += 1
            health_info.last_failure = now
            health_info.error_message = error_message
            
            # Determine status based on failure count
            if health_info.consecutive_failures >= 5:
                health_info.status = HealthStatus.UNHEALTHY
            elif health_info.consecutive_failures >= 2:
                health_info.status = HealthStatus.DEGRADED
            else:
                health_info.status = HealthStatus.HEALTHY
        
        # Update timing information
        health_info.last_check = now
        health_info.response_time = response_time
        
        # Calculate success rate (simple moving average over last 10 attempts)
        # This is a simplified implementation - in production you'd want more sophisticated metrics
        if hasattr(health_info, '_recent_attempts'):
            health_info._recent_attempts.append(is_healthy)
            if len(health_info._recent_attempts) > 10:
                health_info._recent_attempts.pop(0)
        else:
            health_info._recent_attempts = [is_healthy]
        
        health_info.success_rate = sum(health_info._recent_attempts) / len(health_info._recent_attempts)
        
        # Cache the updated health info in both caches
        self._health_cache[provider_key] = health_info
        
        # Cache in enhanced cache as well
        health_dict = {
            "name": health_info.name,
            "status": health_info.status.value,
            "last_check": health_info.last_check.isoformat(),
            "response_time": health_info.response_time,
            "error_message": health_info.error_message,
            "consecutive_failures": health_info.consecutive_failures,
            "success_rate": health_info.success_rate,
            "last_success": health_info.last_success.isoformat() if health_info.last_success else None,
            "last_failure": health_info.last_failure.isoformat() if health_info.last_failure else None,
            "metadata": health_info.metadata
        }
        
        self._enhanced_cache.cache_provider_health(provider_key, health_dict)
        
        logger.debug(f"Updated health for {provider_name}: {health_info.status.value}")

        # Invalidate routing cache on status change
        # KIRE retired: routing cache invalidation is owned by RuntimeResilience.
        try:
            pass
        except Exception:
            pass
    
    def get_all_provider_health(self) -> Dict[str, ProviderHealthInfo]:
        """Get health status for all known providers"""
        result = {}
        
        for provider in self._known_providers:
            health_info = self.get_provider_health(provider)
            if health_info:
                result[provider] = health_info
        
        return result
    
    def get_healthy_providers(self) -> List[str]:
        """Get list of currently healthy providers"""
        healthy_providers = []
        
        for provider in self._known_providers:
            health_info = self.get_provider_health(provider)
            if health_info and health_info.status == HealthStatus.HEALTHY:
                healthy_providers.append(provider)
        
        return healthy_providers
    
    def get_alternative_providers(self, failed_provider: str) -> List[str]:
        """
        Get list of alternative providers when one fails
        
        Args:
            failed_provider: The provider that failed
            
        Returns:
            List of alternative healthy providers
        """
        alternatives = []
        failed_provider_key = failed_provider.lower()
        
        for provider in self._known_providers:
            if provider.lower() != failed_provider_key:
                health_info = self.get_provider_health(provider)
                if health_info and health_info.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]:
                    alternatives.append(provider)
        
        # Sort by success rate (best first)
        alternatives.sort(
            key=lambda p: self.get_provider_health(p).success_rate,
            reverse=True
        )
        
        return alternatives
    
    def record_provider_interaction(
        self,
        provider_name: str,
        success: bool,
        response_time: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Record the result of an interaction with a provider
        
        This method should be called after each API call to track provider health
        
        Args:
            provider_name: Name of the provider
            success: Whether the interaction was successful
            response_time: Response time in seconds
            error_message: Error message if failed
        """
        self.update_provider_health(
            provider_name=provider_name,
            is_healthy=success,
            response_time=response_time,
            error_message=error_message
        )
    
    def get_provider_recommendations(self, error_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get provider recommendations based on current health status
        
        Args:
            error_context: Context about the error that occurred
            
        Returns:
            Dictionary with recommendations and alternatives
        """
        failed_provider = error_context.get("provider_name")
        
        recommendations = {
            "failed_provider": failed_provider,
            "alternatives": [],
            "health_summary": {},
            "suggestions": []
        }
        
        if failed_provider:
            # Get alternatives
            alternatives = self.get_alternative_providers(failed_provider)
            recommendations["alternatives"] = alternatives[:3]  # Top 3 alternatives
            
            # Add specific suggestions based on failure type
            failed_health = self.get_provider_health(failed_provider)
            if failed_health:
                if failed_health.status == HealthStatus.UNHEALTHY:
                    recommendations["suggestions"].append(
                        f"{failed_provider} is currently experiencing issues. Try using {alternatives[0] if alternatives else 'an alternative provider'}."
                    )
                elif failed_health.consecutive_failures > 0:
                    recommendations["suggestions"].append(
                        f"{failed_provider} has had recent issues. Consider switching to a backup provider."
                    )
        
        # Add general health summary
        all_health = self.get_all_provider_health()
        recommendations["health_summary"] = {
            name: {
                "status": info.status.value,
                "success_rate": info.success_rate,
                "last_check": info.last_check.isoformat() if info.last_check else None
            }
            for name, info in all_health.items()
        }
        
        return recommendations
    
    def clear_cache(self) -> None:
        """Clear the health status cache"""
        self._health_cache.clear()
        self._enhanced_cache.cache.clear()
        logger.info("Provider health cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the health cache"""
        now = datetime.utcnow()
        
        stats = {
            "total_providers": len(self._health_cache),
            "healthy_count": 0,
            "degraded_count": 0,
            "unhealthy_count": 0,
            "unknown_count": 0,
            "cache_age_seconds": {},
            "average_response_time": None
        }
        
        response_times = []
        
        for provider_name, health_info in self._health_cache.items():
            # Count by status
            if health_info.status == HealthStatus.HEALTHY:
                stats["healthy_count"] += 1
            elif health_info.status == HealthStatus.DEGRADED:
                stats["degraded_count"] += 1
            elif health_info.status == HealthStatus.UNHEALTHY:
                stats["unhealthy_count"] += 1
            else:
                stats["unknown_count"] += 1
            
            # Track cache age
            cache_age = (now - health_info.last_check).total_seconds()
            stats["cache_age_seconds"][provider_name] = cache_age
            
            # Collect response times
            if health_info.response_time:
                response_times.append(health_info.response_time)
        
        # Calculate average response time
        if response_times:
            stats["average_response_time"] = sum(response_times) / len(response_times)
        
        return stats


# Global instance for easy access
_health_monitor = None


def get_health_monitor() -> ProviderHealthMonitor:
    """Get the global provider health monitor instance"""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = ProviderHealthMonitor()
    return _health_monitor


def record_provider_success(provider_name: str, response_time: Optional[float] = None) -> None:
    """Convenience function to record a successful provider interaction"""
    monitor = get_health_monitor()
    monitor.record_provider_interaction(
        provider_name=provider_name,
        success=True,
        response_time=response_time
    )


def record_provider_failure(provider_name: str, error_message: str) -> None:
    """Convenience function to record a failed provider interaction"""
    monitor = get_health_monitor()
    monitor.record_provider_interaction(
        provider_name=provider_name,
        success=False,
        error_message=error_message
    )
