from __future__ import annotations

from ai_karen_engine.platform.observability.metrics import MetricsCollector


def test_histogram_preserves_label_values() -> None:
    collector = MetricsCollector()
    histogram = collector.histogram(
        "request_latency_seconds",
        "Request latency",
        ["method", "path"],
    )

    histogram.labels(method="GET", path="/a").observe(0.1)
    histogram.labels(method="POST", path="/b").observe(0.2)

    assert histogram.collect() == {
        ("GET", "/a"): [0.1],
        ("POST", "/b"): [0.2],
    }


def test_gauge_preserves_label_values() -> None:
    collector = MetricsCollector()
    gauge = collector.gauge(
        "inflight_requests",
        "In-flight requests",
        ["method", "path"],
    )

    gauge.labels(method="GET", path="/a").set(2)
    gauge.labels(method="POST", path="/b").set(3)

    assert gauge.collect() == {
        ("GET", "/a"): 2,
        ("POST", "/b"): 3,
    }
