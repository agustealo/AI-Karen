from __future__ import annotations

from pathlib import Path

from ai_karen_engine.extensions.platform.core.plugin_lifecycle_manager import (
    PluginLifecycleManager,
    PluginLifecycleState,
)
from ai_karen_engine.extensions.platform.core.registry.database_models import (
    ExtensionDBModel,
)


ROOT = Path(__file__).resolve().parents[2]


def test_extension_model_exposes_durable_lifecycle_fields() -> None:
    columns = ExtensionDBModel.__table__.columns
    for name in ("lifecycle_state", "installed_at", "enabled", "install_path"):
        assert name in columns


def test_local_discovery_is_not_treated_as_installed_without_database_state() -> None:
    source = (
        ROOT
        / "src"
        / "ai_karen_engine"
        / "extensions"
        / "platform"
        / "core"
        / "plugin_lifecycle_manager.py"
    ).read_text(encoding="utf-8")

    assert "Filesystem presence means the plugin is discoverable, not installed." in source
    assert 'plugin_path / "plugin_manifest.json"' in source
    assert 'plugin_path / "manifest.json"' not in source


def test_lifecycle_manager_uses_process_scoped_operation_lock() -> None:
    source = (
        ROOT
        / "src"
        / "ai_karen_engine"
        / "extensions"
        / "platform"
        / "core"
        / "plugin_lifecycle_manager.py"
    ).read_text(encoding="utf-8")

    assert "_PLUGIN_OPERATION_LOCK = asyncio.Lock()" in source
    assert "self._operation_lock = _PLUGIN_OPERATION_LOCK" in source
    assert "self._operation_lock = asyncio.Lock()" not in source


def test_lifecycle_runtime_load_unload_delegate_to_extension_core() -> None:
    source = (
        ROOT
        / "src"
        / "ai_karen_engine"
        / "extensions"
        / "platform"
        / "core"
        / "plugin_lifecycle_manager.py"
    ).read_text(encoding="utf-8")

    assert "get_extension_core_manager().load_extension(plugin_id)" in source
    assert "get_extension_core_manager().unload_extension(plugin_id)" in source
    assert "self.registry.load_extension(plugin_id)" not in source
    assert "self.registry.unload_extension(plugin_id)" not in source
