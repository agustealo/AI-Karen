"""
Prospective Memory for AI-Karen

Future intention and commitment tracking.
Remembering that there is unfinished business is cognition.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.contracts import ProspectiveMemory


class ProspectiveMemoryStore:
    """
    Stores and manages prospective memories.
    """

    def __init__(self):
        self._memories: Dict[str, ProspectiveMemory] = {}
        self._by_status: Dict[str, List[str]] = {}

    def add(self, memory: ProspectiveMemory) -> str:
        """Add a prospective memory."""
        memory_id = f"pm:{memory.intention}:{datetime.utcnow().timestamp()}"
        self._memories[memory_id] = memory
        status = memory.status
        if status not in self._by_status:
            self._by_status[status] = []
        self._by_status[status].append(memory_id)
        return memory_id

    def get(self, memory_id: str) -> Optional[ProspectiveMemory]:
        """Get a prospective memory by ID."""
        return self._memories.get(memory_id)

    def get_by_status(self, status: str) -> List[ProspectiveMemory]:
        """Get all prospective memories with a given status."""
        memory_ids = self._by_status.get(status, [])
        return [self._memories[mid] for mid in memory_ids if mid in self._memories]

    def get_open(self) -> List[ProspectiveMemory]:
        """Get all open prospective memories."""
        return self.get_by_status("open")

    def complete(self, memory_id: str) -> None:
        """Mark a prospective memory as completed."""
        if memory_id in self._memories:
            memory = self._memories[memory_id]
            memory.status = "completed"
            memory.completed_at = datetime.utcnow()
            # Move to completed list
            if "open" in self._by_status and memory_id in self._by_status["open"]:
                self._by_status["open"].remove(memory_id)
            if "completed" not in self._by_status:
                self._by_status["completed"] = []
            self._by_status["completed"].append(memory_id)

    def cancel(self, memory_id: str) -> None:
        """Cancel a prospective memory."""
        if memory_id in self._memories:
            memory = self._memories[memory_id]
            memory.status = "cancelled"
            if "open" in self._by_status and memory_id in self._by_status["open"]:
                self._by_status["open"].remove(memory_id)
            if "cancelled" not in self._by_status:
                self._by_status["cancelled"] = []
            self._by_status["cancelled"].append(memory_id)

    def check_triggers(self, context: Dict[str, Any]) -> List[ProspectiveMemory]:
        """Check if any prospective memories are triggered by the current context."""
        triggered = []
        for memory in self._memories.values():
            if memory.status != "open":
                continue
            if self._matches_trigger(memory.trigger, context):
                triggered.append(memory)
        return triggered

    def _matches_trigger(self, trigger: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Check if a trigger matches the current context."""
        for key, value in trigger.items():
            if key not in context:
                return False
            if context[key] != value:
                return False
        return True
