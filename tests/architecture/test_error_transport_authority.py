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


@pytest.mark.asyncio
async def test_registered_exception_handlers_redact_sql_jwt_and_validation_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Prove FastAPI's registered exception owners, not just outer middleware."""
    import logging

    from fastapi import FastAPI, HTTPException
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.exc import StatementError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from ai_karen_engine.auth.auth_middleware import AuthenticationError
    from ai_karen_engine.server.exception_handlers import setup_exception_handlers

    secret = "PRIVATE_BOUND_SQL_HTTP_SENTINEL"
    sql_error = StatementError(
        "private SQL operation", "SELECT :private_value",
        {"private_value": secret}, RuntimeError("secret database driver"),
    )
    assert secret in str(sql_error)

    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/unhandled")
    async def unhandled():
        raise sql_error

    @app.get("/explicit-500")
    async def explicit_500():
        raise HTTPException(status_code=500, detail=str(sql_error))

    @app.get("/starlette-500")
    async def starlette_500():
        raise StarletteHTTPException(status_code=500, detail=str(sql_error))

    @app.get("/unsafe-auth")
    async def unsafe_auth():
        raise AuthenticationError(f"Invalid token: {secret}", 401)

    @app.get("/expired")
    async def expired():
        raise AuthenticationError("Token has expired", 401)

    @app.get("/denied")
    async def denied():
        raise HTTPException(status_code=403, detail="Access denied")

    @app.get("/available-later")
    async def available_later():
        raise HTTPException(
            status_code=503, detail="Run event history unavailable",
        )

    @app.get("/validated")
    async def validated(limit: int):
        return {"limit": limit}

    with caplog.at_level(
        logging.DEBUG, logger="ai_karen_engine.server.exception_handlers",
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            responses = {
                name: await client.get(f"/{name}")
                for name in (
                    "unhandled", "explicit-500", "starlette-500",
                    "unsafe-auth", "expired", "denied", "available-later",
                )
            }
            invalid = await client.get(f"/validated?limit={secret}")

    assert responses["unhandled"].status_code == 500
    assert responses["unhandled"].json()["detail"] == "Internal server error"
    assert responses["unhandled"].json()["error_code"] == "INTERNAL_SERVER_ERROR"
    assert responses["explicit-500"].json()["detail"] == "Internal server error"
    assert responses["starlette-500"].json()["detail"] == "Internal server error"
    assert responses["unsafe-auth"].status_code == 401
    assert responses["unsafe-auth"].json()["detail"] == "Authentication required"
    assert responses["expired"].json()["detail"] == "Token has expired"
    assert responses["denied"].status_code == 403
    assert responses["denied"].json()["detail"] == "Access denied"
    assert responses["available-later"].status_code == 503
    assert (
        responses["available-later"].json()["detail"]
        == "Run event history unavailable"
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Validation error"
    assert invalid.json()["message"] == "Invalid request parameters"

    emitted = caplog.text + "".join(response.text for response in responses.values())
    emitted += invalid.text
    for forbidden in (secret, "SELECT :private_value", "secret database driver"):
        assert forbidden not in emitted
    assert "exception_message" not in emitted
    assert all(
        record.exc_info is None
        for record in caplog.records
        if record.name == "ai_karen_engine.server.exception_handlers"
    )


@pytest.mark.parametrize(
    ("decoder", "expected"),
    [
        ("_decode_jwt", "Invalid token"),
        ("_decode_refresh_token", "Invalid refresh token"),
    ],
)
def test_jwt_decoder_does_not_expose_library_exception_details(
    monkeypatch: pytest.MonkeyPatch, decoder: str, expected: str,
) -> None:
    import jwt

    from ai_karen_engine.auth.auth_middleware import (
        AuthenticationError,
        SecureAuthMiddleware,
    )

    secret = "PRIVATE_INVALID_JWT_SENTINEL"

    def reject_decode(*_args, **_kwargs):
        raise jwt.InvalidTokenError(secret)

    monkeypatch.setattr(jwt, "decode", reject_decode)
    auth = object.__new__(SecureAuthMiddleware)
    auth.jwt_secret = "test-secret"
    auth.jwt_algorithm = "HS256"

    with pytest.raises(AuthenticationError) as captured:
        getattr(auth, decoder)("invalid-token")
    assert str(captured.value) == expected
    assert secret not in str(captured.value)


def test_legacy_health_handlers_do_not_serialize_exception_text() -> None:
    """Source contract avoids importing the full production app during unit CI."""
    import ast

    source = (
        ROOT / "src/ai_karen_engine/server/app.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    checked = {
        "health_check",
        "database_health",
        "test_database_connection",
        "degraded_mode_status",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name not in checked:
            continue
        excerpt = ast.get_source_segment(source, node)
        assert excerpt is not None
        assert "str(e)" not in excerpt
        assert "str(exc)" not in excerpt
        checked.remove(node.name)
    assert not checked
