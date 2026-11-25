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

    logger = logging.Logger("uvicorn.access")
    monkeypatch.setattr(logging, "getLogger", lambda name: logger)
    install_request_target_privacy_filter()
    install_request_target_privacy_filter()
    assert len(logger.filters) == 1
    assert isinstance(logger.filters[0], RequestTargetPrivacyFilter)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        "GET /inventory?search=private", (), None,
    )
    assert not logger.filters[0].filter(record)
