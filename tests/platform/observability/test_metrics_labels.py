from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_karen_engine.platform.observability.metrics import HistogramSnapshot, MetricsCollector


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
        ("GET", "/a"): HistogramSnapshot(1, 0.1, (0, 0, 1, 1, 1, 1, 1, 1)),
        ("POST", "/b"): HistogramSnapshot(1, 0.2, (0, 0, 0, 1, 1, 1, 1, 1)),
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


def test_histogram_storage_is_bounded_per_series_and_snapshot_is_immutable() -> None:
    histogram = MetricsCollector().histogram("latency_ms", "Latency", ["provider"], [10, 100])
    series = histogram.labels(provider="local")
    for value in (0, 10, 50, 100, 500):
        series.observe(value)
    before = histogram.collect()[("local",)]
    assert before == HistogramSnapshot(5, 660.0, (2, 4))
    for _ in range(10000):
        series.observe(10)
    after = histogram.collect()[("local",)]
    assert after == HistogramSnapshot(10005, 100660.0, (10002, 10004))
    assert before == HistogramSnapshot(5, 660.0, (2, 4))
    # The only retained state is count, sum and one counter per finite bucket.
    assert len(histogram._values[("local",)].bucket_counts) == 2


def test_concurrent_observations_and_scrapes_keep_histogram_consistent() -> None:
    histogram = MetricsCollector().histogram("latency_ms", "Latency", ["provider"], [10, 100])
    series = histogram.labels(provider="local")

    def observe() -> None:
        for _ in range(500):
            series.observe(50)
            snapshot = histogram.collect()[("local",)]
            assert snapshot.bucket_counts == (0, snapshot.count)
            assert snapshot.total == snapshot.count * 50

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: observe(), range(8)))
    assert histogram.collect()[("local",)] == HistogramSnapshot(4000, 200000.0, (0, 4000))


@pytest.mark.parametrize("buckets", [[1, 1], [2, 1], [float("inf")], [float("nan")]])
def test_invalid_bucket_configuration_is_rejected(buckets) -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        MetricsCollector().histogram("latency_ms", "Latency", [], buckets)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_observations_do_not_create_or_corrupt_series(value) -> None:
    histogram = MetricsCollector().histogram("latency_ms", "Latency", [])
    with pytest.raises(ValueError, match="finite"):
        histogram.labels().observe(value)
    assert histogram.collect() == {}
