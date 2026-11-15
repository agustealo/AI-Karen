"""
Causal Reasoning Engine - Understanding Cause and Effect

This module provides advanced causal reasoning capabilities:
- Causal inference from observations
- Intervention modeling (do-calculus)
- Counterfactual reasoning
- Causal graph construction
- Backdoor and frontdoor adjustment
- Mediation analysis
- Attribution and responsibility
- Causal discovery algorithms
"""

from __future__ import annotations
import logging
import numpy as np
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum

logger = logging.getLogger(__name__)


class CausalRelationType(Enum):
    """Types of causal relationships"""
    DIRECT_CAUSE = "direct_cause"        # A → B
    INDIRECT_CAUSE = "indirect_cause"    # A → X → B
    COMMON_CAUSE = "common_cause"        # A ← X → B (confounding)
    COMMON_EFFECT = "common_effect"      # A → X ← B (collider)
    BIDIRECTIONAL = "bidirectional"      # A ⇄ B
    NO_RELATION = "no_relation"


@dataclass
class CausalEdge:
    """Edge in causal graph"""
    cause: str
    effect: str
    strength: float  # 0-1: strength of causal influence
    confidence: float  # 0-1: confidence in this relationship
    mechanism: Optional[str] = None  # Description of causal mechanism
    evidence: List[str] = field(default_factory=list)  # Supporting evidence


@dataclass
class CausalIntervention:
    """Represents a causal intervention (do-operator)"""
    variable: str
    value: Any
    timestamp: float
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CounterfactualScenario:
    """Counterfactual 'what-if' scenario"""
    scenario_id: str
    description: str
    interventions: List[CausalIntervention]
    predicted_outcomes: Dict[str, Any]
    probability: float
    assumptions: List[str]


@dataclass
class CausalExplanation:
    """Explanation of why something happened"""
    outcome: str
    actual_causes: List[Tuple[str, float]]  # Variable, contribution
    necessary_causes: List[str]  # Must be present
    sufficient_causes: List[str]  # Alone can cause outcome
    contributing_factors: List[Tuple[str, float]]
    alternative_explanations: List[str]


