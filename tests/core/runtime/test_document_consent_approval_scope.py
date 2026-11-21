"""WS-04A9F: immutable consent approval binding cannot be scope-replayed."""
from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.document_consent_approval import (
    DocumentConsentApprovalScope,
)


def scope() -> DocumentConsentApprovalScope:
    return DocumentConsentApprovalScope(
        tenant_id=str(uuid.uuid4()),
        author_actor_id=str(uuid.uuid4()),
        session_id=uuid.uuid4().hex,
        profile_id=str(uuid.uuid4()),
        artifact_id=str(uuid.uuid4()),
        source_sha256="a" * 64,
        action="issue",
        analysis_allowed=True,
        style_use_allowed=False,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_scope_fingerprint_binds_revision_purpose_principal_and_session() -> None:
    original = scope()
    digest = original.fingerprint()
    assert len(digest) == 64
    assert digest == original.fingerprint()
    assert replace(original, source_sha256="b" * 64).fingerprint() != digest
    assert replace(original, style_use_allowed=True).fingerprint() != digest
    assert replace(original, action="revoke").fingerprint() != digest
    assert replace(original, session_id=uuid.uuid4().hex).fingerprint() != digest
    assert replace(original, author_actor_id=str(uuid.uuid4())).fingerprint() != digest
    assert "source_text" not in original.to_record()


@pytest.mark.parametrize("field,value", [
    ("tenant_id", ""),
    ("author_actor_id", "not-a-uuid"),
    ("artifact_id", "UPPERCASE"),
    ("source_sha256", "a" * 63),
    ("source_sha256", "A" * 64),
    ("session_id", ""),
    ("session_id", "space in session"),
    ("action", "publish"),
    ("analysis_allowed", False),
    ("style_use_allowed", 1),
    ("expires_at", datetime(2020, 1, 1, tzinfo=timezone.utc)),
    ("expires_at", datetime(2030, 1, 1)),
])
def test_invalid_author_consent_scope_is_rejected(field, value) -> None:
    with pytest.raises(ValueError):
        replace(scope(), **{field: value})


def test_scope_cannot_be_mutated_after_binding() -> None:
    original = scope()
    with pytest.raises(FrozenInstanceError):
        original.action = "revoke"


def test_scope_requires_matching_verified_context() -> None:
    bound = scope()
    principal = SimpleNamespace(
        user_id=bound.author_actor_id, tenant_id=bound.tenant_id,
    )
    context = SimpleNamespace(
        tenant_id=bound.tenant_id,
        user_id=bound.author_actor_id,
        session_id=bound.session_id,
        require_authenticated_user=lambda: principal,
    )
    bound.require_matching_context(context)
    for field, value in [
        ("tenant_id", str(uuid.uuid4())),
        ("user_id", str(uuid.uuid4())),
        ("session_id", uuid.uuid4().hex),
    ]:
        with pytest.raises(PermissionError):
            bound.require_matching_context(SimpleNamespace(
                **{**vars(context), field: value}
            ))


def test_missing_authenticated_principal_is_never_approval() -> None:
    bound = scope()
    with pytest.raises(PermissionError):
        bound.require_matching_context(SimpleNamespace(
            tenant_id=bound.tenant_id,
            user_id=bound.author_actor_id,
            session_id=bound.session_id,
        ))
