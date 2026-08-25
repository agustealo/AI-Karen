"""
Prospective memory, intentions, and commitments for AI-Karen.

Core owns the intention.  It does not own cron execution.
Commitments require stronger evidence than ordinary goals.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from .contracts import (
    Commitment,
    CommitmentEvidence,
    CommitmentSource,
    CommitmentStatus,
    CommitmentStrength,
    Goal,
    GoalState,
    Intention,
    IntentionEvidence,
    IntentionState,
    IntentionTriggerType,
    ProspectiveMemory,
    ProspectiveState,
)

logger = logging.getLogger(__name__)


class IntentionLifecycle:
    """Manages intention state transitions and trigger evaluation."""

    def __init__(self) -> None:
        self._intentions: dict[str, Intention] = {}

    def add(self, intention: Intention) -> Intention:
        self._intentions[intention.intention_id] = intention
        return intention

    def get(self, intention_id: str) -> Intention | None:
        return self._intentions.get(intention_id)

    def all(self) -> list[Intention]:
        return list(self._intentions.values())

    def all_for_user(self, user_id: str, tenant_id: str) -> list[Intention]:
        return [
            i for i in self._intentions.values()
            if i.tenant_id == tenant_id and i.user_id == user_id
        ]

    def can_transition(self, intention: Intention, target: IntentionState) -> bool:
        current = intention.state
        valid: dict[IntentionState, set] = {
            IntentionState.FORMED: {
                IntentionState.WAITING, IntentionState.READY,
                IntentionState.ACTIVE, IntentionState.CANCELLED,
                IntentionState.INVALIDATED,
            },
            IntentionState.WAITING: {
                IntentionState.READY, IntentionState.ACTIVE,
                IntentionState.CANCELLED, IntentionState.INVALIDATED,
            },
            IntentionState.READY: {
                IntentionState.ACTIVE, IntentionState.WAITING,
                IntentionState.CANCELLED, IntentionState.INVALIDATED,
            },
            IntentionState.ACTIVE: {
                IntentionState.FULFILLED, IntentionState.CANCELLED,
                IntentionState.INVALIDATED,
            },
            IntentionState.FULFILLED: set(),
            IntentionState.CANCELLED: set(),
            IntentionState.INVALIDATED: set(),
        }
        if current == target:
            return True
        return target in valid.get(current, set())

    def transition(
        self,
        intention: Intention,
        target: IntentionState,
        reason: str = "",
    ) -> Intention:
        if not self.can_transition(intention, target):
            raise ValueError(
                f"Cannot transition intention {intention.intention_id} "
                f"from {intention.state.value} to {target.value}"
            )
        now = datetime.utcnow()
        original = intention.state
        intention.state = target

        if target == IntentionState.ACTIVE:
            intention.activated_at = now
        elif target in (IntentionState.FULFILLED, IntentionState.INVALIDATED):
            intention.fulfilled_at = now
            intention.invalidated_at = now
        elif target == IntentionState.CANCELLED:
            intention.invalidated_at = now

        logger.info(
            "intention.transition goal=%s %s->%s reason=%s",
            intention.goal_id, original.value, target.value, reason,
        )
        return intention

    def evaluate_trigger(
        self,
        intention: Intention,
        goals: dict[str, Goal],
    ) -> bool:
        """Evaluate whether an intention's trigger condition is met."""
        if intention.state in (
            IntentionState.FULFILLED,
            IntentionState.INVALIDATED,
            IntentionState.CANCELLED,
        ):
            return False

        trigger = intention.trigger_type
        condition = intention.trigger_condition

        if trigger == IntentionTriggerType.GOAL_STATE_RELEVANT:
            goal = goals.get(intention.goal_id)
            if goal is None and condition:
                goal = goals.get(condition.split(":")[0])
            if goal is None:
                return False
            parts = condition.split(":")
            if len(parts) >= 2:
                target_state = parts[1]
                return goal.state.value == target_state
            return goal.state == GoalState.COMPLETED
        elif trigger == IntentionTriggerType.EVENT_RELEVANT:
            goal = goals.get(intention.goal_id)
            if goal is None:
                return False
            return goal.state == GoalState.SATISFIED
        elif trigger == IntentionTriggerType.CONTEXT_RELEVANT:
            return True
        elif trigger == IntentionTriggerType.TIME_RELEVANT:
            if intention.activated_at is not None:
                return (datetime.utcnow() - intention.activated_at).total_seconds() > 0
            return True
        elif trigger == IntentionTriggerType.USER_RELEVANT or trigger == IntentionTriggerType.PROJECT_RELEVANT:
            return True
        return False

    def tick(
        self,
        goals: dict[str, Goal],
        now: datetime | None = None,
    ) -> list[Intention]:
        """Evaluate all intentions and update dormant ones to READY/ACTIVE."""
        now = now or datetime.utcnow()
        activated: list[Intention] = []
        for intention in self._intentions.values():
            if intention.state == IntentionState.WAITING:
                if self.evaluate_trigger(intention, goals):
                    self.transition(intention, IntentionState.READY, "trigger met")
                    self.transition(intention, IntentionState.ACTIVE, "trigger active")
                    activated.append(intention)
            elif intention.state == IntentionState.READY:
                if self.evaluate_trigger(intention, goals):
                    self.transition(intention, IntentionState.ACTIVE, "trigger active")
                    activated.append(intention)
        return activated

    def add_evidence(self, intention: Intention, evidence: IntentionEvidence) -> Intention:
        intention.evidence_refs.append(evidence.evidence_id)
        if evidence not in getattr(intention, "_evidence_store", []):
            pass
        return intention

    def fulfill(self, intention: Intention, evidence_ref: str) -> Intention:
        if evidence_ref not in intention.evidence_refs:
            intention.evidence_refs.append(evidence_ref)
        self.transition(intention, IntentionState.FULFILLED, "objective achieved")
        return intention