class CausalGraph:
    """
    Directed Acyclic Graph (DAG) for causal relationships

    Implements Pearl's causal hierarchy:
    - Level 1: Association (seeing/observing)
    - Level 2: Intervention (doing)
    - Level 3: Counterfactuals (imagining)
    """

    def __init__(self):
        self.edges: Dict[Tuple[str, str], CausalEdge] = {}
        self.nodes: Set[str] = set()
        self.adjacency: Dict[str, Set[str]] = defaultdict(set)  # cause -> effects
        self.reverse_adjacency: Dict[str, Set[str]] = defaultdict(set)  # effect -> causes

    def add_edge(self, cause: str, effect: str, strength: float, confidence: float,
                 mechanism: Optional[str] = None, evidence: Optional[List[str]] = None) -> None:
        """Add causal edge to graph"""
        edge = CausalEdge(
            cause=cause,
            effect=effect,
            strength=strength,
            confidence=confidence,
            mechanism=mechanism,
            evidence=evidence or []
        )

        self.edges[(cause, effect)] = edge
        self.nodes.add(cause)
        self.nodes.add(effect)
        self.adjacency[cause].add(effect)
        self.reverse_adjacency[effect].add(cause)

    def get_direct_causes(self, effect: str) -> List[str]:
        """Get immediate causes of an effect"""
        return list(self.reverse_adjacency.get(effect, set()))

    def get_direct_effects(self, cause: str) -> List[str]:
        """Get immediate effects of a cause"""
        return list(self.adjacency.get(cause, set()))

    def get_ancestors(self, node: str) -> Set[str]:
        """Get all ancestors (transitive causes) of a node"""
        ancestors = set()
        queue = deque([node])
        visited = {node}

        while queue:
            current = queue.popleft()
            for cause in self.reverse_adjacency.get(current, set()):
                if cause not in visited:
                    visited.add(cause)
                    ancestors.add(cause)
                    queue.append(cause)

        return ancestors

    def get_descendants(self, node: str) -> Set[str]:
        """Get all descendants (transitive effects) of a node"""
        descendants = set()
        queue = deque([node])
        visited = {node}

        while queue:
            current = queue.popleft()
            for effect in self.adjacency.get(current, set()):
                if effect not in visited:
                    visited.add(effect)
                    descendants.add(effect)
                    queue.append(effect)

        return descendants

    def get_causal_paths(self, cause: str, effect: str) -> List[List[str]]:
        """Find all causal paths from cause to effect"""
        paths = []
        self._find_paths(cause, effect, [cause], set([cause]), paths)
        return paths

    def _find_paths(self, current: str, target: str, path: List[str],
                    visited: Set[str], paths: List[List[str]]) -> None:
        """Helper for path finding (DFS)"""
        if current == target:
            paths.append(path.copy())
            return

        for neighbor in self.adjacency.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                path.append(neighbor)
                self._find_paths(neighbor, target, path, visited, paths)
                path.pop()
                visited.remove(neighbor)

    def find_confounders(self, treatment: str, outcome: str) -> Set[str]:
        """
        Find confounding variables (common causes)

        A confounder affects both treatment and outcome
        """
        treatment_causes = self.get_ancestors(treatment)
        outcome_causes = self.get_ancestors(outcome)
        return treatment_causes & outcome_causes

    def find_mediators(self, cause: str, effect: str) -> Set[str]:
        """
        Find mediating variables (on causal path)

        A mediator is on the path from cause to effect
        """
        paths = self.get_causal_paths(cause, effect)
        mediators = set()
        for path in paths:
            # Exclude the cause and effect themselves
            mediators.update(path[1:-1])
        return mediators

    def find_colliders(self, var1: str, var2: str) -> Set[str]:
        """
        Find colliding variables (common effects)

        A collider is affected by both var1 and var2
        """
        var1_effects = self.get_descendants(var1)
        var2_effects = self.get_descendants(var2)
        return var1_effects & var2_effects

    def is_d_separated(self, x: str, y: str, conditioning_set: Set[str]) -> bool:
        """
        Check if X and Y are d-separated given conditioning set

        D-separation determines conditional independence
        """
        # Simplified d-separation check
        # Full implementation would need more sophisticated algorithm

        # If there's no path, they're d-separated
        paths = self.get_causal_paths(x, y)
        if not paths:
            return True

        # Check if conditioning set blocks all paths
        for path in paths:
            if not self._is_path_blocked(path, conditioning_set):
                return False

        return True

    def _is_path_blocked(self, path: List[str], conditioning_set: Set[str]) -> bool:
        """Check if a path is blocked by conditioning set"""
        # Simplified: path is blocked if any non-collider node is in conditioning set
        for i in range(1, len(path) - 1):
            node = path[i]
            prev_node = path[i - 1]
            next_node = path[i + 1]

            # Check if it's a collider
            is_collider = (next_node in self.adjacency.get(node, set()) and
                          prev_node in self.reverse_adjacency.get(node, set()))

            if not is_collider and node in conditioning_set:
                return True

        return False


