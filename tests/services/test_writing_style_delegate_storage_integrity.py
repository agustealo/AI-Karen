"""WS-04B7: delegated style release needs live, owner-scoped Storage proof.

These are deterministic contract tests only. Real PostgreSQL RLS, private
functions and exact-head migrations are exercised in the dedicated SQL suite;
canonical Supabase 206/Content-Range and streaming are tested by the existing
artifact-store suite. No test pretends to be a real-host Storage acceptance.
"""
from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
    KariSignatureRevision,
    KariSignatureResolver,
)
from ai_karen_engine.services.database.repositories.artifact_store import (
    VerifiedArtifactText,
)
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleProfileRepository,
)

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DELEGATE = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PROFILE = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
REVISION = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
ARTIFACT = "ffffffff-ffff-4fff-8fff-ffffffffffff"
SOURCE = "authornote"
DIGEST = hashlib.sha256(SOURCE.encode("utf-8")).hexdigest()


def _revision() -> KariSignatureRevision:
    expression = {"tone": "direct"}
    return KariSignatureRevision(
        tenant_id=TENANT,
        profile_id=PROFILE,
        revision_id=REVISION,
        revision_number=1,
        state="published",
        approved_expression=expression,
        content_digest=KariSignatureRevision.digest(expression),
    )


def _request() -> KariSignatureRequest:
    return KariSignatureRequest(
        tenant_id=TENANT,
        actor_id=DELEGATE,
        profile_id=PROFILE,
        purpose="draft_email",
        correlation_id="ws04b7-storage-test",
    )


class SqlHarness:
    """Only simulated SQL execution, never an auth provider."""

    def __init__(self, *, document: bool = True):
        self.authorized = True
        self.rows = (
            [{"artifact_id": ARTIFACT, "owner_actor_id": OWNER,
              "source_sha256": DIGEST}]
            if document else []
        )
        self.calls: list[str] = []
        self.on_document_query = None
        self.closed = False

    async def execute(self, statement, args=None):
        sql = str(statement)
        self.calls.append(sql)
        if "set_config(" in sql:
            return SimpleNamespace(first=lambda: None)
        if sql.startswith("SELECT r.revision_id"):
            record = {
                "revision_id": REVISION,
                "revision_number": 1,
                "approved_expression": {"tone": "direct"},
                "content_digest": _revision().content_digest,
            }
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    one_or_none=lambda: record if self.authorized else None,
                )
            )
        if sql.startswith("SELECT 1 FROM public.writing_style_profiles"):
            return SimpleNamespace(
                first=lambda: object() if self.authorized else None
            )
        if "kari_internal.writing_style_authorized_document_sources" in sql:
            if self.on_document_query is not None:
                self.on_document_query()
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(all=lambda: list(self.rows))
            )
        raise AssertionError("Unexpected SQL in delegated-use contract")

    @asynccontextmanager
    async def get_async_session(self):
        try:
            yield self
        finally:
            self.closed = True


class StorageHarness:
    def __init__(self, *, sql: SqlHarness | None = None):
        self.content = SOURCE
        self.mime_type = "text/plain"
        self.sql = sql
        self.calls = []
        self.delay = 0.0
        self.storage_exception = None
        self.change_grant_after_read = False
        self.download = AsyncMock(
            side_effect=AssertionError("unbounded download forbidden"),
        )

    async def read_owner_active_text_bounded(
        self, artifact_id, tenant_id, user_id, *, max_bytes=65536,
    ):
        self.calls.append((artifact_id, tenant_id, user_id, max_bytes))
        if self.storage_exception is not None:
            raise self.storage_exception
        if self.delay:
            await asyncio.sleep(self.delay)
        if (
            artifact_id != ARTIFACT
            or tenant_id != TENANT
            or user_id != OWNER
        ):
            return RepositoryResult(success=False, error="denied")
        if self.change_grant_after_read and self.sql is not None:
            self.sql.authorized = False
        return RepositoryResult(
            success=True,
            data=VerifiedArtifactText(
                artifact_id=artifact_id,
                tenant_id=tenant_id,
                user_id=user_id,
                filename="author.txt",
                mime_type=self.mime_type,
                sha256=DIGEST,
                text=self.content,
            ),
        )


def _repo(sql: SqlHarness, storage: StorageHarness | None):
    return WritingStyleProfileRepository(
        client_factory=lambda: sql,
        artifact_store=storage,
    )


@pytest.mark.asyncio
async def test_delegate_receives_only_style_after_one_live_verified_read():
    sql = SqlHarness()
    store = StorageHarness(sql=sql)
    resolution = await KariSignatureResolver(_repo(sql, store)).resolve(
        _request(),
    )
    assert resolution.presentation == {"tone": "direct"}
    assert not hasattr(resolution, "text")
    assert store.calls == [(ARTIFACT, TENANT, OWNER, 65536)]
    assert sql.closed is True
    assert len([s for s in sql.calls if "kari_internal." in s]) == 2
    store.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_store_does_not_disable_manually_authored_style():
    manually_authored = SqlHarness(document=False)
    assert await _repo(manually_authored, None).authorize_use(
        request=_request(), revision=_revision(),
    ) is True
    document = SqlHarness(document=True)
    assert await _repo(document, None).authorize_use(
        request=_request(), revision=_revision(),
    ) is False


