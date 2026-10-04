from __future__ import annotations

from ai_karen_engine.agent_medusa.contracts.events import AgentEventType
from ai_karen_engine.agent_medusa.telemetry.tracing import MedusaTracer


def test_end_trace_preserves_terminal_event_before_archival() -> None:
    tracer = MedusaTracer()
    trace = tracer.start_trace("researcher", correlation_id="corr-1")

    completed = tracer.end_trace(trace.trace_id, success=True)

    assert completed is not None
    assert completed.end_time is not None
    assert completed.events[-1].type == AgentEventType.AGENT_COMPLETED
    assert completed.events[-1].correlation_id == "corr-1"
    assert tracer.get_trace(trace.trace_id) is completed


def test_end_trace_records_failure_terminal_event() -> None:
    tracer = MedusaTracer()
    trace = tracer.start_trace("analyst", correlation_id="corr-2")

    failed = tracer.end_trace(trace.trace_id, success=False)

    assert failed is not None
    assert failed.events[-1].type == AgentEventType.AGENT_FAILED
