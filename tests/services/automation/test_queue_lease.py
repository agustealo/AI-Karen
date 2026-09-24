from __future__ import annotations

import asyncio

import pytest

from ai_karen_engine.services.automation.queue_lease import (
    QueueClaimLost,
    run_with_queue_claim_heartbeat,
)
from ai_karen_engine.services.database.repositories.base import RepositoryResult
from ai_karen_engine.services.database.repositories.queue_client import QueueItem


class FakeQueueClient:
    def __init__(self, renewals: list[RepositoryResult[bool]]) -> None:
        self._renewals = list(renewals)
        self.renew_calls = 0

    async def renew_claim(self, queue, item_id, claim_token=None):
        self.renew_calls += 1
        if self._renewals:
            return self._renewals.pop(0)
        return RepositoryResult(success=True, data=True)


def _item() -> QueueItem:
    return QueueItem(
        id="queue-item-1",
        queue="automation",
        claim_token="claim-token-1",
    )


@pytest.mark.asyncio
async def test_long_operation_renews_claim_until_completion():
    client = FakeQueueClient([RepositoryResult(success=True, data=True)])

    async def work():
        await asyncio.sleep(0.02)
        return "done"

    result = await run_with_queue_claim_heartbeat(
        client,
        _item(),
        work(),
        heartbeat_seconds=0.005,
    )

    assert result == "done"
    assert client.renew_calls >= 1


@pytest.mark.asyncio
async def test_lost_claim_cancels_unowned_work():
    client = FakeQueueClient([RepositoryResult(success=True, data=False)])
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    with pytest.raises(QueueClaimLost):
        await run_with_queue_claim_heartbeat(
            client,
            _item(),
            work(),
            heartbeat_seconds=0.001,
        )

    assert client.renew_calls == 1
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_missing_claim_token_refuses_to_start_work():
    client = FakeQueueClient([])
    started = False

    async def work():
        nonlocal started
        started = True

    item = _item()
    item.claim_token = None

    with pytest.raises(QueueClaimLost):
        await run_with_queue_claim_heartbeat(
            client,
            item,
            work(),
            heartbeat_seconds=0.001,
        )

    assert started is False
    assert client.renew_calls == 0