class CommitmentLifecycle:
    """Manages commitment state and evidence."""

    MIN_COMMITMENT_CONFIDENCE = 0.7

    def __init__(self) -> None:
        self._commitments: dict[str, Commitment] = {}

    def add(self, commitment: Commitment) -> Commitment:
        self._commitments[commitment.commitment_id] = commitment
        return commitment

    def get(self, commitment_id: str) -> Commitment | None:
        return self._commitments.get(commitment_id)

    def all(self) -> list[Commitment]:
        return list(self._commitments.values())

    def all_for_user(self, user_id: str, tenant_id: str) -> list[Commitment]:
        return [
            c for c in self._commitments.values()
            if c.tenant_id == tenant_id and c.user_id == user_id
        ]

    def validate_evidence(self, commitment: Commitment) -> bool:
        """A commitment requires stronger evidence than an ordinary goal."""
        if commitment.strength == CommitmentStrength.BOUND:
            min_count = 3
        elif commitment.strength == CommitmentStrength.COMMITTED:
            min_count = 2
        else:
            min_count = 1

        if len(commitment.evidence) < min_count:
            return False

        max_conf = max((e.confidence for e in commitment.evidence), default=0.0)
        return max_conf >= self.MIN_COMMITMENT_CONFIDENCE

    def can_transition(
        self, commitment: Commitment, target: CommitmentStatus
    ) -> bool:
        current = commitment.status
        valid: dict[CommitmentStatus, set] = {
            CommitmentStatus.PROPOSED: {
                CommitmentStatus.ACKNOWLEDGED,
                CommitmentStatus.ACTIVE,
                CommitmentStatus.CANCELLED,
                CommitmentStatus.SUPERSEDED,
            },
            CommitmentStatus.ACKNOWLEDGED: {
                CommitmentStatus.ACTIVE,
                CommitmentStatus.CANCELLED,
                CommitmentStatus.SUPERSEDED,
            },
            CommitmentStatus.ACTIVE: {
                CommitmentStatus.FULFILLED,
                CommitmentStatus.FAILED,
                CommitmentStatus.CANCELLED,
                CommitmentStatus.SUPERSEDED,
            },
            CommitmentStatus.FULFILLED: set(),
            CommitmentStatus.FAILED: {CommitmentStatus.SUPERSEDED},
            CommitmentStatus.CANCELLED: set(),
            CommitmentStatus.SUPERSEDED: set(),
        }
        if current == target:
            return True
        return target in valid.get(current, set())

    def transition(
        self,
        commitment: Commitment,
        target: CommitmentStatus,
        reason: str = "",
    ) -> Commitment:
        if not self.can_transition(commitment, target):
            raise ValueError(
                f"Cannot transition commitment {commitment.commitment_id} "
                f"from {commitment.status.value} to {target.value}"
            )
        original = commitment.status
        commitment.status = target

        if target == CommitmentStatus.ACTIVE:
            commitment.committed_at = datetime.utcnow()
        elif target == CommitmentStatus.FULFILLED:
            commitment.fulfilled_at = datetime.utcnow()
        elif target in (CommitmentStatus.FAILED,):
            commitment.failed_at = datetime.utcnow()

        logger.info(
            "commitment.transition parties=%s %s->%s reason=%s",
            [p.value for p in commitment.parties],
            original.value, target.value, reason,
        )
        return commitment

    def try_activate(self, commitment: Commitment) -> bool:
        """Attempt to move a commitment from PROPOSED to ACTIVE.

        Requires valid evidence and all conditions met.
        """
        if commitment.status != CommitmentStatus.PROPOSED:
            return False
        if not self.validate_evidence(commitment):
            return False
        if not all(c.met for c in commitment.conditions):
            return False
        self.transition(commitment, CommitmentStatus.ACTIVE, "evidence validated")
        return True

    def fulfill(self, commitment: Commitment, evidence_ref: str) -> Commitment:
        if all(c.met for c in commitment.conditions) or not commitment.conditions:
            self.transition(commitment, CommitmentStatus.FULFILLED, "conditions met")
        return commitment

    def fail(self, commitment: Commitment, reason: str = "") -> Commitment:
        self.transition(commitment, CommitmentStatus.FAILED, reason or "commitment unmet")
        return commitment

    def supersede(self, commitment: Commitment, replacement_id: str) -> Commitment:
        self.transition(
            commitment, CommitmentStatus.SUPERSEDED,
            f"superseded by {replacement_id}",
        )
        commitment.superseded_by = replacement_id
        return commitment