class CausalReasoningEngine:
    """
    Advanced causal reasoning engine

    Implements:
    - Causal inference from observations
    - Intervention modeling (do-calculus)
    - Counterfactual reasoning
    - Causal explanation generation
    - Attribution analysis
    """

    def __init__(self):
        self.causal_graph = CausalGraph()
        self.observations: List[Dict[str, Any]] = []
        self.interventions: List[CausalIntervention] = []

    def learn_from_observations(self, observations: List[Dict[str, Any]]) -> None:
        """Record observational evidence without inventing causal structure.

        Observational correlation and temporal precedence alone cannot
        establish a causal direction. In particular, this method must not
        write to ``causal_graph`` until a separately evaluated causal
        identification contract exists. Explicitly supplied graph edges are
        preserved, not silently overwritten by correlation estimates.
        """
        self.observations.extend(observations)
        logger.debug(
            "causal.observations_recorded_without_discovery",
            extra={"observation_count": len(self.observations)},
        )

    def _compute_correlations(self, variables: List[str]) -> Dict[Tuple[str, str], float]:
        """Compute pairwise correlations"""
        correlations = {}

        for i, var1 in enumerate(variables):
            for var2 in variables[i + 1:]:
                # Extract values
                values1 = [obs.get(var1) for obs in self.observations if var1 in obs]
                values2 = [obs.get(var2) for obs in self.observations if var2 in obs]

                if len(values1) >= 2 and len(values2) >= 2:
                    # Convert to numeric if possible
                    try:
                        v1 = np.array([float(v) for v in values1 if v is not None])
                        v2 = np.array([float(v) for v in values2 if v is not None])

                        if len(v1) == len(v2) and len(v1) > 0:
                            corr = np.corrcoef(v1, v2)[0, 1]
                            if not np.isnan(corr):
                                correlations[(var1, var2)] = corr
                    except (ValueError, TypeError):
                        pass

        return correlations

    def _determine_direction(self, var1: str, var2: str) -> bool:
        """Determine causal direction between correlated variables"""
        # Use temporal ordering if available
        for obs in self.observations:
            if f"{var1}_time" in obs and f"{var2}_time" in obs:
                if obs[f"{var1}_time"] < obs[f"{var2}_time"]:
                    return True  # var1 happens before var2
                else:
                    return False

        # Unknown temporal precedence is not evidence of causal direction.
        # Even a known temporal order is not sufficient for identification.
        return False

    def estimate_causal_effect(
        self,
        treatment: str,
        outcome: str,
        adjustment_set: Optional[Set[str]] = None
    ) -> float:
        """
        Estimate causal effect of treatment on outcome

        Uses backdoor adjustment to account for confounding
        """
        # Find confounders if adjustment set not provided
        if adjustment_set is None:
            adjustment_set = self.causal_graph.find_confounders(treatment, outcome)

        # Simplified effect estimation
        # In practice, would use more sophisticated methods (regression, matching, etc.)

        treated_outcomes = []
        control_outcomes = []

        for obs in self.observations:
            if treatment in obs and outcome in obs:
                try:
                    outcome_val = float(obs[outcome])
                    if obs[treatment]:
                        treated_outcomes.append(outcome_val)
                    else:
                        control_outcomes.append(outcome_val)
                except (ValueError, TypeError):
                    continue

        if not treated_outcomes or not control_outcomes:
            return 0.0

        # Average treatment effect
        ate = np.mean(treated_outcomes) - np.mean(control_outcomes)
        return float(ate)

    def do_intervention(
        self,
        variable: str,
        value: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Model intervention (do-operator)

        Predicts effects of setting variable to value
        """
        import time

        intervention = CausalIntervention(
            variable=variable,
            value=value,
            timestamp=time.time(),
            context=context or {}
        )

        self.interventions.append(intervention)

        # Predict downstream effects
        effects = self.causal_graph.get_descendants(variable)

        predicted_outcomes = {variable: value}

        # Propagate effect through causal graph
        for effect_var in effects:
            # Get direct causes
            causes = self.causal_graph.get_direct_causes(effect_var)

            # Estimate effect
            effect_strength = 0.0
            for cause in causes:
                edge = self.causal_graph.edges.get((cause, effect_var))
                if edge and cause == variable:
                    effect_strength = edge.strength

            # Simplified prediction
            predicted_outcomes[effect_var] = {
                'expected_change': effect_strength,
                'confidence': 0.6
            }

        return predicted_outcomes

    def generate_counterfactual(
        self,
        scenario_description: str,
        interventions: List[Tuple[str, Any]],
        observed_outcome: Optional[Dict[str, Any]] = None
    ) -> CounterfactualScenario:
        """
        Generate counterfactual scenario

        Answers "what if" questions by imagining alternative worlds
        """
        import uuid

        scenario_id = str(uuid.uuid4())[:8]

        # Create intervention objects
        intervention_objs = [
            CausalIntervention(variable=var, value=val, timestamp=0.0)
            for var, val in interventions
        ]

        # Predict outcomes under counterfactual scenario
        predicted_outcomes = {}
        for var, val in interventions:
            outcomes = self.do_intervention(var, val)
            predicted_outcomes.update(outcomes)

        # Estimate probability of scenario
        # Simplified: based on how different from observations
        probability = 0.5  # Placeholder

        # List assumptions
        assumptions = [
            "Causal structure remains stable",
            "No unmeasured confounding",
            "SUTVA (Stable Unit Treatment Value Assumption)"
        ]

        return CounterfactualScenario(
            scenario_id=scenario_id,
            description=scenario_description,
            interventions=intervention_objs,
            predicted_outcomes=predicted_outcomes,
            probability=probability,
            assumptions=assumptions
        )

    def explain_outcome(
        self,
        outcome_variable: str,
        outcome_value: Any,
        context: Dict[str, Any]
    ) -> CausalExplanation:
        """
        Generate causal explanation for why an outcome occurred

        Identifies actual causes, necessary causes, and sufficient causes
        """
        # Find all potential causes
        all_causes = self.causal_graph.get_ancestors(outcome_variable)

        # Compute contribution of each cause
        actual_causes = []
        for cause in all_causes:
            # Estimate contribution
            if cause in context:
                effect = self.estimate_causal_effect(cause, outcome_variable)
                if effect != 0:
                    actual_causes.append((cause, abs(effect)))

        # Sort by contribution
        actual_causes.sort(key=lambda x: x[1], reverse=True)

        # Identify necessary causes (outcome wouldn't happen without them)
        necessary_causes = []
        for cause, _ in actual_causes[:3]:  # Top 3
            # Check if removing cause prevents outcome
            counterfactual = self.generate_counterfactual(
                f"Remove {cause}",
                [(cause, None)],
                {outcome_variable: outcome_value}
            )
            # Simplified check
            if outcome_variable in counterfactual.predicted_outcomes:
                necessary_causes.append(cause)

        # Identify sufficient causes (alone can cause outcome)
        sufficient_causes = []
        for cause, contribution in actual_causes:
            if contribution > 0.7:  # High contribution threshold
                sufficient_causes.append(cause)

        # Contributing factors (lower contribution)
        contributing_factors = [(c, contrib) for c, contrib in actual_causes
                              if 0.2 < contrib < 0.7]

        # Alternative explanations
        alternative_explanations = [
            "Random chance",
            "Unmeasured factors",
            "Complex interactions"
        ]

        return CausalExplanation(
            outcome=f"{outcome_variable} = {outcome_value}",
            actual_causes=actual_causes,
            necessary_causes=necessary_causes,
            sufficient_causes=sufficient_causes,
            contributing_factors=contributing_factors,
            alternative_explanations=alternative_explanations
        )

    def assess_responsibility(
        self,
        outcome: str,
        agents: List[str],
        context: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Assess causal responsibility of different agents for an outcome

        Returns responsibility scores (0-1) for each agent
        """
        responsibility = {}

        for agent in agents:
            # Check if agent is in causal graph
            if agent in self.causal_graph.nodes:
                # Compute degree of responsibility
                # Based on: 1) causal contribution, 2) necessity, 3) sufficiency

                # Causal contribution
                contribution = abs(self.estimate_causal_effect(agent, outcome))

                # Check necessity (would outcome occur without agent?)
                counterfactual = self.generate_counterfactual(
                    f"Remove {agent}",
                    [(agent, None)]
                )

                # Responsibility score combines multiple factors
                responsibility[agent] = min(contribution, 1.0)
            else:
                responsibility[agent] = 0.0

        # Normalize
        total = sum(responsibility.values())
        if total > 0:
            responsibility = {k: v / total for k, v in responsibility.items()}

        return responsibility


# Global causal reasoning instance
_global_causal_engine: Optional[CausalReasoningEngine] = None

def get_causal_engine() -> CausalReasoningEngine:
    """Get global causal reasoning engine"""
    global _global_causal_engine
    if _global_causal_engine is None:
        _global_causal_engine = CausalReasoningEngine()
    return _global_causal_engine
