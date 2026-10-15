"""Fail-closed authorization and event provenance for legacy profile repairs."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.core.memory.protocols import VaultContext
from ai_karen_engine.platform.memory.postgres.profile_reconciliation import (
    _provenance_issue,
    _require_maintenance_authority,
)


def context(*, capability=True, actor=True, authorized=True, denied=False):
    tenant, user = str(uuid4()), str(uuid4())
    return VaultContext(
        tenant_id=tenant, user_id=user, request_id=str(uuid4()),
        correlation_id=str(uuid4()), actor_id="operator" if actor else None,
        policy_context={
            "allowed_capabilities": ["memory.maintenance"] if capability else [],
            "authorized_tenant_id": tenant if authorized else str(uuid4()),
            "authorized_user_id": user,
            "denied": denied,
        },
    )


def test_maintenance_context_requires_explicit_capability_and_identity():
    authorized = context()
    tenant, user = _require_maintenance_authority(authorized)
    assert str(tenant) == authorized.tenant_id
    assert str(user) == authorized.user_id
    for invalid in (
        context(capability=False), context(actor=False),
        context(authorized=False), context(denied=True),
    ):
        with pytest.raises(PermissionError):
            _require_maintenance_authority(invalid)


def sample():
    tenant, user = uuid4(), uuid4()
    value = {
        "value": "Bob Marley", "text": "I love Bob Marley",
        "cardinality": "set", "domain": "music",
    }
    row = SimpleNamespace(
        category="preference", attribute="favorite_artist",
        value=value, source_type="chat_user",
        valid_from=None,
    )
    event = SimpleNamespace(
        tenant_id=tenant, user_id=user,
        source_type="chat_user",
        consent_state="granted",
        valid_from=None, valid_to=None,
        payload={
            "content": "I love Bob Marley",
            "metadata": {"custom": {"signal_semantics": {
                "category": "preference", "attribute": "favorite_artist",
                "normalized_value": "Bob Marley",
                "cardinality": "set", "domain": "music",
            }}},
            "vault": {"consent_scope": "memory.write"},
        },
    )
    return tenant, user, row, event


def issue(row, event, tenant, user, *, consent=None):
    return _provenance_issue(
        row, event, tenant_id=tenant, user_id=user,
        consent=consent or {}, now=datetime.utcnow(),
    )


def test_original_evidence_must_match_value_scope_and_text():
    tenant, user, row, event = sample()
    assert issue(row, event, tenant, user) is None
    row.value["value"] = "Not Bob"
    assert issue(row, event, tenant, user) == "evidence_value_mismatch"
    row.value["value"] = "Bob Marley"
    row.value["domain"] = "travel"
    assert issue(row, event, tenant, user) == "evidence_scope_mismatch"
    row.value["domain"] = "music"
    row.value["text"] = "fabricated statement"
    assert issue(row, event, tenant, user) == "evidence_text_mismatch"


def test_revocation_and_cross_tenant_provenance_fail_closed():
    tenant, user, row, event = sample()
    assert issue(row, event, uuid4(), user) == "missing_or_cross_scope_event"
    assert issue(row, None, tenant, user) == "missing_or_cross_scope_event"
    event.consent_state = "revoked"
    assert issue(row, event, tenant, user) == "revoked_event"
    event.consent_state = "granted"
    event.valid_to = datetime.utcnow() - timedelta(seconds=5)
    assert issue(row, event, tenant, user) == "inactive_event"
    event.valid_to = None
    assert issue(row, event, tenant, user, consent={"memory.write": False}) == (
        "revoked_consent_scope"
    )


def test_unverifiable_legacy_payload_is_never_guessed():
    tenant, user, row, event = sample()
    event.payload = {"text": row.value["text"]}
    assert issue(row, event, tenant, user) == "unverifiable_evidence"


def test_semantic_category_and_source_claims_must_match():
    tenant, user, row, event = sample()
    row.source_type = "untrusted_api"
    assert issue(row, event, tenant, user) == "source_mismatch"
    row.source_type = "chat_user"
    event.payload["metadata"]["custom"]["signal_semantics"]["attribute"] = "job"
    assert issue(row, event, tenant, user) == "unverifiable_semantics"



def test_legacy_value_without_normalization_must_equal_original_event_text():
    tenant, user, row, event = sample()
    del event.payload["metadata"]["custom"]["signal_semantics"]["normalized_value"]
    # The old projector fell back to signal.text when no normalized value
    # existed. It is not proof for any other rendered profile value.
    assert issue(row, event, tenant, user) == "evidence_value_mismatch"
    row.value["value"] = row.value["text"]
    assert issue(row, event, tenant, user) is None


def test_scope_qualifier_cannot_be_assigned_without_original_evidence():
    tenant, user, row, event = sample()
    row.value["scope"] = "project:karen"
    assert issue(row, event, tenant, user) == "evidence_scope_mismatch"
    event.payload["metadata"]["custom"]["signal_semantics"]["scope"] = "project:karen"
    assert issue(row, event, tenant, user) is None
