from ai_karen_engine.core.logging.redaction import redact_text, redact_data

def test_redact_api_key():
    text = "api_key: sk-1234567890abcdef12345678"
    assert "sk-123" not in redact_text(text)
    assert "[REDACTED]" in redact_text(text)

def test_redact_password():
    text = "user password is myPassword123"
    assert "myPassword123" not in redact_text(text)
    assert "[REDACTED]" in redact_text(text)

def test_redact_jwt():
    text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    assert "eyJ" not in redact_text(text)
    assert "[JWT_REDACTED]" in redact_text(text)

def test_redact_dict():
    data = {
        "user": "bob",
        "secret": "supersecret12345",
        "nested": {"key": "key-9876543210"}
    }
    redacted = redact_data(data)
    assert redacted["user"] == "bob"
    assert redacted["secret"] == "[REDACTED]"
    assert redacted["nested"]["key"] == "[REDACTED]"


def test_access_log_removes_query_before_any_formatter():
    import logging

    from uvicorn.logging import AccessFormatter

    from ai_karen_engine.core.logging.formatters import RuntimeJSONFormatter, RuntimeTextFormatter
    from ai_karen_engine.core.logging.redaction import RequestTargetPrivacyFilter

    target = "/api/plugins/file-explorer/hierarchy?search=private%20report&file_cursor=opaque"
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", target, "1.1", 200), None,
    )
    assert RequestTargetPrivacyFilter().filter(record)
    assert record.args == (
        "127.0.0.1:1234", "GET", "/api/plugins/file-explorer/hierarchy", "1.1", 200,
    )
    for formatter in (
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s'),
        RuntimeJSONFormatter(redact_secrets=False),
        RuntimeTextFormatter(),
    ):
        output = formatter.format(record)
        assert "/api/plugins/file-explorer/hierarchy" in output
        assert "200" in output
        assert "private" not in output and "opaque" not in output
        assert "search=" not in output and "file_cursor=" not in output


def test_access_filter_denies_unknown_formats_and_is_idempotent(monkeypatch):
    import logging

    from ai_karen_engine.core.logging.redaction import (
        RequestTargetPrivacyFilter,
        install_request_target_privacy_filter,
    )

    logger = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(logger, "filters", [])
    install_request_target_privacy_filter()
    install_request_target_privacy_filter()
    assert len(logger.filters) == 1
    assert isinstance(logger.filters[0], RequestTargetPrivacyFilter)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        "GET /inventory?search=private", (), None,
    )
    assert not logger.filters[0].filter(record)


def test_installed_access_filter_protects_all_handlers(monkeypatch):
    import io
    import logging

    from uvicorn.logging import AccessFormatter

    from ai_karen_engine.core.logging.formatters import RuntimeJSONFormatter
    from ai_karen_engine.core.logging.redaction import install_request_target_privacy_filter

    access = logging.getLogger("uvicorn.access")
    streams = [io.StringIO(), io.StringIO()]
    handlers = [logging.StreamHandler(stream) for stream in streams]
    handlers[0].setFormatter(AccessFormatter('%(request_line)s %(status_code)s'))
    handlers[1].setFormatter(RuntimeJSONFormatter(redact_secrets=False))
    monkeypatch.setattr(access, "filters", [])
    monkeypatch.setattr(access, "handlers", handlers)
    monkeypatch.setattr(access, "propagate", False)
    monkeypatch.setattr(access, "disabled", False)
    monkeypatch.setattr(access, "level", logging.INFO)
    install_request_target_privacy_filter()

    access.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:1234", "GET",
        "/inventory?search=private%20report&cursor=opaque", "1.1", 200,
    )
    access.info("GET /inventory?search=unsafe")
    for stream in streams:
        output = stream.getvalue()
        assert "/inventory" in output and "200" in output
        assert "private" not in output
        assert "opaque" not in output
        assert "unsafe" not in output
        assert "search=" not in output
        assert len(output.splitlines()) == 1


def test_canonical_postgres_engines_hide_parameters_even_with_sql_echo(monkeypatch):
    from types import SimpleNamespace

    from ai_karen_engine.persistence.postgres import engine

    settings = SimpleNamespace(
        postgres=SimpleNamespace(
            build_database_url=lambda: "postgresql://test:test@127.0.0.1:5432/test",
            build_async_database_url=lambda: "postgresql+asyncpg://test:test@127.0.0.1:5432/test",
        ),
        pool=SimpleNamespace(
            echo_sql=True, pool_pre_ping=True, pool_size=1, max_overflow=0,
            pool_timeout=1, pool_recycle=60,
        ),
    )
    monkeypatch.setattr(engine, "get_database_settings", lambda: settings)
    # Engine construction does not connect to PostgreSQL. This verifies the
    # actual SQLAlchemy engine settings, not just the factory call arguments.
    instance = engine.PostgresEngine()
    instance.initialize()
    try:
        assert instance.engine.echo is True
        assert instance.engine.hide_parameters is True
        assert instance._async_engine.sync_engine.echo is True
        assert instance._async_engine.sync_engine.hide_parameters is True
    finally:
        instance.engine.dispose()
        instance._async_engine.sync_engine.dispose()
