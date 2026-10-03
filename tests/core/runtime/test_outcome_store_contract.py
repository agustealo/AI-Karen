from __future__ import annotations

import pytest

from ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    reset_correlation_context,
    set_correlation_context,
)
from ai_karen_engine.core.runtime.outcome.contracts import ExecutionStatus
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore, OutcomeStore


class FailingStore(OutcomeStore):
    def save_outcome(self, payload):
        raise RuntimeError("database exploded")

    def get_for_trajectory(self, trajectory_id, *, tenant_id=None):
        return []

    def list_for_tenant(self, tenant_id, *, limit=100, user_id=None):
        return []


def test_in_memory_store_can_filter_user_within_tenant() -> None:
    store = InMemoryOutcomeStore()
    store.save_outcome({"outcome_id": "o1", "tenant_id": "t1", "user_id": "u1"})
    store.save_outcome({"outcome_id": "o2", "tenant_id": "t1", "user_id": "u2"})
    assert [item["outcome_id"] for item in store.list_for_tenant("t1", user_id="u1")] == ["o1"]


def test_recorder_reports_persistence_failure_without_faking_success() -> None:
    token = set_correlation_context(
        CorrelationContext(
            correlation_id="corr",
            tenant_id="t1",
            user_id="u1",
        )
    )
    try:
        payload = OutcomeRecorder(store=FailingStore()).record_execution_outcome(
            trajectory_id="traj",
            status=ExecutionStatus.SUCCESS,
        )
    finally:
        reset_correlation_context(token)
    assert payload["outcome_store_status"] == "failed"
    assert payload["outcome_store_error_code"] == "outcome_persistence_failed"


def test_recorder_reports_stored_when_store_accepts_record() -> None:
    store = InMemoryOutcomeStore()
    token = set_correlation_context(
        CorrelationContext(
            correlation_id="corr",
            tenant_id="t1",
            user_id="u1",
        )
    )
    try:
        payload = OutcomeRecorder(store=store).record_execution_outcome(
            trajectory_id="traj",
            status=ExecutionStatus.SUCCESS,
        )
    finally:
        reset_correlation_context(token)
    assert payload["outcome_store_status"] == "stored"
    assert len(store.list_for_tenant("t1", user_id="u1")) == 1



class AsyncTrackingStore(OutcomeStore):
    def __init__(self) -> None:
        self.async_calls = 0

    def save_outcome(self, payload):
        raise AssertionError("sync save must not run on async runtime path")

    async def save_outcome_async(self, payload):
        self.async_calls += 1

    def get_for_trajectory(self, trajectory_id, *, tenant_id=None):
        return []

    def list_for_tenant(self, tenant_id, *, limit=100, user_id=None):
        return []


@pytest.mark.asyncio
async def test_async_recorder_uses_async_store_path() -> None:
    store = AsyncTrackingStore()
    token = set_correlation_context(
        CorrelationContext(
            correlation_id="corr-async",
            tenant_id="t1",
            user_id="u1",
        )
    )
    try:
        payload = await OutcomeRecorder(store=store).record_execution_outcome_async(
            trajectory_id="traj-async",
            status=ExecutionStatus.SUCCESS,
        )
    finally:
        reset_correlation_context(token)

    assert store.async_calls == 1
    assert payload["outcome_store_status"] == "stored"
