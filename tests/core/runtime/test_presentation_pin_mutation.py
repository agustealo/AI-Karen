"""KUI-002D3B2: authenticated runtime-owned mutation proof acquisition."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    PresentationPinReference,
)
from ai_karen_engine.core.runtime.presentation_pin_mutation import (
    PresentationPinMutation,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
FOREIGN = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
THREAD = "44444444-4444-4444-8444-444444444444"
MESSAGE = "22222222-2222-5222-8222-222222222222"
KEY = "99999999-9999-4999-8999-999999999999"
PIN = "88888888-8888-4888-8888-888888888888"


def context():
    return ChatExecutionContext(
        tenant_id=TENANT,
        user_id=USER,
        session_id=THREAD,
        conversation_id=THREAD,
        request_id="request-1",
        correlation_id="correlation-1",
        authenticated_user=UserData(user_id=USER, tenant_id=TENANT),
    )


def source():
    return PresentationPinReference(
        conversation_id=THREAD,
        assistant_message_id=MESSAGE,
        presentation_id="verified-clock",
        evidence_ref="clock-proof",
    )


def service():
    repository = AsyncMock()
    repository.replay_committed_pin_receipt.return_value = None
    gateway = AsyncMock()
    runs = AsyncMock()
    gateway.get_owned_snapshot.return_value = object()
    runs.completed_replay_attestations.return_value = {MESSAGE: ("run", "digest")}
    return (
        PresentationPinMutation(
            repository=repository, gateway=gateway, run_repository=runs
        ),
        repository, gateway, runs,
    )


@pytest.mark.asyncio
async def test_pin_derives_identity_and_trusted_source_from_runtime():
    mutation, repo, gateway, runs = service()
    ctx = context()
    await mutation.execute(
        context=ctx, idempotency_key=KEY, operation="pin",
        reference=source(), position=0,
    )
    requested = repo.mutate_with_receipt.await_args.kwargs
    assert requested["authenticated_tenant_id"] == TENANT
    assert requested["authenticated_user_id"] == USER
    assert requested["request_id"] == "request-1"
    assert requested["correlation_id"] == "correlation-1"
    assert requested["reference"] == source()
    assert requested["owned_snapshot"] is gateway.get_owned_snapshot.return_value
    assert requested["completed_run_attestations"] is runs.completed_replay_attestations.return_value
    owned = gateway.get_owned_snapshot.await_args.args[0]
    assert owned is not ctx
    assert owned.conversation_id == THREAD
    assert gateway.get_owned_snapshot.await_args.kwargs["message_limit"] == 501
    runs.completed_replay_attestations.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER, conversation_id=THREAD,
    )


@pytest.mark.asyncio
async def test_reorder_uses_authenticated_identity_without_fetching_source():
    mutation, repo, gateway, runs = service()
    await mutation.execute(
        context=context(), idempotency_key=KEY, operation="reorder",
        pin_id=PIN, expected_revision=2, position=5,
    )
    requested = repo.mutate_with_receipt.await_args.kwargs
    assert requested["pin_id"] == PIN
    assert requested["expected_revision"] == 2
    assert requested["owned_snapshot"] is None
    assert requested["completed_run_attestations"] is None
    gateway.get_owned_snapshot.assert_not_awaited()
    runs.completed_replay_attestations.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverified_context_cannot_access_any_owner():
    mutation, repo, gateway, runs = service()
    with pytest.raises(PermissionError):
        await mutation.execute(
            context=replace(context(), authenticated_user=None),
            idempotency_key=KEY, operation="unpin", pin_id=PIN,
        )
    gateway.get_owned_snapshot.assert_not_awaited()
    runs.completed_replay_attestations.assert_not_awaited()
    repo.mutate_with_receipt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", [
    UserData(user_id=FOREIGN, tenant_id=TENANT),
    UserData(user_id=USER, tenant_id=FOREIGN),
    UserData(user_id=USER, tenant_id=TENANT, is_active=False),
    UserData(user_id=USER, tenant_id=TENANT, is_verified=False),
])
async def test_foreign_or_inactive_principals_fail_before_sql(principal):
    mutation, repo, gateway, _ = service()
    with pytest.raises(PermissionError):
        await mutation.execute(
            context=replace(context(), authenticated_user=principal),
            idempotency_key=KEY, operation="unpin", pin_id=PIN,
        )
    gateway.get_owned_snapshot.assert_not_awaited()
    repo.mutate_with_receipt.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_denial_does_not_mutate():
    mutation, repo, gateway, runs = service()
    gateway.get_owned_snapshot.side_effect = PermissionError("not owned")
    with pytest.raises(PermissionError):
        await mutation.execute(
            context=context(), idempotency_key=KEY, operation="pin",
            reference=source(),
        )
    repo.mutate_with_receipt.assert_not_awaited()
    runs.completed_replay_attestations.assert_not_awaited()


@pytest.mark.asyncio
async def test_attestation_outage_does_not_mutate():
    mutation, repo, _, runs = service()
    runs.completed_replay_attestations.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError, match="db down"):
        await mutation.execute(
            context=context(), idempotency_key=KEY, operation="pin",
            reference=source(),
        )
    repo.mutate_with_receipt.assert_not_awaited()



@pytest.mark.asyncio
async def test_committed_pin_retry_survives_deleted_source_and_attestation_outage():
    mutation, repo, gateway, runs = service()
    receipt = object()
    repo.replay_committed_pin_receipt.return_value = receipt
    gateway.get_owned_snapshot.side_effect = RuntimeError("conversation_not_found")
    runs.completed_replay_attestations.side_effect = RuntimeError("attestation offline")

    result = await mutation.execute(
        context=context(), idempotency_key=KEY,
        operation="pin", reference=source(), position=0,
    )
    assert result is receipt
    repo.replay_committed_pin_receipt.assert_awaited_once_with(
        authenticated_tenant_id=TENANT,
        authenticated_user_id=USER,
        idempotency_key=KEY,
        reference=source(),
        position=0,
    )
    gateway.get_owned_snapshot.assert_not_awaited()
    runs.completed_replay_attestations.assert_not_awaited()
    repo.mutate_with_receipt.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_committed_receipt_requires_fresh_source_admission():
    mutation, repo, gateway, _ = service()
    gateway.get_owned_snapshot.side_effect = RuntimeError("conversation_not_found")
    with pytest.raises(RuntimeError, match="conversation_not_found"):
        await mutation.execute(
            context=context(), idempotency_key=KEY,
            operation="pin", reference=source(),
        )
    repo.replay_committed_pin_receipt.assert_awaited_once()
    repo.mutate_with_receipt.assert_not_awaited()


@pytest.mark.asyncio
async def test_receipt_replay_outage_fails_closed_before_new_mutation():
    mutation, repo, gateway, _ = service()
    repo.replay_committed_pin_receipt.side_effect = RuntimeError("receipt db offline")
    with pytest.raises(RuntimeError, match="receipt db offline"):
        await mutation.execute(
            context=context(), idempotency_key=KEY,
            operation="pin", reference=source(),
        )
    gateway.get_owned_snapshot.assert_not_awaited()
    repo.mutate_with_receipt.assert_not_awaited()
