"""The consumer plugin UI must expose invalid execution envelopes honestly."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/services/IntelligentSearchApi.ts"


def test_bad_plugin_envelope_is_not_silent_empty_success():
    text = API.read_text(encoding="utf-8")
    assert "throw new Error('Search returned an invalid response." in text
    assert "summary: ''," not in text
    assert "Array.isArray(record.sources)" in text
    assert "Array.isArray(record.results)" in text
