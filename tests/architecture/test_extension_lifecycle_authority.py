from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_APP = REPO_ROOT / "server" / "app.py"
STARTUP = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "startup.py"
CANONICAL_HEALTH = REPO_ROOT / "src" / "ai_karen_engine" / "extensions" / "health.py"
LEGACY_HEALTH = REPO_ROOT / "server" / "extension_health_monitor.py"


def test_canonical_startup_owns_active_extension_bootstrap() -> None:
    source = STARTUP.read_text(encoding="utf-8")

    assert "get_extension_core_manager" in source
    assert "extension_manager = get_extension_core_manager()" in source
    assert "asyncio.create_task(extension_manager.initialize())" in source


def test_root_server_app_owns_no_extension_lifecycle() -> None:
    source = SERVER_APP.read_text(encoding="utf-8")

    forbidden = (
        "initialize_extensions_for_production",
        "initialize_extension_system",
        "shutdown_extension_health_monitoring",
        "server.extension_health_monitor",
        "EXTENSIONS_AVAILABLE",
        "app.router.on_startup.append(initialize_extension_system)",
        "app.router.on_shutdown.append(shutdown_extension_health_monitoring)",
    )
    for token in forbidden:
        assert token not in source


def test_metrics_endpoint_has_no_extension_lifecycle_side_effects() -> None:
    source = SERVER_APP.read_text(encoding="utf-8")

    metrics_source = source.split('@app.get("/metrics"', 1)[1].split(
        '@app.get("/plugins"', 1
    )[0]
    assert "extension_health_monitor" not in metrics_source
    assert "check_extension_system_health" not in metrics_source
    assert "update_extension_metrics" not in metrics_source


def test_canonical_extension_health_module_exists() -> None:
    source = CANONICAL_HEALTH.read_text(encoding="utf-8")

    assert "class ExtensionHealthMonitor" in source
    assert "async def initialize_extension_health_monitor" in source
    assert "async def shutdown_extension_health_monitor" in source


def test_legacy_root_extension_health_monitor_is_retired() -> None:
    assert not LEGACY_HEALTH.exists()
