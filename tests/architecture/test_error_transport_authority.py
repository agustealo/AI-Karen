from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIDDLEWARE = ROOT / "src/ai_karen_engine/server/middleware.py"
EXCEPTION_HANDLERS = ROOT / "src/ai_karen_engine/server/exception_handlers.py"
INTELLIGENT_ERRORS = (
    ROOT / "src/ai_karen_engine/middleware/intelligent_error_handler.py"
)


def test_transport_errors_do_not_fabricate_model_output() -> None:
    middleware = MIDDLEWARE.read_text(encoding="utf-8")
    handlers = EXCEPTION_HANDLERS.read_text(encoding="utf-8")

    forbidden = (
        "_build_copilot_degraded_response",
        "exception-handler-fallback",
        '"provider": "fallback"',
        '"model_id":',
        '"answer":',
    )
    for token in forbidden:
        assert token not in middleware
        assert token not in handlers


def test_failed_copilot_transport_is_never_rewritten_to_http_200() -> None:
    middleware = MIDDLEWARE.read_text(encoding="utf-8")
    handlers = EXCEPTION_HANDLERS.read_text(encoding="utf-8")

    assert "Returning degraded Copilot response" not in middleware
    assert 'request.url.path.startswith("/api/copilot/assist")' not in handlers
    assert "status_code=200" not in handlers


def test_error_middleware_uses_structured_logging_not_print() -> None:
    source = INTELLIGENT_ERRORS.read_text(encoding="utf-8")

    assert "print(" not in source
    assert "logger.exception(" in source


def test_canonical_middleware_contains_no_deployment_rewrite_or_dead_validator() -> None:
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "fix_internal_redirects" not in source
    assert "internal_hosts" not in source
    assert "HTTPRequestValidator" not in source
    assert "SessionMiddleware" not in source
    assert "fallback validation configuration" not in source.lower()
