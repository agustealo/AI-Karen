from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIDDLEWARE = ROOT / "src/ai_karen_engine/middleware/intelligent_error_handler.py"
API_CLIENT = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/lib/api.ts"
)


def test_error_envelope_carries_non_secret_diagnostic_identity() -> None:
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert '"correlation_id": correlation_id' in source
    assert '"error_type": error_type' in source
    assert '"X-Correlation-Id": request_meta["correlation_id"]' in source


def test_browser_error_message_includes_safe_diagnostic_fingerprint() -> None:
    source = API_CLIENT.read_text(encoding="utf-8")

    assert "nestedError.error_type" in source
    assert "nestedError.correlation_id" in source
    assert "type=${errorType}" in source
    assert "correlation=${correlationId}" in source
