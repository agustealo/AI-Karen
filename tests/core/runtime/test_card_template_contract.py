"""KGUI-CARD-STUDIO-01A: inert host vocabulary, no implicit rights or facts."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ai_karen_engine.core.runtime.presentation_contract import (
    CARD_TEMPLATE_COMPONENT_TYPES,
    PRESENTATION_COMPONENT_TYPES,
    built_in_card_template_catalog,
    compose_card_template_with_verified_parts,
    validate_card_template_draft,
    validate_presentation,
)


def draft(*, component: str = "time.observation") -> dict:
    return {
        "schema_version": 1,
        "template_key": "current-clock",
        "title": "Current clock",
        "layout": "stack",
        "density": "comfortable",
        "interaction_mode": "read_only",
        "slots": [{"slot_id": "main", "component_type": component}],
    }


def clock(*, evidence: str = "request-1:clock", name: str = "clock-1") -> dict:
    return {
        "schema_version": 1,
        "presentation_id": name,
        "component_type": "time.observation",
        "evidence_ref": evidence,
        "data": {"formatted": "10:15 AM", "timezone": "America/Detroit", "token": "redact-me"},
    }


def test_system_catalog_is_immutable_seed_projection_not_a_second_renderer_registry() -> None:
    catalog = built_in_card_template_catalog()
    assert len(catalog) == len(CARD_TEMPLATE_COMPONENT_TYPES) == 8
    assert set(CARD_TEMPLATE_COMPONENT_TYPES) < set(PRESENTATION_COMPONENT_TYPES)
    assert {item["definition"]["slots"][0]["component_type"] for item in catalog} == CARD_TEMPLATE_COMPONENT_TYPES
    assert len({item["definition"]["template_key"] for item in catalog}) == len(catalog)
    assert all(item["origin"] == "system" and item["editable"] is False for item in catalog)
    assert all(validate_card_template_draft(item["definition"]) == item["definition"] for item in catalog)
    catalog[0]["definition"]["title"] = "Mutated caller copy"
    assert built_in_card_template_catalog()[0]["definition"]["title"] != "Mutated caller copy"


@pytest.mark.parametrize("field,value", [
    ("schema_version", True),
    ("schema_version", 2),
    ("template_key", "system/card.jsx"),
    ("template_key", "x" * 65),
    ("title", "   "),
    ("title", "<iframe>"),
    ("title", "Unsafe\ntext"),
    ("layout", "iframe"),
    ("density", "fullscreen"),
    ("interaction_mode", "write"),
    ("slots", []),
    ("slots", [draft()["slots"][0]] * 7),
])
def test_unapproved_template_shapes_fail_closed(field: str, value: object) -> None:
    assert validate_card_template_draft({**draft(), field: value}) is None


@pytest.mark.parametrize("extra", [
    {"data": {"formatted": "faked"}},
    {"evidence_ref": "unverified"},
    {"tenant_id": "foreign-tenant"},
    {"source_url": "https://example.com/secrets"},
    {"permissions": ["admin"]},
    {"code": "<script>alert(1)</script>"},
    {"revision": 999},
    {"origin": "system"},
])
def test_model_drafts_cannot_claim_facts_scope_or_system_authority(extra: dict) -> None:
    assert validate_card_template_draft({**draft(), **extra}) is None


@pytest.mark.parametrize("component", [
    "code.artifact", "surface.composition", "unsafe.html", "action.execute", None,
])
def test_templates_cannot_bypass_host_vocabulary_or_embed_revocable_code(component: object) -> None:
    assert validate_card_template_draft(draft(component=component)) is None


def test_slots_are_strict_unique_ordered_and_inert() -> None:
    bad = draft()
    bad["slots"] = [
        {"slot_id": "same", "component_type": "time.observation"},
        {"slot_id": "same", "component_type": "data.table"},
    ]
    assert validate_card_template_draft(bad) is None
    for invalid in (
        {"slot_id": "main", "component_type": "time.observation", "on_click": "delete"},
        {"slot_id": "main", "component_type": "time.observation", "payload": {"token": "x"}},
        {"slot_id": "Main", "component_type": "time.observation"},
    ):
        assert validate_card_template_draft({**draft(), "slots": [invalid]}) is None
    safe = validate_card_template_draft({
        **draft(), "title": " Current clock ", "description": " Read-only local time ",
    })
    assert safe is not None
    assert safe["title"] == "Current clock"
    assert safe["description"] == "Read-only local time"


def test_binding_only_uses_admitted_parts_with_canonical_sanitization() -> None:
    params = dict(
        template=draft(),
        authorized_parts_by_slot={"main": clock()},
        presentation_id="template-result-1",
        evidence_ref="request-1:clock",
    )
    bound = compose_card_template_with_verified_parts(**params)
    assert bound is not None
    assert bound["component_type"] == "surface.composition"
    assert bound["data"]["layout"] == "stack"
    assert bound["data"]["items"][0]["data"] == {
        "formatted": "10:15 AM", "timezone": "America/Detroit",
    }
    assert "redact-me" not in str(bound)
    assert validate_presentation(bound) == bound
    assert compose_card_template_with_verified_parts(**{
        **params, "evidence_ref": "foreign:clock",
    }) is None
    assert compose_card_template_with_verified_parts(**{
        **params, "authorized_parts_by_slot": {"another_slot": clock()},
    }) is None
    assert compose_card_template_with_verified_parts(**{
        **params, "authorized_parts_by_slot": {"main": {**clock(), "component_type": "date.observation"}},
    }) is None


def test_multisource_card_requires_explicit_authorized_reference_manifest() -> None:
    double = {
        **draft(),
        "layout": "grid",
        "slots": [
            {"slot_id": "first", "component_type": "time.observation"},
            {"slot_id": "second", "component_type": "time.observation"},
        ],
    }
    parts = {
        "first": clock(name="a", evidence="receipt-a"),
        "second": clock(name="b", evidence="receipt-b"),
    }
    kwargs = dict(
        template=double,
        authorized_parts_by_slot=parts,
        presentation_id="multi-1",
        evidence_ref="bundle:request-1",
    )
    assert compose_card_template_with_verified_parts(**kwargs) is None
    allowed = compose_card_template_with_verified_parts(
        **kwargs,
        authorized_evidence_refs=["receipt-a", "receipt-b"],
    )
    assert allowed is not None
    assert allowed["data"]["evidence_refs"] == ["receipt-a", "receipt-b"]
    assert compose_card_template_with_verified_parts(
        **kwargs,
        authorized_evidence_refs=["receipt-a", "untrusted"],
    ) is None
    duplicate = deepcopy(parts)
    duplicate["second"]["presentation_id"] = "a"
    assert compose_card_template_with_verified_parts(
        **{**kwargs, "authorized_parts_by_slot": duplicate},
        authorized_evidence_refs=["receipt-a", "receipt-b"],
    ) is None
