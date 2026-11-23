"""Opt-in real-host acceptance of the canonical bounded Supabase artifact reader.

Run only inside an approved isolated target deployment with a disposable,
author-owned text artifact already registered in canonical PostgreSQL and
Supabase Storage. Never mocks SQL, storage, HTTP or digest verification.
No source text, signed URL, token or identifying fixture value is logged.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid

import pytest

from ai_karen_engine.database.factory import DatabaseServiceFactory
from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio

_LIVE_FLAG = "KAREN_DOCUMENT_STORAGE_LIVE_ACCEPTANCE"
_DIGEST_FLAG = "KAREN_DOCUMENT_AUTHOR_SOURCE_SHA256"
_ARTIFACT_FLAG = "KAREN_DOCUMENT_AUTHOR_ARTIFACT_ID"
_TENANT_FLAG = "KAREN_DOCUMENT_AUTHOR_TENANT_ID"
_OWNER_FLAG = "KAREN_DOCUMENT_AUTHOR_USER_ID"


def _canonical_uuid_env(name: str) -> str:
    value = os.environ.get(name, "")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError("Noncanonical UUID")
    except (ValueError, TypeError, AttributeError) as exc:
        raise AssertionError(f"Valid approved fixture {name} is required") from exc
    return value


def _source_digest() -> str:
    value = os.environ.get(_DIGEST_FLAG, "")
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AssertionError(f"Valid approved fixture {_DIGEST_FLAG} is required")
    return value


async def test_real_bounded_storage_read_and_wrong_principal_denial() -> None:
    if os.environ.get(_LIVE_FLAG) != "true":
        pytest.skip("Real target-host storage acceptance requires explicit opt-in")

    # Fail rather than skip when opted in without a genuine source or principal.
    artifact = _canonical_uuid_env(_ARTIFACT_FLAG)
    tenant = _canonical_uuid_env(_TENANT_FLAG)
    owner = _canonical_uuid_env(_OWNER_FLAG)
    expected_digest = _source_digest()

    factory = DatabaseServiceFactory()
    assert factory.create_canonical_repositories() is not None, (
        "Approved target-host canonical repositories unavailable"
    )
    store = factory.get_service("artifact_store")
    assert isinstance(store, SupabaseArtifactStore), (
        "Acceptance requires real canonical SupabaseArtifactStore"
    )

    started = time.perf_counter()
    result = await store.read_owner_active_text_bounded(
        artifact, tenant, owner, max_bytes=65536,
    )
    read_ms = round((time.perf_counter() - started) * 1000, 2)
    assert result.success is True and result.data is not None, (
        "Real bounded storage read unavailable or rejected"
    )
    verified = result.data
    assert verified.artifact_id == artifact
    assert verified.tenant_id == tenant
    assert verified.user_id == owner
    assert verified.sha256 == expected_digest
    assert verified.mime_type == "text/plain"
    body = verified.text
    assert isinstance(body, str)
    size = len(body.encode("utf-8"))
    assert 1 <= size <= 65536
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == expected_digest
    # Prove that the repository refuses the same real object when the caller's
    # transport budget is even one byte too small, rather than accepting a
    # fully buffered oversized file. For a single byte, zero is invalid and
    # must be denied under the canonical resource-bound contract.
    undersized = await store.read_owner_active_text_bounded(
        artifact, tenant, owner, max_bytes=size - 1,
    )
    assert undersized.success is False and undersized.data is None
    # Prove denial using real PostgreSQL + storage ownership, not a simulated
    # alternate identity or a browser-supplied authorization flag.
    foreign_owner = str(uuid.uuid4())
    foreign_tenant = str(uuid.uuid4())
    assert foreign_owner != owner and foreign_tenant != tenant
    owner_denied = await store.read_owner_active_text_bounded(
        artifact, tenant, foreign_owner, max_bytes=65536,
    )
    tenant_denied = await store.read_owner_active_text_bounded(
        artifact, foreign_tenant, owner, max_bytes=65536,
    )
    assert owner_denied.success is False and owner_denied.data is None
    assert tenant_denied.success is False and tenant_denied.data is None
    # Sanitized and measured, not a performance SLA or a content artifact.
    logger.info(
        "document_storage_live_acceptance_passed",
        extra={
            "bounded_read_ms": read_ms,
            "bytes_verified": size,
            "foreign_owner_denied": True,
            "foreign_tenant_denied": True,
            "undersized_budget_denied": True,
        },
    )
