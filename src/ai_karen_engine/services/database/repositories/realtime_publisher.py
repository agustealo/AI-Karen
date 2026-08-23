"""
Realtime contract for KAREN's UI event bus.

RealtimePublisher is the canonical abstraction for broadcasting
application events to connected clients. The default implementation
uses Supabase Realtime Broadcast, but the contract allows other
transports without touching runtime code.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .base import Repository, RepositoryResult

logger = logging.getLogger(__name__)


@dataclass
class RealtimeEvent:
    """Canonical realtime event envelope."""

    topic: str
    event: str
    payload: Dict[str, Any] = field(default_factory=dict)
    tenant_id: Optional[str] = None
    correlation_id: Optional[str] = None


class RealtimePublisher(Repository):
    """Canonical contract for realtime event publication.

    Runtime code must NOT import Supabase SDK directly.
    """

    @abstractmethod
    async def publish(self, topic: str, event: str, payload: Dict[str, Any]) -> None:
        """Publish a single event to a topic."""

    @abstractmethod
    async def publish_many(self, events: List[Tuple[str, str, Dict[str, Any]]]) -> None:
        """Publish multiple events in a single batch."""

    @abstractmethod
    async def health_check(self) -> RepositoryResult:
        """Return publisher health metadata."""


__all__ = [
    "RealtimeEvent",
    "RealtimePublisher",
]
