from __future__ import annotations

import asyncio
import contextvars
import re
from datetime import datetime

from ai_karen_engine.core.observability.context import (
    ObservabilityContext,
    bind_observability_context,
    clear_observability_context,
    get_observability_context,
    set_observability_context,
)
from ai_karen_engine.core.observability.contracts import RuntimeEvent, RuntimeEventType
from ai_karen_engine.core.observability.emitter import (
    get_observability_emitter,
)
from ai_karen_engine.core.observability.redaction import redact_data, redact_text


class TestRuntimeEventContractIsCanonical:
    """The RuntimeEvent dataclass is the single source of truth for event fields."""

    def test_event_has_required_fields(self) -> None:
        event = RuntimeEvent(
            event_id="evt_1",
            event_type=RuntimeEventType.REQUEST_RECEIVED,
            correlation_id="corr_1",
            request_id="req_1",
            tenant_id="tenant_1",
            user_id="user_1",
            session_id="sess_1",
            conversation_id="conv_1",
            provider="openai",
            model="gpt-4o",
            policy_decision_id="pol_1",
            plugin_id="plugin_1",
            plugin_version="1.0.0",
            duration_ms=120.5,
            status="success",
            error_type=None,
            error_code=None,
            metadata={"key": "value"},
        )
        assert event.event_id == "evt_1"
        assert event.event_type == RuntimeEventType.REQUEST_RECEIVED
        assert event.correlation_id == "corr_1"
        assert event.tenant_id == "tenant_1"
        assert event.provider == "openai"
        assert event.metadata == {"key": "value"}

    def test_event_to_dict_serializes(self) -> None:
        event = RuntimeEvent(
            event_id="evt_2",
            event_type=RuntimeEventType.PROVIDER_ATTEMPT_FAILED,
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            correlation_id="corr_2",
            tenant_id="tenant_2",
            duration_ms=45.0,
            status="failure",
            error_type="RateLimitError",
            error_code="RATE_LIMIT",
        )
        payload = event.to_dict()
        assert payload["event_type"] == "provider.attempt.failed"
        assert payload["timestamp"] == "2024-01-01T12:00:00"
        assert payload["correlation_id"] == "corr_2"
        assert payload["error_code"] == "RATE_LIMIT"
        assert "metadata" not in payload

    def test_event_to_dict_omits_none_fields(self) -> None:
        event = RuntimeEvent(
            event_id="evt_3",
            event_type=RuntimeEventType.REQUEST_RECEIVED,
        )
        payload = event.to_dict()
        assert "correlation_id" not in payload
        assert "tenant_id" not in payload


class TestCorrelationIdPropagatesEndToEnd:
    """Correlation context flows through the execution path."""

    def test_set_and_get_context(self) -> None:
        clear_observability_context()
        ctx = ObservabilityContext(
            correlation_id="corr_42",
            request_id="req_42",
            tenant_id="tenant_42",
            user_id="user_42",
            session_id="sess_42",
            conversation_id="conv_42",
        )
        token = set_observability_context(ctx)
        try:
            current = get_observability_context()
            assert current.correlation_id == "corr_42"
            assert current.request_id == "req_42"
            assert current.tenant_id == "tenant_42"
        finally:
            clear_observability_context()
            _ = token

    def test_bind_context_updates_select_fields(self) -> None:
        clear_observability_context()
        ctx = ObservabilityContext(
            correlation_id="corr_1",
            request_id="req_1",
            tenant_id="tenant_1",
        )
        set_observability_context(ctx)
        bind_observability_context(session_id="sess_1", conversation_id="conv_1")
        current = get_observability_context()
        assert current.correlation_id == "corr_1"
        assert current.session_id == "sess_1"
        assert current.conversation_id == "conv_1"
        clear_observability_context()

    def test_context_is_isolated_per_async_task(self) -> None:
        clear_observability_context()
        set_observability_context(ObservabilityContext(correlation_id="corr_main"))

        async def _task(name: str, expected: str) -> str:
            if name == "child":
                bind_observability_context(correlation_id=expected)
            return get_observability_context().correlation_id

        async def run() -> tuple[str, str]:
            main_ctx = get_observability_context()
            child_token = contextvars.copy_context()
            result = await asyncio.create_task(
                _task("child", "corr_child"), context=child_token
            )
            return main_ctx.correlation_id, result

        main_corr, child_corr = asyncio.run(run())
        assert main_corr == "corr_main"
        assert child_corr == "corr_child"
        clear_observability_context()


