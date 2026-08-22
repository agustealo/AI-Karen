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
