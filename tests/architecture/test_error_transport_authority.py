from __future__ import annotations

from pathlib import Path

import pytest


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
    assert "logger.error(" in source
    assert "logger.exception(" not in source
    assert "traceback.format_exc()" not in source


def test_canonical_middleware_contains_no_deployment_rewrite_or_dead_validator() -> None:
    source = MIDDLEWARE.read_text(encoding="utf-8")

    assert "fix_internal_redirects" not in source
    assert "internal_hosts" not in source
    assert "HTTPRequestValidator" not in source
    assert "SessionMiddleware" not in source
    assert "fallback validation configuration" not in source.lower()



@pytest.mark.asyncio
@pytest.mark.parametrize("debug", (False, True))
async def test_unhandled_postgres_sql_parameters_never_reach_client_or_log(
    caplog: pytest.LogCaptureFixture, debug: bool,
) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.exc import StatementError
    from ai_karen_engine.middleware.intelligent_error_handler import (
        IntelligentErrorHandlerMiddleware,
    )

    sentinel = "SECRET_BOUND_SQL_PARAMETER"
    app = FastAPI()
    app.add_middleware(
        IntelligentErrorHandlerMiddleware,
        enable_intelligent_responses=False,
        debug_mode=debug,
    )

    @app.get("/failure")
    async def broken_endpoint():
        raise StatementError(
            "private SQL exception", "SELECT :sensitive",
            {"sensitive": sentinel}, RuntimeError("secret driver"),
        )

    @app.get("/denied")
    async def expected_denial():
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Access denied")

    with caplog.at_level("ERROR"):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://localhost",
        ) as client:
            failed = await client.get("/failure")
            denied = await client.get("/denied")
    assert failed.status_code == 500
    assert failed.json() == {"detail": "Internal server error"}
    assert denied.status_code == 403
    assert denied.json() == {"detail": "Access denied"}
    assert sentinel not in failed.text + denied.text + caplog.text
    assert "SELECT :sensitive" not in failed.text + caplog.text
    assert "secret driver" not in failed.text + caplog.text
    assert "traceback" not in failed.text
    assert "technical_details" not in failed.text
    assert all(record.exc_info is None for record in caplog.records
               if record.name == "ai_karen_engine.middleware.intelligent_error_handler")
