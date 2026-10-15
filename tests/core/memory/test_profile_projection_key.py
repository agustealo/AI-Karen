"""Adversarial projection identity contract for current profile slots."""

from __future__ import annotations

from uuid import uuid4

import pytest

from ai_karen_engine.core.memory.semantic_contract import (
    profile_projection_key,
    profile_projection_slot,
)
from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)


def key(
    value="black", *, tenant="tenant-1", user="user-1",
    category="preference", attribute="favorite_color",
    cardinality=None, event="event-1", **qualifiers,
):
    entry = {"value": value, **qualifiers}
    if cardinality is not None:
        entry["cardinality"] = cardinality
    return profile_projection_key(
        tenant_id=tenant,
        user_id=user,
        category=category,
        attribute=attribute,
        value=entry,
        source_event_id=event,
    )


def test_singleton_value_changes_share_current_slot_but_not_evidence():
    assert key("black") == key("green", event="event-2")
    assert key("black") == key(
        "green", cardinality="singleton", event="event-2",
    )


def test_scope_and_qualifiers_prevent_unrelated_supersession():
    assert key("dark", project_id="karen") != key(
        "light", project_id="website",
    )
    assert key("Bob Marley", domain="music", facet="reggae") != key(
        "Nina Simone", domain="music", facet="jazz",
    )
    assert key("Bob Marley", context="work") != key(
        "Bob Marley", context="home",
    )
    assert key("black") != key("green", scope="project:marketing")


def test_set_member_is_canonical_and_independent():
    assert key("Bob Marley", cardinality="set") == key(
        " bob marley ", cardinality="set", event="event-2",
    )
    assert key("Bob Marley", cardinality="set") != key(
        "Nina Simone", cardinality="set",
    )
    assert key("Bob Marley", cardinality="set") != key(
        "Bob Marley", cardinality="singleton",
    )


def test_events_and_temporal_series_use_event_identity():
    for cardinality in ("event", "temporal_series"):
        assert key("concert", cardinality=cardinality) != key(
            "concert", cardinality=cardinality, event="event-2",
        )
        assert key("concert", cardinality=cardinality) == key(
            "concert", cardinality=cardinality,
        )
        assert profile_projection_slot(
            {"value": "concert", "cardinality": cardinality}
        ) is None


def test_tenant_user_and_predicate_boundaries_are_in_hash():
    original = key()
    assert original != key(tenant="tenant-2")
    assert original != key(user="user-2")
    assert original != key(category="identity")
    assert original != key(attribute="favorite_food")


def test_projection_key_is_deterministic_bounded_hex():
    fact_key = key(" Bob Marley ", domain=" MUSIC ", facet=" Reggae ")
    assert fact_key == key("Bob Marley", domain="music", facet="reggae")
    assert len(fact_key) == 64
    assert all(character in "0123456789abcdef" for character in fact_key)


@pytest.mark.parametrize("payload", [
    {"value": "red", "cardinality": "invalid"},
    {"value": ["Bob Marley"], "cardinality": "set"},
    {"value": "red", "domain": {"malicious": True}},
    {"value": "red", "scope": ["other_user"]},
])
def test_malformed_or_ambiguous_slot_is_rejected(payload):
    with pytest.raises(ValueError):
        profile_projection_key(
            tenant_id="tenant", user_id="user",
            category="preference", attribute="favorite_artist",
            value=payload, source_event_id="event",
        )


def test_existing_legacy_and_explicit_singleton_share_slot():
    matches = PostgresDerivedMemoryProjector._same_profile_identity
    assert matches(existing={"value": "black"}, incoming={
        "value": "green", "cardinality": "singleton",
    })
    assert not matches(existing={"value": "black"}, incoming={
        "value": "green", "cardinality": "scoped_singleton",
    })


def test_invalid_historical_slot_does_not_erase_new_valid_fact():
    matches = PostgresDerivedMemoryProjector._same_profile_identity
    assert not matches(
        existing={"value": "red", "cardinality": "invalid"},
        incoming={"value": "black"},
    )


def test_hash_does_not_depend_on_new_random_event_for_singletons():
    one, two = str(uuid4()), str(uuid4())
    assert key("black", event=one) == key("green", event=two)
