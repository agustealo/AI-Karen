from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_APP = REPO_ROOT / "server" / "app.py"
SERVER_METRICS = REPO_ROOT / "server" / "metrics.py"
CANONICAL_APP = REPO_ROOT / "src" / "ai_karen_engine" / "app.py"
CANONICAL_ROUTE = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "api_routes"
    / "monitoring"
    / "metrics.py"
)
CANONICAL_CATALOG = (
    REPO_ROOT
    / "src"
    / "ai_karen_engine"
    / "platform"
    / "observability"
    / "http_metrics.py"
)


def test_server_app_owns_no_metrics_exposition() -> None:
    source = SERVER_APP.read_text(encoding="utf-8")

    forbidden = (
        '@app.get("/metrics"',
        "prometheus_client",
        "generate_latest",
        "REGISTRY",
        "PROMETHEUS_ENABLED",
        "api_key_header",
    )
    for token in forbidden:
        assert token not in source


def test_metrics_route_is_wired_at_canonical_application_boundary() -> None:
    source = CANONICAL_APP.read_text(encoding="utf-8")

    assert "from ai_karen_engine.api_routes.monitoring.metrics import router as metrics_router" in source
    assert "app.include_router(metrics_router)" in source
    assert "_canonical_metrics_routes_registered" in source


def test_metrics_route_reads_canonical_collector_and_preserves_scrape_policy() -> None:
    source = CANONICAL_ROUTE.read_text(encoding="utf-8")

    assert "get_metrics_collector" in source
    assert 'APIKeyHeader(name="X-API-KEY", auto_error=False)' in source
    assert "KARI_PUBLIC_METRICS" in source
    assert 'raise HTTPException(status_code=401, detail="Invalid or missing API key")' in source


def test_http_metric_catalog_is_canonical() -> None:
    source = CANONICAL_CATALOG.read_text(encoding="utf-8")

    assert "get_metrics_collector" in source
    assert '"kari_http_requests_total"' in source
    assert '"kari_http_request_duration_seconds"' in source
    assert '"kari_http_errors_total"' in source


def test_server_metrics_is_only_a_compatibility_reexport() -> None:
    source = SERVER_METRICS.read_text(encoding="utf-8")

    assert "ai_karen_engine.platform.observability.http_metrics" in source
    assert "get_metrics_manager" not in source
    assert "prometheus_client" not in source
    assert "manager.counter(" not in source
    assert "manager.histogram(" not in source
    assert "manager.gauge(" not in source
