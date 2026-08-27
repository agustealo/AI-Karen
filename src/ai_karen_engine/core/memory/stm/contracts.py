"""Canonical short-term memory contracts.

STM owns bounded cross-request continuity semantics. Physical storage belongs to
platform adapters such as Redis. Durable history belongs to NeuroVault/Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class STMSlot(str, Enum):
    """Bounded session-state slots with independent physical keys/TTLs."""

    ACTIVE_EPISODE = "active_episode"
    ACTIVE_GOAL = "active_goal"
    ACTIVE_PROJECT = "active_project"
    RECENT_CONTEXT = "recent_context"
    WORKING_STATE = "working_state"
    TOOL_STATE = "tool_state"


@dataclass(frozen=True, slots=True)
class STMScope:
    """Fail-closed identity scope for session-oriented STM."""

    tenant_id: str
    user_id: str
    session_id: str

    def validate(self) -> None:
        required = {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError(f"STM scope missing required fields: {', '.join(missing)}")
        if self.tenant_id == "default":
            raise ValueError("STM tenant_id must be explicit and non-default")


@runtime_checkable
class STMPort(Protocol):
    """Backend-neutral bounded short-term memory boundary."""

    async def get_slot(self, *, scope: STMScope, slot: STMSlot) -> dict[str, Any] | None: ...

    async def put_slot(
        self,
        *,
        scope: STMScope,
        slot: STMSlot,
        value: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> bool: ...

    async def delete_slot(self, *, scope: STMScope, slot: STMSlot) -> bool: ...

    def degraded(self) -> bool: ...


__all__ = ["STMScope", "STMSlot", "STMPort"]
