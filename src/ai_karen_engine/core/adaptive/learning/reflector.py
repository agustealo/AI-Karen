"""
Reflection engine for AI-Karen adaptive learning.

Transforms experience into durable learning candidates.
Reflection produces candidates; it does NOT persist directly.

Pipeline:
    Experience -> Reflection -> Candidate -> Evaluation -> Belief check
    -> Memory Policy -> PROMOTE / DEFER / REJECT
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
from ai_karen_engine.core.adaptive.learning.observation import Observation  # noqa: F401

from .reflection_contracts import (
    BeliefAssessmentLike,
    ConsolidationPolicyLike,
    ExperienceEvent,
    FailureLessonCandidate,
    GoalContextLike,
    OutcomeEvidence,
    PromotionAction,
    PromotionPolicy,
    PromotionResult,
    ReflectionCandidate,
    ReflectionCandidateType,
    ReflectionContext,
    ReflectionEvent,
    ReflectionInput,
    ReflectionPolicy,
    make_candidate_id,
)

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """Transforms experience events into reflection candidates."""

    def __init__(self, policy: Optional[ReflectionPolicy] = None) -> None:
        self._policy = policy or ReflectionPolicy()
        self._dedup_signatures: set[str] = set()
        self._events_log: List[ExperienceEvent] = []

    def reflect(
        self,
        input_data: ReflectionInput,
    ) -> List[ReflectionCandidate]:
        """Reflect on experience events and produce learning candidates."""
        self._events_log.extend(input_data.events)
        candidates: List[ReflectionCandidate] = []
        events = input_data.events[: self._policy.max_events_per_session]

        if self._policy.detect_failures:
            candidates.extend(self._detect_failures(events))
        if self._policy.detect_successes:
            candidates.extend(self._detect_successes(events))
        if self._policy.detect_patterns:
            candidates.extend(self._detect_patterns(events))
        if self._policy.detect_preferences:
            candidates.extend(self._detect_preferences(events))
        if self._policy.detect_goals:
            candidates.extend(self._detect_goal_updates(events))

        deduped: List[ReflectionCandidate] = []
        for c in candidates:
            sig = self._dedup_signature(c)
            if sig not in self._dedup_signatures:
                self._dedup_signatures.add(sig)
                deduped.append(c)

        deduped.sort(key=lambda c: c.confidence * c.salience, reverse=True)
        return deduped[: input_data.max_candidates]

    # ---- detection methods ----

    def _detect_failures(self, events: List[ExperienceEvent]) -> List[ReflectionCandidate]:
        """Detect failure lessons from unsuccessful outcomes."""
        failures: List[Tuple[ExperienceEvent, OutcomeEvidence]] = []
        for ev in events:
            if ev.outcome is not None and ev.outcome.execution_status == "failure":
                failures.append((ev, ev.outcome))

        candidates: List[ReflectionCandidate] = []
        for ev, outcome in failures:
            if not ev.explicit:
                continue
            failure_lesson = FailureLessonCandidate(
                attempt_id=ev.event_id,
                expected_outcome=self._expected_outcome(ev),
                actual_outcome=outcome.execution_status,
                failure_reason=outcome.metadata.get("error", "unknown"),
                recovery=ev.metadata.get("recovery", "retry with different approach"),
                final_result="failed",
                evidence_refs=[ev.event_id] + ev.evidence_refs,
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
            )
            candidate = ReflectionCandidate(
                candidate_id=make_candidate_id(),
                candidate_type=ReflectionCandidateType.FAILURE_LESSON,
                summary=f"Do not retry provider X when error class is {failure_lesson.failure_reason}",
                confidence=0.7,
                salience=0.8,
                evidence_refs=failure_lesson.evidence_refs,
                support_count=1,
                scope=str(ev.user_id or "default"),
                proposed_action="avoid_error_class",
                reason_codes=["explicit", "failure_observed"],
                failure_lesson=failure_lesson,
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
                metadata={"failure_reason": failure_lesson.failure_reason},
            )
            candidates.append(candidate)
        return candidates

    def _detect_successes(self, events: List[ExperienceEvent]) -> List[ReflectionCandidate]:
        """Detect success patterns from successful outcomes."""
        successes = [
            (ev, ev.outcome)
            for ev in events
            if ev.outcome is not None
            and ev.outcome.execution_status == "success"
            and ev.outcome.completion
        ]

        if len(successes) < 2:
            single_candidates: List[ReflectionCandidate] = []
            if len(successes) == 1:
                ev, outcome = successes[0]
                candidate = ReflectionCandidate(
                    candidate_id=make_candidate_id(),
                    candidate_type=ReflectionCandidateType.SUCCESS_PATTERN,
                    summary=ev.description,
                    confidence=0.4,
                    salience=0.5,
                    evidence_refs=[ev.event_id] + ev.evidence_refs,
                    support_count=1,
                    scope=str(ev.user_id or "default"),
                    proposed_action="continue_pattern",
                    reason_codes=["tentative", "single_observation"],
                    tenant_id=ev.tenant_id,
                    user_id=ev.user_id,
                )
                single_candidates.append(candidate)
            return single_candidates

        # Multiple successes -> look for shared context
        context_keys = self._shared_context(successes)
        if context_keys:
            ev, _ = successes[0]
            candidate = ReflectionCandidate(
                candidate_id=make_candidate_id(),
                candidate_type=ReflectionCandidateType.SUCCESS_PATTERN,
                summary=f"Success pattern: {', '.join(context_keys)[:80]}",
                confidence=0.6,
                salience=0.7,
                evidence_refs=[ev.event_id for ev, _ in successes],
                support_count=len(successes),
                scope=str(ev.user_id or "default"),
                proposed_action="generalize_pattern",
                reason_codes=["repeated", "success_corroborated"],
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
            )
            return [candidate]
        return []

    def _detect_patterns(self, events: List[ExperienceEvent]) -> List[ReflectionCandidate]:
        """Detect repeated behavior patterns."""
        pattern_groups: Dict[str, List[ExperienceEvent]] = defaultdict(list)
        for ev in events:
            key = self._pattern_key(ev)
            if key:
                pattern_groups[key].append(ev)

        candidates: List[ReflectionCandidate] = []
        for pattern_key, group in pattern_groups.items():
            if len(group) < 2:
                continue
            first = group[0]
            candidate = ReflectionCandidate(
                candidate_id=make_candidate_id(),
                candidate_type=ReflectionCandidateType.BEHAVIOR_PATTERN,
                summary=f"Behavior pattern: {pattern_key}",
                confidence=min(0.9, 0.3 + len(group) * 0.15),
                salience=0.6,
                evidence_refs=[ev.event_id for ev in group],
                support_count=len(group),
                scope=str(first.user_id or "default"),
                proposed_action="form_behavior_preference",
                reason_codes=["repeated", "behavior_pattern"],
                tenant_id=first.tenant_id,
                user_id=first.user_id,
            )
            candidates.append(candidate)
        return candidates

    def _detect_preferences(self, events: List[ExperienceEvent]) -> List[ReflectionCandidate]:
        """Detect preference signals from explicit user feedback."""
        preference_events = [ev for ev in events if ev.explicit]
        if len(preference_events) < 1:
            return []

        candidates: List[ReflectionCandidate] = []
        for ev in preference_events:
            if ev.metadata.get("preference_ref"):
                candidate = ReflectionCandidate(
                    candidate_id=make_candidate_id(),
                    candidate_type=ReflectionCandidateType.PREFERENCE,
                    summary=ev.description,
                    confidence=0.85,
                    salience=0.9,
                    evidence_refs=[ev.event_id] + ev.evidence_refs,
                    support_count=1,
                    scope=str(ev.user_id or "default"),
                    proposed_action="adopt_preference",
                    reason_codes=["explicit", "user_preference"],
                    tenant_id=ev.tenant_id,
                    user_id=ev.user_id,
                    metadata={"preference_ref": str(ev.metadata.get("preference_ref"))},
                )
                candidates.append(candidate)
        return candidates

    def _detect_goal_updates(self, events: List[ExperienceEvent]) -> List[ReflectionCandidate]:
        """Detect goal state changes from events."""
        goal_events = [ev for ev in events if ev.goal_refs]
        if not goal_events:
            return []

        candidates: List[ReflectionCandidate] = []
        for ev in goal_events:
            candidate = ReflectionCandidate(
                candidate_id=make_candidate_id(),
                candidate_type=ReflectionCandidateType.GOAL_UPDATE,
                summary=ev.description,
                confidence=0.7,
                salience=ev.salience,
                evidence_refs=[ev.event_id] + ev.evidence_refs,
                support_count=1,
                scope=str(ev.user_id or "default"),
                proposed_action="reconsider_goal_hierarchy",
                reason_codes=["goal_state_change"],
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
            )
            candidates.append(candidate)
        return candidates

    # ---- helpers ----

    def _dedup_signature(self, candidate: ReflectionCandidate) -> str:
        raw = "|".join([
            candidate.candidate_type.value,
            candidate.summary,
            str(candidate.scope),
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _pattern_key(self, ev: ExperienceEvent) -> str:
        if ev.outcome is None:
            return ""
        return f"{ev.outcome.execution_status}:{ev.metadata.get('action_type', '')}"

    def _shared_context(
        self, successes: List[Tuple[ExperienceEvent, OutcomeEvidence]]
    ) -> List[str]:
        """Find shared context keys across successful events."""
        context_sets: List[set[str]] = []
        for ev, _ in successes:
            ctx = set()
            if ev.outcome:
                if ev.outcome.action_type:
                    ctx.add(f"action:{ev.outcome.action_type}")
                if ev.metadata.get("project"):
                    ctx.add(f"project:{ev.metadata['project']}")
                if ev.metadata.get("task_type"):
                    ctx.add(f"task_type:{ev.metadata['task_type']}")
            context_sets.append(ctx)

        if not context_sets:
            return []
        shared = set.intersection(*context_sets) if context_sets else set()
        return list(shared)

    def _expected_outcome(self, ev: ExperienceEvent) -> str:
        return ev.metadata.get("expected_outcome", "successful completion")

    def events_logged(self) -> int:
        return len(self._events_log)


class PromotionGate:
    """Evaluates reflection candidates against evidence thresholds.

    Does NOT persist directly.  Uses BeliefAssessmentLike and
    GoalContextLike protocols for cross-sprint interoperability.
    """

    def __init__(self, policy: Optional[PromotionPolicy] = None) -> None:
        self._policy = policy or PromotionPolicy()

    def evaluate(
        self,
        candidate: ReflectionCandidate,
        belief_assessments: Optional[List[BeliefAssessmentLike]] = None,
        goal_contexts: Optional[List[GoalContextLike]] = None,
        existing_claims: Optional[List[Any]] = None,
        consolidation_policy: Optional[ConsolidationPolicyLike] = None,
    ) -> PromotionResult:
        """Evaluate a candidate for promotion, deferral, or rejection."""
        reasons: List[str] = []
        messages: List[str] = []
        policy = self._policy

        # --- Evidence count thresholds ---
        is_explicit = (
            candidate.is_explicit
            or "explicit" in candidate.reason_codes
            or candidate.confidence >= 0.9
        )

        min_evidence = (
            policy.min_explicit_evidence if is_explicit
            else policy.min_inferred_evidence
        )

        if candidate.support_count < min_evidence:
            if is_explicit and candidate.support_count < policy.min_explicit_evidence:
                return self._result(
                    candidate, PromotionAction.DEFER,
                    ["insufficient_evidence"],
                    [f"explicit candidate has {candidate.support_count} < {policy.min_explicit_evidence} supporting evidence"],
                )
            if not is_explicit:
                return self._result(
                    candidate, PromotionAction.DEFER,
                    ["insufficient_evidence"],
                    [f"inferred candidate has {candidate.support_count} < {policy.min_inferred_evidence} supporting evidence"],
                )

        # --- Source diversity ---
        evidence_list = candidate.evidence_refs
        unique_sources = len(set(evidence_list))
        if unique_sources < policy.min_source_diversity:
            reasons.append("low_source_diversity")
            messages.append(f"source diversity {unique_sources} < {policy.min_source_diversity}")

        # --- Contradiction check ---
        contradiction_ratio = (
            len(candidate.contradiction_refs) / max(1, len(candidate.evidence_refs))
            if candidate.evidence_refs else 0.0
        )
        if contradiction_ratio > policy.max_contradiction_ratio:
            return self._result(
                candidate, PromotionAction.REJECT,
                ["contradiction_exceeds_threshold"],
                [f"contradiction ratio {contradiction_ratio:.2f} > {policy.max_contradiction_ratio}"],
            )

        # --- Salience ---
        if candidate.salience < policy.min_salience:
            return self._result(
                candidate, PromotionAction.DEFER,
                ["low_salience"],
                [f"salience {candidate.salience:.2f} < {policy.min_salience}"],
            )

        # --- Belief check (cross-sprint protocol) ---
        belief_confidence = self._belief_confidence(belief_assessments)
        if belief_confidence is not None:
            if belief_confidence < 0.2:
                return self._result(
                    candidate, PromotionAction.REJECT,
                    ["belief_active_contradiction"],
                    ["active contradiction from belief engine"],
                )
            if belief_confidence < 0.3:
                return self._result(
                    candidate, PromotionAction.DEFER,
                    ["belief_low_confidence"],
                    ["belief engine reports low confidence for related claims"],
                )
            # Strengthen if belief corroborates
            if belief_confidence > 0.7 and not reasons:
                return self._result(
                    candidate, PromotionAction.REINFORCE,
                    ["belief_corroborates"],
                    ["belief engine corroborates the candidate"],
                )

        # --- Goal context check ---
        if goal_contexts:
            for gc in goal_contexts:
                if gc.tenant_id != candidate.tenant_id:
                    continue
                # Check for conflicts
                if candidate.candidate_type == ReflectionCandidateType.GOAL_UPDATE:
                    if "conflict" in gc.description.lower():
                        reasons.append("goal_conflict")
                        messages.append(f"candidate conflicts with goal {gc.goal_id}")

        # --- Consolidation policy check ---
        if consolidation_policy and existing_claims is not None:
            promotable, policy_reasons = consolidation_policy.is_promotable(
                candidate, existing_claims
            )
            if not promotable:
                return self._result(
                    candidate, PromotionAction.DEFER,
                    ["consolidation_policy_blocked"] + policy_reasons,
                    ["consolidation policy requires more evidence"],
                )

        # --- Risk check ---
        if self._is_risky(candidate):
            return self._result(
                candidate, PromotionAction.DEFER,
                ["high_risk"],
                ["candidate marked risky; requires review"],
            )

        # --- Final decision ---
        if reasons:
            return self._result(
                candidate, PromotionAction.DEFER,
                reasons,
                messages,
            )
        return self._result(
            candidate, PromotionAction.PROMOTE,
            ["passed_all_gates"],
            ["candidate promoted for memory consolidation"],
        )

    def _belief_confidence(
        self, assessments: Optional[List[BeliefAssessmentLike]]
    ) -> float | None:
        if not assessments:
            return None
        return max((a.overall_confidence for a in assessments), default=0.0)

    def _is_risky(self, candidate: ReflectionCandidate) -> bool:
        if candidate.candidate_type == ReflectionCandidateType.GOAL_UPDATE:
            return True
        if candidate.candidate_type == ReflectionCandidateType.SEMANTIC_FACT:
            return candidate.confidence < 0.6
        if candidate.candidate_type == ReflectionCandidateType.NONE:
            return True
        return False

    def _result(
        self,
        candidate: ReflectionCandidate,
        action: PromotionAction,
        reason_codes: List[str],
        messages: List[str],
    ) -> PromotionResult:
        return PromotionResult(
            candidate_id=candidate.candidate_id,
            action=action,
            reason_codes=reason_codes,
            messages=messages,
            confidence=candidate.confidence,
        )


def make_experience_event(
    event_type: str,
    description: str,
    timestamp: str | None = None,
    outcome: OutcomeEvidence | None = None,
    user_id: str = "u1",
    tenant_id: str = "t1",
    salience: float = 0.5,
    explicit: bool = False,
    evidence_refs: list[str] | None = None,
    goal_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExperienceEvent:
    """Factory for experience events."""
    return ExperienceEvent(
        event_id=make_event_id(),
        event_type=event_type,
        description=description,
        timestamp=timestamp or datetime.utcnow().isoformat(),
        outcome=outcome,
        user_scope={"tenant_id": tenant_id, "user_id": user_id},
        salience=salience,
        explicit=explicit,
        evidence_refs=evidence_refs or [],
        goal_refs=goal_refs or [],
        metadata=metadata or {},
    )


def make_event_id() -> str:
    from .reflection_contracts import make_event_id as _make
    return _make()


from .reflection_contracts import make_event_id as _make_event_id  # noqa: E402


def make_event_id_public() -> str:
    return _make_event_id()


__all__ = [
    "ReflectionEngine",
    "PromotionGate",
    "make_experience_event",
    "make_event_id_public",
]
