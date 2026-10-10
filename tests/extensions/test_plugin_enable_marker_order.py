"""Enabling an uploaded plugin must not discard its durable gate on failure."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_karen_engine.extensions.plugin_kernel import PluginKernel


@pytest.mark.asyncio
async def test_failed_enable_keeps_persistent_gate(tmp_path: Path, monkeypatch):
    kernel = PluginKernel(tmp_path)
    pkg = tmp_path / "demo"
    pkg.mkdir()
    marker = pkg / ".karen-manual-disabled"
    marker.write_text("requires enable")

    class Registry:
        def get(self, name):
            return SimpleNamespace(manifest=SimpleNamespace(id=name))

        async def update_state(self, name, state):
            raise RuntimeError("activation rejected")

    kernel.runtime_registry = Registry()
    with pytest.raises(RuntimeError, match="activation rejected"):
        await kernel.enable("demo")
    assert marker.is_file()