class TestProviderAttemptEventsAreStructured:
    """Provider attempt events carry structured provider/model/status fields."""

    def test_attempt_started_event_shape(self) -> None:
        emitter = get_observability_emitter()
        bind_observability_context(
            correlation_id="corr_p",
            request_id="req_p",
            tenant_id="tenant_p",
        )
        try:
            event = emitter.emit(
                RuntimeEventType.PROVIDER_ATTEMPT_STARTED,
                provider="openai",
                model="gpt-4o",
                runtime_engine="openai",
                policy_decision_id="pol_p",
                status="started",
            )
            payload = event.to_dict()
            assert payload["provider"] == "openai"
            assert payload["model"] == "gpt-4o"
            assert payload["runtime_engine"] == "openai"
            assert payload["status"] == "started"
            assert payload["correlation_id"] == "corr_p"
        finally:
            clear_observability_context()

    def test_attempt_failed_event_shape(self) -> None:
        emitter = get_observability_emitter()
        bind_observability_context(correlation_id="corr_f")
        try:
            event = emitter.emit(
                RuntimeEventType.PROVIDER_ATTEMPT_FAILED,
                provider="anthropic",
                model="claude-3-opus",
                duration_ms=2300.0,
                status="failure",
                error_type="RateLimitError",
                error_code="RATE_LIMIT",
            )
            payload = event.to_dict()
            assert payload["provider"] == "anthropic"
            assert payload["error_type"] == "RateLimitError"
            assert payload["duration_ms"] == 2300.0
        finally:
            clear_observability_context()


class TestFallbackEventContainsActualProvider:
    """Fallback events record the provider that actually handled the request."""

    def test_fallback_event_has_provider(self) -> None:
        emitter = get_observability_emitter()
        bind_observability_context(
            correlation_id="corr_fb",
            tenant_id="tenant_fb",
            request_id="req_fb",
        )
        try:
            event = emitter.emit(
                RuntimeEventType.FALLBACK_APPLIED,
                provider="openai",
                model="gpt-4o-mini",
                fallback_level=1,
                degraded_mode=True,
                response_source="fallback",
                policy_decision_id="pol_fb",
                status="success",
            )
            payload = event.to_dict()
            assert payload["provider"] == "openai"
            assert payload["fallback_level"] == 1
            assert payload["degraded_mode"] is True
            assert payload["response_source"] == "fallback"
        finally:
            clear_observability_context()


class TestPluginEventContainsPolicyDecision:
    """Plugin events include the policy decision that authorized execution."""

    def test_plugin_completed_has_policy_decision(self) -> None:
        emitter = get_observability_emitter()
        bind_observability_context(
            correlation_id="corr_pl",
            tenant_id="tenant_pl",
        )
        try:
            event = emitter.emit(
                RuntimeEventType.PLUGIN_COMPLETED,
                plugin_id="plugin_1",
                plugin_version="2.0.0",
                policy_decision_id="pol_pl",
                status="success",
                duration_ms=12.3,
            )
            payload = event.to_dict()
            assert payload["plugin_id"] == "plugin_1"
            assert payload["plugin_version"] == "2.0.0"
            assert payload["policy_decision_id"] == "pol_pl"
        finally:
            clear_observability_context()


