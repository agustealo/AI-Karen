"""
Memory Lifecycle for AI-Karen

Defines the canonical memory lifecycle:
PERCEIVE → ENCODE → SCORE_SALIENCE → ASSOCIATE → STORE_EPISODE →
REPLAY_REFLECT → CONSOLIDATE → GENERALIZE → RETRIEVE →
RECONSOLIDATE → DECAY_SUPERSEDE_FORGET

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.memory.contracts import (
    MemoryClaim,
    ProspectiveMemory,
    RecallScoreComponents,
    SalienceScore,
)
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryStatus


# ===================================
# LIFECYCLE STATE
# ===================================

class LifecycleEvent(str, Enum):
    """Events that trigger lifecycle transitions."""
    PERCEIVED = "perceived"
    ENCODED = "encoded"
    SALIENCE_SCORED = "salience_scored"
    ASSOCIATED = "associated"
    STORED = "stored"
    REPLAYED = "replayed"
    REFLECTED = "reflected"
    CONSOLIDATED = "consolidated"
    GENERALIZED = "generalized"
    RETRIEVED = "retrieved"
    RECONSOLIDATED = "reconsolidated"
    DECAYED = "decayed"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


@dataclass
class LifecycleState:
    """Current state of a memory in the lifecycle."""
    state: str = "perceive"
    memory_id: Optional[str] = None
    entered_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ===================================
# LIFECYCLE HOOKS
# ===================================

class LifecycleHook(ABC):
    """Base class for lifecycle hooks."""

    @abstractmethod
    async def on_event(self, event: LifecycleEvent, memory: MemoryEntry, context: Dict[str, Any]) -> Optional[MemoryEntry]:
        """Handle a lifecycle event. Return modified memory or None."""
        pass


class MemoryLifecycle:
    """
    Manages the memory lifecycle for a single memory entry.

    The lifecycle is:
    PERCEIVE → ENCODE → SCORE_SALIENCE → ASSOCIATE → STORE_EPISODE →
    REPLAY_REFLECT → CONSOLIDATE → GENERALIZE → RETRIEVE →
    RECONSOLIDATE → DECAY_SUPERSEDE_FORGET
    """

    TRANSITIONS = {
        "perceive": ["encode"],
        "encode": ["score_salience"],
        "score_salience": ["associate"],
        "associate": ["store_episode"],
        "store_episode": ["replay_reflect", "retrieve"],
        "replay_reflect": ["consolidate"],
        "consolidate": ["generalize"],
        "generalize": ["retrieve"],
        "retrieve": ["reconsolidate", "decay_supersede_forget"],
        "reconsolidate": ["retrieve", "decay_supersede_forget"],
        "decay_supersede_forget": [],
    }

    def __init__(self, memory: MemoryEntry):
        self.memory = memory
        self.state = LifecycleState(state="perceive", memory_id=memory.id)
        self.hooks: List[LifecycleHook] = []

    def add_hook(self, hook: LifecycleHook) -> None:
        """Add a lifecycle hook."""
        self.hooks.append(hook)

    async def transition(self, event: LifecycleEvent, context: Dict[str, Any]) -> bool:
        """Attempt to transition to a new state."""
        current = self.state.state
        allowed = self.TRANSITIONS.get(current, [])
        target = event.value.replace("_", " ") if hasattr(event, "value") else str(event)

        # Map event to state
        state_map = {
            "perceived": "perceive",
            "encoded": "encode",
            "salience_scored": "score_salience",
            "associated": "associate",
            "stored": "store_episode",
            "replayed": "replay_reflect",
            "reflected": "replay_reflect",
            "consolidated": "consolidate",
            "generalized": "generalize",
            "retrieved": "retrieve",
            "reconsolidated": "reconsolidate",
            "decayed": "decay_supersede_forget",
            "superseded": "decay_supersede_forget",
            "forgotten": "decay_supersede_forget",
        }
        next_state = state_map.get(target, target)

        if next_state not in allowed:
            return False

        # Run hooks
        for hook in self.hooks:
            result = await hook.on_event(event, self.memory, context)
            if result is not None:
                self.memory = result

        self.state = LifecycleState(state=next_state, memory_id=self.memory.id)
        return True

    def can_transition(self, event: LifecycleEvent) -> bool:
        """Check if transition is allowed."""
        current = self.state.state
        allowed = self.TRANSITIONS.get(current, [])
        target = event.value.replace("_", " ") if hasattr(event, "value") else str(event)
        state_map = {
            "perceived": "perceive",
            "encoded": "encode",
            "salience_scored": "score_salience",
            "associated": "associate",
            "stored": "store_episode",
            "replayed": "replay_reflect",
            "reflected": "replay_reflect",
            "consolidated": "consolidate",
            "generalized": "generalize",
            "retrieved": "retrieve",
            "reconsolidated": "reconsolidate",
            "decayed": "decay_supersede_forget",
            "superseded": "decay_supersede_forget",
            "forgotten": "decay_supersede_forget",
        }
        next_state = state_map.get(target, target)
        return next_state in allowed
