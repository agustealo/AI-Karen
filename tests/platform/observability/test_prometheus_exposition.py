from __future__ import annotations

from ai_karen_engine.api_routes.monitoring.metrics import render_prometheus_text
from ai_karen_engine.platform.observability.metrics import get_metrics_collector


def test_prometheus_exposition_uses_canonical_collector() -> None:
    collector = get_metrics_collector()
    counter = collector.counter(
        "test_observability_requests_total",
        "Test requests",
        ["status"],
    )
    histogram = collector.histogram(
        "test_observability_latency_seconds",
        "Test latency",
        ["route"],
        buckets=[0.1, 0.5],
    )

    counter.labels(status="ok").inc(2)
    histogram.labels(route="chat").observe(0.2)

    payload = render_prometheus_text()

    assert "# TYPE test_observability_requests_total counter" in payload
    assert 'test_observability_requests_total{status="ok"} 2' in payload
    assert "# TYPE test_observability_latency_seconds histogram" in payload
    assert 'test_observability_latency_seconds_bucket{route="chat",le="0.5"} 1' in payload
    assert 'test_observability_latency_seconds_count{route="chat"} 1' in payload
