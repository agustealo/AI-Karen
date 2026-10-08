"""Contract guards for canonical plugin catalog availability and UI truth.

These boundaries deliberately distinguish a genuinely empty discovered catalog
from backend/proxy errors and prevent bundler import maps from granting access.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "src/ui_launchers/Karen-AI-Theme/src"
ENGINE = ROOT / "src/ai_karen_engine"


def test_proxy_preserves_catalog_failure_status() -> None:
    route = (WEB / "app/api/extensions/list/route.ts").read_text(encoding="utf-8")
    assert "return proxied;" in route
    assert "NextResponse.json([], { status: 200 })" not in route


def test_backend_does_not_report_failed_discovery_as_empty() -> None:
    routes = (
        ENGINE / "api_routes/extensions/extensions.py"
    ).read_text(encoding="utf-8")
    assert 'status_code=503, detail="Extension catalog unavailable"' in routes
    assert "logger.exception(\"Extension catalog refresh failed\")" in routes


def test_loader_requires_discovered_backend_registration() -> None:
    loader = (WEB / "plugin_host/loader.ts").read_text(encoding="utf-8")
    assert "if (!entry) return [];" in loader
    assert "throw new Error('Invalid plugin catalog response')" in loader
    assert "throw error;" in loader
    assert "If no catalog entry, assume it's valid" not in loader


def test_frontend_recognizes_canonical_enabled_state() -> None:
    registry = (WEB / "plugin_host/registry.tsx").read_text(encoding="utf-8")
    assert "['active', 'registered', 'enabled', 'loaded'].includes(raw.status)" in registry
