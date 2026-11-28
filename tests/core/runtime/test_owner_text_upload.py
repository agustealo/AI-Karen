"""Internal owner text transfer state orchestration; no live Storage claims."""
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_karen_engine.core.runtime.owner_text_upload import (
    OwnerTextUploadService, UploadOutcomeUnavailable,
)
from ai_karen_engine.services.database.repositories.artifact_store import VerifiedArtifactText
from ai_karen_engine.services.database.repositories.upload_session import UploadSession


@pytest.fixture
def transfer():
    tenant, owner, session, lease, key = (str(uuid4()) for _ in range(5))
    data = b"verified document"
    filename = "document.txt"
    digest = sha256(data).hexdigest()
    context = SimpleNamespace(
        tenant_id=tenant, user_id=owner, request_id="request", correlation_id="trace",
        revalidate_runtime_artifact_write_session=AsyncMock(),
    )
    state = SimpleNamespace(value=None, start="created")
    async def create(**kw):
        state.value = UploadSession(
            session, tenant, owner, kw["destination_id"], kw["recipe"],
            state.start, kw["manifest_sha256"], len(data), 0, None,
            expected_sha256=digest,
        )
        return state.value

    async def receiving(**kw):
        return replace(state.value, state="receiving")

    async def staged(**kw):
        return replace(state.value, state="staged", received_bytes=len(data))

    async def claim(**kw):
        return replace(state.value, state="committing", lease_owner=lease)

    proof = VerifiedArtifactText(session, tenant, owner, filename, "text/plain", digest, data.decode())
    sessions = SimpleNamespace(
        create_or_get=AsyncMock(side_effect=create),
        transition=AsyncMock(side_effect=receiving),
        record_staged=AsyncMock(side_effect=staged),
        claim_commit=AsyncMock(side_effect=claim),
        mark_expired_commit_uncertain=AsyncMock(return_value=None),
        reconcile_verified_text=AsyncMock(),
        read_committed_verified_text=AsyncMock(return_value=proof),
    )
    artifacts = SimpleNamespace(upload_reserved_text=AsyncMock())
    service = OwnerTextUploadService(sessions=sessions, artifacts=artifacts)
    return SimpleNamespace(service=service, context=context, sessions=sessions,
                           artifacts=artifacts, state=state, data=data, filename=filename,
                           key=key, session=session, lease=lease, proof=proof, admission=AsyncMock())


async def save(t):
    return await t.service.save(
        t.context, filename=t.filename, data=t.data, idempotency_key=t.key,
        authorize_transfer=t.admission,
    )


@pytest.mark.asyncio
async def test_fresh_transfer_uses_one_claim_and_committed_readback(transfer):
    t = transfer
    result = await save(t)
    assert result.artifact_id == t.session
    assert result.sha256 == sha256(t.data).hexdigest()
    assert not hasattr(result, "text")
    t.sessions.transition.assert_awaited_once()
    t.sessions.record_staged.assert_awaited_once()
    t.sessions.claim_commit.assert_awaited_once()
    t.artifacts.upload_reserved_text.assert_awaited_once()
    args, kw = t.artifacts.upload_reserved_text.await_args
    assert args[0].data == t.data and args[0].tenant_id == t.context.tenant_id
    assert kw["session_id"] == t.session and kw["lease_token"] == t.lease
    assert callable(kw["before_write"])
    t.sessions.read_committed_verified_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["committed", "reconcile_required"])
async def test_existing_receipt_never_replays_write(transfer, state):
    t = transfer
    t.state.start = state
    assert (await save(t)).artifact_id == t.session
    t.artifacts.upload_reserved_text.assert_not_awaited()
    t.sessions.claim_commit.assert_not_awaited()
    assert t.sessions.reconcile_verified_text.await_count == int(state == "reconcile_required")


@pytest.mark.asyncio
async def test_live_foreign_claim_is_not_stolen(transfer):
    t = transfer
    t.state.start = "committing"
    with pytest.raises(UploadOutcomeUnavailable):
        await save(t)
    t.artifacts.upload_reserved_text.assert_not_awaited()
    t.sessions.claim_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_session_before_write(transfer):
    t = transfer
    t.context.revalidate_runtime_artifact_write_session.side_effect = [
        None, None, None, None, PermissionError(),
    ]
    with pytest.raises(PermissionError):
        await save(t)
    t.artifacts.upload_reserved_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_receipt_never_reports_success(transfer):
    t = transfer
    t.sessions.read_committed_verified_text.return_value = None
    with pytest.raises(UploadOutcomeUnavailable):
        await save(t)
    t.artifacts.upload_reserved_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrong_filename_proof_denied(transfer):
    t = transfer
    t.sessions.read_committed_verified_text.return_value = replace(t.proof, filename="different.txt")
    with pytest.raises(UploadOutcomeUnavailable):
        await save(t)


@pytest.mark.asyncio
async def test_invalid_payload_never_creates_session(transfer):
    t = transfer
    t.filename = "../document.txt"
    with pytest.raises(ValueError):
        await save(t)
    t.sessions.create_or_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_admission_denial_precedes_session_creation(transfer):
    transfer.admission.side_effect = PermissionError("host denied")
    with pytest.raises(PermissionError):
        await save(transfer)
    transfer.sessions.create_or_get.assert_not_awaited()
