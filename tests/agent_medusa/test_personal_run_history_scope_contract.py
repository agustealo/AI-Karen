"""User-scoped Medusa history is applied inside the canonical run manager."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANAGER = (ROOT / "src/ai_karen_engine/agent_medusa/execution/run_manager.py").read_text()
LEDGER = (ROOT / "src/ai_karen_engine/agent_medusa/execution/durable_run_ledger.py").read_text()
CONTROL = (ROOT / "src/ai_karen_engine/agent_medusa/control_plane.py").read_text()


def test_run_manager_scopes_every_history_source():
    assert "and (user_id is None or run.user_id == user_id)" in MANAGER
    assert 'str(snapshot.get("user_id") or "") == user_id' in MANAGER
    assert '"user_id": user_id' in MANAGER
    assert "user_id: str | None = None" in CONTROL


def test_durable_history_filters_by_owner_before_limit():
    assert 'owner_clause = " AND user_id = :user_id" if user_id is not None else ""' in LEDGER
    assert '+ owner_clause' in LEDGER
    assert LEDGER.index('+ owner_clause') < LEDGER.index('ORDER BY started_at DESC LIMIT :limit')
    assert '"user_id": user_id' in LEDGER


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["owned", "empty", "foreign_user", "foreign_tenant", "wrong_run", "bad_correlation", "missing"]
)
async def test_participation_control_plane_checks_owner_before_read(monkeypatch, mode):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from ai_karen_engine.agent_medusa import control_plane as module
    from ai_karen_engine.agent_medusa.execution.run_manager import RunNotFoundError
    from ai_karen_engine.core.runtime.outcome.store import OutcomeStoreError

    run = {"run_id": "run", "request_id": "run", "tenant_id": "tenant",
           "user_id": "owner", "correlation_id": "corr", "status": "completed"}
    if mode == "foreign_user":
        run["user_id"] = "other"
    elif mode == "foreign_tenant":
        run["tenant_id"] = "other"
    elif mode == "wrong_run":
        run["run_id"] = "other"
    elif mode == "bad_correlation":
        run["correlation_id"] = None
    manager = SimpleNamespace(get=AsyncMock(return_value=run))
    if mode == "missing":
        manager.get.side_effect = RunNotFoundError("run")
    evidence = {
        "outcome_id": "receipt",
        "metadata": {"step_id": "step", "specialist_id": "researcher", "phase": "interrupted"},
        "recorded_at": "2026-11-26T11:00:00+00:00",
        "user_id": "owner",
    }
    store = SimpleNamespace(list_specialist_participation_async=AsyncMock(
        return_value=([] if mode == "empty" else [evidence], False)
    ))
    monkeypatch.setattr(module, "get_outcome_store", lambda: store)
    plane = module.AgentMedusaControlPlane(
        run_manager=manager, registry=SimpleNamespace(), audit_logger=SimpleNamespace(),
    )
    kwargs = dict(run_id="run", tenant_id="tenant", user_id="owner")
    if mode == "bad_correlation":
        with pytest.raises(OutcomeStoreError):
            await plane.read_run_participation(**kwargs)
    else:
        result = await plane.read_run_participation(**kwargs)
        if mode in {"owned", "empty"}:
            assert result["evidence_status"] == ("recorded" if mode == "owned" else "empty")
            assert result["run_id"] == "run"
            assert result["response_source"] == "postgres_outcome_records"
            assert result["receipts"] == ([] if mode == "empty" else [{
                "receipt_id": "receipt", "step_id": "step", "specialist_id": "researcher",
                "phase": "interrupted", "observed_at": evidence["recorded_at"],
            }])
            store.list_specialist_participation_async.assert_awaited_once_with(
                trajectory_id="run", correlation_id="corr", tenant_id="tenant", user_id="owner",
            )
        else:
            assert result is None
    if mode not in {"owned", "empty"}:
        store.list_specialist_participation_async.assert_not_awaited()
    manager.get.assert_awaited_once_with(
        run_id="run", tenant_id="tenant", require_durable_history=True, user_id="owner",
    )
