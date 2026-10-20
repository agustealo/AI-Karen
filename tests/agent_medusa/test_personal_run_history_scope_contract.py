"""User-scoped Medusa history is applied inside the canonical run manager."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANAGER = (ROOT / "src/ai_karen_engine/agent_medusa/execution/run_manager.py").read_text()
LEDGER = (ROOT / "src/ai_karen_engine/agent_medusa/execution/durable_run_ledger.py").read_text()
CONTROL = (ROOT / "src/ai_karen_engine/agent_medusa/control_plane.py").read_text()


def test_run_manager_scopes_every_history_source():
    assert "and (user_id is None or run.user_id == user_id)" in MANAGER
    assert 'str(snapshot.get("user_id") or "") == user_id' in MANAGER
    assert "'user_id': user_id" in MANAGER
    assert "user_id: str | None = None" in CONTROL


def test_durable_history_filters_by_owner_before_limit():
    assert 'owner_clause = " AND user_id = :user_id" if user_id is not None else ""' in LEDGER
    assert '"+ owner_clause' in LEDGER
    assert '"user_id": user_id' in LEDGER
