from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    ROOT
    / "src"
    / "ui_launchers"
    / "Karen-AI-Theme"
    / "tools"
    / "check-no-prod-mocks.sh"
)


def test_mock_gate_has_scanner_fallback_and_fails_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "command -v rg" in source
    assert "command -v grep" in source
    assert "scan_with_grep" in source
    assert "refusing to skip production mock detection" in source
    assert "exit 2" in source


def test_mock_gate_checks_scanner_failures_instead_of_masking_them() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "status=$?" in source
    assert 'exit "$status"' in source
    assert "No forbidden mock/demo patterns found" in source
