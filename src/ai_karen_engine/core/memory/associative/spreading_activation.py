"""
Spreading Activation for AI-Karen

Implements spreading activation for associative recall.
Activation spreads from recalled concepts to graph neighbors.

Author: AI-Karen Core Team
Version: 1.0.0 (Cognitive Architecture)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from ai_karen_engine.core.memory.contracts import RecallScoreComponents
from ai_karen_engine.core.memory.types import CognitiveMemoryEntry


@dataclass
class AssociationGraph:
    """
    Graph of memory associations for spreading activation.
    """
    nodes: Dict[str, CognitiveMemoryEntry] = field(default_factory=dict)
    edges: Dict[str, List[str]] = field(default_factory=dict)  # memory_id -> related memory_ids
    concept_index: Dict[str, List[str]] = field(default_factory=dict)  # concept -> memory_ids

    def add_memory(self, entry: CognitiveMemoryEntry) -> None:
        """Add a memory to the graph."""
        self.nodes[entry.base_entry.id] = entry
        self.edges[entry.base_entry.id] = entry.associations

    def add_association(self, source_id: str, target_id: str) -> None:
        """Add an association between two memories."""
        if source_id not in self.edges:
            self.edges[source_id] = []
        if target_id not in self.edges.get(target_id, []):
            self.edges[source_id].append(target_id)

    def get_neighbors(self, memory_id: str, depth: int = 1) -> Set[str]:
        """Get neighbors up to a certain depth."""
        visited = set()
        queue = [(memory_id, 0)]
        while queue:
            current, d = queue.pop(0)
            if current in visited or d >= depth:
                continue
            visited.add(current)
            for neighbor in self.edges.get(current, []):
                if neighbor not in visited:
                    queue.append((neighbor, d + 1))
        return visited - {memory_id}


class SpreadingActivation:
    """
    Implements spreading activation for associative recall.

    Activation spreads from seed concepts to graph neighbors,
    producing an activation map that can be combined with
    semantic similarity for recall scoring.
    """

    def __init__(self, graph: AssociationGraph):
        self.graph = graph
        self.activation_decay: float = 0.5
        self.max_propagation_depth: int = 3

    def activate(self, seed_concepts: List[str], context: Dict[str, Any]) -> Dict[str, float]:
        """
        Spread activation from seed concepts.

        Returns a dict of memory_id -> activation_strength.
        """
        activations: Dict[str, float] = {}
        queue: List[tuple[str, float, int]] = []

        # Initialize with seed concepts
        for concept in seed_concepts:
            for memory_id in self.graph.concept_index.get(concept, []):
                activations[memory_id] = 1.0
                queue.append((memory_id, 1.0, 0))

        # Propagate
        while queue:
            current_id, current_activation, depth = queue.pop(0)
            if depth >= self.max_propagation_depth:
                continue

            for neighbor in self.graph.edges.get(current_id, []):
                new_activation = current_activation * self.activation_decay
                if neighbor not in activations or new_activation > activations[neighbor]:
                    activations[neighbor] = new_activation
                    queue.append((neighbor, new_activation, depth + 1))

        return activations

    def compute_recall_score(self, base_score: RecallScoreComponents, activations: Dict[str, float]) -> float:
        """Add associative activation to recall score."""
        if not activations:
            return base_score.total()
        max_activation = max(activations.values())
        base_score.associative_activation = max_activation * 2.0  # Weight associative activation
        return base_score.total()
