"""KOC-04H: host-supervised admission uses SQL claims, never native event authority."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.persistence.repositories.channel_repository import InboundAdmission
from ai_karen_engine.services.channels.worker import ChannelInboxWorker

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BINDING = "cccccccc-cccc-cccc-cccc-cccccccccccc"
INBOX = "dddddddd-dddd-dddd-dddd-dddddddddddd"
CLAIM = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def admission(*, tenant_id=TENANT, inbox_id=INBOX, user_id=USER) -> InboundAdmission:
    return InboundAdmission(
        tenant_id=tenant_id,
        user_id=user_id,
        binding_id=BINDING,
        inbox_id=inbox_id,
        correlation_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        inserted=True,
    )


def make_worker(*, claim=None):
    receipt = admission()
    repo = SimpleNamespace(
        claim_inbound=AsyncMock(return_value=(
            CLAIM, receipt if claim is None else claim
        )),
    )
    execution = SimpleNamespace(execute_claimed_text=AsyncMock(return_value=True))
    worker = ChannelInboxWorker(
        repository=repo, execution=execution, max_inflight=1,
        lease_seconds=30,
    )
    worker.start()
    return worker, repo, execution


@pytest.mark.asyncio
async def test_supervisor_requires_durable_claim_before_chat_runtime():
    worker, repo, execution = make_worker()
    assert await worker.submit(admission()) is True
    await asyncio.gather(*tuple(worker._tasks))
    repo.claim_inbound.assert_awaited_once_with(
        tenant_id=TENANT, inbox_id=INBOX, lease_seconds=30,
    )
    execution.execute_claimed_text.assert_awaited_once_with(
        tenant_id=TENANT, inbox_id=INBOX, claim_token=CLAIM,
        lease_seconds=30,
    )
    await worker.shutdown()


@pytest.mark.asyncio
async def test_duplicate_admission_does_not_spawn_parallel_work():
    worker, repo, execution = make_worker()
    gate = asyncio.Event()

    async def held_execution(**kwargs):
        await gate.wait()
        return True

    execution.execute_claimed_text.side_effect = held_execution
    assert await worker.submit(admission()) is True
    assert await worker.submit(admission()) is False
    await asyncio.sleep(0)
    gate.set()
    await asyncio.gather(*tuple(worker._tasks))
    repo.claim_inbound.assert_awaited_once()
    execution.execute_claimed_text.assert_awaited_once()
    await worker.shutdown()


@pytest.mark.asyncio
async def test_claim_denied_never_executes_runtime():
    worker, repo, execution = make_worker()
    repo.claim_inbound.return_value = None
    await worker.submit(admission())
    await asyncio.gather(*tuple(worker._tasks))
    execution.execute_claimed_text.assert_not_awaited()
    await worker.shutdown()


@pytest.mark.asyncio
async def test_claim_principal_mismatch_refuses_execution():
    foreign = admission(user_id="11111111-1111-1111-1111-111111111111")
    worker, repo, execution = make_worker(claim=foreign)
    await worker.submit(admission())
    await asyncio.gather(*tuple(worker._tasks))
    execution.execute_claimed_text.assert_not_awaited()
    await worker.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_active_execution_and_refuses_more_admission():
    worker, repo, execution = make_worker()
    entered = asyncio.Event()

    async def blocked(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    execution.execute_claimed_text.side_effect = blocked
    await worker.submit(admission())
    await entered.wait()
    await worker.shutdown()
    assert await worker.submit(admission()) is False
    assert not worker._tasks
    assert not worker._scheduled


@pytest.mark.asyncio
async def test_worker_validates_budgets_and_canonical_receipts():
    for concurrency, lease in ((0, 30), (65, 30), (1, 2), (1, 3601)):
        with pytest.raises(ValueError):
            ChannelInboxWorker(
                repository=SimpleNamespace(), execution=SimpleNamespace(),
                max_inflight=concurrency, lease_seconds=lease,
            )
    worker, repo, execution = make_worker()
    with pytest.raises(TypeError):
        await worker.submit({"tenant_id": TENANT, "inbox_id": INBOX})
    await worker.shutdown()


@pytest.mark.asyncio
async def test_scheduled_task_budget_caps_waiters_without_claiming_overflow():
    worker, repo, execution = make_worker()
    worker._max_scheduled = 1
    entered = asyncio.Event()
    release = asyncio.Event()

    async def block(**kwargs):
        entered.set()
        await release.wait()
        return True

    execution.execute_claimed_text.side_effect = block
    assert await worker.submit(admission()) is True
    await entered.wait()
    other = admission(inbox_id="22222222-2222-2222-2222-222222222222")
    assert await worker.submit(other) is False
    assert repo.claim_inbound.await_count == 1
    release.set()
    await asyncio.gather(*tuple(worker._tasks))
    assert await worker.submit(other) is True
    await asyncio.gather(*tuple(worker._tasks))
    await worker.shutdown()


def test_invalid_scheduled_budget_is_denied():
    for budget in (0, 2, 4097):
        with pytest.raises(ValueError):
            ChannelInboxWorker(
                repository=SimpleNamespace(),
                execution=SimpleNamespace(),
                max_inflight=4,
                max_scheduled=budget,
            )


@pytest.mark.asyncio
async def test_committed_inbox_stages_then_dispatches_using_persisted_preflight():
    import uuid
    from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
    worker, repo, execution = make_worker()
    dispatch = AsyncMock(return_value=True)
    worker._dispatch_outbox = dispatch
    repo.get_delivery_preflight = AsyncMock(return_value=SimpleNamespace(
        user_id=USER, connection_id="conn-a", external_conversation_id="room-a",
    ))
    assert await worker.submit(admission())
    await asyncio.gather(*tuple(worker._tasks))
    delivery_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"karen-channel-delivery:{INBOX}",
    ))
    session_id = ChannelDeliveryService._session_id(
        tenant_id=TENANT, user_id=USER, connection_id="conn-a",
        external_conversation_id="room-a",
    )
    repo.get_delivery_preflight.assert_awaited_once_with(
        tenant_id=TENANT, delivery_id=delivery_id,
    )
    dispatch.assert_awaited_once_with(
        tenant_id=TENANT, delivery_id=delivery_id,
        user_id=USER, session_id=session_id,
    )
    await worker.shutdown()


@pytest.mark.asyncio
async def test_uncommitted_execution_never_dispatches_outbound():
    worker, repo, execution = make_worker()
    dispatch = AsyncMock()
    worker._dispatch_outbox = dispatch
    execution.execute_claimed_text.return_value = False
    repo.get_delivery_preflight = AsyncMock()
    await worker.submit(admission())
    await asyncio.gather(*tuple(worker._tasks))
    repo.get_delivery_preflight.assert_not_awaited()
    dispatch.assert_not_awaited()
    await worker.shutdown()


@pytest.mark.asyncio
async def test_outbox_preflight_principal_mismatch_never_dispatches():
    worker, repo, execution = make_worker()
    dispatch = AsyncMock()
    worker._dispatch_outbox = dispatch
    repo.get_delivery_preflight = AsyncMock(return_value=SimpleNamespace(
        user_id="99999999-9999-9999-9999-999999999999",
        connection_id="conn-a", external_conversation_id="room-a",
    ))
    await worker.submit(admission())
    await asyncio.gather(*tuple(worker._tasks))
    dispatch.assert_not_awaited()
    await worker.shutdown()


@pytest.mark.asyncio
async def test_outbound_policy_denial_never_reexecutes_chat_runtime():
    worker, repo, execution = make_worker()
    worker._dispatch_outbox = AsyncMock(side_effect=PermissionError("RBAC revoked"))
    repo.get_delivery_preflight = AsyncMock(return_value=SimpleNamespace(
        user_id=USER, connection_id="conn-a", external_conversation_id="room-a",
    ))
    await worker.submit(admission())
    await asyncio.gather(*tuple(worker._tasks))
    execution.execute_claimed_text.assert_awaited_once()
    repo.claim_inbound.assert_awaited_once()
    await worker.shutdown()
