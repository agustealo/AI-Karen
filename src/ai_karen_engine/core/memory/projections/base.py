"""
Base Projection Worker for AI Karen Memory System.

Defines the interface and common logic for projecting memory events to various stores.
"""

import abc
import time
from typing import Any

from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)

class ProjectionWorker(abc.ABC):
    """Abstract base class for all projection workers."""

    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    async def project(self, event_data: dict[str, Any], assertion_data: dict[str, Any] | None = None) -> bool:
        """
        Project the memory event/assertion to the target store.
        
        Args:
            event_data: The full memory event record from the ledger.
            assertion_data: The specific memory assertion or profile fact if applicable.
            
        Returns:
            True if successful, False otherwise.
        """

    def get_projection_lag(self, event_timestamp: float) -> float:
        """Calculate the lag between event creation and projection."""
        return time.time() - event_timestamp

class ProjectionResult:
    """Represents the result of a projection attempt."""
    def __init__(self, success: bool, error: str | None = None, retryable: bool = True):
        self.success = success
        self.error = error
        self.retryable = retryable