@pytest.mark.asyncio
async def test_bad_grant_blocks_private_scope_and_storage_read():
    sql = SqlHarness()
    sql.authorized = False
    store = StorageHarness()
    assert await _repo(sql, store).authorize_use(
        request=_request(), revision=_revision(),
    ) is False
    assert store.calls == []
    assert not any("kari_internal." in s for s in sql.calls)


@pytest.mark.parametrize("change", [
    "same_length_tamper",
    "wrong_owner",
    "wrong_mime",
    "wrong_artifact",
    "wrong_digest",
    "missing_text",
    "storage_exception",
])
@pytest.mark.asyncio
async def test_doc_use_fails_closed_without_leaking_private_source(change):
    sql = SqlHarness()
    store = StorageHarness()
    if change == "same_length_tamper":
        store.content = "authorN0te"
    elif change == "wrong_owner":
        sql.rows[0]["owner_actor_id"] = "99999999-9999-4999-8999-999999999999"
    elif change == "wrong_mime":
        store.mime_type = "application/pdf"
    elif change == "wrong_artifact":
        sql.rows[0]["artifact_id"] = "not-a-uuid"
    elif change == "wrong_digest":
        sql.rows[0]["source_sha256"] = "0" * 64
    elif change == "missing_text":
        store.content = ""
    elif change == "storage_exception":
        store.storage_exception = RuntimeError(
            "private storage credentials and signed URL must not escape"
        )
    repo = _repo(sql, store)
    with pytest.raises(PermissionError, match="style_unavailable") as denied:
        await KariSignatureResolver(repo).resolve(_request())
    assert "storage" not in str(denied.value)
    assert "credentials" not in str(denied.value)
    store.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_revocation_after_storage_read_denies_release():
    sql = SqlHarness()
    store = StorageHarness(sql=sql)
    store.change_grant_after_read = True
    assert await _repo(sql, store).authorize_use(
        request=_request(), revision=_revision(),
    ) is False
    assert sql.closed is True
    assert len(store.calls) == 1


@pytest.mark.asyncio
async def test_private_receipt_set_change_between_checks_denies_release():
    sql = SqlHarness()
    store = StorageHarness(sql=sql)
    query_count = 0

    def mutate():
        nonlocal query_count
        query_count += 1
        if query_count == 2:
            sql.rows = []

    sql.on_document_query = mutate
    assert await _repo(sql, store).authorize_use(
        request=_request(), revision=_revision(),
    ) is False
    assert len(store.calls) == 1


@pytest.mark.asyncio
async def test_bounded_total_deadline_rejects_slow_storage(monkeypatch):
    sql = SqlHarness()
    store = StorageHarness()
    store.delay = 0.1
    monkeypatch.setenv(
        "KAREN_STYLE_DELEGATED_INTEGRITY_DEADLINE_SECONDS", "0.01",
    )
    assert await _repo(sql, store).authorize_use(
        request=_request(), revision=_revision(),
    ) is False
    assert sql.closed is True
    assert len(store.calls) == 1


@pytest.mark.asyncio
async def test_private_source_count_cap_rejects_before_any_storage_read(monkeypatch):
    sql = SqlHarness()
    sql.rows = [
        {"artifact_id": ARTIFACT, "owner_actor_id": OWNER,
         "source_sha256": DIGEST}
        for _ in range(3)
    ]
    monkeypatch.setenv("KAREN_STYLE_DELEGATED_MAX_DOCUMENT_SOURCES", "2")
    store = StorageHarness()
    assert await _repo(sql, store).authorize_use(
        request=_request(), revision=_revision(),
    ) is False
    assert store.calls == []


def test_reject_unbounded_store_substitute():
    with pytest.raises(ValueError, match="canonical_bounded_artifact_store_required"):
        WritingStyleProfileRepository(
            client_factory=SqlHarness,
            artifact_store=object(),
        )


def test_delegated_style_integrity_config_bounds(monkeypatch):
    from ai_karen_engine.config.artifact_storage import ArtifactStorageConfig

    for variable, values, expected in (
        (
            "KAREN_STYLE_DELEGATED_MAX_DOCUMENT_SOURCES",
            ("0", "65", "not-an-int", ""),
            "Invalid delegated style document source limit",
        ),
        (
            "KAREN_STYLE_DELEGATED_INTEGRITY_DEADLINE_SECONDS",
            ("0", "121", "nan", "inf", "not-a-float", ""),
            "Invalid delegated style integrity deadline",
        ),
    ):
        for value in values:
            monkeypatch.setenv(variable, value)
            with pytest.raises(ValueError, match=expected):
                ArtifactStorageConfig.from_environment()
        monkeypatch.delenv(variable, raising=False)

    monkeypatch.setenv("KAREN_STYLE_DELEGATED_MAX_DOCUMENT_SOURCES", "3")
    monkeypatch.setenv(
        "KAREN_STYLE_DELEGATED_INTEGRITY_DEADLINE_SECONDS", "0.5",
    )
    configured = ArtifactStorageConfig.from_environment()
    assert configured.style_use_max_document_sources == 3
    assert configured.style_use_integrity_total_timeout_seconds == 0.5
