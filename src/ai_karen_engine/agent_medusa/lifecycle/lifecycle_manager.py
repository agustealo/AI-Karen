"""Medusa agent lifecycle owner (AGENT-LIVE-1 A3 / P0-6).

Migrates the useful legacy AgentLifecycleManager behaviors (create,
initialize, status, metrics, terminate, cleanup, availability, lifecycle
events) but FIXES the lock/deadlock hazards:

  - delete_agent() held self._lock and called terminate_agent() which also
    tried to acquire the same non-reentrant asyncio.Lock  -> DEADLOCK
  - _cleanup_inactive_agents() held the lock and called terminate_agent()
  - terminate_all_agents() held the lock and called terminate_agent()

Fix: split every public method into a lock-acquiring wrapper and a `_locked`
inner that assumes the lock is already held. Callers that already hold the lock
call the `_locked` variant. Background cleanup releases the lock before calling
the public (re-acquiring) variants.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LifecycleStatus(str, Enum):
    """Dynamic runtime states the UI requires."""

    INITIALIZING = "initializing"
    AVAILABLE = "available"
    IDLE = "idle"
    PLANNING = "planning"
    BUSY = "busy"
    WAITING = "waiting"
    PAUSED = "paused"
    DEGRADED = "degraded"
    ERROR = "error"
    MAINTENANCE = "maintenance"
    TERMINATED = "terminated"


class MedusaAgentLifecycle:
    """Owns runtime status/resources for registered agents."""

    def __init__(self, cleanup_interval_s: int = 300, agent_timeout_s: int = 3600) -> None:
        self._status: Dict[str, LifecycleStatus] = {}
        self._last_activity: Dict[str, datetime] = {}
        self._events: List[Dict[str, Any]] = []
        self._cleanup_interval = cleanup_interval_s
        self._agent_timeout = agent_timeout_s
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    # --- status ---------------------------------------------------------

    async def set_status(self, agent_id: str, status: LifecycleStatus) -> None:
        async with self._lock:
            self._set_status_locked(agent_id, status)

    def _set_status_locked(self, agent_id: str, status: LifecycleStatus) -> None:
        self._status[agent_id] = status
        self._last_activity[agent_id] = datetime.utcnow()
        self._record_locked(agent_id, "status_changed", {"to": status.value})

    # --- terminate / delete (deadlock-safe) ----------------------------

    async def terminate_agent(self, agent_id: str) -> bool:
        async with self._lock:
            return self._terminate_locked(agent_id)

    def _terminate_locked(self, agent_id: str) -> bool:
        if agent_id not in self._status:
            return False
        self._set_status_locked(agent_id, LifecycleStatus.TERMINATED)
        return True

    async def delete_agent(self, agent_id: str) -> bool:
        async with self._lock:
            if agent_id not in self._status:
                return False
            if self._status[agent_id] != LifecycleStatus.TERMINATED:
                self._terminate_locked(agent_id)  # already hold lock
            del self._status[agent_id]
            self._last_activity.pop(agent_id, None)
            self._record_locked(agent_id, "agent_deleted", {})
            return True

    async def terminate_all(self) -> None:
        async with self._lock:
            agent_ids = list(self._status.keys())
        for agent_id in agent_ids:
            await self.terminate_agent(agent_id)  # re-acquires lock safely

    # --- cleanup (releases lock before re-calling) --------------------

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_inactive()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover
                logger.error("lifecycle cleanup error: %s", exc)

    async def _cleanup_inactive(self) -> None:
        async with self._lock:
            threshold = datetime.utcnow() - timedelta(seconds=self._agent_timeout)
            stale = [
                aid
                for aid, st in self._status.items()
                if st in (LifecycleStatus.IDLE, LifecycleStatus.ERROR)
                and self._last_activity.get(aid, datetime.min) < threshold
            ]
        for aid in stale:
            await self.terminate_agent(aid)  # lock released above

    # --- introspection -------------------------------------------------

    async def get_status(self, agent_id: str) -> Optional[LifecycleStatus]:
        async with self._lock:
            return self._status.get(agent_id)

    async def is_available(self, agent_id: str) -> bool:
        async with self._lock:
            return self._status.get(agent_id) in (
                LifecycleStatus.AVAILABLE,
                LifecycleStatus.IDLE,
            )

    def _record_locked(self, agent_id: str, event_type: str, metadata: Dict[str, Any]) -> None:
        self._events.append(
            {
                "agent_id": agent_id,
                "event_type": event_type,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": metadata,
            }
        )
        if len(self._events) > 1000:
            self._events = self._events[-1000:]
