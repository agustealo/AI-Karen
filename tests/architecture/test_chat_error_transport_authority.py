from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHAT_ROUTE = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"
ERROR_MIDDLEWARE = ROOT / "src/ai_karen_engine/middleware/intelligent_error_handler.py"


def test_chat_transport_does_not_replace_unexpected_runtime_errors() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    assert 'raise HTTPException(status_code=500, detail="Internal server error")' not in source
    assert 'context="unexpected_error"' not in source


def test_chat_transport_keeps_expected_validation_translation() -> None:
    source = CHAT_ROUTE.read_text(encoding="utf-8")

    assert source.count("except HTTPException:") >= 2
    assert source.count("except ValueError as exc:") >= 2
    assert "raise HTTPException(status_code=400, detail=str(exc)) from exc" in source


def test_global_error_middleware_owns_unexpected_exception_translation() -> None:
    source = ERROR_MIDDLEWARE.read_text(encoding="utf-8")

    assert "except Exception as exc:" in source
    assert "traceback_str = traceback.format_exc()" in source
    assert "error_type = type(exc).__name__" in source
