from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / 'src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsPage.tsx'


def test_active_run_refresh_is_visibility_scoped():
    source = SOURCE.read_text(encoding='utf-8')
    assert '["queued", "running", "cancelling"].includes(run.status.toLowerCase())' in source
    assert 'if (!isAuthenticated || !hasActiveRunPolling) return;' in source
    assert 'document.visibilityState === "visible"' in source
    assert 'window.setInterval(' in source
    assert 'window.clearInterval(timer)' in source


def test_transient_failure_keeps_polling_and_surfaces_error():
    source = SOURCE.read_text(encoding="utf-8")
    assert "setHasActiveRunPolling((response.runs || []).some(" in source
    assert "Run status refresh failed: {runsError}" in source


def test_run_list_coalesces_polling_and_replays_priority_refresh():
    source = SOURCE.read_text(encoding="utf-8")
    assert "const runListRequestPromiseRef = useRef<Promise<void> | null>(null);" in source
    assert "const runListRefreshQueuedRef = useRef(false);" in source
    assert "if (runListRequestPromiseRef.current)" in source
    assert "if (priority) runListRefreshQueuedRef.current = true;" in source
    assert "while (runListRefreshQueuedRef.current)" in source
    assert "runListRequestPromiseRef.current = task;" in source
    assert "runListRequestPromiseRef.current = null;" in source
    assert "loadRuns(true)" in source
