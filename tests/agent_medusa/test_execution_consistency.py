from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai_karen_engine.agent_medusa.contracts.runtime_request import RuntimeRequest
from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerTransitionConflict,
    _canonical_tenant_id,
    _require_transition,
)


@dataclass
class _Result:
    rowcount: int


def test_runtime_request_rejects_missing_tenant_scope() -> None:
    with pytest.raises(ValueError, match="requires tenant_id"):
        RuntimeRequest(query="hello", session_id="session-1")


def test_runtime_request_accepts_typed_tenant_scope() -> None:
    request = RuntimeRequest(
        query="hello",
        session_id="session-1",
        tenant_id="tenant-a",
    )

    assert request.tenant_id == "tenant-a"
    assert request.to_dict()["tenant_id"] == "tenant-a"


def test_runtime_request_migrates_context_tenant_without_defaulting() -> None:
    request = RuntimeRequest(
        query="hello",
        session_id="session-1",
        context={"tenant_id": "tenant-from-context"},
    )

    assert request.tenant_id == "tenant-from-context"


def test_empty_durable_tenant_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires tenant_id"):
        _canonical_tenant_id("")


def test_durable_transition_requires_exactly_one_active_row() -> None:
    _require_transition(_Result(rowcount=1), run_id="run-1", transition="heartbeat")

    with pytest.raises(DurableRunLedgerTransitionConflict, match="run-2"):
        _require_transition(_Result(rowcount=0), run_id="run-2", transition="heartbeat")

    with pytest.raises(DurableRunLedgerTransitionConflict, match="run-3"):
        _require_transition(_Result(rowcount=2), run_id="run-3", transition="cancelled")
