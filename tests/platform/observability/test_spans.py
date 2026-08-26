from __future__ import annotations

import pytest

from ai_karen_engine.platform.observability.context import (
    CorrelationContext,
    clear_correlation_context,
    set_correlation_context,
)
from ai_karen_engine.platform.observability.contracts import EventType
from ai_karen_engine.platform.observability.events import (
    InMemorySink,
    get_observability_emitter,
)
from ai_karen_engine.platform.observability.spans import observe_span


class TestLatencySpanRecordsTiming:
    """OBS-110: spans record started/completed timing."""

    def setup_method(self) -> None:
        clear_correlation_context()
        set_correlation_context(CorrelationContext(correlation_id="corr_span"))
        self.sink = InMemorySink()
        get_observability_emitter().register_sink(self.sink)

    def teardown_method(self) -> None:
        clear_correlation_context()
        emitter = get_observability_emitter()
        emitter._sinks = [s for s in emitter._sinks if s is not self.sink]

    def test_observe_span_emits_start_and_complete(self) -> None:
        with observe_span(EventType.PROVIDER_EXECUTION_COMPLETED) as span:
            span.duration_ms = 42.0
        types = [e.event_type for e in self.sink.events]
        assert EventType.PROVIDER_EXECUTION_COMPLETED in types
        completed = [e for e in self.sink.events if e.status == "completed"]
        assert completed, "expected a completed event"
        assert completed[0].duration_ms is not None
        assert completed[0].duration_ms >= 0

    def test_observe_span_emits_failure_on_exception(self) -> None:
        with (
            pytest.raises(ImportError),
            observe_span(EventType.PROVIDER_EXECUTION_FAILED),
        ):
            raise ImportError("boom")
        failed = [e for e in self.sink.events if e.status == "failed"]
        assert failed, "expected a failed event on exception"
        assert failed[0].error_type == "ImportError"
