from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COORDINATOR = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "agent_medusa"
    / "coordinator"
    / "medusa_coordinator.py"
)
CONTROL_PLANE = (
    ROOT / "src" / "ai_karen_engine" / "agent_medusa" / "control_plane.py"
)


def test_medusa_coordinator_uses_process_wide_run_manager_and_real_task_cancellation() -> None:
    source = COORDINATOR.read_text(encoding="utf-8")

    assert "get_medusa_run_manager" in source
    assert "self.run_manager.register(" in source
    assert "asyncio.current_task()" in source
    assert "except asyncio.CancelledError" in source
    assert "self.run_manager.mark_cancelled" in source


def test_admin_projection_keeps_agent_daemon_control_closed() -> None:
    source = CONTROL_PLANE.read_text(encoding="utf-8")

    assert '"agent_daemon_control_not_applicable"' in source
    assert '"scope": "run_id"' in source
    assert '"actions": ["observe", "cancel"]' in source
    assert "start_agent" not in source
    assert "restart_agent" not in source
