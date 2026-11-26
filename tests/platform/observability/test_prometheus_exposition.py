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


def test_prometheus_histogram_uses_exact_cumulative_counts_and_milliseconds(monkeypatch) -> None:
    from ai_karen_engine.api_routes.monitoring import metrics as route
    from ai_karen_engine.platform.observability.metric_names import PROVIDER_LATENCY_MS
    from ai_karen_engine.platform.observability.metrics import MetricsCollector

    collector = MetricsCollector()
    monkeypatch.setattr(route, "get_metrics_collector", lambda: collector)
    histogram = collector.histogram(
        PROVIDER_LATENCY_MS, "Provider latency in milliseconds", ["provider"], [10, 100],
    )
    for value in (10, 75, 100, 101):
        histogram.labels(provider="local").observe(value)
    payload = route.render_prometheus_text()
    assert 'kari_provider_latency_ms_bucket{provider="local",le="10"} 1' in payload
    assert 'kari_provider_latency_ms_bucket{provider="local",le="100"} 3' in payload
    assert 'kari_provider_latency_ms_bucket{provider="local",le="+Inf"} 4' in payload
    assert 'kari_provider_latency_ms_sum{provider="local"} 286' in payload
    assert 'kari_provider_latency_ms_count{provider="local"} 4' in payload
