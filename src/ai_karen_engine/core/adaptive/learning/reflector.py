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
from collections import defaultdict
from datetime import datetime
from typing import Any

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
    ReflectionInput,
    ReflectionPolicy,
    make_candidate_id,
    make_event_id,
)

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """Transforms experience events into reflection candidates."""

    def __init__(self, policy: ReflectionPolicy | None = None) -> None:
        self._policy = policy or ReflectionPolicy()
        self._dedup_signatures: set[str] = set()
        self._events_log: list[ExperienceEvent] = []

    def reflect(
        self,
        input_data: ReflectionInput,
    ) -> list[ReflectionCandidate]:
        """Reflect on experience events and produce learning candidates."""
        self._events_log.extend(input_data.events)
        candidates: list[ReflectionCandidate] = []
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

        deduped: list[ReflectionCandidate] = []
        for c in candidates:
            sig = self._dedup_signature(c)
            if sig not in self._dedup_signatures:
                self._dedup_signatures.add(sig)
                deduped.append(c)

        deduped.sort(key=lambda c: c.confidence * c.salience, reverse=True)
        return deduped[: input_data.max_candidates]

    def _detect_failures(self, events: list[ExperienceEvent]) -> list[ReflectionCandidate]:
        """Detect failure lessons from unsuccessful outcomes."""
        failures: list[ExperienceEvent] = []
        for ev in events:
            if ev.outcome is not None and ev.outcome.execution_status == "failure":
                failures.append(ev)

        candidates: list[ReflectionCandidate] = []
        for ev in failures:
            if not ev.explicit:
                continue
            outcome = ev.outcome
            failure_reason = (outcome.metadata.get("error", "unknown")
                              if outcome else "unknown")
            failure_lesson = FailureLessonCandidate(
                attempt_id=ev.event_id,
                expected_outcome=self._expected_outcome(ev),
                actual_outcome=outcome.execution_status if outcome else "unknown",
                failure_reason=failure_reason,
                recovery=ev.metadata.get("recovery", "retry with different approach"),
                final_result="failed",
                evidence_refs=[ev.event_id] + ev.evidence_refs,
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
            )
            candidate = ReflectionCandidate(
                candidate_id=make_candidate_id(),
                candidate_type=ReflectionCandidateType.FAILURE_LESSON,
                summary=f"Do not retry provider X when error class is {failure_reason}",
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
                metadata={"failure_reason": failure_reason},
            )
            candidates.append(candidate)
        return candidates

    def _detect_successes(self, events: list[ExperienceEvent]) -> list[ReflectionCandidate]:
        """Detect success patterns from successful outcomes."""
        successes = [
            ev for ev in events
            if ev.outcome is not None
            and ev.outcome.execution_status == "success"
            and ev.outcome.completion
        ]

        if len(successes) < 2:
            single_candidates: list[ReflectionCandidate] = []
            if len(successes) == 1:
                ev = successes[0]
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

        context_keys = self._shared_context(successes)
        if context_keys:
            ev = successes[0]
            candidate = ReflectionCandidate(
                candidate_id=make_candidate_id(),
                candidate_type=ReflectionCandidateType.SUCCESS_PATTERN,
                summary=f"Success pattern: {', '.join(context_keys)[:80]}",
                confidence=0.6,
                salience=0.7,
                evidence_refs=[ev.event_id for ev in successes],
                support_count=len(successes),
                scope=str(ev.user_id or "default"),
                proposed_action="generalize_pattern",
                reason_codes=["repeated", "success_corroborated"],
                tenant_id=ev.tenant_id,
                user_id=ev.user_id,
            )
            return [candidate]
        return []

    def _detect_patterns(self, events: list[ExperienceEvent]) -> list[ReflectionCandidate]:
        """Detect repeated behavior patterns."""
        pattern_groups: dict[str, list[ExperienceEvent]] = defaultdict(list)
        for ev in events:
            key = self._pattern_key(ev)
            if key:
                pattern_groups[key].append(ev)

        candidates: list[ReflectionCandidate] = []
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

    def _detect_preferences(self, events: list[ExperienceEvent]) -> list[ReflectionCandidate]:
        """Detect preference signals from explicit user feedback."""
        preference_events = [ev for ev in events if ev.explicit]
        if len(preference_events) < 1:
            return []

        candidates: list[ReflectionCandidate] = []
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

    def _detect_goal_updates(self, events: list[ExperienceEvent]) -> list[ReflectionCandidate]:
        """Detect goal state changes from events."""
        goal_events = [ev for ev in events if ev.goal_refs]
        if not goal_events:
            return []

        candidates: list[ReflectionCandidate] = []
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
        action_type = ev.metadata.get("action_type", "")
        return f"{ev.outcome.execution_status}:{action_type}"

    def _shared_context(self, successes: list[ExperienceEvent]) -> list[str]:
        """Find shared context keys across successful events."""
        context_sets: list[set[str]] = []
        for ev in successes:
            ctx: set[str] = set()
            action_type = ev.metadata.get("action_type")
            if action_type:
                ctx.add(f"action:{action_type}")
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

    def __init__(self, policy: PromotionPolicy | None = None) -> None:
        self._policy = policy or PromotionPolicy()

    def evaluate(
        self,
        candidate: ReflectionCandidate,
        belief_assessments: list[BeliefAssessmentLike] | None = None,
        goal_contexts: list[GoalContextLike] | None = None,
        existing_claims: list[Any] | None = None,
        consolidation_policy: ConsolidationPolicyLike | None = None,
    ) -> PromotionResult:
        """Evaluate a candidate for promotion, deferral, or rejection."""
        reasons: list[str] = []
        messages: list[str] = []
        policy = self._policy

        if candidate.confidence < 0.2:
            return self._result(
                candidate, PromotionAction.REJECT,
                ["confidence_below_minimum"],
                [f"confidence {candidate.confidence} below minimum viable threshold"],
            )

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
            return self._result(
                candidate, PromotionAction.DEFER,
                ["insufficient_evidence"],
                [f"candidate has {candidate.support_count} < {min_evidence} supporting evidence"],
            )

        unique_sources = len(set(candidate.evidence_refs))
        if unique_sources < policy.min_source_diversity:
            reasons.append("low_source_diversity")
            messages.append(f"source diversity {unique_sources} < {policy.min_source_diversity}")

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

        if candidate.salience < policy.min_salience:
            return self._result(
                candidate, PromotionAction.DEFER,
                ["low_salience"],
                [f"salience {candidate.salience:.2f} < {policy.min_salience}"],
            )

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
            if belief_confidence > 0.7 and not reasons:
                return self._result(
                    candidate, PromotionAction.REINFORCE,
                    ["belief_corroborates"],
                    ["belief engine corroborates the candidate"],
                )

        if goal_contexts:
            for gc in goal_contexts:
                if gc.tenant_id != candidate.tenant_id:
                    continue
                if candidate.candidate_type == ReflectionCandidateType.GOAL_UPDATE:
                    if "conflict" in gc.description.lower():
                        reasons.append("goal_conflict")
                        messages.append(f"candidate conflicts with goal {gc.goal_id}")

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

        if self._is_risky(candidate):
            return self._result(
                candidate, PromotionAction.DEFER,
                ["high_risk"],
                ["candidate marked risky; requires review"],
            )

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
        self, assessments: list[BeliefAssessmentLike] | None
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
        reason_codes: list[str],
        messages: list[str],
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


__all__ = [
    "PromotionGate",
    "ReflectionEngine",
    "make_event_id",
    "make_experience_event",
]
