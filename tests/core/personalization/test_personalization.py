"""Adversarial tests for personalization boundaries."""

from __future__ import annotations

from datetime import datetime

from ai_karen_engine.core.personalization.contracts import (
    PreferenceCategory,
    PreferenceRecord,
    PreferenceScope,
    PreferenceStability,
    PreferenceState,
)
from ai_karen_engine.core.personalization.evaluation.corpus import EvaluationCorpus
from ai_karen_engine.core.personalization.preferences.resolver import PreferenceResolver


def _preference(
    *,
    scope: PreferenceScope,
    value: str,
    state: PreferenceState = PreferenceState.STABLE,
) -> PreferenceRecord:
    now = datetime.utcnow()
    return PreferenceRecord(
        preference_id=f"p-{scope.value}-{value}",
        user_id="u1",
        tenant_id="t1",
        key="communication.verbosity",
        value=value,
        confidence=0.9,
        stability=PreferenceStability.LONG_TERM,
        state=state,
        evidence_count=1,
        contradiction_count=0,
        first_observed_at=now,
        last_observed_at=now,
        last_confirmed_at=now,
        source_types=["canonical_memory_projection"],
        scope=scope,
        version=1,
        category=PreferenceCategory.COMMUNICATION,
    )


def test_global_preference_resolves_for_general_task() -> None:
    resolver = PreferenceResolver()
    snapshot = type(
        "Snapshot",
        (),
        {
            "user_id": "u1",
            "tenant_id": "t1",
            "stable_preferences": [
                _preference(scope=PreferenceScope.GLOBAL, value="concise")
            ],
            "tentative_preferences": [],
        },
    )()

    result = resolver.resolve(snapshot, {"intent": "chat"})

    assert result.resolved["communication.verbosity"] == "concise"


def test_narrow_preference_does_not_leak_into_global_scope() -> None:
    resolver = PreferenceResolver()
    snapshot = type(
        "Snapshot",
        (),
        {
            "user_id": "u1",
            "tenant_id": "t1",
            "stable_preferences": [],
            "tentative_preferences": [
                _preference(
                    scope=PreferenceScope.CONVERSATION,
                    value="detailed",
                    state=PreferenceState.TENTATIVE,
                )
            ],
        },
    )()

    result = resolver.resolve(
        snapshot,
        {"intent": "chat"},
        requested_scope=PreferenceScope.GLOBAL,
    )

    assert "communication.verbosity" not in result.resolved


def test_evaluation_corpus_keeps_core_personalization_cases() -> None:
    names = [case["name"] for case in EvaluationCorpus.all_cases()]

    assert "explicit_preference" in names
    assert "contradictory_preference" in names
    assert "repeated_behavior" in names
    assert "preference_reversal" in names
    assert "stale_preference" in names
