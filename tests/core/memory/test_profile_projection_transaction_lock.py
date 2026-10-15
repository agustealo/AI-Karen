"""Transaction lock key invariants for concurrent profile projections."""

from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)


def key(tenant="t1", user="u1", category="preference", attribute="favorite_color"):
    return PostgresDerivedMemoryProjector._profile_projection_lock_id(
        tenant_id=tenant, user_id=user, category=category, attribute=attribute,
    )


def test_lock_id_is_deterministic_signed_bigint():
    first = key()
    assert first == key()
    assert -(2**63) <= first < 2**63


def test_tenant_and_user_boundaries_use_distinct_lanes():
    assert key() != key(tenant="t2")
    assert key() != key(user="u2")


def test_different_attributes_and_categories_use_distinct_lanes():
    assert key() != key(attribute="favorite_food")
    assert key() != key(category="identity")


def test_casefold_normalizes_attribute_and_category():
    assert key() == key(category=" PREFERENCE ", attribute=" FAVORITE_COLOR ")


def test_scope_is_serialized_at_attribute_lane():
    # Distinct contexts under one attribute safely serialize before the
    # projector checks which fact slot should be superseded.
    assert key() == key()
