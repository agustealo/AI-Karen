"""Bounded spreading activation for AI-Karen associative recall.

Associative activation is a retrieval primitive. It does not own durable graph
truth, persistence, final NeuroRecall ranking, or truth confidence.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from ai_karen_engine.core.memory.contracts import RecallScoreComponents
from ai_karen_engine.core.memory.types import CognitiveMemoryEntry


@dataclass
class AssociationGraph:
    """Bounded in-process view of memory associations used for recall compute."""

    nodes: Dict[str, CognitiveMemoryEntry] = field(default_factory=dict)
    edges: Dict[str, List[str]] = field(default_factory=dict)
    concept_index: Dict[str, List[str]] = field(default_factory=dict)

    def add_memory(self, entry: CognitiveMemoryEntry) -> None:
        """Add or refresh one memory in the associative compute view."""
        memory_id = entry.base_entry.id
        self.nodes[memory_id] = entry
        self.edges[memory_id] = list(entry.associations)

    def add_association(self, source_id: str, target_id: str) -> None:
        """Add one directed association without duplicating an existing edge."""
        neighbors = self.edges.setdefault(source_id, [])
        if target_id not in neighbors:
            neighbors.append(target_id)

    def get_neighbors(self, memory_id: str, depth: int = 1) -> Set[str]:
        """Return unique neighbors reachable within ``depth`` hops.

        The seed is never returned. Traversal is cycle-safe and intentionally
        bounded because this structure is a recall-time compute view, not a
        durable graph repository.
        """
        if depth <= 0:
            return set()

        discovered: Set[str] = set()
        visited: Set[str] = {memory_id}
        queue = deque([(memory_id, 0)])

        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            for neighbor in self.edges.get(current, []):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                discovered.add(neighbor)
                queue.append((neighbor, current_depth + 1))

        return discovered


class SpreadingActivation:
    """Compute bounded associative activation over an ``AssociationGraph``."""

    def __init__(
        self,
        graph: AssociationGraph,
        *,
        activation_decay: float = 0.5,
        max_propagation_depth: int = 3,
    ) -> None:
        if not 0.0 <= activation_decay <= 1.0:
            raise ValueError("activation_decay must be between 0 and 1")
        if max_propagation_depth < 0:
            raise ValueError("max_propagation_depth must be non-negative")
        self.graph = graph
        self.activation_decay = activation_decay
        self.max_propagation_depth = max_propagation_depth

    def activate(
        self,
        seed_concepts: List[str],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, float]:
        """Spread activation from seed concepts and return memory-local scores.

        ``context`` is retained for compatibility with callers that already
        provide recall context. It is deliberately not interpreted here;
        authorized scope and temporal filtering belong upstream when the
        canonical graph neighborhood is materialized.
        """
        del context

        activations: Dict[str, float] = {}
        queue = deque()

        for concept in seed_concepts:
            for memory_id in self.graph.concept_index.get(concept, []):
                if activations.get(memory_id, 0.0) < 1.0:
                    activations[memory_id] = 1.0
                    queue.append((memory_id, 1.0, 0))

        while queue:
            current_id, current_activation, depth = queue.popleft()
            if depth >= self.max_propagation_depth:
                continue

            for neighbor in self.graph.edges.get(current_id, []):
                new_activation = current_activation * self.activation_decay
                if new_activation <= activations.get(neighbor, -1.0):
                    continue
                activations[neighbor] = new_activation
                queue.append((neighbor, new_activation, depth + 1))

        return activations

    def compute_recall_score(
        self,
        base_score: RecallScoreComponents,
        activations: Dict[str, float],
    ) -> float:
        """Add bounded associative activation to an existing recall score."""
        if not activations:
            return base_score.total()
        max_activation = max(activations.values())
        base_score.associative_activation = max_activation * 2.0
        return base_score.total()