class ProspectiveMemoryManager:
    """Manages prospective memory items and their semantic triggers."""

    def __init__(self) -> None:
        self._items: dict[str, ProspectiveMemory] = {}

    def add(self, pm: ProspectiveMemory) -> ProspectiveMemory:
        self._items[pm.pm_id] = pm
        return pm

    def get(self, pm_id: str) -> ProspectiveMemory | None:
        return self._items.get(pm_id)

    def all_dormant(self, tenant_id: str, user_id: str | None = None) -> list[ProspectiveMemory]:
        result: list[ProspectiveMemory] = []
        for pm in self._items.values():
            if pm.state != ProspectiveState.DORMANT:
                continue
            if pm.tenant_id != tenant_id:
                continue
            if user_id is not None and pm.user_id != user_id:
                continue
            result.append(pm)
        return result

    def evaluate_trigger(
        self,
        pm: ProspectiveMemory,
        intentions: dict[str, Intention],
        goals: dict[str, Goal],
    ) -> bool:
        """Evaluate whether the prospective memory's trigger is met."""
        if pm.state != ProspectiveState.DORMANT:
            return False

        trigger = pm.trigger
        trigger_type = trigger.trigger_type

        if trigger_type == IntentionTriggerType.GOAL_STATE_RELEVANT:
            target_ref = trigger.target_ref
            parts = target_ref.split(":")
            goal_id = parts[0]
            goal = goals.get(goal_id)
            if goal is None:
                return False
            if len(parts) >= 2:
                target_state = parts[1]
                return goal.state.value == target_state
            return goal.state == GoalState.COMPLETED
        elif trigger_type == IntentionTriggerType.EVENT_RELEVANT:
            if pm.target_intention_id:
                intention = intentions.get(pm.target_intention_id)
                if intention and intention.state == IntentionState.FULFILLED:
                    return True
            if pm.target_goal_id:
                goal = goals.get(pm.target_goal_id)
                if goal and goal.state == GoalState.SATISFIED:
                    return True
            return False
        elif trigger_type == IntentionTriggerType.CONTEXT_RELEVANT:
            if trigger.condition:
                return True
            return False
        elif trigger_type == IntentionTriggerType.USER_RELEVANT or trigger_type == IntentionTriggerType.TIME_RELEVANT or trigger_type == IntentionTriggerType.PROJECT_RELEVANT:
            return True
        return False

    def check_all(
        self,
        intentions: dict[str, Intention],
        goals: dict[str, Goal],
        tenant_id: str,
        user_id: str | None = None,
    ) -> list[ProspectiveMemory]:
        """Check all dormant prospective memories and trigger those whose conditions are met."""
        triggered: list[ProspectiveMemory] = []
        for pm in self.all_dormant(tenant_id, user_id):
            if self.evaluate_trigger(pm, intentions, goals):
                pm.state = ProspectiveState.TRIGGERED
                pm.triggered_at = datetime.utcnow()
                triggered.append(pm)
        return triggered

    def archive(self, pm: ProspectiveMemory) -> ProspectiveMemory:
        pm.state = ProspectiveState.ARCHIVED
        pm.archived_at = datetime.utcnow()
        return pm


def make_intention_id() -> str:
    return f"int_{uuid.uuid4().hex[:12]}"


def make_commitment_id() -> str:
    return f"comm_{uuid.uuid4().hex[:12]}"


def make_pm_id() -> str:
    return f"pm_{uuid.uuid4().hex[:12]}"


def make_commitment_evidence(
    source: CommitmentSource,
    confidence: float,
    strength: CommitmentStrength,
    source_ref: str | None = None,
    tenant_id: str = "",
    user_id: str | None = None,
) -> CommitmentEvidence:
    """Factory for commitment evidence."""
    return CommitmentEvidence(
        evidence_id=f"comm_ev_{uuid.uuid4().hex[:12]}",
        source=source,
        source_ref=source_ref,
        confidence=max(0.0, min(1.0, confidence)),
        observed_at=datetime.utcnow(),
        strength=strength,
        tenant_id=tenant_id,
        user_id=user_id,
    )


__all__ = [
    "CommitmentLifecycle",
    "IntentionLifecycle",
    "ProspectiveMemoryManager",
    "make_commitment_evidence",
    "make_commitment_id",
    "make_intention_id",
    "make_pm_id",
]
