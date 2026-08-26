from __future__ import annotations

from datetime import datetime

from ai_karen_engine.platform.observability.context import (
    bind_correlation_context,
    clear_correlation_context,
    get_correlation_context,
    set_correlation_context,
)
from ai_karen_engine.platform.observability.contracts import (
    ErrorCategory,
    EventType,
    ExecutionEvent,
)
from ai_karen_engine.platform.observability.events import (
    InMemorySink,
    ObservabilityEmitter,
)


class TestEventTypeTaxonomyIsComplete:
    """OBS-102: the canonical vocabulary covers the full execution path."""

    REQUIRED = frozenset({
        "request.received",
        "request.completed",
        "request.failed",
        "auth.started",
        "auth.succeeded",
        "auth.failed",
        "intelligence.started",
        "intelligence.completed",
        "memory.recall.started",
        "memory.recall.completed",
        "cortex.started",
        "cortex.completed",
        "policy.started",
        "policy.completed",
        "policy.denied",
        "prompt.started",
        "prompt.completed",
        "prompt.failed",
        "provider.selection.completed",
        "provider.execution.started",
        "provider.execution.completed",
        "provider.execution.failed",
        "provider.fallback",
        "workflow.started",
        "workflow.completed",
        "workflow.failed",
        "extension.resolution.started",
        "extension.execution.started",
        "extension.execution.completed",
        "extension.execution.failed",
        "tool.started",
        "tool.completed",
        "tool.failed",
        "persistence.started",
        "persistence.completed",
        "persistence.failed",
    })

    def test_all_required_event_types_present(self) -> None:
        members = {event_type.value for event_type in EventType}
        missing = self.REQUIRED - members
        assert not missing, f"Missing canonical event types: {sorted(missing)}"


class TestExecutionEventContract:
    """OBS-101: the typed envelope serializes and omits empty fields."""

    def test_to_dict_serializes_known_fields(self) -> None:
        event = ExecutionEvent(
            event_id="evt_1",
            event_type=EventType.REQUEST_RECEIVED,
            timestamp=datetime(2024, 1, 1, 12, 0, 0),  # noqa: DTZ001
            request_id="req_1",
            correlation_id="corr_1",
            tenant_id="t_1",
            user_id="u_1",
            session_id="s_1",
            conversation_id="c_1",
            status="received",
        )
        payload = event.to_dict()
        assert payload["event_type"] == "request.received"
        assert payload["request_id"] == "req_1"
        assert payload["tenant_id"] == "t_1"
        assert payload["timestamp"] == "2024-01-01T12:00:00"

    def test_to_dict_omits_none_fields(self) -> None:
        event = ExecutionEvent(event_id="evt_2", event_type=EventType.PROVIDER_FALLBACK)
        payload = event.to_dict()
        assert "user_id" not in payload
        assert "metadata" in payload
        assert payload["metadata"] == {}

    def test_error_fields_present(self) -> None:
        event = ExecutionEvent(
            event_id="evt_3",
            event_type=EventType.PROVIDER_EXECUTION_FAILED,
            error_category=ErrorCategory.PROVIDER,
            error_type="ProviderUnavailable",
            error_code="unavailable",
            retryable=True,
            duration_ms=814.0,
        )
        payload = event.to_dict()
        assert payload["error_category"] == "PROVIDER"
        assert payload["error_code"] == "unavailable"
        assert payload["retryable"] is True
        assert payload["duration_ms"] == 814.0


