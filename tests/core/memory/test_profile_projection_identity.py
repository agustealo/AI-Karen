"""Guard profile projections against broad attribute-level supersession."""

import pytest

from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)


def matches(existing, incoming):
    return PostgresDerivedMemoryProjector._same_profile_identity(
        existing=existing, incoming=incoming,
    )


def test_global_singleton_new_value_supersedes_same_slot():
    assert matches({"value": "black"}, {"value": "green"})


def test_independent_genre_favorites_coexist():
    old = {"value": "Bob Marley", "domain": "music", "facet": "reggae"}
    new = {"value": "Nina Simone", "domain": "music", "facet": "jazz"}
    assert not matches(old, new)


def test_distinct_project_preferences_coexist():
    old = {"value": "dark", "project_id": "karen", "scope": "ui"}
    new = {"value": "light", "project_id": "marketing", "scope": "ui"}
    assert not matches(old, new)


def test_scoped_preference_does_not_erase_global_preference():
    assert not matches(
        {"value": "black"},
        {"value": "green", "scope": "project"},
    )


def test_multi_value_set_members_remain_independent():
    first = {"value": "Bob Marley", "cardinality": "set", "domain": "music"}
    second = {"value": "Nina Simone", "cardinality": "set", "domain": "music"}
    same = {"value": "bob marley", "cardinality": "set", "domain": "music"}
    assert not matches(first, second)
    assert matches(first, same)


def test_episodes_and_temporal_series_never_supersede_implicitly():
    for cardinality in ("event", "temporal_series"):
        value = {"value": "concert", "cardinality": cardinality}
        assert not matches(value, value)


def test_legacy_and_explicit_singleton_are_compatible():
    assert matches({"value": "black"}, {"value": "green", "cardinality": "singleton"})


def test_unknown_cardinality_cannot_be_silently_projected():
    with pytest.raises(ValueError, match="unsupported"):
        matches({"value": "old", "cardinality": "alien"},
                {"value": "new", "cardinality": "alien"})


def test_broken_or_unrecognized_old_view_not_overwritten():
    assert not matches("legacy-text-row", {"value": "new"})
