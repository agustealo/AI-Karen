"""Selected execution detail must be reverified when the run ledger refreshes."""
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsPage.tsx"


def test_refreshed_run_list_invalidates_cached_selected_detail() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "const [runListRevision, setRunListRevision] = useState(0);" in source
    assert "setRunListRevision((revision) => revision + 1);" in source
    assert "[selectedRunId, isAuthenticated, isAdmin, runListRevision]" in source
    assert "if (active) setVerifiedRun(record)" in source


def test_failed_run_list_refresh_clears_stale_details() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    failure = source.split("const loadRuns = useCallback", 1)[1].split("const copyVerifiedRunContext =", 1)[0]
    assert 'setRuns([]);\n      setSelectedRunId(null);\n      setVerifiedRun(null);\n      setContextMessage("");' in failure
    assert "setRunsError(" in failure