class TestCorrelationContextPropagates:
    """OBS-103: one inbound request maps to one correlation lineage."""

    def setup_method(self) -> None:
        clear_correlation_context()

    def teardown_method(self) -> None:
        clear_correlation_context()

    def test_correlation_preserved_across_spans(self) -> None:
        set_correlation_context(
            __import__(
                "ai_karen_engine.platform.observability.context", fromlist=["CorrelationContext"]
            ).CorrelationContext(
                request_id="req_1",
                correlation_id="corr_1",
                tenant_id="t_1",
            )
        )
        bind_correlation_context(user_id="u_1", session_id="s_1")
        ctx = get_correlation_context()
        assert ctx.request_id == "req_1"
        assert ctx.correlation_id == "corr_1"
        assert ctx.user_id == "u_1"
        assert ctx.session_id == "s_1"

    def test_bind_does_not_replace_existing_identity(self) -> None:
        set_correlation_context(
            __import__(
                "ai_karen_engine.platform.observability.context", fromlist=["CorrelationContext"]
            ).CorrelationContext(request_id="req_x", tenant_id="t_x")
        )
        bind_correlation_context(tenant_id="t_y")
        ctx = get_correlation_context()
        assert ctx.request_id == "req_x"
        assert ctx.tenant_id == "t_y"


class TestEmitAndRetrieveEvent:
    def setup_method(self) -> None:
        clear_correlation_context()
        self.sink = InMemorySink()
        self.emitter = ObservabilityEmitter([self.sink])

    def teardown_method(self) -> None:
        clear_correlation_context()

    def test_emit_event_records_and_binds_correlation(self) -> None:
        set_correlation_context(
            __import__(
                "ai_karen_engine.platform.observability.context", fromlist=["CorrelationContext"]
            ).CorrelationContext(correlation_id="corr_e", request_id="req_e", tenant_id="t_e")
        )
        event = self.emitter.emit(
            EventType.PROVIDER_EXECUTION_COMPLETED,
            provider="lm_studio",
            model="qwen",
            duration_ms=814.0,
            status="success",
        )
        assert len(self.sink.events) == 1
        assert event.correlation_id == "corr_e"
        assert event.request_id == "req_e"
        payload = event.to_dict()
        assert payload["provider"] == "lm_studio"
        assert payload["duration_ms"] == 814.0

    def test_sink_failure_does_not_crash_request_path(self) -> None:
        class BrokenSink:
            name = "broken"

            def emit_from_dict(self, payload):
                raise RuntimeError("boom")

        emitter = ObservabilityEmitter([BrokenSink()])
        event = emitter.emit(EventType.REQUEST_RECEIVED, status="received")
        assert event.event_id is not None


class TestFailureEmitsCompletionEvent:
    def setup_method(self) -> None:
        clear_correlation_context()
        self.sink = InMemorySink()
        self.emitter = ObservabilityEmitter([self.sink])

    def teardown_method(self) -> None:
        clear_correlation_context()

    def test_failed_stage_emits_failed_event(self) -> None:
        event = self.emitter.emit(
            EventType.PROVIDER_EXECUTION_FAILED,
            provider="gemini",
            status="failure",
            error_category=ErrorCategory.PROVIDER,
            error_code="unavailable",
        )
        assert event.status == "failure"
        assert event.event_type == EventType.PROVIDER_EXECUTION_FAILED


class TestFallbackEventProduced:
    def setup_method(self) -> None:
        clear_correlation_context()
        self.sink = InMemorySink()
        self.emitter = ObservabilityEmitter([self.sink])

    def teardown_method(self) -> None:
        clear_correlation_context()

    def test_fallback_event_has_level_and_source(self) -> None:
        event = self.emitter.emit(
            EventType.PROVIDER_FALLBACK,
            provider="lm_studio",
            model="qwen",
            fallback_level=1,
            response_source="fallback_provider_runtime",
            status="success",
        )
        payload = event.to_dict()
        assert payload["fallback_level"] == 1
        assert payload["response_source"] == "fallback_provider_runtime"
        assert payload["event_type"] == "provider.fallback"


