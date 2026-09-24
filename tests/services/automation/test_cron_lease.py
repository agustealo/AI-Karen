from __future__ import annotations

import asyncio

import pytest

from ai_karen_engine.services.automation.cron_lease import (
    CronClaimLost,
    run_with_cron_claim_heartbeat,
)


class FakeCronRepository:
    def __init__(self, renewals: list[bool]) -> None:
        self.renewals = list(renewals)
        self.calls = 0

    async def renew_cron_claim(self, cron_id, claim_token):
        self.calls += 1
        assert cron_id == "cron-a"
        assert claim_token == "claim-a"
        if self.renewals:
            return self.renewals.pop(0)
        return True


def _job():
    return {"id": "cron-a", "claim_token": "claim-a"}


@pytest.mark.asyncio
async def test_long_cron_dispatch_renews_claim_until_completion():
    repo = FakeCronRepository([True])

    async def work():
        await asyncio.sleep(0.02)
        return "done"

    result = await run_with_cron_claim_heartbeat(
        repo,
        _job(),
        work(),
        heartbeat_seconds=0.005,
    )

    assert result == "done"
    assert repo.calls >= 1


@pytest.mark.asyncio
async def test_lost_cron_claim_cancels_dispatch():
    repo = FakeCronRepository([False])
    cancelled = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    with pytest.raises(CronClaimLost):
        await run_with_cron_claim_heartbeat(
            repo,
            _job(),
            work(),
            heartbeat_seconds=0.001,
        )

    assert repo.calls == 1
    assert cancelled.is_set()
