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


def test_discovery_cannot_create_shadow_catalog_or_swallow_scan_errors() -> None:
    discovery = (
        ENGINE / "extensions/platform/core/registry/discovery.py"
    ).read_text(encoding="utf-8")
    assert "self.extensions_dir.mkdir(" not in discovery
    assert 'raise FileNotFoundError(' in discovery
    assert 'self.logger.exception("Extension discovery failed")' in discovery
    assert 'self.logger.exception("Failed to scan extension directories")' in discovery


def test_legacy_loader_cannot_create_shadow_plugin_root() -> None:
    loader = (
        ENGINE / "extensions/platform/core/host/loader.py"
    ).read_text(encoding="utf-8")
    assert "self.extensions_dir.mkdir(" not in loader
    assert "Configured extensions directory unavailable:" in loader