class TestMetricsCollectorIncrements:
    def setup_method(self) -> None:
        from ai_karen_engine.platform.observability.metrics import MetricsCollector

        self.collector = MetricsCollector()

    def test_counter_increments(self) -> None:
        counter = self.collector.counter("t_requests_total", "total", ("status",))
        counter.labels(status="success").inc()
        counter.labels(status="success").inc()
        assert counter.value(status="success") == 2.0

    def test_histogram_records(self) -> None:
        histogram = self.collector.histogram("t_latency_ms", "latency", ("provider",))
        histogram.labels(provider="qwen").observe(12.0)
        histogram.labels(provider="qwen").observe(31.0)
        snapshot = self.collector.snapshot()
        assert len(snapshot["histograms"]["t_latency_ms"][()]) == 2

    def test_gauge_set(self) -> None:
        gauge = self.collector.gauge("t_in_flight", "in flight")
        gauge.set(5.0)
        assert gauge.value() == 5.0


class TestHighCardinalityLabelsRejected:
    """OBS-106: unbounded identifiers must not become metric labels."""

    def setup_method(self) -> None:
        from ai_karen_engine.platform.observability.metrics import (
            CardinalityError,
            MetricsCollector,
        )
        self.collector = MetricsCollector()
        self.CardinalityError = CardinalityError

    def test_rejects_user_id_label(self) -> None:
        with_ = self.CardinalityError
        import pytest

        with pytest.raises(with_):
            self.collector.counter("m", "d", ("user_id",))

    def test_rejects_request_id_label(self) -> None:
        import pytest

        with pytest.raises(self.CardinalityError):
            self.collector.histogram("m", "d", ("request_id",))

    def test_accepts_bounded_labels(self) -> None:
        counter = self.collector.counter("m_total", "d", ("provider", "status"))
        counter.labels(provider="qwen", status="success").inc()
        assert counter.value(provider="qwen", status="success") == 1.0


class TestRuntimeMetadataBridge:
    """OBS-107: runtime metadata maps into events without platform importing the runtime."""

    def setup_method(self) -> None:
        from ai_karen_engine.platform.observability.context import (
            CorrelationContext,
            set_correlation_context,
        )

        clear_correlation_context()
        set_correlation_context(CorrelationContext(correlation_id="corr_meta"))
        self.sink = InMemorySink()

    def teardown_method(self) -> None:
        clear_correlation_context()

    def test_record_runtime_metadata_maps_fields(self) -> None:
        from ai_karen_engine.platform.observability.events import ObservabilityEmitter
        from ai_karen_engine.platform.observability.runtime_bridge import (
            record_runtime_metadata,
        )

        class FakeMetadata:
            requested_target = "gemini"
            resolved_target = "lm_studio"
            provider = "lm_studio"
            model = "qwen3"
            runtime_engine = "lm_studio"
            execution_layer = "provider"
            response_source = "fallback_provider_runtime"
            fallback_level = 1
            degraded_mode = True
            degradation_type = "provider_unavailable"

        emitter = ObservabilityEmitter([self.sink])
        event = record_runtime_metadata(FakeMetadata(), emitter=emitter)
        payload = event.to_dict()
        assert payload["requested_target"] == "gemini"
        assert payload["resolved_target"] == "lm_studio"
        assert payload["fallback_level"] == 1
        assert payload["degraded_mode"] is True
        assert payload["degradation_type"] == "provider_unavailable"


class TestBoundedBufferEvictsOldest:
    def test_oldest_evicted_at_capacity(self) -> None:
        from ai_karen_engine.platform.observability.diagnostics_buffer import (
            BoundedDiagnosticsBuffer,
        )
        from ai_karen_engine.platform.observability.events import (
            EventType,
            ExecutionEvent,
        )

        buffer = BoundedDiagnosticsBuffer(capacity=3)
        for i in range(5):
            buffer.add(
                ExecutionEvent(event_id=f"evt_{i}", event_type=EventType.REQUEST_RECEIVED)
            )
        recent = buffer.recent()
        ids = [e["event_id"] for e in recent]
        assert ids == ["evt_2", "evt_3", "evt_4"]
