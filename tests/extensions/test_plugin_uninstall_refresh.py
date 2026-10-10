"""Uninstall refresh cannot retain state for a removed plugin."""
from pathlib import Path

import pytest

from ai_karen_engine.extensions.plugin_kernel import PluginKernel


@pytest.mark.asyncio
async def test_refresh_prunes_uninstalled_plugin_disable_state(tmp_path: Path):
    kernel = PluginKernel(tmp_path)
    kernel._disabled.update({"removed_plugin", "other_removed_plugin"})

    class EmptyCatalog:
        async def refresh(self):
            return None

        def list_discovered(self):
            return []

    kernel.catalog_registry = EmptyCatalog()
    await kernel.refresh()
    assert kernel._disabled == set()
    assert kernel.get_record("removed_plugin") is None
