from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / 'src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsPage.tsx'


def test_cancellation_response_does_not_claim_terminal_cancellation():
    source = SOURCE.read_text(encoding='utf-8')
    assert 'Cancellation endpoint responded for ${runId}. Reported status: ${response.status}.' in source
    assert 'Check the refreshed run details for current state.' in source
    assert 'Cancellation requested for ${runId}. Runtime status:' not in source
