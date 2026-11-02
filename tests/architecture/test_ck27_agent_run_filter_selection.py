"""CK-27K: selecting a run in one filter must not persist across different filters."""
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsPage.tsx"


def test_status_filter_clears_selected_execution_and_context() -> None:
    source = AGENTS.read_text(encoding="utf-8")
    assert 'onClick={() => { setWorkFilter(filter); setSelectedRunId(null); setVerifiedRun(null); setContextMessage(""); }}' in source
    assert "aria-pressed={selectedRunId === run.run_id}" in source
    assert "setSelectedRunId(run.run_id)" in source
