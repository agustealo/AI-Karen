from __future__ import annotations

from ai_karen_engine.platform.observability.redaction import (
    redact_data,
    redact_text,
    redact_url,
)


class TestSecretFieldsRedacted:
    """OBS-109: secrets must never be emitted."""

    def test_api_key_redacted(self) -> None:
        assert redact_text("api_key=sk-1234567890abcdef1234567890") == "[REDACTED]"

    def test_access_token_redacted(self) -> None:
        text = "access_token=eyJhbGciOiJIUzI1NiJ9abcdef123456"
        assert "eyJ" not in redact_text(text)
        assert "[REDACTED]" in redact_text(text)

    def test_bearer_authorization_redacted(self) -> None:
        text = "Authorization: Bearer abcdef1234567890abcdef1234567890"
        assert "Bearer" in redact_text(text)
        assert "[REDACTED]" in redact_text(text)
        assert "abcdef1234567890" not in redact_text(text)

    def test_password_redacted(self) -> None:
        text = "password=supersecretvalue123"
        assert "supersecretvalue123" not in redact_text(text)

    def test_jwt_redacted(self) -> None:
        text = "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc13signaturexxx"
        assert "[JWT_REDACTED]" in redact_text(text)

    def test_dict_sensitive_keys_redacted(self) -> None:
        data = {
            "user": "alice",
            "api_key": "sk-secret",
            "client_secret": "shhh",
            "nested": {"password": "secret123", "two_factor_secret": "x", "safe": "value"},
        }
        redacted = redact_data(data)
        assert redacted["user"] == "alice"
        assert redacted["api_key"] == "[REDACTED]"
        assert redacted["client_secret"] == "[REDACTED]"
        assert redacted["nested"]["password"] == "[REDACTED]"
        assert redacted["nested"]["two_factor_secret"] == "[REDACTED]"
        assert redacted["nested"]["safe"] == "value"

    def test_url_credentials_redacted(self) -> None:
        text = "postgres://user:s3cret@localhost:5432/db"
        assert "s3cret" not in redact_url(text)

    def test_url_sensitive_query_redacted(self) -> None:
        text = "https://example.com/callback?api_key=supersecret&page=2"
        redacted = redact_url(text)
        assert "supersecret" not in redacted
        assert "page=2" in redacted


class TestNoSecretsEmittedInEventPayload:
    def test_metadata_secrets_redacted_on_emit(self) -> None:
        from ai_karen_engine.platform.observability.context import (
            CorrelationContext,
            clear_correlation_context,
            set_correlation_context,
        )
        from ai_karen_engine.platform.observability.events import (
            EventType,
            ObservabilityEmitter,
        )
        from ai_karen_engine.platform.observability.redaction import redact_data

        clear_correlation_context()
        set_correlation_context(CorrelationContext(correlation_id="c"))
        try:
            sink_type = __import__(
                "ai_karen_engine.platform.observability.events",
                fromlist=["InMemorySink"],
            ).InMemorySink
            sink = sink_type()
            emitter = ObservabilityEmitter([sink])
            emitter.emit(
                EventType.REQUEST_FAILED,
                metadata={"error": "api_key=sk-leakvalue12345678", "note": "ok"},
            )
            assert sink.events, "expected an event to be emitted"
            serialized = redact_data(sink.events[0].to_dict())
            assert "sk-leakvalue" not in str(serialized)
            assert serialized["metadata"]["note"] == "ok"
        finally:
            clear_correlation_context()
