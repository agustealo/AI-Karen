"""Selected execution detail must be reverified when the run ledger refreshes."""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsPage.tsx"


def test_refreshed_run_list_invalidates_cached_selected_detail() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "const [runListRevision, setRunListRevision] = useState(0);" in source
    assert "setRunListRevision((revision) => revision + 1);" in source
    assert "[selectedRunId, isAuthenticated, isAdmin, runListRevision]" in source
    assert "if (active) setVerifiedRun(record)" in source
