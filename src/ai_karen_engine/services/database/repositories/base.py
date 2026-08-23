"""Canonical repository contracts for KAREN's durable data layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class RepositoryResult:
    """Standard result envelope for repository operations."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Repository(ABC):
    """Base repository contract."""

    @abstractmethod
    async def health_check(self) -> RepositoryResult:
        """Verify repository connectivity and basic operability."""
