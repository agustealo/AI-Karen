"""
Offline Mode Indicator

Phase 2: Provides offline status and capabilities for frontend integration.
- Detects offline state (no server connectivity)
- Provides API for frontend to show offline indicator
- Sync status tracking (for Phase 3)

Frontend Integration:
    <OfflineIndicator />
        {isOffline && <span>Offline Mode</span>}
        {!isOffline && <span>Online</span>}
    </OfflineIndicator>

Use Cases:
1. User disconnects from network → Show offline indicator
2. Sync status → Show "Last synced: 5 min ago"
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from ai_karen_engine.core.logging import get_logger

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logger = get_logger(__name__)


class OfflineMode:
    """
    Offline mode detector and status tracker.
    
    Features:
    - Connectivity checks (configurable endpoints)
    - Sync status tracking
    - Graceful degradation
    - Frontend API
    """
    
    def __init__(
        self,
        check_interval: int = 30,  # seconds
        check_timeout: int = 3,  # seconds
        health_endpoints: list[str] | None = None,
    ):
        """
        Initialize offline mode detector.
        
        Args:
            check_interval: How often to check connectivity (seconds)
            check_timeout: Timeout for health checks (seconds)
            health_endpoints: List of URLs to check
        """
        self.check_interval = check_interval
        self.check_timeout = check_timeout
        self.health_endpoints = health_endpoints or [
            "https://www.google.com",
            "https://api.github.com",
        ]
        
        # State
        self.is_offline = False
        self.last_check = None
        self.last_sync = None
        self._running = False
        self._task: asyncio.Task | None = None
        
        # Callbacks
        self.on_state_change = None
        
    async def start(self) -> None:
        """Start background connectivity check."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("[OfflineMode] Started connectivity monitoring")
        
        # Initial check
        await self._check_connectivity()
    
    async def stop(self) -> None:
        """Stop background connectivity check."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("[OfflineMode] Stopped connectivity monitoring")
    
    async def _check_loop(self) -> None:
        """Background loop to check connectivity."""
        while self._running:
            try:
                await self._check_connectivity()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as ex:
                logger.warning(f"[OfflineMode] Check loop error: {ex}")
    
    async def _check_connectivity(self) -> None:
        """Check network connectivity."""
        was_offline = self.is_offline
        self.is_offline = False
        self.last_check = datetime.utcnow()
        
        if AIOHTTP_AVAILABLE:
            try:
                # Check all endpoints with timeout
                timeout = aiohttp.ClientTimeout(total=self.check_timeout)
                
                for endpoint in self.health_endpoints:
                    try:
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(endpoint, timeout=timeout) as response:
                                if response.status == 200:
                                    break
                    except Exception:
                        # Try next endpoint
                        continue
                else:
                    # All endpoints failed
                    self.is_offline = True
                    
            except Exception as ex:
                logger.debug(f"[OfflineMode] Connectivity check failed: {ex}")
                self.is_offline = True
        else:
            # If aiohttp not available, assume online
            pass
        
        # Detect state change
        if was_offline != self.is_offline:
            logger.info(f"[OfflineMode] State changed: {'offline' if self.is_offline else 'online'}")
            if self.on_state_change:
                try:
                    if asyncio.iscoroutinefunction(self.on_state_change):
                        await self.on_state_change(self.is_offline)
                    else:
                        self.on_state_change(self.is_offline)
                except Exception as ex:
                    logger.error(f"[OfflineMode] State change callback error: {ex}")
    
    def get_status(self) -> dict[str, Any]:
        """
        Get current offline status for frontend.
        
        Returns:
            Dict with status information
            {
                "is_offline": bool,
                "last_check": ISO timestamp,
                "last_sync": ISO timestamp,
                "capabilities": List[str],
            }
        """
        capabilities = []
        if not self.is_offline:
            capabilities.append("server_search")
            capabilities.append("cloud_sync")
        
        return {
            "is_offline": self.is_offline,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "capabilities": capabilities,
        }
    
    def update_last_sync(self, timestamp: datetime | None = None) -> None:
        """Update last sync timestamp (for Phase 3)."""
        self.last_sync = timestamp or datetime.utcnow()
        logger.info(f"[OfflineMode] Last sync: {self.last_sync.isoformat()}")
    
    def force_offline(self, offline: bool = True) -> None:
        """
        Force offline mode (for testing or manual override).
        Args:
            offline: True to force offline, False to reset
        """
        was_offline = self.is_offline
        self.is_offline = offline
        logger.info(f"[OfflineMode] Forced offline mode: {offline}")
        
        if was_offline != self.is_offline:
            if self.on_state_change:
                try:
                    if asyncio.iscoroutinefunction(self.on_state_change):
                        asyncio.create_task(self.on_state_change(self.is_offline))
                    else:
                        self.on_state_change(self.is_offline)
                except Exception as ex:
                    logger.error(f"[OfflineMode] State change callback error: {ex}")


# Singleton instance
_offline_mode_instance: OfflineMode | None = None


def get_offline_mode(
    check_interval: int = 30,
    check_timeout: int = 3,
    health_endpoints: list[str] | None = None,
) -> OfflineMode:
    """
    Get or create global offline mode instance.
    
    Args:
        check_interval: How often to check connectivity (seconds)
        check_timeout: Timeout for health checks (seconds)
        health_endpoints: List of URLs to check
        
    Returns:
        OfflineMode instance
    """
    global _offline_mode_instance
    
    if _offline_mode_instance is None:
        _offline_mode_instance = OfflineMode(
            check_interval=check_interval,
            check_timeout=check_timeout,
            health_endpoints=health_endpoints,
        )
        logger.info("[OfflineMode] Created global offline mode instance")
    
    return _offline_mode_instance


__all__ = [
    "OfflineMode",
    "OfflineModeManager",
    "get_offline_mode",
]


OfflineModeManager = OfflineMode
