"""Missing scope and mismatched personas must never widen preferences."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.personalization.contracts import (
    PreferenceCategory, PreferenceRecord, PreferenceScope,
    PreferenceStability, PreferenceState,
)
from ai_karen_engine.core.personalization.preferences.resolver import PreferenceResolver


def _pref(scope, value, metadata=None, confidence=0.9):
    now = datetime.utcnow()
    return PreferenceRecord(
        preference_id=f"{scope.value}-{value}",
        user_id="user", tenant_id="tenant",
        key="communication.verbosity", value=value, confidence=confidence,
        stability=PreferenceStability.LONG_TERM, state=PreferenceState.STABLE,
        evidence_count=1, contradiction_count=0,
        first_observed_at=now, last_observed_at=now,
        last_confirmed_at=now, source_types=["explicit_user_statement"],
        scope=scope, version=1, category=PreferenceCategory.COMMUNICATION,
        metadata=metadata or {},
    )


def _resolve(preferences, context=None, scope=None):
    snapshot = SimpleNamespace(
        user_id="user", tenant_id="tenant",
        stable_preferences=preferences, tentative_preferences=[],
    )
    return PreferenceResolver().resolve(snapshot, context or {}, scope)


@pytest.mark.parametrize("scope,field,value", [
    (PreferenceScope.DOMAIN, "domain", "design"),
    (PreferenceScope.TASK_TYPE, "task_type", "review"),
    (PreferenceScope.PROJECT, "project", "brand-a"),
    (PreferenceScope.SESSION, "session_id", "session-a"),
    (PreferenceScope.CONVERSATION, "conversation_id", "thread-a"),
])
def test_scoped_preferences_require_exact_selector(scope, field, value):
    pref = _pref(scope, "detailed", {field: value})
    assert not _resolve([pref]).resolved
    assert not _resolve([pref], {field: "different"}).resolved
    applied = _resolve([pref], {field: value})
    assert applied.resolved["communication.verbosity"] == "detailed"
    assert applied.applied_scope == scope


def test_missing_scope_metadata_is_not_wildcard():
    assert not _resolve(
        [_pref(PreferenceScope.PROJECT, "detailed")],
        {"project": "brand-a"},
    ).resolved


def test_narrow_scope_wins_without_depending_on_database_order():
    broad = _pref(PreferenceScope.GLOBAL, "concise")
    narrow = _pref(PreferenceScope.PROJECT, "detailed", {"project": "brand-a"})
    for records in ([broad, narrow], [narrow, broad]):
        result = _resolve(records, {"project": "brand-a"})
        assert result.resolved["communication.verbosity"] == "detailed"
        assert result.applied_scope == PreferenceScope.PROJECT
    assert _resolve([broad, narrow]).resolved["communication.verbosity"] == "concise"


def test_persona_private_preference_requires_matching_context():
    pref = _pref(
        PreferenceScope.PROJECT, "detailed",
        {"project": "brand-a", "persona_id": "Troy"},
    )
    assert not _resolve([pref], {"project": "brand-a"}).resolved
    assert not _resolve(
        [pref], {"project": "brand-a", "persona_id": "Morgan"},
    ).resolved
    assert _resolve(
        [pref], {"project": "brand-a", "persona_id": "Troy"},
    ).resolved["communication.verbosity"] == "detailed"


def test_unrelated_confidence_is_excluded_from_result():
    global_pref = _pref(PreferenceScope.GLOBAL, "concise", confidence=0.3)
    other_pref = _pref(
        PreferenceScope.PROJECT, "detailed",
        {"project": "other"}, confidence=1.0,
    )
    assert _resolve([global_pref, other_pref]).confidence == pytest.approx(0.3)