class TestSensitiveValuesAreRedacted:
    """Sensitive values are redacted before emission."""

    def test_redact_api_key(self) -> None:
        text = "api_key=sk-1234567890abcdef"
        assert redact_text(text) == "[REDACTED]"

    def test_redact_bearer_token(self) -> None:
        text = "Authorization: Bearer abcdef1234567890"
        assert redact_text(text) == "Authorization: [REDACTED]"

    def test_redact_password(self) -> None:
        text = "password=supersecret123"
        assert redact_text(text) == "password=[REDACTED]"

    def test_redact_data_dict(self) -> None:
        data = {
            "user": "alice",
            "api_key": "sk-secret",
            "nested": {"password": "secret123", "safe": "value"},
        }
        redacted = redact_data(data)
        assert redacted["user"] == "alice"
        assert redacted["api_key"] == "[REDACTED]"
        assert redacted["nested"]["password"] == "[REDACTED]"
        assert redacted["nested"]["safe"] == "value"

    def test_redact_jwt(self) -> None:
        text = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdef"
        assert "[JWT_REDACTED]" in redact_text(text)

    def test_redact_db_url(self) -> None:
        text = "postgres://user:secret@localhost/db"
        assert "secret" not in redact_text(text)
        assert "[REDACTED]" in redact_text(text)


class TestNoPrintBasedRuntimeTelemetry:
    """Runtime telemetry must not rely on raw print() statements."""

    def test_no_print_in_observability_package(self) -> None:
        import os

        obs_dir = os.path.join(os.path.dirname(__file__), "..", "core", "observability")
        for root, _dirs, files in os.walk(obs_dir):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(root, filename)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert not re.search(r"\bprint\s*\(", content), (
                    f"print() found in observability package: {path}"
                )

    def test_no_print_in_core_logging_package(self) -> None:
        import os

        logging_dir = os.path.join(os.path.dirname(__file__), "..", "core", "logging")
        for root, _dirs, files in os.walk(logging_dir):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(root, filename)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert not re.search(r"\bprint\s*\(", content), (
                    f"print() found in core/logging package: {path}"
                )


class TestChatRuntimeEmitsRequestLifecycle:
    """A request emits the full lifecycle through the observability emitter."""

    def test_request_lifecycle_events(self) -> None:
        emitter = get_observability_emitter()
        bind_observability_context(
            correlation_id="corr_lc",
            request_id="req_lc",
            tenant_id="tenant_lc",
            user_id="user_lc",
            session_id="sess_lc",
            conversation_id="conv_lc",
        )
        try:
            events: list[RuntimeEvent] = []
            original_emit = emitter.emit
            captured: list[dict[str, Any]] = []

            def _capture(event_type, **kwargs):
                event = original_emit(event_type, **kwargs)
                captured.append(event.to_dict())
                events.append(event)
                return event

            emitter.emit = _capture  # type: ignore[method-assign]

            emitter.emit(RuntimeEventType.REQUEST_RECEIVED, intent="chat", status="received")
            emitter.emit(
                RuntimeEventType.PROVIDER_SELECTION,
                provider="openai",
                model="gpt-4o",
                policy_decision_id="pol_lc",
                status="selected",
            )
            emitter.emit(
                RuntimeEventType.PROVIDER_ATTEMPT_STARTED,
                provider="openai",
                model="gpt-4o",
                status="started",
            )
            emitter.emit(
                RuntimeEventType.PROVIDER_ATTEMPT_COMPLETED,
                provider="openai",
                model="gpt-4o",
                duration_ms=350.0,
                status="success",
            )
            emitter.emit(
                RuntimeEventType.REQUEST_COMPLETED,
                status="success",
                duration_ms=360.0,
                response_source="provider",
            )

            types_seen = [e["event_type"] for e in captured]
            assert types_seen == [
                "request.received",
                "provider.selection",
                "provider.attempt.started",
                "provider.attempt.completed",
                "request.completed",
            ]
            assert all(e["correlation_id"] == "corr_lc" for e in captured)
            assert all(e["tenant_id"] == "tenant_lc" for e in captured)
        finally:
            clear_observability_context()
