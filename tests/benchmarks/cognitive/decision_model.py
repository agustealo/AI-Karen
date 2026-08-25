"""Test-owned reference decision model for COG-EVAL-1.

No production behavior selector exists, and the benchmark must not edit
``src/ai_karen_engine``.  This module therefore defines a deterministic,
reference DecisionModel derived *from* Karen's real cognitive signals
(belief revision, salience, preference resolution, goal state, memory
security posture, deletion provenance).  It is a benchmark oracle, not a
generic decision framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from benchmarks.cognitive.contracts import (
    BehaviorDecision,
    BehaviorOption,
    DeletionStatus,
    SecurityCheck,
)
from benchmarks.cognitive.builders import CognitiveState


@dataclass
class BehaviorSelector:
    """Picks a behavior option from real cognitive signals."""

    behavior_map: dict[str, BehaviorOption] = field(default_factory=dict)

    def select(
        self,
        state: CognitiveState,
        belief: Any | None,
        salience: Any | None,
        preferences: list[Any] | None,
        policy_constraints: dict[str, Any] | None,
    ) -> BehaviorOption:
        constraints = policy_constraints or {}
        deny = constraints.get("deny", []) or []
        salience_value = _salience_score(salience)
        confidence = _confidence(belief)
        user_emphasis = any(_is_emphasis_critical(e) for e in (state.user_emphasis or []))

        blocked = _preferred_behavior(preferences)
        if blocked is not None:
            base = blocked
        elif user_emphasis or salience_value >= 0.75:
            base = BehaviorOption.VERIFY
        elif confidence >= 0.8 and _belief_strong(belief):
            base = BehaviorOption.ACT
        elif confidence < 0.4:
            base = BehaviorOption.ASK
        else:
            base = BehaviorOption.ACT

        if base.value in deny:
            return BehaviorOption.POLICY_WINS
        if salience_value >= 0.9:
            base = _escalate(base)
        if base.value in deny:
            return BehaviorOption.POLICY_WINS
        return base

    def to_decision(
        self,
        option: BehaviorOption,
        rationale: str,
        confidence: float,
        constraints: list[str],
    ) -> BehaviorDecision:
        return BehaviorDecision(
            option=option,
            rationale=rationale,
            confidence=confidence,
            applied_constraints=constraints,
        )


@dataclass
class PolicyGuard:
    """Validates a behavior decision against tenant/user policy constraints."""

    def is_allowed(
        self,
        decision: BehaviorDecision,
        policy_constraints: dict[str, Any] | None,
    ) -> SecurityCheck:
        constraints = policy_constraints or {}
        deny = constraints.get("deny", []) or []
        if decision.option.value in deny:
            return SecurityCheck.BLOCKED
        if constraints.get("tenant_boundary") and decision.option == BehaviorOption.ACT:
            return SecurityCheck.BLOCKED
        if (
            constraints.get("max_score") is not None
            and decision.confidence > float(constraints.get("max_score"))
        ):
            return SecurityCheck.BLOCKED
        return SecurityCheck.ALLOWED


@dataclass
class SecurityGuard:
    """Determines per-item access from memory security posture."""

    def check_memory_access(
        self,
        item: Any,
        policy_constraints: dict[str, Any] | None,
        requester_tenant: str,
        item_tenant: str,
    ) -> SecurityCheck:
        constraints = policy_constraints or {}
        if constraints.get("tenant_boundary", True) and requester_tenant != item_tenant:
            return SecurityCheck.BLOCKED
        return SecurityCheck.ALLOWED


@dataclass
class DeletionPropagator:
    """Assesses deletion provenance from the materialized cognitive state."""

    def propagate(self, state: CognitiveState) -> DeletionStatus:
        claim_ids = {getattr(c, "claim_id", None) for c in state.claims}
        deleted = set(state.deleted_ids)
        if deleted & claim_ids:
            return DeletionStatus.RETRACTED
        if state.purged_claims:
            return DeletionStatus.PURGED
        if deleted:
            return DeletionStatus.DELETED
        return DeletionStatus.PURGED


def evaluate_decision(
    state: CognitiveState,
    belief: Any | None,
    salience: Any | None,
    preferences: list[Any] | None,
    policy_constraints: dict[str, Any] | None,
    selector: BehaviorSelector | None = None,
) -> BehaviorDecision:
    selector = selector or BehaviorSelector()
    option = selector.select(state, belief, salience, preferences, policy_constraints)
    confidence = _decision_confidence(option, belief, salience)
    deny = list((policy_constraints or {}).get("deny", []) or [])
    decision = selector.to_decision(
        option=option,
        rationale=_rationale(option, belief, salience),
        confidence=confidence,
        constraints=deny,
    )
    guard = PolicyGuard()
    decision.allowed = guard.is_allowed(decision, policy_constraints)
    return decision


def summarize_memory_security(
    state: CognitiveState,
    policy_constraints: dict[str, Any] | None,
    requester_tenant: str,
) -> dict[str, Any]:
    guard = SecurityGuard()
    checks: dict[str, SecurityCheck] = {}
    for c in state.claims:
        checks[getattr(c, "claim_id", id(c))] = guard.check_memory_access(
            c,
            policy_constraints,
            requester_tenant,
            getattr(c, "tenant_id", requester_tenant),
        )
    return checks


def summarize_deletion(state: CognitiveState) -> DeletionStatus:
    return DeletionPropagator().propagate(state)


def _confidence(belief: Any) -> float:
    if belief is None:
        return 0.5
    for attr in ("overall_confidence", "confidence", "reasoning_confidence"):
        val = getattr(belief, attr, None)
        if isinstance(val, (int, float)):
            return float(val)
    assessment = getattr(belief, "assessment", None)
    if assessment is not None:
        for attr in ("overall_confidence", "confidence"):
            val = getattr(assessment, attr, None)
            if isinstance(val, (int, float)):
                return float(val)
    return 0.5


def _salience_score(salience: Any) -> float:
    if salience is None:
        return 0.0
    val = getattr(salience, "value", None)
    if isinstance(val, (int, float)):
        return float(val)
    signals = getattr(salience, "signals", None) or []
    if signals:
        return float(max(getattr(s, "value", 0.0) for s in signals))
    return 0.0


def _belief_strong(belief: Any) -> bool:
    conf = _confidence(belief)
    reasoning = getattr(belief, "reasoning_confidence", None)
    if isinstance(reasoning, (int, float)) and reasoning < 0.3:
        return False
    return conf >= 0.8


def _is_emphasis_critical(emphasis: Any) -> bool:
    etype = getattr(emphasis, "emphasis_type", None)
    if etype is None:
        return False
    return str(etype).lower() in ("critical", "user_critical", "required")


def _preferred_behavior(preferences: list[Any] | None) -> BehaviorOption | None:
    if not preferences:
        return None
    for p in preferences:
        if getattr(p, "state", None) == "required":
            return BehaviorOption.ACT
    return None


def _escalate(base: BehaviorOption) -> BehaviorOption:
    if base == BehaviorOption.ASK:
        return BehaviorOption.VERIFY
    return base


def _decision_confidence(
    option: BehaviorOption,
    belief: Any,
    salience: Any,
) -> float:
    base = _confidence(belief) * 0.8 + _salience_score(salience) * 0.2
    if option == BehaviorOption.ASK:
        return min(0.5, base)
    return base


def _rationale(
    option: BehaviorOption,
    belief: Any,
    salience: Any,
) -> str:
    parts: list[str] = []
    if belief is not None:
        parts.append(f"belief_confidence={_confidence(belief):.2f}")
    parts.append(f"salience={_salience_score(salience):.2f}")
    parts.append(f"option={option.value}")
    return ", ".join(parts)
