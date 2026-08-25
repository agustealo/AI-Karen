from __future__ import annotations

from ai_karen_engine.core.context.contracts import (
    ContextBudget,
    ContextCandidate,
    ContextConflict,
    ContextFreshness,
    ContextKind,
    ContextOmission,
    ContextPlan,
    ContextPriority,
    ContextReason,
    ContextRequirement,
    ContextTrustLevel,
)


def _candidate(
    candidate_id: str,
    *,
    kind: ContextKind = ContextKind.MEMORY,
    priority: ContextPriority = ContextPriority.MEDIUM,
    reason: ContextReason = ContextReason.RECENT_RELEVANT,
    trust_level: ContextTrustLevel = ContextTrustLevel.EXPLICIT,
    freshness: ContextFreshness = ContextFreshness.LONG_LIVED,
    conflicts: list[ContextConflict] | None = None,
) -> ContextCandidate:
    return ContextCandidate(
        candidate_id=candidate_id,
        kind=kind,
        content=f"content-{candidate_id}",
        priority=priority,
        reason=reason,
        trust_level=trust_level,
        freshness=freshness,
        conflicts=conflicts or [],
    )


def _plan(candidates: list[ContextCandidate], max_items: int = 20, reserved_for_critical: int = 2) -> ContextPlan:
    return ContextPlan(
        candidates=candidates,
        budget=ContextBudget(max_items=max_items, reserved_for_critical=reserved_for_critical),
    )


class TestContextContractsExist:
    def test_enums_are_string_based(self) -> None:
        assert ContextPriority.HIGH.value == "high"
        assert ContextTrustLevel.EXPLICIT.value == "explicit"
        assert ContextFreshness.RECENT.value == "recent"
        assert ContextReason.ACTIVE_GOAL.value == "active_goal"

    def test_candidate_round_trip(self) -> None:
        c = _candidate("c1", priority=ContextPriority.HIGH)
        assert c.candidate_id == "c1"
        assert c.priority == ContextPriority.HIGH

    def test_requirement_example_matches_spec(self) -> None:
        req = ContextRequirement(
            kind=ContextKind.USER_PREFERENCE,
            priority=ContextPriority.HIGH,
            reason="Response style affects current task",
            freshness=ContextFreshness.LONG_LIVED,
            max_items=3,
        )
        assert req.kind == ContextKind.USER_PREFERENCE
        assert req.priority == ContextPriority.HIGH
        assert req.freshness == ContextFreshness.LONG_LIVED
        assert req.max_items == 3


