from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_APP = REPO_ROOT / "server" / "app.py"
STARTUP = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "startup.py"
CANONICAL_HEALTH = REPO_ROOT / "src" / "ai_karen_engine" / "extensions" / "health.py"
LEGACY_HEALTH = REPO_ROOT / "server" / "extension_health_monitor.py"


def test_base_lifespan_owns_extension_health_startup_and_shutdown() -> None:
    source = STARTUP.read_text(encoding="utf-8")

    assert "await init_extension_health_monitor(app)" in source
    assert "await shutdown_extension_health_monitor()" in source
    assert "from ai_karen_engine.extensions.health import (" in source
    assert "ai_karen_engine.extensions.health_monitor" not in source


def test_extension_health_uses_canonical_core_manager_host() -> None:
    source = STARTUP.read_text(encoding="utf-8")

    assert "get_extension_core_manager" in source
    assert "extension_manager.host" in source
    assert "app.state.extension_system = extension_manager" in source


def test_root_server_app_owns_no_extension_lifecycle() -> None:
    source = SERVER_APP.read_text(encoding="utf-8")

    forbidden = (
        "initialize_extensions_for_production",
        "initialize_extension_system",
        "shutdown_extension_health_monitoring",
        "server.extension_health_monitor",
        "app.router.on_startup.append(initialize_extension_system)",
        "app.router.on_shutdown.append(shutdown_extension_health_monitoring)",
    )
    for token in forbidden:
        assert token not in source


def test_canonical_extension_health_module_exists() -> None:
    source = CANONICAL_HEALTH.read_text(encoding="utf-8")

    assert "class ExtensionHealthMonitor" in source
    assert "async def initialize_extension_health_monitor" in source
    assert "async def shutdown_extension_health_monitor" in source


def test_legacy_root_extension_health_monitor_is_retired() -> None:
    assert not LEGACY_HEALTH.exists()
