"""Opt-in, read-only live acceptance of delegated KariSignature use before/after author revocation.

This is a two-phase target-host trial against an approved disposable fixture.
The test never creates users, grants, profiles, receipts, or revocations.
An authorized operator performs first-party revocation through the existing
authenticated author workflow between the BEFORE and AFTER runs.

Precondition: a genuine published revision and live delegated grant exist
before the first run. A successful AFTER-only run is NOT acceptance evidence.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid

import pytest

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
    KariSignatureResolver,
    KariSignatureRevision,
)
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleProfileRepository,
)

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio

_FLAG = "KAREN_DOCUMENT_DELEGATED_USE_LIVE_ACCEPTANCE"
_PHASE = "KAREN_DOCUMENT_DELEGATED_USE_PHASE"
_TENANT = "KAREN_DOCUMENT_AUTHOR_TENANT_ID"
_PROFILE = "KAREN_DOCUMENT_AUTHOR_PROFILE_ID"
_DELEGATE = "KAREN_DOCUMENT_DELEGATE_USER_ID"
_REVISION = "KAREN_DOCUMENT_PUBLISHED_REVISION_ID"
_REVISION_NUMBER = "KAREN_DOCUMENT_PUBLISHED_REVISION_NUMBER"
_REVISION_DIGEST = "KAREN_DOCUMENT_PUBLISHED_REVISION_SHA256"
_PURPOSE = "KAREN_DOCUMENT_DELEGATED_PURPOSE"
_EXPRESSION = "KAREN_DOCUMENT_PUBLISHED_EXPRESSION_JSON"

def _uuid(name: str) -> str:
    value = os.environ.get(name, "")
    try:
        canonical = str(uuid.UUID(value))
    except (TypeError, AttributeError, ValueError) as exc:
        raise AssertionError(f"Approved fixture {name} requires canonical UUID") from exc
    assert value == canonical, f"Approved fixture {name} requires canonical UUID"
    return value


def _fixture() -> tuple[KariSignatureRequest, KariSignatureRevision]:
    tenant = _uuid(_TENANT)
    profile = _uuid(_PROFILE)
    actor = _uuid(_DELEGATE)
    revision = _uuid(_REVISION)
    number = os.environ.get(_REVISION_NUMBER, "")
    assert number.isdecimal() and 1 <= int(number) <= 1_000_000, (
        "Approved published revision number required"
    )
    digest = os.environ.get(_REVISION_DIGEST, "")
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), (
        "Approved published revision SHA-256 required"
    )
    purpose = os.environ.get(_PURPOSE, "")
    # The canonical KariSignatureRequest validates token shape. Whether this
    # exact purpose is actually granted is decided by live PostgreSQL RLS.
    assert purpose, "Approved delegated-use purpose required"
    try:
        expression = json.loads(os.environ.get(_EXPRESSION, ""))
    except (TypeError, ValueError) as exc:
        raise AssertionError("Approved published expression JSON required") from exc
    assert isinstance(expression, dict) and expression, (
        "Approved nonempty published expression required"
    )
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in expression.items()), (
        "Approved expression fields must be strings"
    )
    assert KariSignatureRevision.digest(expression) == digest, (
        "Approved expression and revision digest disagree"
    )
    request = KariSignatureRequest(
        tenant_id=tenant, actor_id=actor, profile_id=profile,
        purpose=purpose, correlation_id="ws04a9-live-delegated-use",
    )
    revision_record = KariSignatureRevision(
        tenant_id=tenant, profile_id=profile, revision_id=revision,
        revision_number=int(number), state="published",
        approved_expression=expression, content_digest=digest,
    )
    return request, revision_record


async def test_live_delegated_use_before_and_after_revocation() -> None:
    if os.environ.get(_FLAG) != "true":
        pytest.skip("Real delegated-use acceptance requires explicit opt-in")

    phase = os.environ.get(_PHASE, "").lower()
    assert phase in {"before", "after"}, (
        "Set an explicit before or after phase; do not infer consent state"
    )
    request, known_revision = _fixture()
    repository = WritingStyleProfileRepository()
    started = time.perf_counter()
    current = await repository.read_current_published(request=request)
    allowed = await repository.authorize_use(
        request=request, revision=known_revision,
    )
    resolver = KariSignatureResolver(repository)
    if phase == "before":
        # A live positive check is necessary, otherwise a revoked grant could
        # make a negative-only test vacuously pass without any functioning use.
        assert current is not None, "No actually usable delegated publication"
        assert current.revision_id == known_revision.revision_id
        assert current.revision_number == known_revision.revision_number
        assert current.content_digest == known_revision.content_digest
        assert allowed is True, "Current delegated-use grant was not authorized"
        resolved = await resolver.resolve(request)
        assert resolved.revision_id == known_revision.revision_id
        assert resolved.content_digest == known_revision.content_digest
    else:
        # Must run only after the separately verified first-party author
        # revocation on the same approved fixture. This is a read-only proof
        # that the previously usable revision can no longer be delegated.
        assert current is None, "Revoked published revision remains visible"
        assert allowed is False, "Revoked delegated-use grant remains usable"
        with pytest.raises(PermissionError, match="style_unavailable"):
            await resolver.resolve(request)

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "document_delegated_use_live_acceptance",
        extra={
            "phase": phase,
            "read_authorize_resolve_ms": duration_ms,
            "published_visible": current is not None,
            "delegated_use_allowed": allowed is True,
        },
    )