class TestSemanticBehaviorRules:
    def test_recent_relevant_outranks_recent_irrelevant(self) -> None:
        relevant = _candidate(
            "relevant",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.RECENT_RELEVANT,
            freshness=ContextFreshness.RECENT,
        )
        irrelevant = _candidate(
            "irrelevant",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.RECENT_IRRELEVANT,
            freshness=ContextFreshness.RECENT,
        )
        plan = _plan([irrelevant, relevant], max_items=3)
        selected = plan.select()
        assert len(selected) == 1
        assert selected[0].candidate_id == "relevant"

    def test_high_salience_memory_outranks_merely_recent_memory(self) -> None:
        salience = _candidate(
            "salience",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.HIGH_SALIENCE_MEMORY,
        )
        recent = _candidate(
            "recent",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.RECENT_RELEVANT,
        )
        plan = _plan([recent, salience], max_items=3)
        selected = plan.select()
        assert len(selected) == 1
        assert selected[0].candidate_id == "salience"

    def test_explicit_user_facts_outrank_inferred_assumptions(self) -> None:
        explicit = _candidate(
            "explicit",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.EXPLICIT_USER_FACT,
            trust_level=ContextTrustLevel.EXPLICIT,
        )
        inferred = _candidate(
            "inferred",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.INFERRED_ASSUMPTION,
            trust_level=ContextTrustLevel.INFERRED,
        )
        plan = _plan([inferred, explicit], max_items=3)
        selected = plan.select()
        assert len(selected) == 1
        assert selected[0].candidate_id == "explicit"

    def test_contradictory_context_is_surfaced_not_collapsed(self) -> None:
        contradicted = _candidate(
            "contradicted",
            priority=ContextPriority.HIGH,
            reason=ContextReason.CONTRADICTED,
            trust_level=ContextTrustLevel.CONTRADICTED,
        )
        normal = _candidate("normal", priority=ContextPriority.MEDIUM)
        plan = _plan([contradicted, normal], max_items=4)
        selected = plan.select()
        assert len(selected) == 1
        assert selected[0].candidate_id == "normal"
        assert contradicted not in selected

    def test_stale_facts_can_be_excluded_when_freshness_matters(self) -> None:
        stale = _candidate(
            "stale",
            priority=ContextPriority.HIGH,
            reason=ContextReason.STALE_FACT,
            freshness=ContextFreshness.STALE,
        )
        fresh = _candidate(
            "fresh",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.RECENT_RELEVANT,
            freshness=ContextFreshness.RECENT,
        )
        plan = _plan([stale, fresh], max_items=4)
        selected = plan.select()
        assert stale not in selected
        assert fresh in selected

    def test_active_goals_influence_context_priority(self) -> None:
        active_goal = _candidate(
            "goal",
            priority=ContextPriority.MEDIUM,
            reason=ContextReason.ACTIVE_GOAL,
        )
        trivia = _candidate(
            "trivia",
            priority=ContextPriority.HIGH,
            reason=ContextReason.CONVERSATIONAL_TRIVIA,
        )
        plan = _plan([trivia, active_goal], max_items=3)
        selected = plan.select()
        assert len(selected) == 1
        assert selected[0].candidate_id == "goal"

    def test_unresolved_intentions_can_enter_context_when_relevant(self) -> None:
        intention = _candidate(
            "intention",
            priority=ContextPriority.LOW,
            reason=ContextReason.UNRESOLVED_INTENTION,
        )
        plan = _plan([intention], max_items=3)
        selected = plan.select()
        assert len(selected) == 1
        assert selected[0].candidate_id == "intention"

    def test_token_pressure_causes_graceful_prioritization(self) -> None:
        low = _candidate("low", priority=ContextPriority.LOW)
        medium = _candidate("medium", priority=ContextPriority.MEDIUM)
        high = _candidate("high", priority=ContextPriority.HIGH)
        critical = _candidate("critical", priority=ContextPriority.CRITICAL)
        plan = _plan([low, medium, high, critical], max_items=4)
        selected = plan.select()
        assert len(selected) == 2
        assert critical in selected
        assert high in selected

    def test_critical_policy_context_cannot_be_dropped_for_trivia(self) -> None:
        policy = _candidate(
            "policy",
            priority=ContextPriority.CRITICAL,
            reason=ContextReason.POLICY_REQUIREMENT,
        )
        trivia = _candidate(
            "trivia",
            priority=ContextPriority.HIGH,
            reason=ContextReason.CONVERSATIONAL_TRIVIA,
        )
        plan = _plan([trivia, policy], max_items=3)
        selected = plan.select()
        assert len(selected) == 1
        assert selected[0].candidate_id == "policy"

    def test_context_selection_is_explainable_by_reason_codes(self) -> None:
        candidate = _candidate(
            "explainable",
            priority=ContextPriority.HIGH,
            reason=ContextReason.EXPLICIT_USER_FACT,
        )
        plan = _plan([candidate], max_items=3)
        selected = plan.select()
        assert len(selected) == 1
        explanations = plan.explain_selection(selected)
        assert any("selected explainable" in e for e in explanations)
        assert any("reason=explicit_user_fact" in e for e in explanations)

    def test_omission_reason_is_recorded(self) -> None:
        omitted = ContextOmission(
            reason=ContextReason.TOKEN_PRESSURE,
            detail="budget exceeded",
            omitted_ids=["c1", "c2"],
        )
        assert omitted.reason == ContextReason.TOKEN_PRESSURE
        assert len(omitted.omitted_ids) == 2
